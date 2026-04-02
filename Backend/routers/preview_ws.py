"""WebSocket /ws/preview endpoint for binary JPEG frame streaming.

Exports:
    router -- APIRouter with /ws/preview WebSocket endpoint
"""
import asyncio
import logging

import cv2
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["preview"])


@router.websocket("/ws/preview")
async def ws_preview(websocket: WebSocket):
    """Stream live JPEG frames from the capture device as binary WebSocket messages.

    Sends frames as fast as the capture device produces them (no artificial limit).
    If the capture device is unavailable, the connection is kept open and retried
    every second rather than closing abruptly.

    On client disconnect, the loop exits cleanly.

    Access pattern: reads ``websocket.app.state.capture`` for frame acquisition.
    """
    await websocket.accept()
    capture = websocket.app.state.capture

    try:
        while True:
            try:
                frame = await capture.get_frame()
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok:
                    await websocket.send_bytes(buf.tobytes())
                # Cap at ~30 fps to avoid flooding the client
                await asyncio.sleep(0.033)
            except RuntimeError:
                # Capture device unavailable — keep connection alive, retry in 1s
                logger.debug("ws_preview: capture device unavailable, retrying in 1s")
                await asyncio.sleep(1.0)
    except (WebSocketDisconnect, Exception):
        # Client disconnected or unexpected error — clean exit
        logger.debug("ws_preview: client disconnected")
