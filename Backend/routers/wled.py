"""WLED device CRUD + zeroconf scan + segment refresh REST endpoints (Phase 19.1).

Provides:
  GET    /api/wled/devices                              — list registered devices with live state
  POST   /api/wled/devices                              — register a new device by IP (fetches /json/info + /json/state)
  DELETE /api/wled/devices/{id}                         — remove device and cascade cache rows + assignments
  PUT    /api/wled/devices/{id}/enabled                 — toggle the per-frame UDP gate (D-12)
  POST   /api/wled/scan                                 — 3s zeroconf scan for `_wled._tcp.local.`
  POST   /api/wled/devices/{device_id}/segments/refresh — Phase 19.1 D-17: fetch /json/state + reconcile cache
  GET    /api/wled/devices/{device_id}/segments         — Phase 19.1 D-18: read wled_seg_cache (no device contact)
  GET    /api/wled/assignments                          — list region->segment assignments (D-13)
  PUT    /api/wled/assignments                          — upsert region->segment assignment (D-13)
  DELETE /api/wled/assignments                          — delete region->segment assignment (D-13)
  PATCH  /api/wled/regions/{region_id}/orientation      — set orientation for all assignments of (region, config)

Security notes:
  No auth (local network tool per PROJECT.md). IP validation via Pydantic
  regex `^(\\d{1,3}\\.){3}\\d{1,3}$` blocks CIDR (`1.2.3.0/24`), hostnames
  (`foo.local`), IPv6, and URL-encoded variants before any HTTP request is
  issued. The regex intentionally does NOT validate octet ranges (0..255) —
  Pydantic `Field(pattern=...)` is a regex match, and an out-of-range octet
  fails downstream at the OS socket / httpx layer (OSError on connect).

  T-17-SSRF: The `GET /json/info` and `GET /json/state` fetches from a
  user-supplied IP are consciously accepted risks. Per PROJECT.md the web UI
  is "local network tool only" — the LAN is the trust boundary.
  `httpx.AsyncClient` does not follow redirects by default in
  `fetch_wled_info`/`fetch_wled_state`, so a compromised WLED device cannot
  redirect us to an attacker endpoint. Both parsers defensively use
  ``data.get(...)`` and never evaluate code.

  T-17-UDP: Devices are registered into the DB with `enabled=1` but no UDP
  traffic flows until `/api/capture/start` is called. WledStreamer's enabled
  gate (D-12) + 30-frame consecutive-failure cooldown (D-15) cap traffic to
  ~60 pps × N devices with auto-disable on unresponsive targets.

Phase 19.1 changes:
  * Channel-CRUD endpoints removed (D-10) — segments are mirrored from
    /json/state, no longer paint-managed.
  * Device registration fetches /json/state in the same coroutine as
    /json/info, so registration fails atomically if either fetch fails
    (D-02). BOTH fetches run BEFORE any DB write to guarantee rollback
    semantics — if the state fetch raises after info succeeds, no
    `wled_devices` row is left behind.
  * Assignments key on `(region_id, wled_device_id, seg_index, entertainment_config_id)`
    instead of the dropped Phase 19 channel-id column (D-13).
  * `Response` is imported for the explicit 204 No-Content body on the
    assignment delete handler — matches Phase 17's delete handler style.

Exports:
    router -- APIRouter for /api/wled prefix
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from services.wled_client import fetch_wled_info, fetch_wled_state
from services.wled_discovery import scan_for_wled_devices
from services.wled_segments import reconcile_segments

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wled", tags=["wled"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class WledDeviceIn(BaseModel):
    ip: str = Field(..., pattern=r"^(\d{1,3}\.){3}\d{1,3}$")


class WledDeviceOut(BaseModel):
    id: str
    ip: str
    name: str
    led_count: int
    enabled: bool
    created_at: str
    connected: bool
    last_error: str | None = None
    last_success_at: str | None = None


class WledDevicesResponse(BaseModel):
    devices: list[WledDeviceOut]


class WledEnabledRequest(BaseModel):
    enabled: bool


class WledScanCandidate(BaseModel):
    ip: str
    name: str


class WledScanResponse(BaseModel):
    candidates: list[WledScanCandidate]


# ---------------------------------------------------------------------------
# Phase 19 - Pydantic models for orientation + assignment (rewritten in 19.1)
# ---------------------------------------------------------------------------


WledOrientation = Literal[
    "auto",
    "horizontal-LTR",
    "horizontal-RTL",
    "vertical-TTB",
    "vertical-BTT",
]


# ---------------------------------------------------------------------------
# Phase 19.1 - Segment cache models (D-17, D-18)
# ---------------------------------------------------------------------------


class WledSegmentOut(BaseModel):
    seg_index: int
    start_led: int
    stop_led: int
    name: str | None = None
    refreshed_at: str | None = None


class WledSegmentsResponse(BaseModel):
    segments: list[WledSegmentOut]


class WledRefreshResponse(BaseModel):
    segments: list[WledSegmentOut]
    dropped_assignments: int


# ---------------------------------------------------------------------------
# Phase 19.1 - Assignment models (D-13) — composite (device_id, seg_index)
# ---------------------------------------------------------------------------


class WledAssignmentUpsert(BaseModel):
    region_id: str
    wled_device_id: str
    seg_index: int
    entertainment_config_id: str
    orientation: WledOrientation | None = None  # falls back to existing or 'auto'


class WledAssignmentDelete(BaseModel):
    region_id: str
    wled_device_id: str
    seg_index: int
    entertainment_config_id: str


class WledAssignmentOut(BaseModel):
    region_id: str
    wled_device_id: str
    seg_index: int
    entertainment_config_id: str
    orientation: WledOrientation


class WledAssignmentsResponse(BaseModel):
    assignments: list[WledAssignmentOut]


class WledOrientationPatch(BaseModel):
    orientation: WledOrientation


class WledOrientationPatchResponse(BaseModel):
    updated: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_out(row, health: dict) -> WledDeviceOut:
    """Merge a persisted device row with the live health_snapshot entry.

    The "connected" field has two modes depending on whether the coordinator
    is currently streaming (i.e. whether the WledStreamer has been started):

    * Streamer idle (health dict empty or device absent from it): the device
      is assumed reachable when it has a valid led_count > 0.  Registration
      already proved reachability via a successful /json/info fetch, so there
      is no need to require a recent UDP send.  Showing "Offline" at idle was
      a bug — devices were never shown as connected unless streaming was active
      AND a channel assignment existed (fix for wled-always-offline).

    * Streamer running (device_id present in health dict): use the
      last_success_at timestamp.  A device is connected when the most recent
      successful UDP send is < 5.0 s old.  None / unparseable timestamps
      surface as connected=False (e.g. the device is in the streamer but has
      never successfully sent — no channel assignment or all sends failed).
    """
    health_entry = health.get(row["id"]) if health else None
    if health_entry is None:
        # Streamer is idle or this device is not yet in the live streamer.
        # Derive connected from the persisted led_count: if the device was
        # successfully registered (led_count > 0 is a registration invariant)
        # treat it as connected.  The cooldown / last_error fields are absent.
        connected = int(row["led_count"]) > 0
        return WledDeviceOut(
            id=row["id"],
            ip=row["ip"],
            name=row["name"],
            led_count=int(row["led_count"]),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            connected=connected,
            last_error=None,
            last_success_at=None,
        )

    # Streamer is running and has a health entry for this device.
    last_success_at = health_entry.get("last_success_at")
    connected = False
    if last_success_at is not None:
        try:
            ts = datetime.fromisoformat(last_success_at)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            delta = (datetime.now(timezone.utc) - ts).total_seconds()
            connected = delta < 5.0
        except (TypeError, ValueError):
            connected = False
    return WledDeviceOut(
        id=row["id"],
        ip=row["ip"],
        name=row["name"],
        led_count=int(row["led_count"]),
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        connected=connected,
        last_error=health_entry.get("last_error"),
        last_success_at=last_success_at,
    )


def _coord_health(request: Request) -> dict:
    """Best-effort live WLED health from the coordinator. Returns `{}` if idle.

    Tolerates a missing coordinator (e.g. tests that don't wire one) and
    a streamer that has not yet been started (`_wled` is always present
    on a real coordinator but defensive `getattr` keeps tests simple).
    """
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is None:
        return {}
    wled = getattr(coordinator, "_wled", None)
    if wled is None:
        return {}
    try:
        return wled.health_snapshot()
    except Exception:  # pragma: no cover — defensive
        return {}


def _seg_row_to_out(row) -> WledSegmentOut:
    """Convert an aiosqlite Row (or tuple) from wled_seg_cache into the API shape."""
    if isinstance(row, dict) or hasattr(row, "keys"):
        return WledSegmentOut(
            seg_index=int(row["seg_index"]),
            start_led=int(row["start_led"]),
            stop_led=int(row["stop_led"]),
            name=row["name"],
            refreshed_at=row["refreshed_at"],
        )
    # Positional tuple fallback for callers that don't set row_factory.
    return WledSegmentOut(
        seg_index=int(row[0]),
        start_led=int(row[1]),
        stop_led=int(row[2]),
        name=row[3],
        refreshed_at=row[4],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/devices", response_model=WledDevicesResponse)
async def list_devices(request: Request) -> WledDevicesResponse:
    """List persisted WLED devices merged with live coordinator health."""
    db = request.app.state.db
    async with db.execute(
        "SELECT id, ip, name, led_count, enabled, created_at "
        "FROM wled_devices ORDER BY created_at ASC"
    ) as cur:
        rows = await cur.fetchall()
    health = _coord_health(request)
    return WledDevicesResponse(devices=[_row_to_out(r, health) for r in rows])


@router.post("/devices", response_model=WledDeviceOut, status_code=201)
async def add_device(body: WledDeviceIn, request: Request) -> WledDeviceOut:
    """Register a new WLED device by IP (Phase 19.1 D-02).

    Flow (T-17-DUPE / T-17-SSRF mitigations):
      1. Pre-INSERT SELECT for duplicate IP — returns 409 cleanly before
         the httpx call fires (avoids hitting an attacker-controlled IP
         on retry of an already-registered device).
      2. `fetch_wled_info(ip)` + `fetch_wled_state(ip)` over httpx in the
         SAME coroutine — both must succeed before any DB write. Timeouts
         and connect errors map to 502; JSON shape errors to 422. The
         atomicity guarantee (D-02): if /json/state fails after /json/info
         succeeds, no `wled_devices` row is created.
      3. Reject `led_count <= 0` with 422 (D-09 prerequisite — the cached
         segments need a valid strip length).
      4. INSERT the device row + commit, then call `reconcile_segments`
         which owns its own transaction over `wled_seg_cache`. Network I/O
         is already complete at this point, so the implicit DB transaction
         window stays tight (RESEARCH.md Pitfall 2).
      5. Return the new row merged with the current health snapshot.
    """
    db = request.app.state.db

    # Pre-INSERT duplicate check (UNIQUE(ip) on the table is the ultimate
    # safety net, but this gives a clean 409 without firing httpx).
    async with db.execute(
        "SELECT id FROM wled_devices WHERE ip = ?", (body.ip,)
    ) as cur:
        existing = await cur.fetchone()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"WLED device with ip '{body.ip}' already registered",
        )

    # D-02: fetch /json/info AND /json/state in the same try-block BEFORE any
    # DB write. Atomic failure: if /json/state raises after /json/info
    # succeeds, we have not yet touched the database, so there is nothing
    # to roll back — the device simply isn't registered.
    try:
        info = await fetch_wled_info(body.ip)
        segments = await fetch_wled_state(body.ip)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"WLED device unreachable (timeout): {exc}",
        )
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"WLED device unreachable: {exc}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"WLED device returned error: {exc}",
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid WLED response: {exc}",
        )

    led_count = int(info.get("led_count", 0))
    if led_count <= 0:
        raise HTTPException(
            status_code=422,
            detail=f"WLED device reported led_count={led_count}; refusing to register.",
        )

    device_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    name = info.get("name", "WLED")

    # Both fetches succeeded — persist. D-10: no more wled_channels auto-seed;
    # the strip is described entirely by the wled_seg_cache rows below.
    await db.execute(
        "INSERT INTO wled_devices (id, ip, name, led_count, enabled, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (device_id, body.ip, name, led_count, now_iso),
    )
    await db.commit()

    # D-02 second half: seed wled_seg_cache from the /json/state we just
    # fetched. `reconcile_segments` owns its own transaction; on the empty
    # cache for this brand-new device it is effectively just an INSERT batch.
    await reconcile_segments(db, device_id, segments)

    health = _coord_health(request)
    return _row_to_out(
        {
            "id": device_id,
            "ip": body.ip,
            "name": name,
            "led_count": led_count,
            "enabled": 1,
            "created_at": now_iso,
        },
        health,
    )


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(device_id: str, request: Request):
    """Cascade-delete a WLED device, its cached segments, and its assignments.

    Phase 19.1 rewrite: replaces the Phase 17 cascade through `wled_channels`
    with a cascade through `wled_seg_cache` (the new source of segment truth)
    and the new `wled_light_assignments` schema (D-13). SQLite FK constraints
    in the schema are documentation-only — the project does NOT run with
    `PRAGMA foreign_keys = ON` (per 17-RESEARCH.md A5), so cascade is
    implemented in code via three explicit DELETE statements:

      1. assignments referencing this device's seg rows (matched directly by
         `wled_device_id` — no subquery needed because D-13 made the device
         id a column on `wled_light_assignments`),
      2. the cache rows for this device,
      3. the device row itself.

    All in one transaction.
    """
    db = request.app.state.db

    # Pre-delete existence check — 404 if missing.
    async with db.execute(
        "SELECT id FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        existing = await cur.fetchone()
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"WLED device '{device_id}' not found",
        )

    # 1) Delete assignments for this device (D-13 direct match — no subquery).
    await db.execute(
        "DELETE FROM wled_light_assignments WHERE wled_device_id = ?",
        (device_id,),
    )

    # 2) Delete cache rows for this device.
    await db.execute(
        "DELETE FROM wled_seg_cache WHERE device_id = ?", (device_id,)
    )

    # 3) Delete device row.
    await db.execute(
        "DELETE FROM wled_devices WHERE id = ?", (device_id,)
    )
    await db.commit()


@router.put("/devices/{device_id}/enabled")
async def set_enabled(
    device_id: str, body: WledEnabledRequest, request: Request
):
    """Toggle the per-frame UDP-send gate (D-12) for a device.

    When the coordinator is wired, the call is routed through it so that
    (a) the DB row is updated and (b) the live ``WledStreamer._devices[id]
    .enabled`` flag is flipped under the streamer lock — a mid-stream
    toggle takes effect on the very next frame without a restart
    (T-17-ENABLE-RACE mitigation).

    In tests without a coordinator, falls back to a direct DB UPDATE so the
    endpoint remains usable for unit-level integration testing of CRUD
    behavior.
    """
    db = request.app.state.db
    async with db.execute(
        "SELECT id FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        existing = await cur.fetchone()
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail=f"WLED device '{device_id}' not found",
        )

    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is not None:
        await coordinator.set_wled_device_enabled(device_id, body.enabled)
    else:
        # Test mode without coordinator — direct DB update (no live gate).
        await db.execute(
            "UPDATE wled_devices SET enabled = ? WHERE id = ?",
            (1 if body.enabled else 0, device_id),
        )
        await db.commit()

    return {"id": device_id, "enabled": body.enabled}


@router.post("/scan", response_model=WledScanResponse)
async def scan(request: Request) -> WledScanResponse:  # noqa: ARG001
    """One-shot zeroconf scan for `_wled._tcp.local.` services.

    Always awaits the full 3s timeout (D-19) so trickling mDNS replies
    aren't missed by an early exit. Returns an empty list when no devices
    are found within the window — the UI surfaces this as "no devices found"
    and the user can fall back to manual IP entry.
    """
    results = await scan_for_wled_devices(timeout_seconds=3.0)
    return WledScanResponse(
        candidates=[
            WledScanCandidate(ip=r["ip"], name=r.get("name", r["ip"]))
            for r in results
        ]
    )


# ---------------------------------------------------------------------------
# Phase 19.1 - Segment refresh + list endpoints (D-17, D-18)
# ---------------------------------------------------------------------------


@router.post(
    "/devices/{device_id}/segments/refresh",
    response_model=WledRefreshResponse,
)
async def refresh_device_segments(
    device_id: str, request: Request
) -> WledRefreshResponse:
    """D-17: fetch /json/state, run reconciliation, return result.

    Flow:
      1. Verify the device exists — 404 if not.
      2. Fire `fetch_wled_state` OUTSIDE any DB transaction (RESEARCH.md
         Pitfall 2 — keep network I/O off the transaction window).
      3. Translate httpx and ValueError to HTTP errors:
         * httpx.TimeoutException  -> 502 "(timeout)"
         * httpx.ConnectError      -> 502 "unreachable"
         * httpx.HTTPError         -> 502 "returned error"
         * ValueError              -> 422 "Invalid WLED response"
      4. Call `reconcile_segments` — single transaction, returns count of
         orphaned `wled_light_assignments` rows dropped.
      5. Re-read `wled_seg_cache` for the device to populate the
         `refreshed_at` column in the response.
    """
    db = request.app.state.db
    async with db.execute(
        "SELECT id, ip FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"WLED device '{device_id}' not found",
        )
    # aiosqlite.Row supports both index and key access.
    ip = row["ip"] if hasattr(row, "keys") else row[1]

    try:
        segments = await fetch_wled_state(ip)
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"WLED device unreachable (timeout): {exc}",
        )
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"WLED device unreachable: {exc}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"WLED device returned error: {exc}",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid WLED response: {exc}",
        )

    dropped = await reconcile_segments(db, device_id, segments)

    # Re-read cache so the response carries the freshly-written refreshed_at.
    async with db.execute(
        "SELECT seg_index, start_led, stop_led, name, refreshed_at "
        "FROM wled_seg_cache WHERE device_id = ? ORDER BY seg_index",
        (device_id,),
    ) as cur:
        rows = await cur.fetchall()
    out = [_seg_row_to_out(r) for r in rows]
    return WledRefreshResponse(segments=out, dropped_assignments=dropped)


@router.get(
    "/devices/{device_id}/segments",
    response_model=WledSegmentsResponse,
)
async def list_device_segments(
    device_id: str, request: Request
) -> WledSegmentsResponse:
    """D-18: return cached segments for a device. No device contact.

    Used by the frontend to render the strip after a page reload without
    forcing a refresh. The cache is on disk so the response is consistent
    across backend restarts (V4 persistence — see test_phase19_1_e2e.py).
    """
    db = request.app.state.db
    async with db.execute(
        "SELECT id FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        if (await cur.fetchone()) is None:
            raise HTTPException(
                status_code=404,
                detail=f"WLED device '{device_id}' not found",
            )

    async with db.execute(
        "SELECT seg_index, start_led, stop_led, name, refreshed_at "
        "FROM wled_seg_cache WHERE device_id = ? ORDER BY seg_index",
        (device_id,),
    ) as cur:
        rows = await cur.fetchall()
    return WledSegmentsResponse(segments=[_seg_row_to_out(r) for r in rows])


# ---------------------------------------------------------------------------
# Phase 19.1 - Assignment endpoints (D-13) — (region_id, wled_device_id,
# seg_index, entertainment_config_id) composite key
# ---------------------------------------------------------------------------


@router.get(
    "/assignments",
    response_model=WledAssignmentsResponse,
)
async def list_assignments(
    request: Request, config: str | None = None
) -> WledAssignmentsResponse:
    """List WLED assignments, optionally scoped to an entertainment config.

    Query param `config` matches the legacy contract (Phase 19's same endpoint
    required it; we keep it optional in 19.1 so the frontend can list-all when
    rendering the WLED tab without a config selected yet).
    """
    db = request.app.state.db
    if config is not None:
        async with db.execute(
            "SELECT region_id, wled_device_id, seg_index, entertainment_config_id, orientation "
            "FROM wled_light_assignments WHERE entertainment_config_id = ?",
            (config,),
        ) as cur:
            rows = await cur.fetchall()
    else:
        async with db.execute(
            "SELECT region_id, wled_device_id, seg_index, entertainment_config_id, orientation "
            "FROM wled_light_assignments"
        ) as cur:
            rows = await cur.fetchall()
    out = [
        WledAssignmentOut(
            region_id=r["region_id"],
            wled_device_id=r["wled_device_id"],
            seg_index=int(r["seg_index"]),
            entertainment_config_id=r["entertainment_config_id"],
            orientation=r["orientation"],
        )
        for r in rows
    ]
    return WledAssignmentsResponse(assignments=out)


@router.put(
    "/assignments",
    response_model=WledAssignmentOut,
)
async def upsert_assignment(
    body: WledAssignmentUpsert, request: Request
) -> WledAssignmentOut:
    """Upsert a region->segment assignment for a config (D-13).

    Per-region orientation invariant (CONTEXT.md D-16 / D-21): if the body
    omits `orientation`, new rows inherit the region's CURRENT orientation in
    this config (every existing row for this region+config carries the same
    value). Existing rows keep their orientation unless `orientation` is
    provided explicitly. Falls back to 'auto' when no prior row exists.
    """
    db = request.app.state.db

    # Resolve orientation: explicit body wins; otherwise read the exact same
    # row if it exists, then fall back to any sibling assignment for this
    # (region, config). Final fallback is 'auto'.
    if body.orientation is not None:
        orientation = body.orientation
    else:
        async with db.execute(
            "SELECT orientation FROM wled_light_assignments "
            "WHERE region_id = ? AND wled_device_id = ? AND seg_index = ? "
            "AND entertainment_config_id = ?",
            (
                body.region_id,
                body.wled_device_id,
                body.seg_index,
                body.entertainment_config_id,
            ),
        ) as cur:
            row = await cur.fetchone()
        if row is not None:
            orientation = row["orientation"]
        else:
            # Inherit from any existing sibling assignment for this region+config.
            async with db.execute(
                "SELECT orientation FROM wled_light_assignments "
                "WHERE region_id = ? AND entertainment_config_id = ? LIMIT 1",
                (body.region_id, body.entertainment_config_id),
            ) as cur:
                row = await cur.fetchone()
            orientation = row["orientation"] if row is not None else "auto"

    await db.execute(
        "INSERT INTO wled_light_assignments "
        "(region_id, wled_device_id, seg_index, entertainment_config_id, orientation) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(region_id, wled_device_id, seg_index, entertainment_config_id) "
        "DO UPDATE SET orientation = excluded.orientation",
        (
            body.region_id,
            body.wled_device_id,
            body.seg_index,
            body.entertainment_config_id,
            orientation,
        ),
    )
    await db.commit()
    return WledAssignmentOut(
        region_id=body.region_id,
        wled_device_id=body.wled_device_id,
        seg_index=body.seg_index,
        entertainment_config_id=body.entertainment_config_id,
        orientation=orientation,
    )


@router.delete(
    "/assignments",
    status_code=204,
)
async def delete_assignment(
    body: WledAssignmentDelete, request: Request
) -> Response:
    """Remove a single region->segment assignment for a config (D-13)."""
    db = request.app.state.db
    await db.execute(
        "DELETE FROM wled_light_assignments "
        "WHERE region_id = ? AND wled_device_id = ? AND seg_index = ? "
        "AND entertainment_config_id = ?",
        (
            body.region_id,
            body.wled_device_id,
            body.seg_index,
            body.entertainment_config_id,
        ),
    )
    await db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Phase 19 - Region orientation PATCH (per-region narrowing, CONTEXT D-16/D-22)
# ---------------------------------------------------------------------------


@router.patch(
    "/regions/{region_id}/orientation",
    response_model=WledOrientationPatchResponse,
)
async def patch_region_orientation(
    region_id: str,
    body: WledOrientationPatch,
    request: Request,
    config: str,
) -> WledOrientationPatchResponse:
    """Set the orientation for EVERY WLED assignment row matching
    (region_id, entertainment_config_id) — per-region narrowing (D-16/D-22).

    Single UPDATE statement; returns the number of rows updated. Returns
    updated=0 if no assignments exist for this region+config (not an error —
    the popover renders an empty state in that case). Phase 19.1 D-13
    rename: the filter columns are unchanged because per-region narrowing
    fans across all rows for that region+config regardless of which
    (wled_device_id, seg_index) they point at.
    """
    db = request.app.state.db
    cur = await db.execute(
        "UPDATE wled_light_assignments SET orientation = ? "
        "WHERE region_id = ? AND entertainment_config_id = ?",
        (body.orientation, region_id, config),
    )
    await db.commit()
    return WledOrientationPatchResponse(updated=cur.rowcount or 0)
