import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from database import DATABASE_PATH, close_db, init_db
from routers.capture import router as capture_router
from routers.health import router as health_router
from routers.hue import router as hue_router
from routers.regions import router as regions_router
from routers.streaming_ws import router as streaming_ws_router
from services.capture_service import LatestFrameCapture
from services.status_broadcaster import StatusBroadcaster
from services.streaming_service import StreamingService

logger = logging.getLogger(__name__)

CAPTURE_DEVICE = os.getenv("CAPTURE_DEVICE", "/dev/video0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open DB connection and initialize schema
    db = await init_db(DATABASE_PATH)
    app.state.db = db

    # Startup: initialize capture service (non-fatal if device absent)
    capture = LatestFrameCapture(CAPTURE_DEVICE)
    try:
        capture.open()
    except RuntimeError as exc:
        logger.warning(
            "Capture device unavailable at startup (%s) — "
            "snapshot endpoint will return 503 until a valid device is configured.",
            exc,
        )
    app.state.capture = capture

    # Startup: create StatusBroadcaster and StreamingService
    broadcaster = StatusBroadcaster()
    app.state.broadcaster = broadcaster

    streaming = StreamingService(db=db, capture=capture, broadcaster=broadcaster)
    app.state.streaming = streaming

    yield

    # Shutdown: stop streaming if active (before releasing capture)
    if streaming.state not in ("idle",):
        await streaming.stop()

    # Shutdown: release capture device
    capture.release()

    # Shutdown: close DB connection
    await close_db(db)


app = FastAPI(lifespan=lifespan)

app.include_router(health_router)
app.include_router(hue_router)
app.include_router(capture_router)
app.include_router(regions_router)
app.include_router(streaming_ws_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
