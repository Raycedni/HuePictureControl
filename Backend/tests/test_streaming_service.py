"""Tests for StreamingService: lifecycle, frame loop, reconnect, channel map."""
import asyncio
import json
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _solid_blue_frame() -> np.ndarray:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :, 0] = 255  # blue channel (BGR)
    return frame


def _mock_region_mask(h=480, w=640):
    """Create a RegionMask covering the full frame for tests."""
    from services.color_math import RegionMask
    mask = np.ones((h, w), dtype=np.uint8) * 255
    return RegionMask(mask=mask, roi_mask=mask, x1=0, y1=0, x2=w, y2=h)


def _make_mocks():
    """Return fresh mock objects for db, capture, registry, broadcaster, and pykit streaming."""
    mock_db = MagicMock()

    # Capture mock
    mock_capture = MagicMock()
    mock_capture.get_frame = AsyncMock(return_value=_solid_blue_frame())
    mock_capture.wait_for_new_frame = AsyncMock(return_value=_solid_blue_frame())
    mock_capture.release = MagicMock()
    mock_capture.open = MagicMock()

    # Registry mock — acquire returns mock_capture so existing frame-loop tests still work
    mock_registry = MagicMock()
    mock_registry.acquire = MagicMock(return_value=mock_capture)
    mock_registry.release = MagicMock()
    mock_registry.get_default = MagicMock(return_value=mock_capture)

    # Broadcaster mock
    mock_broadcaster = MagicMock()
    mock_broadcaster.push_state = AsyncMock()
    mock_broadcaster.update_metrics = MagicMock()
    mock_broadcaster.start_heartbeat = AsyncMock()
    mock_broadcaster.stop_heartbeat = AsyncMock()

    # hue-entertainment-pykit Streaming mock
    mock_streaming = MagicMock()
    mock_streaming.start_stream = MagicMock()
    mock_streaming.stop_stream = MagicMock()
    mock_streaming.set_input = MagicMock()
    mock_streaming.set_color_space = MagicMock()

    return {
        "db": mock_db,
        "capture": mock_capture,
        "registry": mock_registry,
        "broadcaster": mock_broadcaster,
        "streaming": mock_streaming,
    }


def _make_db_with_camera_assignment(config_id: str, stable_id: str | None, device_path: str | None):
    """Return a mock aiosqlite DB that returns camera_assignments + known_cameras rows.

    If stable_id is None, camera_assignments returns no row (no assignment).
    If device_path is None, known_cameras returns no row (unknown camera).
    """
    db = MagicMock()

    def make_cursor_for_assignment():
        cursor = MagicMock()
        if stable_id is not None:
            row = MagicMock()
            row.__getitem__ = MagicMock(side_effect=lambda k: {
                "camera_stable_id": stable_id,
            }[k])
            cursor.fetchone = AsyncMock(return_value=row)
        else:
            cursor.fetchone = AsyncMock(return_value=None)
        cursor.__aenter__ = AsyncMock(return_value=cursor)
        cursor.__aexit__ = AsyncMock(return_value=False)
        return cursor

    def make_cursor_for_known_camera():
        cursor = MagicMock()
        if device_path is not None:
            row = MagicMock()
            row.__getitem__ = MagicMock(side_effect=lambda k: {
                "last_device_path": device_path,
            }[k])
            cursor.fetchone = AsyncMock(return_value=row)
        else:
            cursor.fetchone = AsyncMock(return_value=None)
        cursor.__aenter__ = AsyncMock(return_value=cursor)
        cursor.__aexit__ = AsyncMock(return_value=False)
        return cursor

    cursors = [make_cursor_for_assignment(), make_cursor_for_known_camera()]
    db.execute = AsyncMock(side_effect=cursors)
    return db


def _make_streaming_db_cursor(rows):
    """Create a mock async cursor that returns given rows."""
    cursor = MagicMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    return cursor


def _make_db_with_rows(region_rows, bridge_row=None, assignment_rows=None):
    """Mock aiosqlite db with execute returning given rows.

    The db.execute mock returns (in order, accounting for _resolve_device_path calls):
      1st call: camera_assignments cursor (fetchone) — None (no camera assignment)
             → _resolve_device_path returns early (no known_cameras query)
      2nd call: bridge_config cursor (fetchone)
      3rd call: light_assignments cursor (fetchall) — empty by default
      4th call: regions cursor (fetchall)

    The camera_assignments cursor returns None so _resolve_device_path falls back to CAPTURE_DEVICE.
    """
    if bridge_row is None:
        bridge_row = {
            "ip_address": "192.168.1.100",
            "username": "testuser",
            "client_key": "testkey",
            "rid": "test-rid",
            "bridge_id": "test-bridge",
            "hue_app_id": "test-app",
            "swversion": 1234,
            "name": "Test Bridge",
        }
        # Make bridge_row subscriptable like aiosqlite.Row
        bridge_row_mock = MagicMock()
        bridge_row_mock.__getitem__ = MagicMock(side_effect=lambda k: bridge_row[k])
    else:
        bridge_row_mock = bridge_row

    if assignment_rows is None:
        assignment_rows = []

    # Camera assignment cursor — returns None (no assignment → falls back to CAPTURE_DEVICE)
    # When fetchone returns None, _resolve_device_path returns early without querying known_cameras.
    cam_assign_cursor = MagicMock()
    cam_assign_cursor.fetchone = AsyncMock(return_value=None)
    cam_assign_cursor.__aenter__ = AsyncMock(return_value=cam_assign_cursor)
    cam_assign_cursor.__aexit__ = AsyncMock(return_value=False)

    assignment_cursor = _make_streaming_db_cursor(assignment_rows)
    region_cursor = _make_streaming_db_cursor(region_rows)

    bridge_cursor = MagicMock()
    bridge_cursor.fetchone = AsyncMock(return_value=bridge_row_mock)
    bridge_cursor.__aenter__ = AsyncMock(return_value=bridge_cursor)
    bridge_cursor.__aexit__ = AsyncMock(return_value=False)

    db = MagicMock()
    # 1st: camera_assignments, 2nd: bridge_config, 3rd: light_assignments, 4th: regions
    db.execute = AsyncMock(side_effect=[cam_assign_cursor, bridge_cursor, assignment_cursor, region_cursor])
    return db, bridge_row_mock


def _make_region_row(light_id, polygon_points=None, region_id="region-001"):
    """Create a mock row for regions table with light_id."""
    if polygon_points is None:
        polygon_points = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: {
        "id": region_id,
        "polygon": json.dumps(polygon_points),
        "light_id": light_id,
    }[k])
    return row


def _make_channel_row(channel_id, polygon_points=None):
    """Create a mock row for light_assignments JOIN regions (legacy compat)."""
    if polygon_points is None:
        polygon_points = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: {
        "channel_id": channel_id,
        "polygon": json.dumps(polygon_points),
    }[k])
    return row


# ---------------------------------------------------------------------------
# Import path
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def service_imports():
    """Provide the StreamingService class under pykit mocks (module-scoped: import once)."""
    import sys
    import importlib

    mock_bridge_cls = MagicMock()
    mock_entertainment_cls = MagicMock()
    mock_streaming_cls = MagicMock()
    mock_create_bridge = MagicMock(return_value=mock_bridge_cls())

    pykit_mock = MagicMock()
    pykit_mock.create_bridge = mock_create_bridge
    pykit_mock.Entertainment = mock_entertainment_cls
    pykit_mock.Streaming = mock_streaming_cls

    # Patch the module before import and keep it for the entire test module
    sys.modules["hue_entertainment_pykit"] = pykit_mock

    # Remove cached streaming_service if present (force reimport with mocked pykit)
    sys.modules.pop("services.streaming_service", None)

    from services.streaming_service import StreamingService

    yield StreamingService, mock_create_bridge, mock_entertainment_cls, mock_streaming_cls

    # Cleanup
    sys.modules.pop("hue_entertainment_pykit", None)
    sys.modules.pop("services.streaming_service", None)


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_transitions_to_streaming(service_imports):
    """start() should transition idle -> starting -> streaming and create a task."""
    StreamingService, mock_create_bridge, mock_entertainment_cls, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    rows = [_make_region_row("light-001")]
    db, _ = _make_db_with_rows(rows)

    mock_streaming_instance = mocks["streaming"]
    mock_streaming_cls.return_value = mock_streaming_instance

    service = StreamingService(db, mocks["registry"], mocks["broadcaster"])
    assert service.state == "idle"

    # Patch asyncio.to_thread so streaming calls don't block
    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock):
            with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock, return_value={"light-001": [0]}):
                # Make frame loop exit quickly
                run_count = 0

                async def controlled_get_frame():
                    nonlocal run_count
                    run_count += 1
                    if run_count > 1:
                        service._run_event.clear()
                    return _solid_blue_frame()

                mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=controlled_get_frame)

                await service.start("cfg-001")

                assert service.state in ("starting", "streaming")

                # Wait for the loop to finish
                if service._task:
                    await service._task

    assert service.state == "idle"


@pytest.mark.asyncio
async def test_start_when_already_streaming_is_noop(service_imports):
    """start() called while streaming should return early without changing state."""
    StreamingService, _, __, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._state = "streaming"

    original_task = service._task
    await service.start("cfg-001")

    assert service.state == "streaming"
    assert service._task is original_task
    mocks["broadcaster"].push_state.assert_not_called()


@pytest.mark.asyncio
async def test_stop_when_idle_is_noop(service_imports):
    """stop() when idle should return early without side effects."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    assert service.state == "idle"

    await service.stop()

    assert service.state == "idle"
    mocks["broadcaster"].push_state.assert_not_called()


@pytest.mark.asyncio
async def test_stop_clears_run_event_and_waits_for_task(service_imports):
    """stop() should clear run_event, await the task, and call push_state."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._state = "streaming"

    # Create a task that waits until run_event is cleared
    async def fake_run_loop():
        await asyncio.sleep(0.01)

    service._task = asyncio.create_task(fake_run_loop())
    service._run_event.set()

    await service.stop()

    assert not service._run_event.is_set()
    assert service.state == "idle"
    mocks["broadcaster"].push_state.assert_called()


# ---------------------------------------------------------------------------
# Channel map tests
# ---------------------------------------------------------------------------

def _make_channel_map_db(assignment_rows, region_rows):
    """Mock DB for _load_channel_map which executes two queries:
    1st: light_assignments JOIN regions (assignment_rows)
    2nd: regions WHERE light_id IS NOT NULL (region_rows)
    """
    assign_cursor = _make_streaming_db_cursor(assignment_rows)
    region_cursor = _make_streaming_db_cursor(region_rows)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[assign_cursor, region_cursor])
    return db


@pytest.mark.asyncio
async def test_load_channel_map_returns_dict_with_masks(service_imports):
    """_load_channel_map should return {channel_id: mask_array} from regions + bridge."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    rows = [
        _make_region_row("light-A", region_id="r1"),
        _make_region_row("light-B", [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5]], region_id="r2"),
    ]

    db = _make_channel_map_db([], rows)

    service = StreamingService(db, mocks["registry"], mocks["broadcaster"])
    with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock,
               return_value={"light-A": [0], "light-B": [1]}):
        channel_map = await service._load_channel_map("cfg-001", "192.168.1.1", "testuser")

    assert len(channel_map) == 2
    assert 0 in channel_map
    assert 1 in channel_map
    # Each value should be a RegionMask with a numpy uint8 mask
    from services.color_math import RegionMask
    for region in channel_map.values():
        assert isinstance(region, RegionMask)
        assert region.mask.dtype == np.uint8
        assert region.mask.shape == (480, 640)


@pytest.mark.asyncio
async def test_load_channel_map_empty_returns_empty_dict(service_imports):
    """_load_channel_map with no regions should return empty dict."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    db = _make_channel_map_db([], [])

    service = StreamingService(db, mocks["registry"], mocks["broadcaster"])
    with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock,
               return_value={}):
        channel_map = await service._load_channel_map("cfg-001", "192.168.1.1", "testuser")

    assert channel_map == {}


@pytest.mark.asyncio
async def test_load_channel_map_gradient_light_maps_multiple_channels(service_imports):
    """A region assigned to a gradient light should map to all its channels via fallback."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    rows = [_make_region_row("gradient-light", region_id="r1")]

    db = _make_channel_map_db([], rows)

    service = StreamingService(db, mocks["registry"], mocks["broadcaster"])
    with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock,
               return_value={"gradient-light": [1, 2, 3]}):
        channel_map = await service._load_channel_map("cfg-001", "192.168.1.1", "testuser")

    assert len(channel_map) == 3
    assert 1 in channel_map and 2 in channel_map and 3 in channel_map


@pytest.mark.asyncio
async def test_load_channel_map_uses_assignments_over_fallback(service_imports):
    """light_assignments entries should take precedence over light_id fallback."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    # Assignment row: region r1 maps to channel 0
    assign_row = _make_channel_row(0, [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]])
    # Also add region_id to the assignment row
    orig_side_effect = assign_row.__getitem__.side_effect
    assign_row.__getitem__ = MagicMock(side_effect=lambda k: {
        "region_id": "r1", "channel_id": 0,
        "polygon": json.dumps([[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]),
    }[k])

    # Region r1 has light_id that resolves to channels [0, 1]
    region_row = _make_region_row("light-A", region_id="r1")

    db = _make_channel_map_db([assign_row], [region_row])

    service = StreamingService(db, mocks["registry"], mocks["broadcaster"])
    with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock,
               return_value={"light-A": [0, 1]}):
        channel_map = await service._load_channel_map("cfg-001", "192.168.1.1", "testuser")

    # Channel 0 comes from assignment, channel 1 from fallback — but r1 is in assigned_region_ids
    # so fallback skips r1. Only channel 0 should be present.
    assert 0 in channel_map
    assert 1 not in channel_map


# ---------------------------------------------------------------------------
# Frame loop tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_frame_loop_calls_get_frame_each_iteration(service_imports):
    """Frame loop should call capture.get_frame() on each iteration."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    call_count = 0

    async def controlled_frame():
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=controlled_frame)

    mock_streaming = mocks["streaming"]
    channel_map = {0: _mock_region_mask()}

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    service._run_event.set()
    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service._frame_loop(mock_streaming, channel_map, "192.168.1.1", "testuser")

    assert call_count >= 3


@pytest.mark.asyncio
async def test_frame_loop_calls_extract_region_color_per_channel(service_imports):
    """Frame loop should call extract_region_color once per channel per frame."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    frame_count = 0

    async def one_frame():
        nonlocal frame_count
        frame_count += 1
        if frame_count >= 2:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    channel_map = {
        0: _mock_region_mask(),
        1: _mock_region_mask(),
    }

    extract_calls = []

    def fake_extract(frame, mask):
        extract_calls.append(1)
        return (0, 0, 255)  # blue

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    service._run_event.set()
    with patch("services.streaming_service.extract_region_color", side_effect=fake_extract):
        with patch("asyncio.to_thread", side_effect=fake_to_thread):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    # 2 channels, at least 1 frame = at least 2 calls
    assert len(extract_calls) >= 2


@pytest.mark.asyncio
async def test_frame_loop_calls_rgb_to_xy_and_set_input(service_imports):
    """Frame loop should call rgb_to_xy and set_input with (x, y, bri, channel_id)."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    ran = False

    async def one_frame():
        nonlocal ran
        if ran:
            service._run_event.clear()
        ran = True
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    channel_map = {0: _mock_region_mask()}

    # Track set_input calls via the mock's side_effect
    set_input_calls = []
    def record_set_input(inp):
        set_input_calls.append(inp)
    mocks["streaming"].set_input = MagicMock(side_effect=record_set_input)

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    service._run_event.set()
    with patch("services.streaming_service.extract_region_color", return_value=(0, 0, 255)):
        with patch("services.streaming_service.rgb_to_xy", return_value=(0.153, 0.048)):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    assert len(set_input_calls) >= 1
    tup = set_input_calls[0]
    # set_input called with (x, y, bri, channel_id) tuple
    assert len(tup) == 4
    x, y, bri, ch_id = tup
    assert x == 0.153
    assert y == 0.048
    assert ch_id == 0
    assert bri > 0


@pytest.mark.asyncio
async def test_frame_loop_brightness_clamped_to_min_001(service_imports):
    """Brightness should be clamped to at least 0.01 for dark scene protection."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    ran = False

    async def one_frame():
        nonlocal ran
        if ran:
            service._run_event.clear()
        ran = True
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    channel_map = {0: _mock_region_mask()}

    set_input_calls = []
    def record_set_input(inp):
        set_input_calls.append(inp)
    mocks["streaming"].set_input = MagicMock(side_effect=record_set_input)

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    service._run_event.set()
    # Return pure black (0, 0, 0) — brightness would be 0 without clamping
    with patch("services.streaming_service.extract_region_color", return_value=(0, 0, 0)):
        with patch("services.streaming_service.rgb_to_xy", return_value=(0.3127, 0.3290)):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    assert len(set_input_calls) >= 1
    _, _, bri, _ = set_input_calls[0]
    assert bri >= 0.01


@pytest.mark.asyncio
async def test_frame_loop_16_channels(service_imports):
    """16-channel map should be processed without error (STRM-06)."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    async def one_frame():
        # Clear event during get_frame so exactly one frame is processed
        service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    channel_map = {i: _mock_region_mask() for i in range(16)}

    set_input_calls = []
    def record_set_input(inp):
        set_input_calls.append(inp)
    mocks["streaming"].set_input = MagicMock(side_effect=record_set_input)

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    service._run_event.set()
    with patch("services.streaming_service.extract_region_color", return_value=(100, 100, 200)):
        with patch("services.streaming_service.rgb_to_xy", return_value=(0.2, 0.3)):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    # 16 channels should each get set_input called (exactly one frame processed)
    assert len(set_input_calls) == 16


@pytest.mark.asyncio
async def test_frame_loop_1_channel_non_gradient(service_imports):
    """Single-channel (non-gradient) light should call set_input once (GRAD-05)."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    async def one_frame():
        # Clear event during get_frame so exactly one frame is processed
        service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    channel_map = {0: _mock_region_mask()}

    set_input_calls = []
    def record_set_input(inp):
        set_input_calls.append(inp)
    mocks["streaming"].set_input = MagicMock(side_effect=record_set_input)

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    service._run_event.set()
    with patch("services.streaming_service.extract_region_color", return_value=(100, 100, 200)):
        with patch("services.streaming_service.rgb_to_xy", return_value=(0.2, 0.3)):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    assert len(set_input_calls) == 1


@pytest.mark.asyncio
async def test_frame_loop_calls_update_metrics_not_broadcast(service_imports):
    """Frame loop should call broadcaster.update_metrics() (silent, not broadcast)."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    ran = False

    async def one_frame():
        nonlocal ran
        if ran:
            service._run_event.clear()
        ran = True
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    channel_map = {0: _mock_region_mask()}

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    service._run_event.set()
    with patch("services.streaming_service.extract_region_color", return_value=(0, 0, 255)):
        with patch("services.streaming_service.rgb_to_xy", return_value=(0.153, 0.048)):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    mocks["broadcaster"].update_metrics.assert_called()
    # Verify update_metrics was called with the expected keys
    call_kwargs = mocks["broadcaster"].update_metrics.call_args[0][0]
    assert "fps" in call_kwargs
    assert "latency_ms" in call_kwargs
    assert "packets_sent" in call_kwargs
    assert "seq" in call_kwargs


@pytest.mark.asyncio
async def test_frame_loop_capture_error_stops_and_pushes_error(service_imports):
    """RuntimeError from capture.get_frame() with failed reconnect pushes error and stops."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=RuntimeError("Device disconnected"))

    # Reconnect fails (returns False) — loop should exit with error
    async def fake_reconnect_false():
        return False

    service._capture_reconnect_loop = fake_reconnect_false

    channel_map = {0: _mock_region_mask()}

    service._run_event.set()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    # Error pushed to broadcaster
    mocks["broadcaster"].push_state.assert_called()
    push_call_kwargs = mocks["broadcaster"].push_state.call_args
    # push_state should be called with an error state
    assert push_call_kwargs is not None


# ---------------------------------------------------------------------------
# Reconnect tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconnect_loop_succeeds_on_first_try(service_imports):
    """_reconnect_loop should return True when activation succeeds immediately."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._run_event.set()

    with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock) as mock_activate:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await service._reconnect_loop("cfg-001", "192.168.1.100", "testuser")

    assert result is True
    mock_activate.assert_called_once()


@pytest.mark.asyncio
async def test_reconnect_loop_returns_false_when_run_event_cleared(service_imports):
    """_reconnect_loop should return False when run_event is cleared (user stopped)."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._run_event.clear()  # already stopped

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await service._reconnect_loop("cfg-001", "192.168.1.100", "testuser")

    assert result is False


@pytest.mark.asyncio
async def test_reconnect_loop_exponential_backoff(service_imports):
    """_reconnect_loop should retry with 1s, 2s, 4s delays (capped at 30s)."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._run_event.set()

    sleep_calls = []
    attempt = 0

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    async def activate_fails_twice(bridge_ip, username, config_id):
        nonlocal attempt
        attempt += 1
        if attempt <= 2:
            raise Exception("Bridge unreachable")
        # Success on 3rd attempt

    with patch("services.streaming_service.activate_entertainment_config", side_effect=activate_fails_twice):
        with patch("asyncio.sleep", side_effect=fake_sleep):
            result = await service._reconnect_loop("cfg-001", "192.168.1.100", "testuser")

    assert result is True
    # Should have slept with backoff before retrying
    assert len(sleep_calls) >= 2
    # First sleep should be 1s, second should be 2s
    assert sleep_calls[0] == 1
    assert sleep_calls[1] == 2


@pytest.mark.asyncio
async def test_reconnect_loop_backoff_capped_at_30s(service_imports):
    """_reconnect_loop delays should be capped at 30s."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._run_event.set()

    sleep_calls = []
    attempt = 0
    MAX_ATTEMPTS = 10  # enough to saturate cap

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    async def activate_fails_many(bridge_ip, username, config_id):
        nonlocal attempt
        attempt += 1
        if attempt < MAX_ATTEMPTS:
            raise Exception("Bridge unreachable")
        # Success on last attempt

    with patch("services.streaming_service.activate_entertainment_config", side_effect=activate_fails_many):
        with patch("asyncio.sleep", side_effect=fake_sleep):
            result = await service._reconnect_loop("cfg-001", "192.168.1.100", "testuser")

    assert result is True
    # No sleep should exceed 30s
    for delay in sleep_calls:
        assert delay <= 30


@pytest.mark.asyncio
async def test_reconnect_loop_does_not_touch_capture(service_imports):
    """Capture pipeline must NOT be paused during bridge reconnect."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._run_event.set()

    attempt = 0

    async def activate_fails_once(bridge_ip, username, config_id):
        nonlocal attempt
        attempt += 1
        if attempt < 2:
            raise Exception("Bridge unreachable")

    with patch("services.streaming_service.activate_entertainment_config", side_effect=activate_fails_once):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await service._reconnect_loop("cfg-001", "192.168.1.100", "testuser")

    assert result is True
    # Capture should NOT have been released or modified
    mocks["capture"].release.assert_not_called()
    mocks["capture"].open.assert_not_called()


# ---------------------------------------------------------------------------
# Stop sequence order test
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Capture reconnect tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capture_reconnect_loop_returns_true_on_success(service_imports):
    """_capture_reconnect_loop returns True after capture.open() succeeds on second attempt."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._run_event.set()
    service._capture = mocks["capture"]  # Simulate acquired capture

    attempt = 0

    def open_fails_once(device_path=None):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise RuntimeError("Device disconnected")
        # second call succeeds

    mocks["capture"].open = MagicMock(side_effect=open_fails_once)

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await service._capture_reconnect_loop()

    assert result is True


@pytest.mark.asyncio
async def test_capture_reconnect_loop_returns_false_when_run_event_cleared(service_imports):
    """_capture_reconnect_loop returns False when run_event is cleared during retry."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]
    service._run_event.set()

    call_count = 0

    async def open_always_fails_then_stop(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        service._run_event.clear()  # clear event during retry
        raise RuntimeError("Still disconnected")

    with patch("asyncio.to_thread", side_effect=open_always_fails_then_stop):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await service._capture_reconnect_loop()

    assert result is False


@pytest.mark.asyncio
async def test_capture_reconnect_loop_pushes_reconnecting_state(service_imports):
    """_capture_reconnect_loop pushes 'reconnecting' state to broadcaster on entry."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]
    service._run_event.set()

    mocks["capture"].open = MagicMock()  # succeeds immediately

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service._capture_reconnect_loop()

    # First push_state call should be "reconnecting"
    push_calls = mocks["broadcaster"].push_state.call_args_list
    states_pushed = [c[0][0] for c in push_calls if c[0]]
    assert "reconnecting" in states_pushed


@pytest.mark.asyncio
async def test_capture_reconnect_loop_pushes_streaming_state_on_success(service_imports):
    """_capture_reconnect_loop pushes 'streaming' state to broadcaster on success."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]
    service._run_event.set()

    mocks["capture"].open = MagicMock()  # succeeds immediately

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await service._capture_reconnect_loop()

    assert result is True
    push_calls = mocks["broadcaster"].push_state.call_args_list
    states_pushed = [c[0][0] for c in push_calls if c[0]]
    assert "streaming" in states_pushed


@pytest.mark.asyncio
async def test_frame_loop_calls_capture_reconnect_on_runtime_error(service_imports):
    """_frame_loop calls _capture_reconnect_loop on RuntimeError from get_frame and continues if reconnect succeeds."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    call_count = 0

    async def frame_raises_then_ok():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Device disconnected")
        service._run_event.clear()  # exit after successful reconnect
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=frame_raises_then_ok)

    reconnect_called = False

    async def fake_reconnect():
        nonlocal reconnect_called
        reconnect_called = True
        return True

    channel_map = {0: _mock_region_mask()}

    service._run_event.set()
    service._capture_reconnect_loop = fake_reconnect

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    assert reconnect_called is True


@pytest.mark.asyncio
async def test_frame_loop_exits_when_capture_reconnect_returns_false(service_imports):
    """_frame_loop exits cleanly if _capture_reconnect_loop returns False."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]  # simulate acquired capture

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=RuntimeError("Device gone"))

    async def fake_reconnect_false():
        return False

    channel_map = {0: _mock_region_mask()}

    service._run_event.set()
    service._capture_reconnect_loop = fake_reconnect_false

    with patch("asyncio.sleep", new_callable=AsyncMock):
        await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    # Loop should have exited (no infinite loop / no exception)
    # Verify run_event may still be set (frame loop returns cleanly without clearing it)
    # The run_event is managed by _capture_reconnect_loop and the caller
    assert True  # If we reach here, it exited without hanging


@pytest.mark.asyncio
async def test_capture_open_called_via_to_thread(service_imports):
    """capture.open() is wrapped in asyncio.to_thread to avoid blocking event loop."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._capture = mocks["capture"]
    service._run_event.set()

    to_thread_calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        to_thread_calls.append(fn)
        return fn(*args, **kwargs)

    mocks["capture"].open = MagicMock()

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service._capture_reconnect_loop()

    # capture.open should have been called via asyncio.to_thread
    assert mocks["capture"].open in to_thread_calls


@pytest.mark.asyncio
async def test_stop_sequence_order(service_imports):
    """Stop sequence must be: stop_stream -> deactivate_entertainment_config -> capture.release."""
    StreamingService, _, __, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    rows = [_make_region_row("light-001")]
    db, _ = _make_db_with_rows(rows)

    mock_streaming_instance = mocks["streaming"]
    mock_streaming_cls.return_value = mock_streaming_instance

    call_order = []

    def track_stop_stream():
        call_order.append("stop_stream")

    async def track_deactivate(bridge_ip, username, config_id):
        call_order.append("deactivate")

    def track_release(device_path=None):
        call_order.append("release")

    mock_streaming_instance.stop_stream = MagicMock(side_effect=track_stop_stream)
    mocks["registry"].release = MagicMock(side_effect=track_release)

    frame_count = 0

    async def two_frames():
        nonlocal frame_count
        frame_count += 1
        if frame_count >= 2:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=two_frames)

    service = StreamingService(db, mocks["registry"], mocks["broadcaster"])

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock):
        with patch("services.streaming_service.deactivate_entertainment_config", side_effect=track_deactivate):
            with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock, return_value={"light-001": [0]}):
                with patch("asyncio.to_thread", side_effect=fake_to_thread):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        await service.start("cfg-001")
                        if service._task:
                            await service._task

    assert call_order == ["stop_stream", "deactivate", "release"], \
        f"Expected stop_stream -> deactivate -> release, got: {call_order}"


# ---------------------------------------------------------------------------
# Registry integration tests (Phase 08-02)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_uses_assigned_camera(service_imports):
    """start() calls registry.acquire('/dev/video1') when camera_assignments maps config_id there."""
    StreamingService, _, __, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    camera_db = _make_db_with_camera_assignment("cfg-registry-01", "cam-stable-01", "/dev/video1")
    mock_streaming_cls.return_value = mocks["streaming"]

    service = StreamingService(camera_db, mocks["registry"], mocks["broadcaster"])

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    # Make _run_loop exit quickly after acquiring device
    frame_count = 0

    async def one_frame():
        nonlocal frame_count
        frame_count += 1
        if frame_count >= 1:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock):
        with patch("services.streaming_service.deactivate_entertainment_config", new_callable=AsyncMock):
            with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock, return_value={}):
                with patch("asyncio.to_thread", side_effect=fake_to_thread):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        await service.start("cfg-registry-01")
                        if service._task:
                            await service._task

    mocks["registry"].acquire.assert_called_once_with("/dev/video1")


@pytest.mark.asyncio
async def test_no_assignment_uses_default(service_imports):
    """start() falls back to CAPTURE_DEVICE when camera_assignments has no entry for config_id."""
    StreamingService, _, __, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    # No assignment (stable_id=None)
    camera_db = _make_db_with_camera_assignment("cfg-no-assignment", None, None)
    mock_streaming_cls.return_value = mocks["streaming"]

    service = StreamingService(camera_db, mocks["registry"], mocks["broadcaster"])

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    frame_count = 0

    async def one_frame():
        nonlocal frame_count
        frame_count += 1
        if frame_count >= 1:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock):
        with patch("services.streaming_service.deactivate_entertainment_config", new_callable=AsyncMock):
            with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock, return_value={}):
                with patch("asyncio.to_thread", side_effect=fake_to_thread):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        with patch("services.streaming_service.CAPTURE_DEVICE", "/dev/video0"):
                            await service.start("cfg-no-assignment")
                            if service._task:
                                await service._task

    # Should acquire CAPTURE_DEVICE (the default)
    call_args = mocks["registry"].acquire.call_args[0][0]
    assert call_args == "/dev/video0"


@pytest.mark.asyncio
async def test_assignment_to_unknown_camera_uses_default(service_imports):
    """start() falls back to CAPTURE_DEVICE when camera_assignments has entry but known_cameras has no matching row."""
    StreamingService, _, __, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    # Has assignment but device_path=None (unknown camera in known_cameras)
    camera_db = _make_db_with_camera_assignment("cfg-unknown-cam", "cam-unknown-stable", None)
    mock_streaming_cls.return_value = mocks["streaming"]

    service = StreamingService(camera_db, mocks["registry"], mocks["broadcaster"])

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    frame_count = 0

    async def one_frame():
        nonlocal frame_count
        frame_count += 1
        if frame_count >= 1:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock):
        with patch("services.streaming_service.deactivate_entertainment_config", new_callable=AsyncMock):
            with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock, return_value={}):
                with patch("asyncio.to_thread", side_effect=fake_to_thread):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        with patch("services.streaming_service.CAPTURE_DEVICE", "/dev/video0"):
                            await service.start("cfg-unknown-cam")
                            if service._task:
                                await service._task

    call_args = mocks["registry"].acquire.call_args[0][0]
    assert call_args == "/dev/video0"


@pytest.mark.asyncio
async def test_stop_releases_device(service_imports):
    """After start() acquires a device, the _run_loop finally block calls registry.release()."""
    StreamingService, _, __, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    camera_db = _make_db_with_camera_assignment("cfg-release-01", "cam-01", "/dev/video1")
    mock_streaming_cls.return_value = mocks["streaming"]

    service = StreamingService(camera_db, mocks["registry"], mocks["broadcaster"])

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    frame_count = 0

    async def one_frame():
        nonlocal frame_count
        frame_count += 1
        if frame_count >= 1:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame)

    with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock):
        with patch("services.streaming_service.deactivate_entertainment_config", new_callable=AsyncMock):
            with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock, return_value={}):
                with patch("asyncio.to_thread", side_effect=fake_to_thread):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        await service.start("cfg-release-01")
                        if service._task:
                            await service._task

    mocks["registry"].release.assert_called_once_with("/dev/video1")


@pytest.mark.asyncio
async def test_camera_reassignment_mid_stream(service_imports):
    """start(A), stop(), change DB assignment, start(B) — acquire called with A then B."""
    StreamingService, _, __, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    mock_streaming_cls.return_value = mocks["streaming"]

    # First call: cfg returns /dev/video1
    # Second call: cfg returns /dev/video2
    # We model this by swapping the DB between starts

    db_video1 = _make_db_with_camera_assignment("cfg-reassign", "cam-A", "/dev/video1")
    db_video2 = _make_db_with_camera_assignment("cfg-reassign", "cam-B", "/dev/video2")

    # We'll track which DB to use via a mutable container
    active_db = [db_video1]

    class ProxyDB:
        async def execute(self, *args, **kwargs):
            return await active_db[0].execute(*args, **kwargs)

    service = StreamingService(ProxyDB(), mocks["registry"], mocks["broadcaster"])

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    async def one_frame_then_stop():
        service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame_then_stop)

    with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock):
        with patch("services.streaming_service.deactivate_entertainment_config", new_callable=AsyncMock):
            with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock, return_value={}):
                with patch("asyncio.to_thread", side_effect=fake_to_thread):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        # First run: acquires /dev/video1
                        mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame_then_stop)
                        await service.start("cfg-reassign")
                        if service._task:
                            await service._task

                        # Simulate reassignment
                        active_db[0] = db_video2
                        service._state = "idle"
                        service._run_event.clear()

                        # Second run: acquires /dev/video2
                        mocks["capture"].wait_for_new_frame = AsyncMock(side_effect=one_frame_then_stop)
                        await service.start("cfg-reassign")
                        if service._task:
                            await service._task

    acquire_calls = [c[0][0] for c in mocks["registry"].acquire.call_args_list]
    assert "/dev/video1" in acquire_calls
    assert "/dev/video2" in acquire_calls

    release_calls = [c[0][0] for c in mocks["registry"].release.call_args_list]
    assert "/dev/video1" in release_calls
    assert "/dev/video2" in release_calls


@pytest.mark.asyncio
async def test_run_loop_finally_releases_device(service_imports):
    """When _run_loop exits due to exception, registry.release() is called in finally block."""
    StreamingService, _, __, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    camera_db = _make_db_with_camera_assignment("cfg-err-release", "cam-01", "/dev/video1")
    mock_streaming_cls.return_value = mocks["streaming"]

    # Force an error after acquire — activate raises
    service = StreamingService(camera_db, mocks["registry"], mocks["broadcaster"])

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("services.streaming_service.activate_entertainment_config",
               new_callable=AsyncMock, side_effect=RuntimeError("Bridge offline")):
        with patch("services.streaming_service.deactivate_entertainment_config", new_callable=AsyncMock):
            with patch("services.streaming_service.resolve_light_to_channel_map", new_callable=AsyncMock, return_value={}):
                with patch("asyncio.to_thread", side_effect=fake_to_thread):
                    with patch("asyncio.sleep", new_callable=AsyncMock):
                        await service.start("cfg-err-release")
                        if service._task:
                            await service._task

    # Even on error, release must be called for the acquired device
    mocks["registry"].release.assert_called_once_with("/dev/video1")


@pytest.mark.asyncio
async def test_capture_reconnect_does_not_touch_registry(service_imports):
    """_capture_reconnect_loop calls capture.release() and capture.open() directly, NOT registry."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["registry"], mocks["broadcaster"])
    service._run_event.set()
    service._capture = mocks["capture"]  # Simulate acquired capture

    mocks["capture"].open = MagicMock()

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await service._capture_reconnect_loop()

    # capture.release and capture.open should be called (reconnect logic)
    mocks["capture"].release.assert_called()
    mocks["capture"].open.assert_called()

    # registry.acquire and registry.release should NOT be called
    mocks["registry"].acquire.assert_not_called()
    mocks["registry"].release.assert_not_called()
