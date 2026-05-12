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

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

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
