"""Tests for StreamingCoordinator: state transitions, frame loop, sub-sample fan-out.

Migrated from test_streaming_service.py during Phase 17 Plan 05 refactor.
The coordinator owns the frame loop + capture lifecycle + broadcaster
orchestration; HueStreamer is mocked via dependency injection so these tests
exercise coordinator behavior independently of pykit.
"""
import asyncio
import json

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.streaming_coordinator import StreamingCoordinator
from services.status_broadcaster import StatusBroadcaster
from tests.fixtures.mock_capture import make_mock_capture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _solid_blue_frame() -> np.ndarray:
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :, 0] = 255  # blue channel (BGR)
    return frame


class _MockRegistry:
    """Minimal registry stub: acquire/release behave like the real one."""

    def __init__(self, capture):
        self._capture = capture
        self.acquire_calls: list[str] = []
        self.release_calls: list[str] = []

    def acquire(self, path):
        self.acquire_calls.append(path)
        return self._capture

    def release(self, path):
        self.release_calls.append(path)


def _empty_cursor():
    cur = MagicMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=None)
    cur.fetchone = AsyncMock(return_value=None)
    cur.fetchall = AsyncMock(return_value=[])
    return cur


def _make_db_with_empty_results():
    """DB whose every execute() returns an empty cursor.

    Sufficient for _resolve_device_path (returns CAPTURE_DEVICE) and
    _build_region_plan (returns empty plan).
    """
    db = MagicMock()

    async def _exec(*args, **kwargs):
        return _empty_cursor()

    db.execute = _exec
    return db


def _make_mock_hue():
    mock_hue = MagicMock()
    mock_hue.start = AsyncMock()
    mock_hue.stop = AsyncMock()
    mock_hue.render = AsyncMock()
    mock_hue.handle_bridge_error = AsyncMock(return_value=False)
    return mock_hue


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_initial_state_is_idle():
    """A freshly-constructed coordinator is idle."""
    db = _make_db_with_empty_results()
    broadcaster = StatusBroadcaster()
    coord = StreamingCoordinator(
        db=db,
        capture_registry=None,
        broadcaster=broadcaster,
        hue_streamer=_make_mock_hue(),
    )
    assert coord.state == "idle"


@pytest.mark.asyncio
async def test_stop_when_idle_is_noop():
    """stop() called when idle returns immediately and stays idle."""
    db = _make_db_with_empty_results()
    broadcaster = StatusBroadcaster()
    coord = StreamingCoordinator(
        db=db,
        capture_registry=None,
        broadcaster=broadcaster,
        hue_streamer=_make_mock_hue(),
    )
    await coord.stop()  # must not raise
    assert coord.state == "idle"


@pytest.mark.asyncio
async def test_start_transitions_idle_to_streaming():
    """start() transitions idle -> starting -> streaming and invokes the Hue sink."""
    db = _make_db_with_empty_results()
    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()

    capture = make_mock_capture(_solid_blue_frame())
    registry = _MockRegistry(capture)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
    )
    assert coord.state == "idle"

    await coord.start("cfg-1")
    # Give the task a tick to enter streaming state
    for _ in range(50):
        if coord.state == "streaming":
            break
        await asyncio.sleep(0.01)
    assert coord.state == "streaming"
    mock_hue.start.assert_awaited_once_with("cfg-1")

    await coord.stop()
    assert coord.state == "idle"
    mock_hue.stop.assert_awaited()


@pytest.mark.asyncio
async def test_start_when_already_streaming_is_noop():
    """start() is a no-op when state is not idle/error."""
    db = _make_db_with_empty_results()
    broadcaster = MagicMock()
    broadcaster.push_state = AsyncMock()
    broadcaster.update_metrics = MagicMock()
    broadcaster.start_heartbeat = AsyncMock()
    broadcaster.stop_heartbeat = AsyncMock()

    coord = StreamingCoordinator(
        db=db,
        capture_registry=None,
        broadcaster=broadcaster,
        hue_streamer=_make_mock_hue(),
    )
    coord._state = "streaming"

    original_task = coord._task
    await coord.start("cfg-001")

    assert coord.state == "streaming"
    assert coord._task is original_task
    broadcaster.push_state.assert_not_called()


@pytest.mark.asyncio
async def test_start_acquire_failure_pushes_error():
    """If registry.acquire raises RuntimeError, state transitions to error."""
    db = _make_db_with_empty_results()
    broadcaster = MagicMock()
    broadcaster.push_state = AsyncMock()
    broadcaster.update_metrics = MagicMock()
    broadcaster.start_heartbeat = AsyncMock()
    broadcaster.stop_heartbeat = AsyncMock()

    failing_registry = MagicMock()
    failing_registry.acquire = MagicMock(side_effect=RuntimeError("Device busy"))

    coord = StreamingCoordinator(
        db=db,
        capture_registry=failing_registry,
        broadcaster=broadcaster,
        hue_streamer=_make_mock_hue(),
    )

    await coord.start("cfg-fail")
    assert coord.state == "error"

    # error push_state must explicitly clear active config/device (D-06)
    error_calls = [
        c for c in broadcaster.push_state.call_args_list
        if c.args and c.args[0] == "error"
    ]
    assert error_calls
    assert error_calls[0].kwargs.get("active_config_id") is None
    assert error_calls[0].kwargs.get("active_device_path") is None


# ---------------------------------------------------------------------------
# Frame loop tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frame_loop_calls_hue_render_per_frame():
    """Each captured frame triggers hue.render(region_gradients)."""
    db = _make_db_with_empty_results()
    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()

    capture = make_mock_capture(_solid_blue_frame())
    registry = _MockRegistry(capture)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
    )

    await coord.start("cfg-1")
    # Let the loop run a few frames
    await asyncio.sleep(0.2)
    await coord.stop()

    assert mock_hue.render.call_count > 0


@pytest.mark.asyncio
async def test_frame_loop_passes_region_gradients_to_hue_render():
    """region_gradients dict is keyed by region_id with (N_region, 3) ndarrays."""
    # Build a DB where _resolve_device_path returns no assignment (CAPTURE_DEVICE)
    # and _build_region_plan returns one region with N_region=1.
    # Plan 06: route by SQL content because _load_wled_device_rows now also
    # runs against this DB between hue.start and _build_region_plan.
    polygon = json.dumps([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])

    region_row = MagicMock()
    region_row.__getitem__ = MagicMock(side_effect=lambda k: {
        "region_id": "r1",
        "polygon": polygon,
        "n_region": 1,
        "orientation": "auto",
    }[k])

    db = MagicMock()

    async def _exec(*args, **kwargs):
        sql = args[0] if args else ""
        if "wled_devices WHERE enabled" in sql:
            # No WLED devices registered.
            return _empty_cursor()
        if "FROM wled_channels" in sql:
            return _empty_cursor()
        if "FROM regions r" in sql:
            cur = MagicMock()
            cur.__aenter__ = AsyncMock(return_value=cur)
            cur.__aexit__ = AsyncMock(return_value=None)
            cur.fetchone = AsyncMock(return_value=None)
            cur.fetchall = AsyncMock(return_value=[region_row])
            return cur
        # _resolve_device_path: camera_assignments / known_cameras → empty.
        return _empty_cursor()

    db.execute = _exec

    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()

    capture = make_mock_capture(_solid_blue_frame())
    registry = _MockRegistry(capture)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
    )

    await coord.start("cfg-2")
    await asyncio.sleep(0.15)
    await coord.stop()

    assert mock_hue.render.call_count > 0
    # First positional arg of any render call is the region_gradients dict
    last_call = mock_hue.render.call_args_list[-1]
    region_gradients = last_call.args[0]
    assert isinstance(region_gradients, dict)
    assert "r1" in region_gradients
    grad = region_gradients["r1"]
    assert isinstance(grad, np.ndarray)
    assert grad.dtype == np.uint8
    assert grad.shape[1] == 3   # (N, 3) RGB
    assert grad.shape[0] >= 1   # at least one sample


@pytest.mark.asyncio
async def test_frame_loop_calls_wled_render_when_sink_present():
    """If a WLED sink is injected, render is called once per frame."""
    db = _make_db_with_empty_results()
    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()
    mock_wled = MagicMock()
    mock_wled.start = AsyncMock()
    mock_wled.stop = AsyncMock()
    mock_wled.render = AsyncMock()
    mock_wled.health_snapshot = MagicMock(return_value={})

    capture = make_mock_capture(_solid_blue_frame())
    registry = _MockRegistry(capture)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
        wled_streamer=mock_wled,
    )

    await coord.start("cfg-w")
    await asyncio.sleep(0.15)
    await coord.stop()

    assert mock_wled.render.call_count > 0
    mock_wled.stop.assert_awaited()


@pytest.mark.asyncio
async def test_stop_releases_capture_device():
    """After start() acquires the device, stop() releases it via the registry."""
    db = _make_db_with_empty_results()
    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()

    capture = make_mock_capture(_solid_blue_frame())
    registry = _MockRegistry(capture)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
    )

    await coord.start("cfg-rel")
    await asyncio.sleep(0.05)
    await coord.stop()

    assert registry.acquire_calls, "registry.acquire should be called"
    assert registry.release_calls, "registry.release should be called"
    # Acquire and release with the same path
    assert registry.acquire_calls[0] == registry.release_calls[0]


@pytest.mark.asyncio
async def test_frame_loop_capture_runtime_error_with_failed_reconnect_pushes_error():
    """RuntimeError in wait_for_new_frame triggers reconnect; failed reconnect -> error."""
    db = _make_db_with_empty_results()
    broadcaster = MagicMock()
    broadcaster.push_state = AsyncMock()
    broadcaster.update_metrics = MagicMock()
    broadcaster.start_heartbeat = AsyncMock()
    broadcaster.stop_heartbeat = AsyncMock()

    mock_hue = _make_mock_hue()

    capture = make_mock_capture(_solid_blue_frame())
    capture.wait_for_new_frame = AsyncMock(side_effect=RuntimeError("Device gone"))
    registry = _MockRegistry(capture)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
    )

    # Force capture_reconnect_loop to immediately return False
    async def _fail_reconnect():
        return False

    coord._capture_reconnect_loop = _fail_reconnect

    await coord.start("cfg-rt")
    # Wait for the loop to error out
    for _ in range(50):
        if coord.state == "error":
            break
        await asyncio.sleep(0.01)

    # The frame_loop returns; awaiting the task allows finally{} to run.
    if coord._task:
        await coord._task

    # An error state should have been pushed with cleared kwargs (D-06)
    error_calls = [
        c for c in broadcaster.push_state.call_args_list
        if c.args and c.args[0] == "error"
    ]
    assert error_calls
    assert error_calls[0].kwargs.get("active_config_id") is None
    assert error_calls[0].kwargs.get("active_device_path") is None


# ---------------------------------------------------------------------------
# Region plan tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_region_plan_returns_empty_when_query_fails():
    """Missing wled_* tables produce a logged warning and an empty plan."""
    db = MagicMock()

    async def _exec(*args, **kwargs):
        raise Exception("no such table: wled_light_assignments")

    db.execute = _exec

    broadcaster = StatusBroadcaster()
    coord = StreamingCoordinator(
        db=db,
        capture_registry=None,
        broadcaster=broadcaster,
        hue_streamer=_make_mock_hue(),
    )
    plan = await coord._build_region_plan("cfg-x")
    assert plan == {}


@pytest.mark.asyncio
async def test_build_region_plan_returns_mask_and_n_region():
    """A region row -> (RegionMask, N_region) entry in the plan."""
    polygon = json.dumps([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: {
        "region_id": "rA",
        "polygon": polygon,
        "n_region": 5,
        "orientation": "auto",
    }[k])

    cur = MagicMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=None)
    cur.fetchall = AsyncMock(return_value=[row])

    db = MagicMock()

    async def _exec(*args, **kwargs):
        return cur

    db.execute = _exec

    broadcaster = StatusBroadcaster()
    coord = StreamingCoordinator(
        db=db,
        capture_registry=None,
        broadcaster=broadcaster,
        hue_streamer=_make_mock_hue(),
    )
    plan = await coord._build_region_plan("cfg-y")
    assert "rA" in plan
    mask, n_region, orientation = plan["rA"]
    assert n_region == 5
    assert orientation == "auto"
    # mask is a RegionMask
    from services.color_math import RegionMask
    assert isinstance(mask, RegionMask)


# ---------------------------------------------------------------------------
# Capture reconnect tests (mirrored from test_streaming_service.py since this
# behavior moved to the coordinator)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capture_reconnect_loop_returns_true_on_success():
    """_capture_reconnect_loop returns True after capture.open() succeeds."""
    db = _make_db_with_empty_results()
    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()

    capture = make_mock_capture(_solid_blue_frame())
    attempt = 0

    def open_fails_once(*args, **kwargs):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise RuntimeError("Device disconnected")

    capture.open = MagicMock(side_effect=open_fails_once)

    registry = _MockRegistry(capture)
    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
    )
    coord._capture = capture
    coord._run_event.set()

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await coord._capture_reconnect_loop()

    assert result is True


@pytest.mark.asyncio
async def test_capture_reconnect_loop_returns_false_when_run_event_cleared():
    """_capture_reconnect_loop returns False when run_event is cleared during retry."""
    db = _make_db_with_empty_results()
    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()

    capture = make_mock_capture(_solid_blue_frame())
    registry = _MockRegistry(capture)
    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
    )
    coord._capture = capture
    coord._run_event.set()

    async def open_always_fails(*args, **kwargs):
        coord._run_event.clear()
        raise RuntimeError("Still disconnected")

    with patch("asyncio.to_thread", side_effect=open_always_fails):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await coord._capture_reconnect_loop()

    assert result is False


@pytest.mark.asyncio
async def test_capture_reconnect_pushes_reconnecting_with_active():
    """_capture_reconnect_loop pushes 'reconnecting' state with active config/device kwargs."""
    db = _make_db_with_empty_results()
    broadcaster = MagicMock()
    broadcaster.push_state = AsyncMock()
    broadcaster.update_metrics = MagicMock()
    broadcaster.start_heartbeat = AsyncMock()
    broadcaster.stop_heartbeat = AsyncMock()

    mock_hue = _make_mock_hue()
    capture = make_mock_capture(_solid_blue_frame())
    capture.open = MagicMock()  # succeeds immediately

    registry = _MockRegistry(capture)
    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
    )
    coord._capture = capture
    coord._run_event.set()
    coord._config_id = "cfg-recon"
    coord._device_path = "/dev/video3"

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await coord._capture_reconnect_loop()

    assert result is True

    reconnecting_calls = [
        c for c in broadcaster.push_state.call_args_list
        if c.args and c.args[0] == "reconnecting"
    ]
    assert reconnecting_calls
    assert reconnecting_calls[0].kwargs.get("active_config_id") == "cfg-recon"
    assert reconnecting_calls[0].kwargs.get("active_device_path") == "/dev/video3"


@pytest.mark.asyncio
async def test_capture_reconnect_does_not_touch_registry():
    """_capture_reconnect_loop calls capture.release/open directly, NOT registry."""
    db = _make_db_with_empty_results()
    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()

    capture = make_mock_capture(_solid_blue_frame())
    capture.open = MagicMock()

    registry = _MockRegistry(capture)
    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
    )
    coord._capture = capture
    coord._run_event.set()

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("asyncio.to_thread", side_effect=fake_to_thread):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await coord._capture_reconnect_loop()

    capture.release.assert_called()
    capture.open.assert_called()
    assert registry.acquire_calls == []
    assert registry.release_calls == []


# ---------------------------------------------------------------------------
# Wave 3 fan-out integration test (Plan 06)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_fans_out_to_hue_and_wled(monkeypatch):
    """One captured frame -> Hue.render + WLED.render both called.

    Per Plan 06 preamble:
      * Use ``monkeypatch.setattr`` for ``_build_region_plan`` so pytest auto-
        restores the class attribute on test exit (no leakage to subsequent
        tests).
      * Pass ``udp_port=41324`` to ``WledStreamer(...)`` (Plan 04 ctor kwarg)
        to redirect packets to a loopback ``udp_listener`` without monkey-
        patching the module-level ``UDP_PORT`` constant.
    """
    from services.streaming_coordinator import StreamingCoordinator
    from services.wled_streamer import WledStreamer
    from services.color_math import build_polygon_mask
    from tests.fixtures.wled_loopback import udp_listener

    db = MagicMock()

    async def _exec(*args, **kwargs):
        cur = MagicMock()
        cur.__aenter__ = AsyncMock(return_value=cur)
        cur.__aexit__ = AsyncMock(return_value=None)
        sql = args[0] if args else ""
        if "wled_devices WHERE enabled" in sql:
            cur.fetchall = AsyncMock(return_value=[
                {"id": "d1", "ip": "127.0.0.1", "led_count": 10, "enabled": 1},
            ])
        elif "FROM wled_channels" in sql:
            cur.fetchall = AsyncMock(return_value=[
                {"channel_id": "c1", "start_led": 0, "end_led": 9, "region_id": "r1"},
            ])
        else:
            cur.fetchone = AsyncMock(return_value=None)
            cur.fetchall = AsyncMock(return_value=[])
        return cur

    db.execute = _exec
    db.commit = AsyncMock()

    broadcaster = StatusBroadcaster()
    mock_hue = MagicMock()
    mock_hue.start = AsyncMock()
    mock_hue.stop = AsyncMock()
    mock_hue.render = AsyncMock()
    mock_hue.handle_bridge_error = AsyncMock(return_value=False)

    capture = make_mock_capture(_solid_blue_frame())
    registry = _MockRegistry(capture)

    # Real WledStreamer with loopback-port override (Plan 04 constructor kwarg).
    # NO module-level patching of UDP_PORT.
    real_wled = WledStreamer(udp_port=41324)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
        wled_streamer=real_wled,
    )

    # Inject a full-frame region via monkeypatch so pytest restores the class
    # attribute on test exit (no global state leakage into subsequent tests).
    fake_region = build_polygon_mask(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    )

    async def _fake_plan(self, cfg):
        return {"r1": (fake_region, 10, "auto")}  # N_region=10, orientation=auto

    monkeypatch.setattr(
        "services.streaming_coordinator.StreamingCoordinator._build_region_plan",
        _fake_plan,
    )

    with udp_listener(port=41324) as q:
        await coord.start("cfg-1")
        await asyncio.sleep(0.3)
        await coord.stop()

    assert mock_hue.render.await_count > 0, "Hue render must be called"
    assert not q.empty(), "WLED listener must receive at least one packet"
