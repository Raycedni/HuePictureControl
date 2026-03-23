"""Capture pipeline REST endpoints.

Exports:
    router -- APIRouter for /api/capture prefix
"""
import logging

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from services.color_math import build_polygon_mask, extract_region_color, rgb_to_xy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/capture", tags=["capture"])

# Hard-coded center region polygon (normalized coordinates): a centered 50% box
_DEBUG_CENTER_POLYGON = [
    [0.25, 0.25],
    [0.75, 0.25],
    [0.75, 0.75],
    [0.25, 0.75],
]


class SetDeviceRequest(BaseModel):
    device_path: str


@router.get("/snapshot")
async def get_snapshot(request: Request) -> Response:
    """Return a JPEG-encoded snapshot from the capture device.

    Returns:
        200 image/jpeg on success
        503 if the capture device is unavailable
    """
    capture_service = request.app.state.capture
    try:
        frame = await capture_service.get_frame()
    except RuntimeError as exc:
        logger.warning("Snapshot failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))

    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(status_code=503, detail="Failed to encode frame as JPEG")

    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.put("/device")
async def set_device(body: SetDeviceRequest, request: Request):
    """Switch the capture device path without restarting the container.

    Args:
        body: JSON body with ``device_path`` field

    Returns:
        200 JSON with device_path and status on success
        503 if the new device path is invalid / cannot be opened
    """
    capture_service = request.app.state.capture
    try:
        capture_service.open(body.device_path)
    except RuntimeError as exc:
        logger.warning("Device switch failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))

    logger.info("Capture device switched to %s", body.device_path)
    return {"device_path": body.device_path, "status": "opened"}


@router.get("/debug/color")
async def debug_color(request: Request):
    """Capture one frame and return its CIE xy color for a hard-coded center region.

    The center region is a normalized polygon covering the middle 50% of the
    frame (0.25..0.75 in both dimensions).

    Returns:
        JSON with ``rgb`` (list of 3 ints) and ``xy`` (list of 2 floats)
    """
    capture_service = request.app.state.capture
    try:
        frame = await capture_service.get_frame()
    except RuntimeError as exc:
        logger.warning("Debug color capture failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc))

    h, w = frame.shape[:2]
    mask = build_polygon_mask(_DEBUG_CENTER_POLYGON, width=w, height=h)
    r, g, b = extract_region_color(frame, mask)
    x, y = rgb_to_xy(r, g, b)

    logger.debug("Debug color: rgb=(%d, %d, %d) xy=(%.4f, %.4f)", r, g, b, x, y)

    return {"rgb": [r, g, b], "xy": [x, y]}
