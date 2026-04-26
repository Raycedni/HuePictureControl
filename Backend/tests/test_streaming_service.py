"""Tests for HueStreamer (Phase 17 Plan 05 refactor).

The pre-refactor StreamingService combined capture lifecycle, frame loop, and
Hue DTLS sink. After Plan 05:
  * StreamingCoordinator owns capture + frame loop + broadcaster (tested in
    test_streaming_coordinator.py).
  * HueStreamer owns the Hue-only concerns: channel-map load, bridge / DTLS
    setup, per-channel set_input, and bridge-only reconnect.

Tests in this module focus on the Hue-side narrow surface only:
  * _load_channel_map (DB + bridge fallback) — copied verbatim from old code.
  * _reconnect_loop (bridge-only, with caller-driven cancellation).
  * render(region_gradients) — averages each region's (N, 3) gradient back
    to one RGB and calls set_input with (x, y, bri, channel_id).

State-machine, capture, and frame-loop tests live in
test_streaming_coordinator.py. Phase 17 Plan 06 removed the
``StreamingService`` compatibility shim — ``main.py`` now imports
``StreamingCoordinator`` directly and ``app.state.coordinator`` is the only
surface routers see.
"""
import asyncio
import json
import sys

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers (kept compact — full-fixture helpers live in
# test_streaming_coordinator.py)
# ---------------------------------------------------------------------------


def _make_streaming_db_cursor(rows):
    """Mock async cursor that returns ``rows`` from fetchall()."""
    cursor = MagicMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    cursor.__aenter__ = AsyncMock(return_value=cursor)
    cursor.__aexit__ = AsyncMock(return_value=False)
    return cursor


def _make_region_row(light_id, polygon_points=None, region_id="region-001"):
    if polygon_points is None:
        polygon_points = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: {
        "id": region_id,
        "polygon": json.dumps(polygon_points),
        "light_id": light_id,
    }[k])
    return row


def _make_channel_row(channel_id, polygon_points=None, region_id="region-001"):
    if polygon_points is None:
        polygon_points = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda k: {
        "region_id": region_id,
        "channel_id": channel_id,
        "polygon": json.dumps(polygon_points),
    }[k])
    return row


def _make_channel_map_db(assignment_rows, region_rows):
    """Two-cursor DB: 1st execute → assignments, 2nd → regions."""
    assign_cursor = _make_streaming_db_cursor(assignment_rows)
    region_cursor = _make_streaming_db_cursor(region_rows)
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[assign_cursor, region_cursor])
    return db


# ---------------------------------------------------------------------------
# Import path — module-scoped fixture installs a pykit stub before import
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hue_imports():
    """Import HueStreamer with pykit mocked. Module-scoped so we re-import once."""
    mock_bridge_cls = MagicMock()
    mock_entertainment_cls = MagicMock()
    mock_streaming_cls = MagicMock()
    mock_create_bridge = MagicMock(return_value=mock_bridge_cls())

    pykit_mock = MagicMock()
    pykit_mock.create_bridge = mock_create_bridge
    pykit_mock.Entertainment = mock_entertainment_cls
    pykit_mock.Streaming = mock_streaming_cls

    sys.modules["hue_entertainment_pykit"] = pykit_mock
    # Force fresh import with the pykit mock in place
    sys.modules.pop("services.streaming_service", None)
    sys.modules.pop("services.streaming_coordinator", None)

    from services.streaming_service import HueStreamer

    yield HueStreamer, mock_create_bridge, mock_entertainment_cls, mock_streaming_cls

    sys.modules.pop("hue_entertainment_pykit", None)
    sys.modules.pop("services.streaming_service", None)
    sys.modules.pop("services.streaming_coordinator", None)


# ---------------------------------------------------------------------------
# (Plan 06 removed the StreamingService compatibility shim — there's no
# longer an alias to assert. Routers and main.py now import
# StreamingCoordinator directly; see test_streaming_coordinator.py.)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _load_channel_map tests (Hue-only DB query — preserved verbatim semantics)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_channel_map_returns_dict_with_masks(hue_imports):
    """_load_channel_map returns {channel_id: RegionMask} from regions + bridge."""
    HueStreamer, *_ = hue_imports

    rows = [
        _make_region_row("light-A", region_id="r1"),
        _make_region_row("light-B", [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5]], region_id="r2"),
    ]

    db = _make_channel_map_db([], rows)

    sink = HueStreamer(db)
    with patch("services.streaming_service.resolve_light_to_channel_map",
               new_callable=AsyncMock,
               return_value={"light-A": [0], "light-B": [1]}):
        channel_map = await sink._load_channel_map(
            "cfg-001", "192.168.1.1", "testuser"
        )

    assert len(channel_map) == 2
    assert 0 in channel_map and 1 in channel_map
    from services.color_math import RegionMask
    for region in channel_map.values():
        assert isinstance(region, RegionMask)
        assert region.mask.dtype == np.uint8
        assert region.mask.shape == (480, 640)


@pytest.mark.asyncio
async def test_load_channel_map_empty_returns_empty_dict(hue_imports):
    """No regions / no assignments → empty dict."""
    HueStreamer, *_ = hue_imports

    db = _make_channel_map_db([], [])

    sink = HueStreamer(db)
    with patch("services.streaming_service.resolve_light_to_channel_map",
               new_callable=AsyncMock, return_value={}):
        channel_map = await sink._load_channel_map(
            "cfg-001", "192.168.1.1", "testuser"
        )

    assert channel_map == {}


@pytest.mark.asyncio
async def test_load_channel_map_gradient_light_maps_multiple_channels(hue_imports):
    """A region assigned to a gradient light fans out to all its channels (fallback)."""
    HueStreamer, *_ = hue_imports

    rows = [_make_region_row("gradient-light", region_id="r1")]

    db = _make_channel_map_db([], rows)

    sink = HueStreamer(db)
    with patch("services.streaming_service.resolve_light_to_channel_map",
               new_callable=AsyncMock,
               return_value={"gradient-light": [1, 2, 3]}):
        channel_map = await sink._load_channel_map(
            "cfg-001", "192.168.1.1", "testuser"
        )

    assert len(channel_map) == 3
    assert 1 in channel_map and 2 in channel_map and 3 in channel_map


@pytest.mark.asyncio
async def test_load_channel_map_uses_assignments_over_fallback(hue_imports):
    """light_assignments takes precedence over light_id fallback for same region."""
    HueStreamer, *_ = hue_imports

    assign_row = _make_channel_row(
        0, [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]], region_id="r1"
    )
    region_row = _make_region_row("light-A", region_id="r1")

    db = _make_channel_map_db([assign_row], [region_row])

    sink = HueStreamer(db)
    with patch("services.streaming_service.resolve_light_to_channel_map",
               new_callable=AsyncMock, return_value={"light-A": [0, 1]}):
        channel_map = await sink._load_channel_map(
            "cfg-001", "192.168.1.1", "testuser"
        )

    # r1 is in assigned_region_ids → fallback skips it. Only channel 0
    # (from the explicit assignment) should appear.
    assert 0 in channel_map
    assert 1 not in channel_map


# ---------------------------------------------------------------------------
# _load_channel_to_region tests (new in Plan 05)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_channel_to_region_uses_assignments(hue_imports):
    """Explicit light_assignments rows project (channel_id, region_id) directly."""
    HueStreamer, *_ = hue_imports

    assign_row = MagicMock()
    assign_row.__getitem__ = MagicMock(side_effect=lambda k: {
        "region_id": "r-explicit",
        "channel_id": 7,
    }[k])

    region_rows: list = []  # no fallback regions
    assign_cursor = _make_streaming_db_cursor([assign_row])
    region_cursor = _make_streaming_db_cursor(region_rows)

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[assign_cursor, region_cursor])

    sink = HueStreamer(db)
    with patch("services.streaming_service.resolve_light_to_channel_map",
               new_callable=AsyncMock, return_value={}):
        mapping = await sink._load_channel_to_region(
            "cfg", "192.168.1.1", "testuser"
        )

    assert mapping == {7: "r-explicit"}


@pytest.mark.asyncio
async def test_load_channel_to_region_uses_fallback(hue_imports):
    """Region with light_id but no assignment fans out same region_id to all its channels."""
    HueStreamer, *_ = hue_imports

    region_row = MagicMock()
    region_row.__getitem__ = MagicMock(side_effect=lambda k: {
        "id": "r-grad",
        "light_id": "gradient-light",
    }[k])

    assign_cursor = _make_streaming_db_cursor([])
    region_cursor = _make_streaming_db_cursor([region_row])

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[assign_cursor, region_cursor])

    sink = HueStreamer(db)
    with patch("services.streaming_service.resolve_light_to_channel_map",
               new_callable=AsyncMock,
               return_value={"gradient-light": [10, 11, 12]}):
        mapping = await sink._load_channel_to_region(
            "cfg", "192.168.1.1", "testuser"
        )

    assert mapping == {10: "r-grad", 11: "r-grad", 12: "r-grad"}


# ---------------------------------------------------------------------------
# render() tests — averages region gradient to one RGB and calls set_input
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_noop_when_streaming_not_started(hue_imports):
    """render() before start() is a safe no-op."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())
    # No exception even with garbage gradient input
    await sink.render({"r1": np.zeros((1, 3), dtype=np.uint8)})


@pytest.mark.asyncio
async def test_render_calls_set_input_per_channel(hue_imports):
    """One mapped channel → exactly one set_input call with (x, y, bri, ch_id)."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())
    streaming_mock = MagicMock()
    sink._streaming = streaming_mock
    sink._channel_to_region = {0: "r1"}

    # Solid-blue gradient: RGB = (0, 0, 255). gradient.mean(axis=0) = same.
    region_gradients = {"r1": np.array([[0, 0, 255]], dtype=np.uint8)}

    await sink.render(region_gradients)

    streaming_mock.set_input.assert_called_once()
    args, _ = streaming_mock.set_input.call_args
    inp = args[0]
    assert len(inp) == 4
    x, y, bri, ch_id = inp
    assert ch_id == 0
    assert isinstance(x, float)
    assert isinstance(y, float)
    assert bri >= 0.01  # dark-scene clamp


@pytest.mark.asyncio
async def test_render_brightness_clamped_for_black(hue_imports):
    """Black gradient → bri >= 0.01 (dark-scene protection)."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())
    streaming_mock = MagicMock()
    sink._streaming = streaming_mock
    sink._channel_to_region = {0: "rBlack"}

    region_gradients = {"rBlack": np.zeros((1, 3), dtype=np.uint8)}
    await sink.render(region_gradients)

    args, _ = streaming_mock.set_input.call_args
    _, _, bri, _ = args[0]
    assert bri >= 0.01


@pytest.mark.asyncio
async def test_render_skips_channels_without_region_gradient(hue_imports):
    """If a channel's region_id is missing from region_gradients, skip set_input."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())
    streaming_mock = MagicMock()
    sink._streaming = streaming_mock
    sink._channel_to_region = {0: "rA", 1: "rMissing"}

    region_gradients = {"rA": np.array([[100, 100, 100]], dtype=np.uint8)}
    await sink.render(region_gradients)

    # Only one set_input call — the rMissing channel was skipped.
    assert streaming_mock.set_input.call_count == 1


@pytest.mark.asyncio
async def test_render_averages_n_sample_gradient(hue_imports):
    """For N>1, render uses gradient.mean(axis=0) to collapse to one RGB."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())
    streaming_mock = MagicMock()
    sink._streaming = streaming_mock
    sink._channel_to_region = {0: "r1"}

    # N=4 ramp: mean is (50, 100, 150)
    region_gradients = {
        "r1": np.array([
            [20, 70, 120],
            [40, 90, 140],
            [60, 110, 160],
            [80, 130, 180],
        ], dtype=np.uint8)
    }
    await sink.render(region_gradients)

    streaming_mock.set_input.assert_called_once()
    # If we monkeypatch rgb_to_xy we can assert the exact RGB seen.
    # Easier: re-run with rgb_to_xy patched to identity capture.
    captured: list = []
    streaming_mock.set_input.reset_mock()

    def _capture_rgb(r, g, b):
        captured.append((r, g, b))
        return (0.3, 0.3)

    with patch("services.streaming_service.rgb_to_xy", side_effect=_capture_rgb):
        await sink.render(region_gradients)

    assert captured == [(50, 100, 150)]


# ---------------------------------------------------------------------------
# _reconnect_loop tests (Hue bridge-only — capture is the coordinator's)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconnect_loop_succeeds_on_first_try(hue_imports):
    """_reconnect_loop returns True when activate succeeds immediately."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())

    with patch("services.streaming_service.activate_entertainment_config",
               new_callable=AsyncMock) as mock_activate:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await sink._reconnect_loop(
                "cfg-001", "192.168.1.100", "testuser"
            )

    assert result is True
    mock_activate.assert_called_once()


@pytest.mark.asyncio
async def test_reconnect_loop_exponential_backoff(hue_imports):
    """_reconnect_loop sleeps 1s, then 2s before succeeding on 3rd try."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())

    sleep_calls: list[float] = []
    attempt = 0

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    async def activate_fails_twice(bridge_ip, username, config_id):
        nonlocal attempt
        attempt += 1
        if attempt <= 2:
            raise Exception("Bridge unreachable")
        # Success on 3rd attempt

    with patch("services.streaming_service.activate_entertainment_config",
               side_effect=activate_fails_twice):
        with patch("asyncio.sleep", side_effect=fake_sleep):
            result = await sink._reconnect_loop(
                "cfg-001", "192.168.1.100", "testuser"
            )

    assert result is True
    assert len(sleep_calls) >= 2
    assert sleep_calls[0] == 1
    assert sleep_calls[1] == 2


@pytest.mark.asyncio
async def test_reconnect_loop_backoff_capped_at_30s(hue_imports):
    """_reconnect_loop delays cap at 30s."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())

    sleep_calls: list[float] = []
    attempt = 0
    MAX_ATTEMPTS = 10

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    async def activate_fails_many(bridge_ip, username, config_id):
        nonlocal attempt
        attempt += 1
        if attempt < MAX_ATTEMPTS:
            raise Exception("Bridge unreachable")

    with patch("services.streaming_service.activate_entertainment_config",
               side_effect=activate_fails_many):
        with patch("asyncio.sleep", side_effect=fake_sleep):
            result = await sink._reconnect_loop(
                "cfg-001", "192.168.1.100", "testuser"
            )

    assert result is True
    for delay in sleep_calls:
        assert delay <= 30


@pytest.mark.asyncio
async def test_handle_bridge_error_invokes_reconnect(hue_imports):
    """handle_bridge_error delegates to _reconnect_loop with stored bridge state."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())
    sink._config_id = "cfg-X"
    sink._bridge_ip = "10.0.0.1"
    sink._username = "u"

    # _reconnect_loop will succeed on the first call to activate
    with patch("services.streaming_service.activate_entertainment_config",
               new_callable=AsyncMock) as mock_activate:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            ok = await sink.handle_bridge_error(Exception("socket reset"))

    assert ok is True
    mock_activate.assert_called_once()


# ---------------------------------------------------------------------------
# stop() tests — Hue side only (no capture release here)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_calls_stop_stream_and_deactivate(hue_imports):
    """stop() invokes streaming.stop_stream then deactivate_entertainment_config."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())
    streaming_mock = MagicMock()
    streaming_mock.stop_stream = MagicMock()
    sink._streaming = streaming_mock
    sink._bridge_ip = "10.0.0.1"
    sink._username = "u"
    sink._config_id = "cfg-stop"

    call_order: list[str] = []

    def track_stop_stream(*args, **kwargs):
        call_order.append("stop_stream")

    streaming_mock.stop_stream = MagicMock(side_effect=track_stop_stream)

    async def track_deactivate(bridge_ip, username, config_id):
        call_order.append("deactivate")

    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    with patch("services.streaming_service.deactivate_entertainment_config",
               side_effect=track_deactivate):
        with patch("asyncio.to_thread", side_effect=fake_to_thread):
            await sink.stop()

    assert call_order == ["stop_stream", "deactivate"]
    # _streaming nulled out so a second stop is a no-op
    assert sink._streaming is None


@pytest.mark.asyncio
async def test_stop_is_safe_when_never_started(hue_imports):
    """stop() before start() does not raise."""
    HueStreamer, *_ = hue_imports

    sink = HueStreamer(MagicMock())
    await sink.stop()  # must not raise
    assert sink._streaming is None
