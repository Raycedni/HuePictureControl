"""WLED device CRUD + zeroconf scan REST endpoints.

Provides:
  GET    /api/wled/devices              — list registered devices with live state
  POST   /api/wled/devices              — register a new device by IP (fetches /json/info)
  DELETE /api/wled/devices/{id}         — remove device and cascade channels/assignments
  PUT    /api/wled/devices/{id}/enabled — toggle the per-frame UDP gate (D-12)
  POST   /api/wled/scan                 — 3s zeroconf scan for `_wled._tcp.local.`

Security notes:
  No auth (local network tool per PROJECT.md). IP validation via Pydantic
  regex `^(\\d{1,3}\\.){3}\\d{1,3}$` blocks CIDR (`1.2.3.0/24`), hostnames
  (`foo.local`), IPv6, and URL-encoded variants before any HTTP request is
  issued. The regex intentionally does NOT validate octet ranges (0..255) —
  Pydantic `Field(pattern=...)` is a regex match, and an out-of-range octet
  fails downstream at the OS socket / httpx layer (OSError on connect).

  T-17-SSRF: The `GET /json/info` fetch from a user-supplied IP is a
  consciously accepted risk. Per PROJECT.md the web UI is "local network
  tool only" — the LAN is the trust boundary. `httpx.AsyncClient` does not
  follow redirects by default in `fetch_wled_info`, so a compromised WLED
  device cannot redirect us to an attacker endpoint. `fetch_wled_info`
  parses JSON defensively (`data.get(...)` everywhere), never evaluates
  code.

  T-17-UDP: Devices are registered into the DB with `enabled=1` but no UDP
  traffic flows until `/api/capture/start` is called. WledStreamer's enabled
  gate (D-12) + 30-frame consecutive-failure cooldown (D-15) cap traffic to
  ~60 pps × N devices with auto-disable on unresponsive targets.

Exports:
    router -- APIRouter for /api/wled prefix
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services.wled_channels import (
    create_channel_with_split,
    delete_channel_with_cascade,
    resize_boundary,
)
from services.wled_client import fetch_wled_info
from services.wled_discovery import scan_for_wled_devices

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
# Phase 19 - Pydantic models for channel CRUD + assignment + orientation
# ---------------------------------------------------------------------------


WledOrientation = Literal[
    "auto",
    "horizontal-LTR",
    "horizontal-RTL",
    "vertical-TTB",
    "vertical-BTT",
]


class WledChannelOut(BaseModel):
    id: str
    device_id: str
    name: str
    start_led: int
    end_led: int


class WledChannelsResponse(BaseModel):
    channels: list[WledChannelOut]


class WledChannelCreate(BaseModel):
    start_led: int = Field(..., ge=0)
    end_led: int = Field(..., ge=0)
    name: str | None = None


class WledChannelUpdate(BaseModel):
    name: str | None = None
    start_led: int | None = Field(default=None, ge=0)
    end_led: int | None = Field(default=None, ge=0)


class WledChannelBoundaryUpdate(BaseModel):
    left_channel_id: str
    right_channel_id: str
    boundary: int = Field(..., ge=0)


class WledAssignmentIn(BaseModel):
    region_id: str
    wled_channel_id: str
    entertainment_config_id: str
    orientation: WledOrientation | None = None


class WledAssignmentOut(BaseModel):
    region_id: str
    wled_channel_id: str
    entertainment_config_id: str
    orientation: WledOrientation


class WledAssignmentsResponse(BaseModel):
    assignments: list[WledAssignmentOut]


class WledAssignmentDelete(BaseModel):
    region_id: str
    wled_channel_id: str
    entertainment_config_id: str


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
    """Register a new WLED device by IP.

    Flow (T-17-DUPE / T-17-SSRF mitigations):
      1. Pre-INSERT SELECT for duplicate IP — returns 409 cleanly before
         the httpx call fires (avoids hitting an attacker-controlled IP
         on retry of an already-registered device).
      2. `fetch_wled_info(ip)` over httpx — timeouts/connect errors map to
         502, JSON shape errors map to 422.
      3. Reject `led_count <= 0` with 422 (D-09 prerequisite — the auto-
         seeded channel needs a valid range).
      4. INSERT device + auto-seed one channel covering the full strip
         (D-09) inside one transaction.
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

    # Fetch /json/info — map error categories to 502 (network) / 422 (shape).
    try:
        info = await fetch_wled_info(body.ip)
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
    channel_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    name = info.get("name", "WLED")

    # D-07 + D-09: INSERT device + auto-seed one 'Strip' channel (full strip).
    await db.execute(
        "INSERT INTO wled_devices (id, ip, name, led_count, enabled, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (device_id, body.ip, name, led_count, now_iso),
    )
    await db.execute(
        "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) "
        "VALUES (?, ?, 'Strip', 0, ?, '#ffffff')",
        (channel_id, device_id, led_count - 1),
    )
    await db.commit()

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
    """Cascade-delete a WLED device, its channels, and any region assignments.

    SQLite FK constraints in the schema are documentation-only — the project
    does NOT run with `PRAGMA foreign_keys = ON` (per 17-RESEARCH.md A5), so
    cascade is implemented in code via three explicit DELETE statements
    (T-17-DELETE-ORPHAN mitigation): assignments first (subquery on the
    device's channels), then the channels, then the device row itself.

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

    # 1) Delete assignments via subquery on this device's channels.
    #    Single statement (one grep hit) and correct whether the device has
    #    zero, one, or many channels.
    await db.execute(
        "DELETE FROM wled_light_assignments WHERE wled_channel_id IN "
        "(SELECT id FROM wled_channels WHERE device_id = ?)",
        (device_id,),
    )

    # 2) Delete channels
    await db.execute(
        "DELETE FROM wled_channels WHERE device_id = ?", (device_id,)
    )

    # 3) Delete device
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
# Phase 19 - Channel CRUD endpoints (D-21)
# ---------------------------------------------------------------------------


@router.get(
    "/devices/{device_id}/channels",
    response_model=WledChannelsResponse,
)
async def list_channels(device_id: str, request: Request) -> WledChannelsResponse:
    """List channels for a device ordered by start_led ASC."""
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
        "SELECT id, device_id, name, start_led, end_led FROM wled_channels "
        "WHERE device_id = ? ORDER BY start_led ASC",
        (device_id,),
    ) as cur:
        rows = await cur.fetchall()
    channels = [
        WledChannelOut(
            id=r["id"],
            device_id=r["device_id"],
            name=r["name"],
            start_led=int(r["start_led"]),
            end_led=int(r["end_led"]),
        )
        for r in rows
    ]
    return WledChannelsResponse(channels=channels)


@router.post(
    "/devices/{device_id}/channels",
    response_model=WledChannelOut,
    status_code=201,
)
async def create_channel(
    device_id: str, body: WledChannelCreate, request: Request
) -> WledChannelOut:
    """Create a channel - applies overlap auto-split (D-02)."""
    db = request.app.state.db
    try:
        row = await create_channel_with_split(
            db, device_id, body.start_led, body.end_led
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=422, detail=msg)
    # Optional rename on create
    if body.name is not None:
        await db.execute(
            "UPDATE wled_channels SET name = ? WHERE id = ?",
            (body.name, row["id"]),
        )
        await db.commit()
        row["name"] = body.name
    return WledChannelOut(**row)


@router.put(
    "/devices/{device_id}/channels/boundary",
)
async def resize_channel_boundary(
    device_id: str, body: WledChannelBoundaryUpdate, request: Request
) -> dict:
    """Atomically move the shared boundary between two adjacent channels (D-03).

    ROUTING NOTE: This handler MUST be declared BEFORE the
    `PUT /devices/{device_id}/channels/{channel_id}` handler so that FastAPI
    does not greedily match the literal string "boundary" as a channel_id.
    """
    db = request.app.state.db
    # Verify both channels belong to this device.
    async with db.execute(
        "SELECT id FROM wled_channels WHERE id IN (?, ?) AND device_id = ?",
        (body.left_channel_id, body.right_channel_id, device_id),
    ) as cur:
        rows = await cur.fetchall()
    if len(rows) != 2:
        raise HTTPException(
            status_code=404,
            detail="left_channel_id or right_channel_id not found on device",
        )
    try:
        await resize_boundary(
            db, body.left_channel_id, body.right_channel_id, body.boundary
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ok": True}


@router.put(
    "/devices/{device_id}/channels/{channel_id}",
    response_model=WledChannelOut,
)
async def update_channel(
    device_id: str,
    channel_id: str,
    body: WledChannelUpdate,
    request: Request,
) -> WledChannelOut:
    """Rename and/or resize a channel. Partial PUT - all fields optional."""
    db = request.app.state.db
    async with db.execute(
        "SELECT id, device_id, name, start_led, end_led FROM wled_channels "
        "WHERE id = ? AND device_id = ?",
        (channel_id, device_id),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"channel '{channel_id}' not found on device '{device_id}'",
        )

    # Compute the new state, validating range bounds.
    new_name = body.name if body.name is not None else row["name"]
    new_start = body.start_led if body.start_led is not None else int(row["start_led"])
    new_end = body.end_led if body.end_led is not None else int(row["end_led"])
    if new_start > new_end:
        raise HTTPException(
            status_code=422,
            detail=f"start_led ({new_start}) must be <= end_led ({new_end})",
        )
    async with db.execute(
        "SELECT led_count FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        dev_row = await cur.fetchone()
    if dev_row is None:
        raise HTTPException(
            status_code=404, detail=f"WLED device '{device_id}' not found"
        )
    led_count = int(dev_row["led_count"])
    if new_start < 0 or new_end >= led_count:
        raise HTTPException(
            status_code=422,
            detail=f"range [{new_start}, {new_end}] outside [0, {led_count - 1}]",
        )

    await db.execute(
        "UPDATE wled_channels SET name = ?, start_led = ?, end_led = ? WHERE id = ?",
        (new_name, new_start, new_end, channel_id),
    )
    await db.commit()
    return WledChannelOut(
        id=channel_id,
        device_id=device_id,
        name=new_name,
        start_led=new_start,
        end_led=new_end,
    )


@router.delete(
    "/devices/{device_id}/channels/{channel_id}",
    status_code=204,
)
async def delete_channel(device_id: str, channel_id: str, request: Request) -> None:
    """Delete a channel - cascades to wled_light_assignments (D-04)."""
    db = request.app.state.db
    async with db.execute(
        "SELECT id FROM wled_channels WHERE id = ? AND device_id = ?",
        (channel_id, device_id),
    ) as cur:
        if (await cur.fetchone()) is None:
            raise HTTPException(
                status_code=404,
                detail=f"channel '{channel_id}' not found on device '{device_id}'",
            )
    try:
        await delete_channel_with_cascade(db, channel_id)
    except ValueError as exc:
        # Should be unreachable given the existence check above; defensive.
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Phase 19 - Assignment endpoints (D-21)
# ---------------------------------------------------------------------------


@router.get(
    "/assignments",
    response_model=WledAssignmentsResponse,
)
async def list_assignments(
    request: Request, config: str
) -> WledAssignmentsResponse:
    """List all WLED assignments scoped to an entertainment config."""
    db = request.app.state.db
    async with db.execute(
        "SELECT region_id, wled_channel_id, entertainment_config_id, orientation "
        "FROM wled_light_assignments WHERE entertainment_config_id = ?",
        (config,),
    ) as cur:
        rows = await cur.fetchall()
    out = [
        WledAssignmentOut(
            region_id=r["region_id"],
            wled_channel_id=r["wled_channel_id"],
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
    body: WledAssignmentIn, request: Request
) -> WledAssignmentOut:
    """Upsert a region->channel assignment for a config.

    Per-region orientation invariant (CONTEXT.md D-16): if the body omits
    `orientation`, new rows inherit the region's CURRENT orientation in this
    config (every existing row for this region+config carries the same value).
    Existing rows keep their orientation unless `orientation` is provided.
    """
    db = request.app.state.db

    # Channel existence check (also implicitly validates device via FK).
    async with db.execute(
        "SELECT id FROM wled_channels WHERE id = ?", (body.wled_channel_id,)
    ) as cur:
        if (await cur.fetchone()) is None:
            raise HTTPException(
                status_code=404,
                detail=f"channel '{body.wled_channel_id}' not found",
            )

    # Resolve orientation: explicit body wins; otherwise read region's current
    # orientation (any row for this region+config); fall back to 'auto'.
    if body.orientation is not None:
        orientation = body.orientation
    else:
        async with db.execute(
            "SELECT orientation FROM wled_light_assignments "
            "WHERE region_id = ? AND entertainment_config_id = ? LIMIT 1",
            (body.region_id, body.entertainment_config_id),
        ) as cur:
            r = await cur.fetchone()
        orientation = r["orientation"] if r is not None else "auto"

    await db.execute(
        "INSERT INTO wled_light_assignments "
        "(region_id, wled_channel_id, entertainment_config_id, orientation) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(region_id, wled_channel_id, entertainment_config_id) "
        "DO UPDATE SET orientation = excluded.orientation",
        (
            body.region_id,
            body.wled_channel_id,
            body.entertainment_config_id,
            orientation,
        ),
    )
    await db.commit()
    return WledAssignmentOut(
        region_id=body.region_id,
        wled_channel_id=body.wled_channel_id,
        entertainment_config_id=body.entertainment_config_id,
        orientation=orientation,
    )


@router.delete(
    "/assignments",
    status_code=204,
)
async def delete_assignment(body: WledAssignmentDelete, request: Request) -> None:
    """Remove a single region->channel assignment for a config (D-21)."""
    db = request.app.state.db
    async with db.execute(
        "DELETE FROM wled_light_assignments "
        "WHERE region_id = ? AND wled_channel_id = ? AND entertainment_config_id = ?",
        (body.region_id, body.wled_channel_id, body.entertainment_config_id),
    ):
        pass
    await db.commit()


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
    (region_id, entertainment_config_id) - per-region narrowing (D-16/D-22).

    Single UPDATE statement; returns the number of rows updated. Returns
    updated=0 if no assignments exist for this region+config (not an error -
    the popover renders an empty state in that case).
    """
    db = request.app.state.db
    cur = await db.execute(
        "UPDATE wled_light_assignments SET orientation = ? "
        "WHERE region_id = ? AND entertainment_config_id = ?",
        (body.orientation, region_id, config),
    )
    await db.commit()
    return WledOrientationPatchResponse(updated=cur.rowcount or 0)
