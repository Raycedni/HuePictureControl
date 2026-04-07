"""WebSocket /ws/preview endpoint for binary JPEG frame streaming.

Exports:
    router -- APIRouter with /ws/preview WebSocket endpoint
"""
import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preview"])


async def _resolve_device_path(db, device: str) -> Optional[str]:
    """Resolve a device identifier to a filesystem path.

    If *device* starts with ``/dev/`` it is returned as-is (direct path).
    Otherwise it is treated as a stable_id and resolved via the
    ``known_cameras`` table to its ``last_device_path``.

    Returns None when the stable_id is not found in known_cameras.
    """
    if device.startswith("/dev/"):
        return device
    async with db.execute(
        "SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
        (device,),
    ) as cursor:
        row = await cursor.fetchone()
    return row["last_device_path"] if row else None


@router.websocket("/ws/preview")
async def ws_preview(
    websocket: WebSocket,
    device: Optional[str] = Query(default=None),
):
    """Stream live JPEG frames from a specific capture device.

    The ``?device=`` query parameter is **required** (per D-04).
    Accepts either a device path (``/dev/video0``) or a stable_id
    (``vid:pid:serial``).  Stable IDs are resolved once at connection
    time via the ``known_cameras`` table.

    If the device is unavailable the connection stays open and retries
    every 1 second (per D-02).  Preview uses ``registry.get()`` — a
    non-ref-counted peek (per D-01).
    """
    if device is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    registry = websocket.app.state.capture_registry
    db = websocket.app.state.db

    # Resolve stable_id to device_path once at connection time (per D-03)
    device_path = await _resolve_device_path(db, device)

    try:
        while True:
            if device_path is None:
                # stable_id not found — stay in retry loop
                await asyncio.sleep(1.0)
                continue
            backend = registry.get(device_path)
            if backend is None:
                await asyncio.sleep(1.0)
                continue
            try:
                jpeg_bytes = await backend.get_jpeg()
                await websocket.send_bytes(jpeg_bytes)
                await asyncio.sleep(0.016)
            except RuntimeError:
                logger.debug("ws_preview: capture device unavailable, retrying in 1s")
                await asyncio.sleep(1.0)
    except (WebSocketDisconnect, Exception):
        logger.debug("ws_preview: client disconnected")
