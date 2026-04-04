"""WebSocket /ws/preview endpoint for binary JPEG frame streaming.

Exports:
    router -- APIRouter with /ws/preview WebSocket endpoint
"""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preview"])


@router.websocket("/ws/preview")
async def ws_preview(websocket: WebSocket):
    """Stream live JPEG frames from the capture device as binary WebSocket messages.

    Sends raw MJPEG bytes directly from the capture card, avoiding the
    decode-then-re-encode overhead. If the capture device is unavailable,
    the connection is kept open and retried every second.

    Access pattern: reads ``websocket.app.state.capture`` for frame acquisition.
    """
    await websocket.accept()
    registry = websocket.app.state.capture_registry

    try:
        while True:
            backend = registry.get_default()
            if backend is None:
                await asyncio.sleep(1.0)
                continue
            try:
                jpeg_bytes = await backend.get_jpeg()
                await websocket.send_bytes(jpeg_bytes)
                # Cap at ~60 fps to avoid flooding the client
                await asyncio.sleep(0.016)
            except RuntimeError:
                # Capture device unavailable — keep connection alive, retry in 1s
                logger.debug("ws_preview: capture device unavailable, retrying in 1s")
                await asyncio.sleep(1.0)
    except (WebSocketDisconnect, Exception):
        # Client disconnected or unexpected error — clean exit
        logger.debug("ws_preview: client disconnected")
