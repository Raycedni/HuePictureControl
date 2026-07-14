import json
import logging
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
from routers.settings import router as settings_router
from routers.streaming_ws import router as streaming_ws_router
from routers.wled import router as wled_router
from services.capture_service import CaptureRegistry
from services.status_broadcaster import StatusBroadcaster
from services.streaming_coordinator import StreamingCoordinator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open DB connection and initialize schema
    db = await init_db(DATABASE_PATH)
    app.state.db = db

    # quick-task 260516-kra: hydrate live brightness cutoff from DB so the
    # streamers pick it up on first frame after startup. Default 0.0 (disabled
    # → byte-identical to pre-feature behavior). Defensive try/except: the
    # settings table is always created by init_db on this code path, but a
    # stale DB image without it should still boot cleanly.
    app.state.brightness_cutoff_threshold = 0.0
    try:
        async with db.execute(
            "SELECT value FROM settings WHERE key = ?",
            ("brightness_cutoff_threshold",),
        ) as cur:
            row = await cur.fetchone()
        if row is not None:
            try:
                app.state.brightness_cutoff_threshold = float(row["value"])
            except (TypeError, ValueError):
                pass
    except Exception:
        # settings table may not exist if init_db ran against a stale DB image —
        # safe default already set above.
        pass

    # quick-task 260704-iss: hydrate color_vibrancy + saturation_boost live
    # settings, mirroring the brightness_cutoff_threshold block above so the
    # coordinator's per-frame getattr(app_state, ...) reads pick them up on
    # first frame after startup. Defaults 0.0 (disabled -> byte-identical to
    # pre-feature behavior).
    # quick-task 260704-w88: hdr_input extends the same hydration block.
    # quick-task 260714-txt: color_correction_{r,g,b} extend the same block,
    # but default to 1.0 (identity) not 0.0 -- this feature's neutral value.
    app.state.color_vibrancy = 0.0
    app.state.saturation_boost = 0.0
    app.state.hdr_input = 0.0
    app.state.color_correction_r = 1.0
    app.state.color_correction_g = 1.0
    app.state.color_correction_b = 1.0
    try:
        async with db.execute(
            "SELECT key, value FROM settings WHERE key IN (?, ?, ?, ?, ?, ?)",
            (
                "color_vibrancy",
                "saturation_boost",
                "hdr_input",
                "color_correction_r",
                "color_correction_g",
                "color_correction_b",
            ),
        ) as cur:
            rows = await cur.fetchall()
        for row in rows:
            try:
                setattr(app.state, row["key"], float(row["value"]))
            except (TypeError, ValueError):
                pass
    except Exception:
        # settings table may not exist if init_db ran against a stale DB image —
        # safe defaults already set above.
        pass

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

    # Startup: create capture registry (lazy — no device opened at startup)
    registry = CaptureRegistry()
    app.state.capture_registry = registry

    # Startup: create StatusBroadcaster and StreamingCoordinator
    broadcaster = StatusBroadcaster()
    app.state.broadcaster = broadcaster

    coordinator = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        app_state=app.state,
    )
    app.state.coordinator = coordinator

    yield

    # Shutdown: stop streaming if active (before releasing capture)
    if coordinator.state not in ("idle",):
        await coordinator.stop()

    # Shutdown: release all capture backends
    registry.shutdown()

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
app.include_router(wled_router)
app.include_router(regions_router)
app.include_router(settings_router)
app.include_router(streaming_ws_router)
app.include_router(preview_ws_router)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
