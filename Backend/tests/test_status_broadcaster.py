"""Unit tests for StatusBroadcaster WebSocket fan-out manager."""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws():
    """Create a mock WebSocket with send_text and accept as AsyncMock."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_appends_connection():
    """connect() accepts the WebSocket and grows _connections by 1."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)
    assert ws in sb._connections


@pytest.mark.asyncio
async def test_disconnect_removes_connection():
    """disconnect() removes the WebSocket from _connections."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)
    sb.disconnect(ws)
    assert ws not in sb._connections


@pytest.mark.asyncio
async def test_disconnect_unknown_connection_no_error():
    """disconnect() with an unknown WebSocket raises no error."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    sb.disconnect(ws)  # should not raise


@pytest.mark.asyncio
async def test_update_metrics_updates_internal_state():
    """update_metrics() updates _metrics without sending to clients."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)
    ws.send_text.reset_mock()  # clear send from connect

    sb.update_metrics({"fps": 30, "latency_ms": 5})

    assert sb._metrics["fps"] == 30
    assert sb._metrics["latency_ms"] == 5
    ws.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_update_metrics_with_no_connections_no_error():
    """update_metrics() with no connections does not error."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    sb.update_metrics({"fps": 25})
    assert sb._metrics["fps"] == 25


@pytest.mark.asyncio
async def test_push_state_updates_state_and_broadcasts():
    """push_state() updates state field and immediately broadcasts to all clients."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)
    ws.send_text.reset_mock()

    await sb.push_state("streaming")

    assert sb._metrics["state"] == "streaming"
    ws.send_text.assert_called_once()
    payload = json.loads(ws.send_text.call_args[0][0])
    assert payload["state"] == "streaming"


@pytest.mark.asyncio
async def test_push_state_with_error_includes_error_in_payload():
    """push_state() with error kwarg includes error key in broadcast payload."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)
    ws.send_text.reset_mock()

    await sb.push_state("error", error="Bridge disconnected")

    payload = json.loads(ws.send_text.call_args[0][0])
    assert payload["state"] == "error"
    assert payload["error"] == "Bridge disconnected"


@pytest.mark.asyncio
async def test_connect_sends_current_metrics_snapshot():
    """connect() sends the current _metrics snapshot to the newly connected client."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    sb.update_metrics({"fps": 24, "latency_ms": 10})

    ws = _make_ws()
    await sb.connect(ws)

    ws.send_text.assert_called_once()
    payload = json.loads(ws.send_text.call_args[0][0])
    assert payload["fps"] == 24
    assert payload["latency_ms"] == 10


@pytest.mark.asyncio
async def test_initial_metrics_defaults():
    """Initial _metrics has expected default values (per Phase 16 D-06, Phase 17 D-16)."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    assert sb._metrics == {
        "state": "idle",
        "fps": 0,
        "latency_ms": 0,
        "packets_sent": 0,
        "packets_dropped": 0,
        "seq": 0,
        "active_config_id": None,
        "active_device_path": None,
        "wled_devices": {},
    }


@pytest.mark.asyncio
async def test_push_state_sets_active_config_id_and_device_path():
    """push_state() with active_config_id and active_device_path kwargs populates payload and _metrics."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)
    ws.send_text.reset_mock()

    await sb.push_state("streaming", active_config_id="cfg-abc", active_device_path="/dev/video0")

    payload = json.loads(ws.send_text.call_args[0][0])
    assert payload["state"] == "streaming"
    assert payload["active_config_id"] == "cfg-abc"
    assert payload["active_device_path"] == "/dev/video0"
    assert sb._metrics["active_config_id"] == "cfg-abc"
    assert sb._metrics["active_device_path"] == "/dev/video0"


@pytest.mark.asyncio
async def test_push_state_clears_active_to_none():
    """Explicit None kwargs clear active values on broadcast and internal state."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)

    # First set values
    await sb.push_state("streaming", active_config_id="cfg-1", active_device_path="/dev/video0")
    ws.send_text.reset_mock()

    # Now explicit None — must clear
    await sb.push_state("idle", active_config_id=None, active_device_path=None)

    payload = json.loads(ws.send_text.call_args[0][0])
    assert payload["state"] == "idle"
    assert payload["active_config_id"] is None
    assert payload["active_device_path"] is None
    assert sb._metrics["active_config_id"] is None
    assert sb._metrics["active_device_path"] is None


@pytest.mark.asyncio
async def test_push_state_omitted_kwargs_preserve_current():
    """Omitting active kwargs on push_state preserves current values (no silent clear)."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)

    # Set values first
    await sb.push_state("streaming", active_config_id="cfg-xyz", active_device_path="/dev/video1")
    ws.send_text.reset_mock()

    # Second call without kwargs — must NOT clear to None
    await sb.push_state("starting")

    payload = json.loads(ws.send_text.call_args[0][0])
    assert payload["state"] == "starting"
    assert payload["active_config_id"] == "cfg-xyz"
    assert payload["active_device_path"] == "/dev/video1"
    assert sb._metrics["active_config_id"] == "cfg-xyz"
    assert sb._metrics["active_device_path"] == "/dev/video1"


@pytest.mark.asyncio
async def test_connect_initial_snapshot_includes_active_fields():
    """Fresh connect() sends an initial snapshot that includes both new keys."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)

    ws.send_text.assert_called_once()
    payload = json.loads(ws.send_text.call_args[0][0])
    assert "active_config_id" in payload
    assert "active_device_path" in payload
    assert payload["active_config_id"] is None
    assert payload["active_device_path"] is None


@pytest.mark.asyncio
async def test_update_metrics_accepts_active_fields():
    """update_metrics() accepts active_config_id/active_device_path via dict update (no broadcast)."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)
    ws.send_text.reset_mock()

    sb.update_metrics({"active_config_id": "cfg-1", "active_device_path": "/dev/video2"})

    assert sb._metrics["active_config_id"] == "cfg-1"
    assert sb._metrics["active_device_path"] == "/dev/video2"
    ws.send_text.assert_not_called()


@pytest.mark.asyncio
async def test_heartbeat_loop_sends_to_all_clients():
    """_heartbeat_loop sends _metrics to all connected clients once per second."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws1 = _make_ws()
    ws2 = _make_ws()
    await sb.connect(ws1)
    await sb.connect(ws2)
    ws1.send_text.reset_mock()
    ws2.send_text.reset_mock()

    # Manually invoke one heartbeat tick
    with patch("asyncio.sleep", new=AsyncMock()):
        # Run one iteration of _heartbeat_loop by calling _send_to_all directly
        await sb._send_to_all()

    ws1.send_text.assert_called_once()
    ws2.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_heartbeat_loop_removes_dead_connection():
    """_heartbeat_loop removes dead connections and continues to healthy ones."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    dead_ws = _make_ws()
    alive_ws = _make_ws()

    # Connect both while send_text works, then make dead_ws fail afterwards
    await sb.connect(dead_ws)
    await sb.connect(alive_ws)
    dead_ws.send_text = AsyncMock(side_effect=Exception("connection closed"))
    alive_ws.send_text.reset_mock()

    await sb._send_to_all()

    assert dead_ws not in sb._connections
    assert alive_ws in sb._connections
    alive_ws.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_start_and_stop_heartbeat():
    """start_heartbeat() creates a task; stop_heartbeat() cancels it cleanly."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()

    assert sb._heartbeat_task is None

    await sb.start_heartbeat()
    assert sb._heartbeat_task is not None
    assert not sb._heartbeat_task.done()

    await sb.stop_heartbeat()
    assert sb._heartbeat_task.done()


# ---------------------------------------------------------------------------
# Phase 17 D-16: wled_devices payload key + push_state kwarg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wled_devices_key_present_on_init():
    """`wled_devices` key exists in _metrics at init and equals empty dict (D-16)."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    assert "wled_devices" in sb._metrics
    assert sb._metrics["wled_devices"] == {}


@pytest.mark.asyncio
async def test_update_metrics_merges_wled_devices():
    """update_metrics({'wled_devices': ...}) merges into _metrics (no broadcast)."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    sb.update_metrics({
        "wled_devices": {
            "d1": {
                "last_error": None,
                "last_success_at": "2026-04-20T00:00:00+00:00",
                "in_cooldown": False,
            }
        }
    })
    assert sb._metrics["wled_devices"]["d1"]["in_cooldown"] is False
    assert sb._metrics["wled_devices"]["d1"]["last_error"] is None


@pytest.mark.asyncio
async def test_push_state_preserves_wled_devices_without_kwarg():
    """push_state() without wled_devices kwarg preserves the existing value (via _UNSET)."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    sb._metrics["wled_devices"] = {
        "d1": {"last_error": "x", "last_success_at": None, "in_cooldown": True}
    }
    await sb.push_state("streaming")  # no wled_devices kwarg
    assert sb._metrics["wled_devices"]["d1"]["in_cooldown"] is True
    assert sb._metrics["wled_devices"]["d1"]["last_error"] == "x"


@pytest.mark.asyncio
async def test_push_state_clears_wled_devices_with_explicit_empty():
    """push_state(wled_devices={}) explicitly clears the dict to empty."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    sb._metrics["wled_devices"] = {
        "d1": {"last_error": None, "last_success_at": None, "in_cooldown": False}
    }
    await sb.push_state("idle", wled_devices={})
    assert sb._metrics["wled_devices"] == {}


@pytest.mark.asyncio
async def test_push_state_sets_wled_devices_with_dict():
    """push_state(wled_devices=payload) sets the key AND emits the payload to clients."""
    from services.status_broadcaster import StatusBroadcaster
    sb = StatusBroadcaster()
    ws = _make_ws()
    await sb.connect(ws)
    ws.send_text.reset_mock()

    payload = {
        "d1": {
            "last_error": None,
            "last_success_at": "2026-04-20T00:00:00+00:00",
            "in_cooldown": False,
        }
    }
    await sb.push_state("streaming", wled_devices=payload)
    assert sb._metrics["wled_devices"] == payload

    ws.send_text.assert_called_once()
    sent = json.loads(ws.send_text.call_args[0][0])
    assert sent["wled_devices"]["d1"]["in_cooldown"] is False
