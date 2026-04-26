"""StatusBroadcaster: WebSocket fan-out manager for streaming metrics."""
import asyncio
import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


# Sentinel to distinguish "caller omitted the kwarg" from "caller passed None".
# Used by push_state() so callers can opt-in to setting active_config_id /
# active_device_path without silently clearing them when the kwarg is left off.
_UNSET = object()


class StatusBroadcaster:
    """Manages WebSocket connections and broadcasts streaming metrics.

    The frame loop calls update_metrics() at 50 Hz to silently update internal
    state. A 1 Hz heartbeat loop delivers metrics to all connected clients.
    State transitions via push_state() bypass the rate limit and are sent
    immediately to all clients.
    """

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._metrics: dict = {
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
        self._heartbeat_task: asyncio.Task | None = None

    async def connect(self, ws: WebSocket) -> None:
        """Accept a WebSocket connection and send the current metrics snapshot."""
        await ws.accept()
        try:
            await ws.send_text(json.dumps(self._metrics))
        except Exception:
            logger.debug("WebSocket disconnected during initial send, not adding to pool")
            return
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a WebSocket connection. Safe to call with unknown connections."""
        try:
            self._connections.remove(ws)
        except ValueError:
            pass

    def update_metrics(self, data: dict) -> None:
        """Update internal metrics without sending to clients.

        Called from the 50 Hz frame loop. Clients receive updates at 1 Hz via
        the heartbeat loop; this avoids flooding WebSocket clients.
        """
        self._metrics.update(data)

    async def push_state(
        self,
        state: str,
        error: str | None = None,
        active_config_id: str | None | object = _UNSET,
        active_device_path: str | None | object = _UNSET,
        wled_devices: dict | object = _UNSET,
    ) -> None:
        """Update state and immediately broadcast to all clients.

        Bypasses the 1 Hz rate limit so state transitions (streaming, error,
        idle) are delivered instantly.

        Per Phase 16 D-05/D-06: active_config_id and active_device_path may be
        passed to update the currently-active entertainment config and device.
        Omission preserves the current value in _metrics; passing explicit None
        clears it. This distinguishes "I'm not touching that field" from "I'm
        clearing that field on idle/error".

        Per Phase 17 D-16: wled_devices may be passed to update the per-device
        WLED health dict. Omission preserves the current value (via _UNSET
        sentinel); passing an explicit dict (including ``{}``) overwrites.
        """
        self._metrics["state"] = state
        if error is not None:
            self._metrics["error"] = error
        elif "error" in self._metrics:
            del self._metrics["error"]
        if active_config_id is not _UNSET:
            self._metrics["active_config_id"] = active_config_id  # type: ignore[assignment]
        if active_device_path is not _UNSET:
            self._metrics["active_device_path"] = active_device_path  # type: ignore[assignment]
        if wled_devices is not _UNSET:
            self._metrics["wled_devices"] = wled_devices  # type: ignore[assignment]
        await self._send_to_all()

    async def _send_to_all(self) -> None:
        """Send current metrics to all connected clients; remove dead ones."""
        dead: list[WebSocket] = []
        payload = json.dumps(self._metrics)
        for ws in list(self._connections):
            try:
                await ws.send_text(payload)
            except Exception:
                logger.debug("WebSocket send failed, marking for removal")
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def _heartbeat_loop(self) -> None:
        """Send metrics to all clients once per second (1 Hz)."""
        while True:
            await asyncio.sleep(1.0)
            await self._send_to_all()

    async def start_heartbeat(self) -> None:
        """Start the 1 Hz heartbeat task."""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop_heartbeat(self) -> None:
        """Cancel and await the heartbeat task cleanly."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
