"""Cameras REST endpoints.

Provides:
  GET  /api/cameras                              — list all known capture devices with identity_mode
  POST /api/cameras/reconnect                    — re-scan and match a device by stable_id
  PUT  /api/cameras/assignments/{config_id}      — persist camera assignment for an entertainment config
  GET  /api/cameras/assignments/{config_id}      — retrieve camera assignment (404 if none)

Exports:
    router -- APIRouter for /api/cameras prefix
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

if sys.platform != "win32":
    from services.capture_v4l2 import enumerate_capture_devices
from services.device_identity import get_stable_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CameraDevice(BaseModel):
    device_path: str
    stable_id: str
    display_name: str
    connected: bool
    last_seen_at: str | None


class ZoneHealth(BaseModel):
    entertainment_config_id: str
    camera_name: str
    camera_stable_id: str
    connected: bool
    device_path: str | None


class CamerasResponse(BaseModel):
    devices: list[CameraDevice]
    identity_mode: str  # "stable" | "degraded"
    cameras_available: bool
    zone_health: list[ZoneHealth]


class ReconnectRequest(BaseModel):
    stable_id: str


class ReconnectResponse(BaseModel):
    connected: bool
    device_path: str | None
    display_name: str


class AssignmentRequest(BaseModel):
    camera_stable_id: str
    camera_name: str


class AssignmentResponse(BaseModel):
    entertainment_config_id: str
    camera_stable_id: str
    camera_name: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _scan_devices() -> tuple[dict[str, dict], bool]:
    """Run a fresh V4L2 device scan and return (stable_id -> scan_info, any_degraded).

    The scan is run in a thread executor to avoid blocking the event loop.
    For each device, get_stable_id() is also called in executor (sysfs reads).

    On Windows, V4L2 is unavailable — returns empty results immediately.

    Returns:
        A tuple of:
          - dict mapping stable_id -> {"device_path", "card", "stable_id", "display_name"}
          - bool: True if any device had degraded identity (no sysfs)
    """
    if sys.platform == "win32":
        return {}, True

    loop = asyncio.get_event_loop()

    # enumerate_capture_devices performs ioctl — must run in thread
    devices = await loop.run_in_executor(None, enumerate_capture_devices)

    scan_results: dict[str, dict] = {}
    any_degraded = False

    for info in devices:
        stable_id, sysfs_ok = await loop.run_in_executor(
            None, get_stable_id, info.device_path, info.bus_info, info.card
        )
        if not sysfs_ok:
            any_degraded = True
        scan_results[stable_id] = {
            "device_path": info.device_path,
            "card": info.card,
            "stable_id": stable_id,
            "display_name": info.card,
        }

    return scan_results, any_degraded


async def _upsert_known_cameras(db, scan_results: dict[str, dict]) -> None:
    """Upsert each scanned device into the known_cameras table (D-09)."""
    now = datetime.now(timezone.utc).isoformat()
    for stable_id, info in scan_results.items():
        await db.execute(
            """
            INSERT INTO known_cameras (stable_id, display_name, last_seen_at, last_device_path)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(stable_id) DO UPDATE SET
                display_name = excluded.display_name,
                last_seen_at = excluded.last_seen_at,
                last_device_path = excluded.last_device_path
            """,
            (stable_id, info["display_name"], now, info["device_path"]),
        )
    await db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=CamerasResponse)
async def list_cameras(request: Request) -> CamerasResponse:
    """List all capture-capable V4L2 devices with stable identity metadata.

    Performs a fresh scan on every call (DEVC-03 — no caching).
    Previously-seen devices are returned with connected=False if absent from
    the current scan (D-06 — preserve history).

    Returns:
        CamerasResponse with devices list and identity_mode ("stable" | "degraded").
    """
    db = request.app.state.db

    # Fresh scan every time — no caching per DEVC-03
    scan_results, any_degraded = await _scan_devices()

    # Upsert currently visible devices into known_cameras (D-09)
    if scan_results:
        await _upsert_known_cameras(db, scan_results)

    # Fetch all rows from known_cameras (includes previously-seen-but-gone devices)
    async with db.execute(
        "SELECT stable_id, display_name, last_seen_at, last_device_path FROM known_cameras"
    ) as cursor:
        known_rows = await cursor.fetchall()

    devices: list[CameraDevice] = []
    for row in known_rows:
        sid = row["stable_id"]
        if sid in scan_results:
            # Device is currently connected — use fresh device_path
            device_path = scan_results[sid]["device_path"]
            connected = True
        else:
            # Previously seen but not in current scan
            device_path = row["last_device_path"] or ""
            connected = False

        devices.append(
            CameraDevice(
                device_path=device_path,
                stable_id=sid,
                display_name=row["display_name"],
                connected=connected,
                last_seen_at=row["last_seen_at"],
            )
        )

    # Determine identity_mode: degraded if any sysfs miss, or if sysfs dir absent
    if any_degraded:
        identity_mode = "degraded"
    elif not scan_results and not os.path.isdir("/sys/class/video4linux/"):
        identity_mode = "degraded"
    else:
        identity_mode = "stable"

    # Build zone_health from camera_assignments (per D-05, CAMA-04)
    async with db.execute(
        "SELECT entertainment_config_id, camera_stable_id, camera_name FROM camera_assignments"
    ) as cursor:
        assignment_rows = await cursor.fetchall()

    zone_health: list[ZoneHealth] = []
    for row in assignment_rows:
        sid = row["camera_stable_id"]
        connected = sid in scan_results
        dp = scan_results[sid]["device_path"] if connected else None
        zone_health.append(ZoneHealth(
            entertainment_config_id=row["entertainment_config_id"],
            camera_name=row["camera_name"],
            camera_stable_id=sid,
            connected=connected,
            device_path=dp,
        ))

    return CamerasResponse(
        devices=devices,
        identity_mode=identity_mode,
        cameras_available=len(devices) > 0,
        zone_health=zone_health,
    )


@router.post("/reconnect", response_model=ReconnectResponse)
async def reconnect_camera(body: ReconnectRequest, request: Request) -> ReconnectResponse:
    """Re-scan devices and report whether a given stable_id is now reachable.

    If the stable_id is not in known_cameras at all, returns 404.
    Otherwise returns connected=True/False with current device_path.

    Per DEVC-05, D-04, D-05.
    """
    db = request.app.state.db

    # Check that this stable_id is known at all
    async with db.execute(
        "SELECT stable_id, display_name FROM known_cameras WHERE stable_id = ?",
        (body.stable_id,),
    ) as cursor:
        known_row = await cursor.fetchone()

    if known_row is None:
        raise HTTPException(
            status_code=404,
            detail=f"stable_id '{body.stable_id}' not found in known cameras.",
        )

    # Fresh scan
    scan_results, _ = await _scan_devices()

    if body.stable_id in scan_results:
        # Found — upsert with fresh device_path
        now = datetime.now(timezone.utc).isoformat()
        info = scan_results[body.stable_id]
        await db.execute(
            """
            INSERT INTO known_cameras (stable_id, display_name, last_seen_at, last_device_path)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(stable_id) DO UPDATE SET
                last_seen_at = excluded.last_seen_at,
                last_device_path = excluded.last_device_path
            """,
            (body.stable_id, info["display_name"], now, info["device_path"]),
        )
        await db.commit()
        return ReconnectResponse(
            connected=True,
            device_path=info["device_path"],
            display_name=info["display_name"],
        )
    else:
        # Not found in current scan — device is gone
        return ReconnectResponse(
            connected=False,
            device_path=None,
            display_name=known_row["display_name"],
        )


@router.put("/assignments/{entertainment_config_id}", response_model=AssignmentResponse)
async def put_assignment(
    entertainment_config_id: str,
    body: AssignmentRequest,
    request: Request,
) -> AssignmentResponse:
    """Persist a camera assignment for an entertainment configuration.

    Validates that camera_stable_id exists in known_cameras.
    Upserts the assignment (replaces if already exists for this config).

    Per CAMA-02.
    """
    db = request.app.state.db

    # Validate camera_stable_id exists in known_cameras
    async with db.execute(
        "SELECT stable_id FROM known_cameras WHERE stable_id = ?",
        (body.camera_stable_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"camera_stable_id '{body.camera_stable_id}' not found in known cameras.",
        )

    await db.execute(
        """
        INSERT INTO camera_assignments (entertainment_config_id, camera_stable_id, camera_name)
        VALUES (?, ?, ?)
        ON CONFLICT(entertainment_config_id) DO UPDATE SET
            camera_stable_id = excluded.camera_stable_id,
            camera_name = excluded.camera_name
        """,
        (entertainment_config_id, body.camera_stable_id, body.camera_name),
    )
    await db.commit()

    return AssignmentResponse(
        entertainment_config_id=entertainment_config_id,
        camera_stable_id=body.camera_stable_id,
        camera_name=body.camera_name,
    )


@router.get("/assignments/{entertainment_config_id}", response_model=AssignmentResponse)
async def get_assignment(
    entertainment_config_id: str,
    request: Request,
) -> AssignmentResponse:
    """Retrieve the camera assignment for an entertainment configuration.

    Returns 404 when no assignment exists — the API caller should fall back
    to the default CAPTURE_DEVICE env var per CAMA-03.
    """
    db = request.app.state.db

    async with db.execute(
        "SELECT entertainment_config_id, camera_stable_id, camera_name FROM camera_assignments WHERE entertainment_config_id = ?",
        (entertainment_config_id,),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No camera assignment for this config. Default capture device will be used.",
        )

    return AssignmentResponse(
        entertainment_config_id=row["entertainment_config_id"],
        camera_stable_id=row["camera_stable_id"],
        camera_name=row["camera_name"],
    )
