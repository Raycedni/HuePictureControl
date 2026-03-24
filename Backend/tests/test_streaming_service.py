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


def _make_mocks():
    """Return fresh mock objects for db, capture, broadcaster, and pykit streaming."""
    mock_db = MagicMock()

    # Capture mock
    mock_capture = MagicMock()
    mock_capture.get_frame = AsyncMock(return_value=_solid_blue_frame())
    mock_capture.release = MagicMock()
    mock_capture.open = MagicMock()

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
        "broadcaster": mock_broadcaster,
        "streaming": mock_streaming,
    }


def _make_streaming_db_cursor(rows):
    """Create a mock async cursor that returns given rows."""
    cursor = MagicMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    return cursor


def _make_db_with_rows(rows, bridge_row=None):
    """Mock aiosqlite db with execute returning given rows."""
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

    channel_cursor = _make_streaming_db_cursor(rows)

    bridge_cursor = MagicMock()
    bridge_cursor.fetchone = AsyncMock(return_value=bridge_row_mock)
    bridge_cursor.__aenter__ = AsyncMock(return_value=bridge_cursor)
    bridge_cursor.__aexit__ = AsyncMock(return_value=False)

    db = MagicMock()
    # First call returns bridge cursor, second returns channel cursor
    db.execute = AsyncMock(side_effect=[bridge_cursor, channel_cursor])
    return db, bridge_row_mock


def _make_channel_row(channel_id, polygon_points=None):
    """Create a mock row for light_assignments JOIN regions."""
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
    rows = [_make_channel_row(0)]
    db, _ = _make_db_with_rows(rows)

    mock_streaming_instance = mocks["streaming"]
    mock_streaming_cls.return_value = mock_streaming_instance

    service = StreamingService(db, mocks["capture"], mocks["broadcaster"])
    assert service.state == "idle"

    # Patch asyncio.to_thread so streaming calls don't block
    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock):
            # Make frame loop exit quickly
            run_count = 0

            async def controlled_get_frame():
                nonlocal run_count
                run_count += 1
                if run_count > 1:
                    service._run_event.clear()
                return _solid_blue_frame()

            mocks["capture"].get_frame = AsyncMock(side_effect=controlled_get_frame)

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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])
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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])
    assert service.state == "idle"

    await service.stop()

    assert service.state == "idle"
    mocks["broadcaster"].push_state.assert_not_called()


@pytest.mark.asyncio
async def test_stop_clears_run_event_and_waits_for_task(service_imports):
    """stop() should clear run_event, await the task, and call push_state."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])
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

@pytest.mark.asyncio
async def test_load_channel_map_returns_dict_with_masks(service_imports):
    """_load_channel_map should return {channel_id: mask_array} from db."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    rows = [
        _make_channel_row(0),
        _make_channel_row(1, [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5]]),
    ]

    cursor = _make_streaming_db_cursor(rows)
    db = MagicMock()
    db.execute = AsyncMock(return_value=cursor)

    service = StreamingService(db, mocks["capture"], mocks["broadcaster"])
    channel_map = await service._load_channel_map("cfg-001")

    assert len(channel_map) == 2
    assert 0 in channel_map
    assert 1 in channel_map
    # Each value should be a numpy uint8 mask
    for mask in channel_map.values():
        assert isinstance(mask, np.ndarray)
        assert mask.dtype == np.uint8
        assert mask.shape == (480, 640)


@pytest.mark.asyncio
async def test_load_channel_map_empty_returns_empty_dict(service_imports):
    """_load_channel_map with no rows should return empty dict."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    cursor = _make_streaming_db_cursor([])
    db = MagicMock()
    db.execute = AsyncMock(return_value=cursor)

    service = StreamingService(db, mocks["capture"], mocks["broadcaster"])
    channel_map = await service._load_channel_map("cfg-001")

    assert channel_map == {}


# ---------------------------------------------------------------------------
# Frame loop tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_frame_loop_calls_get_frame_each_iteration(service_imports):
    """Frame loop should call capture.get_frame() on each iteration."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])

    call_count = 0

    async def controlled_frame():
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].get_frame = AsyncMock(side_effect=controlled_frame)

    mock_streaming = mocks["streaming"]
    channel_map = {0: np.ones((480, 640), dtype=np.uint8) * 255}

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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])

    frame_count = 0

    async def one_frame():
        nonlocal frame_count
        frame_count += 1
        if frame_count >= 2:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].get_frame = AsyncMock(side_effect=one_frame)

    channel_map = {
        0: np.ones((480, 640), dtype=np.uint8) * 255,
        1: np.ones((480, 640), dtype=np.uint8) * 255,
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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])

    ran = False

    async def one_frame():
        nonlocal ran
        if ran:
            service._run_event.clear()
        ran = True
        return _solid_blue_frame()

    mocks["capture"].get_frame = AsyncMock(side_effect=one_frame)

    channel_map = {0: np.ones((480, 640), dtype=np.uint8) * 255}
    set_input_calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        if fn == mocks["streaming"].set_input:
            set_input_calls.append(args[0])
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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])

    ran = False

    async def one_frame():
        nonlocal ran
        if ran:
            service._run_event.clear()
        ran = True
        return _solid_blue_frame()

    mocks["capture"].get_frame = AsyncMock(side_effect=one_frame)

    channel_map = {0: np.ones((480, 640), dtype=np.uint8) * 255}
    set_input_calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        if fn == mocks["streaming"].set_input:
            set_input_calls.append(args[0])
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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])

    async def one_frame():
        # Clear event during get_frame so exactly one frame is processed
        service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].get_frame = AsyncMock(side_effect=one_frame)

    channel_map = {i: np.ones((480, 640), dtype=np.uint8) * 255 for i in range(16)}
    set_input_calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        if fn == mocks["streaming"].set_input:
            set_input_calls.append(args[0])
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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])

    async def one_frame():
        # Clear event during get_frame so exactly one frame is processed
        service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].get_frame = AsyncMock(side_effect=one_frame)

    channel_map = {0: np.ones((480, 640), dtype=np.uint8) * 255}
    set_input_calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        if fn == mocks["streaming"].set_input:
            set_input_calls.append(args[0])
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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])

    ran = False

    async def one_frame():
        nonlocal ran
        if ran:
            service._run_event.clear()
        ran = True
        return _solid_blue_frame()

    mocks["capture"].get_frame = AsyncMock(side_effect=one_frame)

    channel_map = {0: np.ones((480, 640), dtype=np.uint8) * 255}

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
    """RuntimeError from capture.get_frame() should stop streaming and push error."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])

    mocks["capture"].get_frame = AsyncMock(side_effect=RuntimeError("Device disconnected"))

    channel_map = {0: np.ones((480, 640), dtype=np.uint8) * 255}

    service._run_event.set()
    with patch("asyncio.sleep", new_callable=AsyncMock):
        await service._frame_loop(mocks["streaming"], channel_map, "192.168.1.1", "testuser")

    # Error pushed to broadcaster
    mocks["broadcaster"].push_state.assert_called()
    push_call_kwargs = mocks["broadcaster"].push_state.call_args
    # push_state should be called with an error state
    assert push_call_kwargs is not None
    # run_event should be cleared
    assert not service._run_event.is_set()


# ---------------------------------------------------------------------------
# Reconnect tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reconnect_loop_succeeds_on_first_try(service_imports):
    """_reconnect_loop should return True when activation succeeds immediately."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])
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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])
    service._run_event.clear()  # already stopped

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await service._reconnect_loop("cfg-001", "192.168.1.100", "testuser")

    assert result is False


@pytest.mark.asyncio
async def test_reconnect_loop_exponential_backoff(service_imports):
    """_reconnect_loop should retry with 1s, 2s, 4s delays (capped at 30s)."""
    StreamingService, _, __, ___ = service_imports

    mocks = _make_mocks()
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])
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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])
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
    service = StreamingService(mocks["db"], mocks["capture"], mocks["broadcaster"])
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

@pytest.mark.asyncio
async def test_stop_sequence_order(service_imports):
    """Stop sequence must be: stop_stream -> deactivate_entertainment_config -> capture.release."""
    StreamingService, _, __, mock_streaming_cls = service_imports

    mocks = _make_mocks()
    rows = [_make_channel_row(0)]
    db, _ = _make_db_with_rows(rows)

    mock_streaming_instance = mocks["streaming"]
    mock_streaming_cls.return_value = mock_streaming_instance

    call_order = []

    def track_stop_stream():
        call_order.append("stop_stream")

    async def track_deactivate(bridge_ip, username, config_id):
        call_order.append("deactivate")

    def track_release():
        call_order.append("release")

    mock_streaming_instance.stop_stream = MagicMock(side_effect=track_stop_stream)
    mocks["capture"].release = MagicMock(side_effect=track_release)

    frame_count = 0

    async def two_frames():
        nonlocal frame_count
        frame_count += 1
        if frame_count >= 2:
            service._run_event.clear()
        return _solid_blue_frame()

    mocks["capture"].get_frame = AsyncMock(side_effect=two_frames)

    service = StreamingService(db, mocks["capture"], mocks["broadcaster"])

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("services.streaming_service.activate_entertainment_config", new_callable=AsyncMock):
        with patch("services.streaming_service.deactivate_entertainment_config", side_effect=track_deactivate):
            with patch("asyncio.to_thread", side_effect=fake_to_thread):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    await service.start("cfg-001")
                    if service._task:
                        await service._task

    assert call_order == ["stop_stream", "deactivate", "release"], \
        f"Expected stop_stream -> deactivate -> release, got: {call_order}"
