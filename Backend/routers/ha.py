"""Home Assistant control REST endpoints (Phase 18).

Provides:
  POST /api/ha/start       — start streaming using selections in ha_state
  POST /api/ha/stop        — stop streaming (idempotent)
  GET  /api/ha/status      — curated HA-friendly status payload (D-09)
  PUT  /api/ha/zone        — persist HA's entertainment zone selection
  PUT  /api/ha/camera      — persist HA's camera selection
  GET  /api/ha/zones       — [{id, name}] discovery wrapper
  GET  /api/ha/cameras     — [{stable_id, name, connected}] discovery wrapper

Security notes:
  No auth — LAN trust boundary per PROJECT.md. HA → HPC direction only.
  No HA token stored. All endpoints are unauthenticated REST.

Exports:
    router -- APIRouter for /api/ha prefix
"""
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from routers.cameras import _scan_devices  # reuse V4L2 scan helper
from services.hue_client import list_entertainment_configs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ha", tags=["ha"])


# ---------------------------------------------------------------------------
# Pydantic models (D-09, D-11, Claude's Discretion)
# ---------------------------------------------------------------------------


class HaZoneRequest(BaseModel):
    zone_id: str = Field(..., min_length=1)


class HaCameraRequest(BaseModel):
    stable_id: str = Field(..., min_length=1)


class HaZoneOut(BaseModel):
    id: str
    name: str


class HaZoneListResponse(BaseModel):
    zones: list[HaZoneOut]


class HaCameraOut(BaseModel):
    stable_id: str
    name: str
    connected: bool


class HaCameraListResponse(BaseModel):
    cameras: list[HaCameraOut]


class HaStatusResponse(BaseModel):
    state: str
    active_config_id: str | None = None
    active_config_name: str | None = None
    active_camera_stable_id: str | None = None
    active_camera_name: str | None = None
    active_device_path: str | None = None
    fps: float = 0
    latency_ms: float = 0
    ha_selected_config_id: str | None = None
    ha_selected_config_name: str | None = None
    ha_selected_camera_stable_id: str | None = None
    ha_selected_camera_name: str | None = None
    bridge_paired: bool = False
    error: str | None = None  # additive — omitted from happy-path via response_model_exclude_none


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _build_status_response(request: Request) -> HaStatusResponse:
    """Assemble the curated D-09 status payload.

    Reads from broadcaster._metrics (active streaming state) and from
    ha_state / bridge_config / entertainment_configs / known_cameras
    (selection persistence + friendly-name resolution).

    Graceful degradation: a transient Hue Bridge error never bubbles a 500
    out of /api/ha/status — friendly names just go null. Pitfall 4.
    """
    db = request.app.state.db
    broadcaster = getattr(request.app.state, "broadcaster", None)
    metrics = broadcaster._metrics if broadcaster is not None else {
        "state": "idle", "fps": 0, "latency_ms": 0,
        "active_config_id": None, "active_device_path": None,
    }

    # Bridge pairing + entertainment configs
    async with db.execute(
        "SELECT ip_address, username FROM bridge_config WHERE id = 1"
    ) as cur:
        bridge_row = await cur.fetchone()
    bridge_paired = (
        bridge_row is not None
        and bridge_row["ip_address"] is not None
        and bridge_row["username"] is not None
    )
    config_name_by_id: dict[str, str] = {}
    if bridge_paired:
        try:
            configs = await list_entertainment_configs(
                bridge_row["ip_address"], bridge_row["username"]
            )
            config_name_by_id = {c["id"]: c["name"] for c in configs}
        except (httpx.HTTPError, TypeError, ValueError, KeyError) as exc:
            logger.warning(
                "Hue bridge unreachable or bridge_config malformed in /api/ha/status: %s",
                exc,
            )

    # ha_state row (lazy — may be missing)
    async with db.execute(
        "SELECT active_config_id, active_camera_stable_id FROM ha_state WHERE id = 1"
    ) as cur:
        ha_row = await cur.fetchone()
    ha_selected_config_id = ha_row["active_config_id"] if ha_row else None
    ha_selected_camera_stable_id = ha_row["active_camera_stable_id"] if ha_row else None

    # Active camera name from device_path reverse lookup
    active_device_path = metrics.get("active_device_path")
    active_camera_stable_id = None
    active_camera_name = None
    if active_device_path:
        async with db.execute(
            "SELECT stable_id, display_name FROM known_cameras "
            "WHERE last_device_path = ? ORDER BY last_seen_at DESC LIMIT 1",
            (active_device_path,),
        ) as cur:
            cam_row = await cur.fetchone()
        if cam_row:
            active_camera_stable_id = cam_row["stable_id"]
            active_camera_name = cam_row["display_name"]

    # HA-selected camera name from stable_id
    ha_selected_camera_name = None
    if ha_selected_camera_stable_id:
        async with db.execute(
            "SELECT display_name FROM known_cameras WHERE stable_id = ?",
            (ha_selected_camera_stable_id,),
        ) as cur:
            row = await cur.fetchone()
        ha_selected_camera_name = row["display_name"] if row else None

    active_config_id = metrics.get("active_config_id")
    return HaStatusResponse(
        state=metrics.get("state", "idle"),
        active_config_id=active_config_id,
        active_config_name=config_name_by_id.get(active_config_id) if active_config_id else None,
        active_camera_stable_id=active_camera_stable_id,
        active_camera_name=active_camera_name,
        active_device_path=active_device_path,
        fps=metrics.get("fps", 0),
        latency_ms=metrics.get("latency_ms", 0),
        ha_selected_config_id=ha_selected_config_id,
        ha_selected_config_name=config_name_by_id.get(ha_selected_config_id) if ha_selected_config_id else None,
        ha_selected_camera_stable_id=ha_selected_camera_stable_id,
        ha_selected_camera_name=ha_selected_camera_name,
        bridge_paired=bridge_paired,
        error=metrics.get("error"),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/start", response_model=HaStatusResponse, response_model_exclude_none=True)
async def ha_start(request: Request) -> HaStatusResponse:
    """Start streaming using ha_state selections (D-08).

    Preconditions enforced in order:
      1. ha_state row exists AND active_config_id is non-null (else 400).
      2. active_config_id still exists in entertainment_configs (else 404).
      3. coordinator is wired on app.state (else 503).

    device_path_override is resolved server-side from
    ha_state.active_camera_stable_id → known_cameras.last_device_path,
    so D-07 (HA does not touch the per-zone assignment table) stays clean.
    """
    db = request.app.state.db

    # D-08 step 1: precondition — ha_state.active_config_id must exist
    async with db.execute(
        "SELECT active_config_id, active_camera_stable_id FROM ha_state WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    if row is None or not row["active_config_id"]:
        raise HTTPException(
            status_code=400,
            detail="no zone selected — call PUT /api/ha/zone first",
        )
    active_config_id = row["active_config_id"]
    active_camera_stable_id = row["active_camera_stable_id"]

    # D-08 step 2: re-validate zone still exists
    async with db.execute(
        "SELECT id FROM entertainment_configs WHERE id = ?",
        (active_config_id,),
    ) as cur:
        if (await cur.fetchone()) is None:
            raise HTTPException(
                status_code=404,
                detail="zone not found — it may have been deleted on the Bridge",
            )

    # D-08 step 3a: resolve override path from ha_state.active_camera_stable_id
    device_path_override: str | None = None
    if active_camera_stable_id:
        async with db.execute(
            "SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
            (active_camera_stable_id,),
        ) as cur:
            cam_row = await cur.fetchone()
        if cam_row and cam_row["last_device_path"]:
            device_path_override = cam_row["last_device_path"]

    # D-08 step 4: delegate (Plan 01 extended start with device_path_override)
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is None:
        raise HTTPException(status_code=503, detail="Coordinator unavailable")
    await coordinator.start(active_config_id, device_path_override=device_path_override)

    return await _build_status_response(request)


@router.post("/stop", response_model=HaStatusResponse, response_model_exclude_none=True)
async def ha_stop(request: Request) -> HaStatusResponse:
    """Stop streaming. Idempotent — 200 even when already idle.

    When the coordinator is not wired (CRUD-only test path), skip the call
    and still return 200 + HaStatusResponse so tests can exercise the route.
    """
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is not None:
        await coordinator.stop()
    return await _build_status_response(request)


@router.get("/status", response_model=HaStatusResponse, response_model_exclude_none=True)
async def ha_status(request: Request) -> HaStatusResponse:
    """Curated HA-friendly status payload (D-09).

    Always 200 — degrades gracefully on Hue Bridge errors (Pitfall 4).
    """
    return await _build_status_response(request)


@router.put("/zone", response_model=HaStatusResponse, response_model_exclude_none=True)
async def ha_put_zone(body: HaZoneRequest, request: Request) -> HaStatusResponse:
    """Persist HA's entertainment-zone selection in ha_state (D-06).

    Conditional dual-write to camera_last_zone: only when ha_state already
    has an active_camera_stable_id (so the web UI's per-camera last-zone
    cascade picks up HA's choice on next reload). Skipped when no camera
    is set — D-06 step 4.
    """
    db = request.app.state.db

    # D-06 step 1: validate zone exists
    async with db.execute(
        "SELECT id FROM entertainment_configs WHERE id = ?",
        (body.zone_id,),
    ) as cur:
        if (await cur.fetchone()) is None:
            raise HTTPException(404, detail=f"zone_id '{body.zone_id}' not found")

    # D-06 step 3 decision input: read current camera (preserve across upsert)
    async with db.execute(
        "SELECT active_camera_stable_id FROM ha_state WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    current_camera = row["active_camera_stable_id"] if row else None

    now_iso = datetime.now(timezone.utc).isoformat()

    # D-06 step 2: upsert ha_state (ON CONFLICT — not REPLACE — to preserve cam)
    await db.execute(
        """
        INSERT INTO ha_state (id, active_config_id, active_camera_stable_id, updated_at)
        VALUES (1, :zone, :cam, :now)
        ON CONFLICT(id) DO UPDATE SET
            active_config_id = excluded.active_config_id,
            updated_at       = excluded.updated_at
        """,
        {"zone": body.zone_id, "cam": current_camera, "now": now_iso},
    )

    # D-06 step 3/4: conditional dual-write
    if current_camera is not None:
        await db.execute(
            """
            INSERT INTO camera_last_zone (camera_stable_id, entertainment_config_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(camera_stable_id) DO UPDATE SET
                entertainment_config_id = excluded.entertainment_config_id,
                updated_at              = excluded.updated_at
            """,
            (current_camera, body.zone_id, now_iso),
        )

    await db.commit()
    return await _build_status_response(request)


@router.put("/camera", response_model=HaStatusResponse, response_model_exclude_none=True)
async def ha_put_camera(body: HaCameraRequest, request: Request) -> HaStatusResponse:
    """Persist HA's camera selection in ha_state (D-07).

    Decoupled from the per-zone assignment table — HA's choice is global.
    The web UI's per-zone camera dropdown remains untouched. The D-07
    NEGATIVE acceptance test asserts the assignment table row count is
    unchanged.
    """
    db = request.app.state.db

    # D-07 step 1: validate camera exists in known_cameras
    async with db.execute(
        "SELECT stable_id FROM known_cameras WHERE stable_id = ?",
        (body.stable_id,),
    ) as cur:
        if (await cur.fetchone()) is None:
            raise HTTPException(404, detail=f"stable_id '{body.stable_id}' not found")

    # D-07 step 2: preserve existing config across the upsert
    async with db.execute(
        "SELECT active_config_id FROM ha_state WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    current_config = row["active_config_id"] if row else None

    now_iso = datetime.now(timezone.utc).isoformat()
    await db.execute(
        """
        INSERT INTO ha_state (id, active_config_id, active_camera_stable_id, updated_at)
        VALUES (1, :cfg, :cam, :now)
        ON CONFLICT(id) DO UPDATE SET
            active_camera_stable_id = excluded.active_camera_stable_id,
            updated_at              = excluded.updated_at
        """,
        {"cfg": current_config, "cam": body.stable_id, "now": now_iso},
    )
    # D-07 step 3 NEGATIVE: do NOT touch the per-zone assignment table here.

    await db.commit()
    return await _build_status_response(request)


@router.get("/zones", response_model=HaZoneListResponse)
async def ha_zones(request: Request) -> HaZoneListResponse:
    """List entertainment zones in [{id, name}] form (D-11).

    Decoupled from /api/hue/configs internal shape — HA template sensors
    only need the two fields. 503 when bridge unpaired (HA-friendly map);
    502 on transient bridge HTTP errors.
    """
    db = request.app.state.db
    async with db.execute(
        "SELECT ip_address, username FROM bridge_config WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="Hue bridge not paired")
    try:
        raw = await list_entertainment_configs(row["ip_address"], row["username"])
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Hue bridge unreachable: {exc}")
    return HaZoneListResponse(zones=[HaZoneOut(id=c["id"], name=c["name"]) for c in raw])


@router.get("/cameras", response_model=HaCameraListResponse)
async def ha_cameras(request: Request) -> HaCameraListResponse:
    """List known cameras in [{stable_id, name, connected}] form (D-11).

    Includes previously-seen-but-currently-disconnected cameras.
    `connected` derives from a fresh V4L2 scan via routers.cameras._scan_devices.
    """
    db = request.app.state.db
    scan_results, _ = await _scan_devices()
    async with db.execute(
        "SELECT stable_id, display_name FROM known_cameras"
    ) as cur:
        rows = await cur.fetchall()
    cameras = [
        HaCameraOut(
            stable_id=r["stable_id"],
            name=r["display_name"],
            connected=r["stable_id"] in scan_results,
        )
        for r in rows
    ]
    return HaCameraListResponse(cameras=cameras)
