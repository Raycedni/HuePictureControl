import json
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import DATABASE_PATH, close_db, init_db
from routers.cameras import router as cameras_router
from routers.capture import router as capture_router
from routers.health import router as health_router
from routers.hue import router as hue_router
from routers.preview_ws import router as preview_ws_router
from routers.regions import router as regions_router
from routers.streaming_ws import router as streaming_ws_router
from services.capture_service import create_capture
from services.status_broadcaster import StatusBroadcaster
from services.streaming_service import StreamingService

logger = logging.getLogger(__name__)

CAPTURE_DEVICE = os.getenv("CAPTURE_DEVICE", "/dev/video0")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open DB connection and initialize schema
    db = await init_db(DATABASE_PATH)
    app.state.db = db

    # Startup: purge regions smaller than MIN_REGION_AREA
    from routers.regions import MIN_REGION_AREA, polygon_area
    async with db.execute("SELECT id, polygon FROM regions") as cursor:
        rows = await cursor.fetchall()
    purged = 0
    for row in rows:
        poly = json.loads(row["polygon"])
        if polygon_area(poly) < MIN_REGION_AREA:
            await db.execute("DELETE FROM regions WHERE id=?", (row["id"],))
            await db.execute("DELETE FROM light_assignments WHERE region_id=?", (row["id"],))
            purged += 1
    if purged:
        await db.commit()
        logger.info("Purged %d undersized regions (area < %s)", purged, MIN_REGION_AREA)

    # Startup: initialize capture service (non-fatal if device absent)
    capture = create_capture(CAPTURE_DEVICE)
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(hue_router)
app.include_router(capture_router)
app.include_router(cameras_router)
app.include_router(regions_router)
app.include_router(streaming_ws_router)
app.include_router(preview_ws_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
