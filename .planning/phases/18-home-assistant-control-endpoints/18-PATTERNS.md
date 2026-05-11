# Phase 18: Home Assistant Control Endpoints - Pattern Map

**Mapped:** 2026-05-11
**Files analyzed:** 6 (3 new, 3 modified)
**Analogs found:** 6 / 6 (all exact-role matches in the codebase)

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Backend/routers/ha.py` (NEW) | router | request-response (CRUD + delegation) | `Backend/routers/wled.py` + `Backend/routers/cameras.py` | exact (controller+CRUD, multi-file) |
| `Backend/tests/test_ha_router.py` (NEW) | test | request-response (unit) | `Backend/tests/test_wled_router.py` | exact |
| `Backend/tests/test_ha_e2e.py` (NEW) | test | event-driven (integration) | `Backend/tests/test_phase17_e2e.py` | exact |
| `Backend/database.py` (MODIFY) | config / schema | DDL | `Backend/database.py` (in-file `bridge_config` block) | exact (self-analog) |
| `Backend/main.py` (MODIFY) | config / wiring | startup | `Backend/main.py` (in-file `wled_router` include) | exact (self-analog) |
| `Backend/services/streaming_coordinator.py` (MODIFY, optional) | service | event-driven | `Backend/services/streaming_coordinator.py::start` (self-analog) | exact |

Notes on choice:
- `routers/wled.py` is the **freshest** router (Phase 17, days-old) and uses the **exact `getattr(request.app.state, "coordinator", None)` test-tolerance pattern** the discretion locks for Phase 18. Use it as the primary analog for: Pydantic model conventions, `_coord_health` helper shape, idempotent-with-coordinator-falls-back-to-DB pattern, error mapping (502/422), router shell.
- `routers/cameras.py` is the **only** existing analog for the **dual-write transactional pattern** (D-06) — `put_last_zone` writes `camera_last_zone` then bumps `known_cameras.last_seen_at` under one `db.commit()`. Use it for: `PUT /api/ha/zone` dual-write, `PUT /api/ha/camera` validation-then-write, ISO timestamp via `datetime.now(timezone.utc).isoformat()`.
- `routers/capture.py::start_capture/stop_capture` are the **minimal coordinator-wiring template** — three lines each. Use for the `POST /api/ha/start` / `POST /api/ha/stop` delegation shape (NOT for body model — D-03 says empty body).
- `routers/hue.py::status` is the **`bridge_paired` flag pattern** (single SELECT 1 against `bridge_config WHERE id=1`).
- `services/hue_client.py::list_entertainment_configs` is **already async and already returns `{id, name, status, channel_count}`** — `GET /api/ha/zones` is a `{id, name}`-only projection (no helper extraction needed unless planner prefers).

---

## Pattern Assignments

### `Backend/routers/ha.py` (router, request-response)

**Primary analog:** `Backend/routers/wled.py`
**Secondary analog:** `Backend/routers/cameras.py` (dual-write + validation chain)
**Tertiary analog:** `Backend/routers/capture.py` (coordinator delegation), `Backend/routers/hue.py` (bridge-paired check)

#### Imports pattern (mirror `routers/wled.py:34-47`)

Copy this header block verbatim, adjusting the `services` imports:

```python
"""Home Assistant control REST endpoints (Phase 18).

Provides:
  POST /api/ha/start       — start streaming using selections in ha_state
  POST /api/ha/stop        — stop streaming (idempotent)
  GET  /api/ha/status      — curated HA-friendly status payload (D-09)
  PUT  /api/ha/zone        — persist HA's entertainment zone selection
  PUT  /api/ha/camera      — persist HA's camera selection (no camera_assignments write)
  GET  /api/ha/zones       — `[{id, name}]` discovery wrapper
  GET  /api/ha/cameras     — `[{stable_id, name, connected}]` discovery wrapper

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

from routers.cameras import _scan_devices  # reuse V4L2 scan
from services.hue_client import list_entertainment_configs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ha", tags=["ha"])
```

Source for shape: `routers/wled.py:34-47`. The `routers.cameras._scan_devices` import follows the discretion-locked "reuse existing helper" choice (CONTEXT.md §Existing Code Insights).

#### Pydantic models pattern (mirror `routers/wled.py:55-86` + `routers/cameras.py:82-89`)

Per CONTEXT.md Claude's Discretion: all models inline, no separate `models/ha.py`. RESEARCH.md §Pattern 2 specifies the exact set. Copy from `routers/cameras.py` style (no `Field(pattern=...)` needed here — IDs are opaque text):

```python
# Mirror of routers/cameras.py:82-89 + routers/wled.py:55-86

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
    error: str | None = None  # D-09 additive — omitted from happy path via exclude_none
```

`Field(..., min_length=1)` rationale: RESEARCH.md §Security Domain row "Empty `zone_id` / empty `stable_id` strings" — recommends adding `min_length=1` to prevent silent upsert of `""`. Marked `[ASSUMED]` in research but cheap hardening.

#### Coordinator access pattern — copy from `routers/wled.py:126-142`

This is the **test-tolerance pattern locked in CONTEXT.md Claude's Discretion**. Use the same `getattr` skeleton; do NOT just call `request.app.state.coordinator` like `routers/capture.py:47` does (the WLED router’s pattern was specifically chosen so unit tests can mount the router without wiring a coordinator).

```python
# Mirror of Backend/routers/wled.py:126-142
def _coord(request: Request):
    """Return the coordinator if wired, else None (tolerant of CRUD-only tests)."""
    return getattr(request.app.state, "coordinator", None)


def _broadcaster_metrics(request: Request) -> dict:
    """Return the broadcaster's _metrics dict, or an idle fallback if not wired."""
    broadcaster = getattr(request.app.state, "broadcaster", None)
    if broadcaster is None:
        return {
            "state": "idle",
            "fps": 0,
            "latency_ms": 0,
            "active_config_id": None,
            "active_device_path": None,
        }
    return broadcaster._metrics
```

For the `POST /api/ha/start` handler specifically — copy the wled.py "if coordinator is None: fall back / else: delegate" structure from `routers/wled.py:329-338`:

```python
# Source: Backend/routers/wled.py:329-338
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
```

For `/api/ha/start` the analog is: if coordinator is None → raise 503 (per RESEARCH.md §Error Semantics table); otherwise call `coordinator.start(...)`. The wled pattern's "fall back to DB" branch does NOT translate to `/start` because there is no test-friendly degraded path for streaming itself; the test simply won't call `/start` without wiring a mock coordinator.

#### Validation-then-write 404 chain — copy verbatim from `routers/cameras.py:412-437`

This is the canonical "validate every FK-like reference, raise 404, THEN write" idiom. Both `PUT /api/ha/zone` and `PUT /api/ha/camera` use it.

```python
# Source: Backend/routers/cameras.py:412-437
async with db.execute(
    "SELECT stable_id FROM known_cameras WHERE stable_id = ?",
    (stable_id,),
) as cursor:
    row = await cursor.fetchone()
if row is None:
    raise HTTPException(
        status_code=404,
        detail=f"stable_id '{stable_id}' not found in known cameras.",
    )

async with db.execute(
    "SELECT id FROM entertainment_configs WHERE id = ?",
    (body.entertainment_config_id,),
) as cursor:
    cfg_row = await cursor.fetchone()
if cfg_row is None:
    raise HTTPException(
        status_code=404,
        detail=(
            f"entertainment_config_id '{body.entertainment_config_id}' "
            "not found in entertainment_configs."
        ),
    )
```

For Phase 18:
- `PUT /api/ha/zone` validates `body.zone_id` in `entertainment_configs` only (single SELECT).
- `PUT /api/ha/camera` validates `body.stable_id` in `known_cameras` only (single SELECT).
- `POST /api/ha/start` validates **after** reading `ha_state.active_config_id`: if NULL → 400, else SELECT against `entertainment_configs` → 404.

#### Transactional dual-write — copy verbatim from `routers/cameras.py:439-457`

This is the D-06 pattern. The shape — `INSERT ... ON CONFLICT DO UPDATE` followed by a second `await db.execute(...)` then a single `await db.commit()` — is the project-locked idiom.

```python
# Source: Backend/routers/cameras.py:439-457
now = datetime.now(timezone.utc).isoformat()

# Upsert the last-zone mapping
await db.execute(
    """
    INSERT INTO camera_last_zone (camera_stable_id, entertainment_config_id, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(camera_stable_id) DO UPDATE SET
        entertainment_config_id = excluded.entertainment_config_id,
        updated_at = excluded.updated_at
    """,
    (stable_id, body.entertainment_config_id, now),
)
# D-10: bump last_seen_at in the same transaction
await db.execute(
    "UPDATE known_cameras SET last_seen_at = ? WHERE stable_id = ?",
    (now, stable_id),
)
await db.commit()
```

For Phase 18 `PUT /api/ha/zone` adapt to:

```python
# D-06 — adapt routers/cameras.py:439-457 to ha_state + conditional camera_last_zone
now = datetime.now(timezone.utc).isoformat()

# 1) upsert ha_state preserving active_camera_stable_id
await db.execute(
    """
    INSERT INTO ha_state (id, active_config_id, active_camera_stable_id, updated_at)
    VALUES (1, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        active_config_id = excluded.active_config_id,
        updated_at       = excluded.updated_at
    """,
    (body.zone_id, current_camera, now),
)

# 2) D-06 conditional dual-write — only when a camera is already set
if current_camera is not None:
    await db.execute(
        """
        INSERT INTO camera_last_zone (camera_stable_id, entertainment_config_id, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(camera_stable_id) DO UPDATE SET
            entertainment_config_id = excluded.entertainment_config_id,
            updated_at              = excluded.updated_at
        """,
        (current_camera, body.zone_id, now),
    )

await db.commit()
```

Key adaptation vs. the camera router source:
- `ha_state` is single-row (`id=1`), so the ON CONFLICT target is `(id)` not `(camera_stable_id)`.
- `active_camera_stable_id` is preserved via the parameter `current_camera` read in a prior `SELECT` (RESEARCH.md §Example 3, lines 1018-1024). This avoids the SQLite REPLACE-drops-columns pitfall (RESEARCH.md §Pitfall 1).
- The dual-write to `camera_last_zone` is **conditional** — that's the new D-06 semantics; cameras.py's version is unconditional. The conditional guard is `if current_camera is not None:` — D-06 step 4.

#### Single-row `INSERT OR REPLACE` (PUT /api/ha/camera) — copy from `routers/hue.py:47-64`

`PUT /api/ha/camera` is a simpler single-write — same single-row upsert pattern as `bridge_config`:

```python
# Source: Backend/routers/hue.py:47-64
await db.execute(
    """
    INSERT OR REPLACE INTO bridge_config
        (id, bridge_id, rid, ip_address, username, hue_app_id, client_key, swversion, name)
    VALUES (1, :bridge_id, :rid, :ip_address, :username, :hue_app_id, :client_key, :swversion, :name)
    """,
    {...},
)
await db.commit()
```

Adapt for `PUT /api/ha/camera` — but **prefer `ON CONFLICT DO UPDATE`** over `INSERT OR REPLACE` to avoid the SQLite REPLACE-drops-columns pitfall (D-07 requires preserving `active_config_id`):

```python
# D-07 — preserve active_config_id; ON CONFLICT pattern over INSERT OR REPLACE
now = datetime.now(timezone.utc).isoformat()
await db.execute(
    """
    INSERT INTO ha_state (id, active_config_id, active_camera_stable_id, updated_at)
    VALUES (1, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        active_camera_stable_id = excluded.active_camera_stable_id,
        updated_at              = excluded.updated_at
    """,
    (current_config, body.stable_id, now),
)
await db.commit()
```

Where `current_config` is read by a prior SELECT (same shape as `current_camera` in PUT /api/ha/zone). RESEARCH.md §Pitfall 1 spells out why ON CONFLICT > INSERT OR REPLACE for partial-column updates.

**D-07 NEGATIVE assertion:** PUT /api/ha/camera **must not** touch `camera_assignments`. No SQL fragment shown — the absence is the point. The test `test_put_camera_does_not_touch_assignments` asserts the count is zero after PUT.

#### Coordinator delegation (POST /api/ha/start) — copy from `routers/capture.py:37-49`

The minimal delegation pattern is two lines:

```python
# Source: Backend/routers/capture.py:37-49
@router.post("/start")
async def start_capture(body: StartCaptureRequest, request: Request):
    coordinator = request.app.state.coordinator
    await coordinator.start(body.config_id, target_hz=body.target_hz)
    return {"status": "starting"}
```

For Phase 18 `POST /api/ha/start`, swap the body shape (empty body — RESEARCH.md §Pitfall 6) and the lookup source (read from `ha_state`, not body):

```python
# Phase 18 — capture.py delegation + D-08 precondition chain + Option C device_path_override
@router.post("/start", response_model=HaStatusResponse, response_model_exclude_none=True)
async def ha_start(request: Request) -> HaStatusResponse:
    db = request.app.state.db

    # 1) Read ha_state row (D-05 lazy — may be missing)
    async with db.execute(
        "SELECT active_config_id, active_camera_stable_id FROM ha_state WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    if row is None or not row["active_config_id"]:
        raise HTTPException(400, detail="no zone selected — call PUT /api/ha/zone first")
    active_config_id = row["active_config_id"]
    active_camera_stable_id = row["active_camera_stable_id"]

    # 2) Re-validate zone still exists (it may have been deleted on the Bridge)
    async with db.execute(
        "SELECT id FROM entertainment_configs WHERE id = ?",
        (active_config_id,),
    ) as cur:
        if (await cur.fetchone()) is None:
            raise HTTPException(404, detail="zone not found — it may have been deleted on the Bridge")

    # 3) Resolve device_path_override from ha_state.active_camera_stable_id (D-08 step 3a)
    device_path_override: str | None = None
    if active_camera_stable_id:
        async with db.execute(
            "SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
            (active_camera_stable_id,),
        ) as cur:
            cam = await cur.fetchone()
        if cam and cam["last_device_path"]:
            device_path_override = cam["last_device_path"]

    # 4) Delegate to coordinator (Option C — RESEARCH.md A1)
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is None:
        raise HTTPException(503, detail="Coordinator unavailable")
    await coordinator.start(active_config_id, device_path_override=device_path_override)

    return await _build_status_response(request)
```

`POST /api/ha/stop` is even simpler:

```python
@router.post("/stop", response_model=HaStatusResponse, response_model_exclude_none=True)
async def ha_stop(request: Request) -> HaStatusResponse:
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is not None:
        await coordinator.stop()
    return await _build_status_response(request)
```

Both endpoints return `HaStatusResponse` (RESEARCH.md §Open Question 2 answer: same response model for all three control endpoints).

#### Bridge-paired check — copy from `routers/hue.py:78-88` + `routers/hue.py:99-113`

For `GET /api/ha/status::bridge_paired` and for `GET /api/ha/zones::503-when-unpaired`:

```python
# Source: Backend/routers/hue.py:78-88
async with db.execute("SELECT ip_address, name FROM bridge_config WHERE id=1") as cursor:
    row = await cursor.fetchone()

if row is None:
    return BridgeStatusResponse(paired=False)
```

```python
# Source: Backend/routers/hue.py:99-113 — bridge-paired guard before calling Hue
async with db.execute(
    "SELECT ip_address, username FROM bridge_config WHERE id=1"
) as cursor:
    row = await cursor.fetchone()

if row is None:
    raise HTTPException(status_code=400, detail="Bridge not paired")

raw = await list_entertainment_configs(row["ip_address"], row["username"])
```

For Phase 18 `GET /api/ha/zones` use the same SELECT but bump 400 → 503 (CONTEXT.md Claude's Discretion — HA-friendly mapping, asymmetric with `/api/hue/configs` is intentional, RESEARCH.md §HA Error Semantics):

```python
@router.get("/zones", response_model=HaZoneListResponse)
async def ha_zones(request: Request) -> HaZoneListResponse:
    db = request.app.state.db
    async with db.execute(
        "SELECT ip_address, username FROM bridge_config WHERE id=1"
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(503, detail="Hue bridge not paired")
    try:
        raw = await list_entertainment_configs(row["ip_address"], row["username"])
    except httpx.HTTPError as exc:
        raise HTTPException(502, detail=f"Hue bridge unreachable: {exc}")
    return HaZoneListResponse(zones=[HaZoneOut(id=c["id"], name=c["name"]) for c in raw])
```

#### Error mapping pattern — copy from `routers/wled.py:194-215`

Used by `GET /api/ha/zones` and by the graceful-degrade try/except in `_build_status_response`. The full `try/except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError)` chain is verified-canonical from wled.py:

```python
# Source: Backend/routers/wled.py:194-215
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
```

For `/api/ha/status` use the **graceful-degrade** variant (do NOT re-raise; RESEARCH.md §Pitfall 4) — collapse all three httpx exceptions into a single `except httpx.HTTPError` block since the parent catches the rest:

```python
# Phase 18 graceful-degrade — adapted from wled.py:194-215
try:
    configs = await list_entertainment_configs(row["ip_address"], row["username"])
    config_name_by_id = {c["id"]: c["name"] for c in configs}
except httpx.HTTPError as exc:
    logger.warning("Hue bridge unreachable in /api/ha/status: %s", exc)
    config_name_by_id = {}  # graceful degrade — names null, payload still valid
```

#### GET /api/ha/status assembly — RESEARCH.md §Example 4 is the full template

Copy the body of `_build_status_response` from RESEARCH.md lines 1065-1138 directly. The function reads:
1. `_metrics` from broadcaster (with `getattr(..., None)` fallback for tests)
2. `bridge_config` row → `bridge_paired` + Hue Bridge address
3. `list_entertainment_configs` via Hue client → name lookup dict (try/except graceful degrade)
4. `ha_state` row → `ha_selected_*` (None when row absent)
5. `known_cameras` reverse lookup on `active_device_path` → `active_camera_*`
6. `known_cameras` PK lookup on `ha_state.active_camera_stable_id` → `ha_selected_camera_name`

Use `response_model_exclude_none=True` on the `/status` route decorator so the optional `error` field stays out of the happy-path payload (CONTEXT.md D-09 Claude's Discretion).

#### GET /api/ha/cameras — reuse `_scan_devices` + project to D-11 shape

```python
# Source for _scan_devices import + usage: routers/cameras.py:162-249

@router.get("/cameras", response_model=HaCameraListResponse)
async def ha_cameras(request: Request) -> HaCameraListResponse:
    db = request.app.state.db
    # Reuse routers/cameras._scan_devices — already async, already runs the
    # ioctl in a thread pool (asyncio.to_thread under the hood).
    scan_results, _ = await _scan_devices()

    # known_cameras includes previously-seen-but-gone devices (per cameras.py:182-192)
    async with db.execute(
        "SELECT stable_id, display_name FROM known_cameras"
    ) as cur:
        rows = await cur.fetchall()

    cameras: list[HaCameraOut] = []
    for r in rows:
        cameras.append(HaCameraOut(
            stable_id=r["stable_id"],
            name=r["display_name"],
            connected=r["stable_id"] in scan_results,
        ))
    return HaCameraListResponse(cameras=cameras)
```

This is the D-11 projection: only `{stable_id, name, connected}` — strip the `last_seen_at`, `last_entertainment_config_id`, `identity_mode`, `zone_health` fields that `GET /api/cameras` returns.

---

### `Backend/tests/test_ha_router.py` (test, request-response)

**Analog:** `Backend/tests/test_wled_router.py`

#### Test scaffolding — copy verbatim from `test_wled_router.py:40-109`

The `_make_db()` helper, `_wled_app_lifespan` asynccontextmanager, `_make_client()` factory, and `_make_app()` factory are the project's locked test scaffolding. Adapt the schema to Phase 18's table set:

```python
# Adapted from Backend/tests/test_wled_router.py:40-79
async def _make_db():
    """In-memory aiosqlite with only the tables routers/ha.py touches."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript("""
        CREATE TABLE bridge_config (
            id INTEGER PRIMARY KEY,
            bridge_id TEXT NOT NULL,
            rid TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            username TEXT NOT NULL,
            hue_app_id TEXT NOT NULL,
            client_key TEXT NOT NULL,
            swversion INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE entertainment_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            channel_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE known_cameras (
            stable_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            last_seen_at TEXT,
            last_device_path TEXT
        );
        CREATE TABLE camera_assignments (
            entertainment_config_id TEXT PRIMARY KEY,
            camera_stable_id TEXT NOT NULL,
            camera_name TEXT NOT NULL
        );
        CREATE TABLE camera_last_zone (
            camera_stable_id TEXT PRIMARY KEY,
            entertainment_config_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE ha_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_config_id TEXT,
            active_camera_stable_id TEXT,
            updated_at TEXT
        );
    """)
    await conn.commit()
    return conn
```

#### Lifespan + client pattern — copy from `test_wled_router.py:82-109`

```python
# Source: Backend/tests/test_wled_router.py:82-109
@asynccontextmanager
async def _wled_app_lifespan(app):
    db = await _make_db()
    app.state.db = db
    try:
        yield
    finally:
        await db.close()


def _make_client() -> TestClient:
    from routers.wled import router as wled_router
    app = FastAPI(lifespan=_wled_app_lifespan)
    app.include_router(wled_router)
    return TestClient(app)


def _make_app() -> FastAPI:
    from routers.wled import router as wled_router
    app = FastAPI(lifespan=_wled_app_lifespan)
    app.include_router(wled_router)
    return app
```

Rename `_wled_app_lifespan` → `_ha_app_lifespan`, swap `routers.wled` → `routers.ha`. Phase 18 unit tests **omit** the coordinator wiring (the `getattr(..., None)` fallback handles it) **except** for the few that drive `/start` and `/stop` — those tests need a `MagicMock` coordinator on `app.state.coordinator` (use the conftest helper `_make_coordinator_mock`, lines 171-177).

#### Direct-DB-poke pattern — copy from `test_wled_router.py:174-189`

The `asyncio.run` + nested async fn pattern is the locked idiom for "after a request, check the DB row was written":

```python
# Source: Backend/tests/test_wled_router.py:174-189
async def _check_channel():
    db = app.state.db
    async with db.execute(
        "SELECT id, name, start_led, end_led, color "
        "FROM wled_channels WHERE device_id = ?",
        (dev_id,),
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1
    ch = rows[0]
    assert ch["name"] == "Strip"
    assert ch["start_led"] == 0
    assert ch["end_led"] == 299
    assert ch["color"] == "#ffffff"

asyncio.run(_check_channel())
```

For Phase 18:
- `test_put_zone_persists_lazy`: after `PUT /api/ha/zone`, assert `ha_state` row has `active_config_id == "cfg1"` and `active_camera_stable_id IS NULL`.
- `test_put_zone_dual_writes_camera_last_zone`: after seeding `ha_state` with a camera, PUT a zone, assert `camera_last_zone` row exists for that camera.
- `test_put_zone_skips_dual_write_when_no_camera`: without seeding a camera, PUT a zone, assert `SELECT COUNT(*) FROM camera_last_zone` is 0.
- `test_put_camera_does_not_touch_assignments`: after `PUT /api/ha/camera`, assert `SELECT COUNT(*) FROM camera_assignments` is 0.
- `test_put_zone_preserves_camera`: PUT camera, PUT zone, assert `ha_state.active_camera_stable_id` is unchanged.

#### Mock-patching pattern — copy from `test_wled_router.py:124-133`

The `patch("routers.<name>.<symbol>", AsyncMock(...))` form is the project idiom. Patch at the **router import path**, not at the service definition path:

```python
# Source: Backend/tests/test_wled_router.py:124-133
def test_add_device_unreachable_returns_502():
    with _make_client() as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(side_effect=httpx.ConnectError("refused")),
        ):
            r = client.post("/api/wled/devices", json={"ip": "192.168.1.99"})
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"].lower()
```

For Phase 18: `patch("routers.ha.list_entertainment_configs", AsyncMock(return_value=[{"id": "cfg1", "name": "TV-Bereich", "status": "inactive", "channel_count": 6}]))` to test `/api/ha/status` friendly-name resolution and `/api/ha/zones` listing. Also `patch("routers.ha._scan_devices", AsyncMock(return_value=({"sid1": {...}}, False)))` for `/api/ha/cameras`.

#### Coordinator mock — use conftest helper from `conftest.py:171-177`

```python
# Source: Backend/tests/conftest.py:171-177
def _make_coordinator_mock():
    """Return a MagicMock StreamingCoordinator with async start/stop and idle state."""
    mock_coordinator = MagicMock()
    mock_coordinator.start = AsyncMock()
    mock_coordinator.stop = AsyncMock()
    type(mock_coordinator).state = property(lambda self: "idle")
    return mock_coordinator
```

For Phase 18:
- `test_start_calls_coordinator_with_resolved_path`: import `_make_coordinator_mock` from `tests.conftest`, attach to `app.state.coordinator` inside the lifespan, seed `ha_state` + `known_cameras`, call `POST /api/ha/start`, then `mock_coordinator.start.assert_called_once_with("cfg1", device_path_override="/dev/video10")`.
- `test_start_idempotent_when_streaming`: override `type(mock_coordinator).state = property(lambda self: "streaming")`. Since `coordinator.start` is itself idempotent (RESEARCH.md §`start` semantics), calling it again is a silent no-op → 200; assert response is `HaStatusResponse`.
- `test_stop_idempotent_when_idle`: default state="idle"; `coordinator.stop` is already a no-op when idle.

---

### `Backend/tests/test_ha_e2e.py` (test, event-driven integration)

**Analog:** `Backend/tests/test_phase17_e2e.py`

#### Schema helper — copy `_make_db_with_phase17_schema` from `test_phase17_e2e.py:42-106`

The phase17 helper already creates `camera_assignments` and `known_cameras` because `_resolve_device_path` needs them. Phase 18 needs the same set **plus** `ha_state`, `bridge_config`, `entertainment_configs`, and `camera_last_zone`:

```python
# Adapted from Backend/tests/test_phase17_e2e.py:42-106
async def _make_db_with_phase18_schema():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript("""
        -- Existing tables phase 17 e2e already creates
        CREATE TABLE regions (
            id TEXT PRIMARY KEY, name TEXT, polygon TEXT NOT NULL,
            order_index INTEGER DEFAULT 0, light_id TEXT,
            entertainment_config_id TEXT
        );
        CREATE TABLE light_assignments (
            region_id TEXT NOT NULL, channel_id INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, channel_id, entertainment_config_id)
        );
        CREATE TABLE wled_devices (
            id TEXT PRIMARY KEY, ip TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            led_count INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE wled_channels (
            id TEXT PRIMARY KEY, device_id TEXT NOT NULL, name TEXT NOT NULL,
            start_led INTEGER NOT NULL, end_led INTEGER NOT NULL,
            color TEXT NOT NULL DEFAULT '#ffffff'
        );
        CREATE TABLE wled_light_assignments (
            region_id TEXT NOT NULL, wled_channel_id TEXT NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id)
        );
        CREATE TABLE camera_assignments (
            entertainment_config_id TEXT PRIMARY KEY,
            camera_stable_id TEXT NOT NULL, camera_name TEXT NOT NULL
        );
        CREATE TABLE known_cameras (
            stable_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            last_seen_at TEXT, last_device_path TEXT
        );
        -- Phase 18 additions
        CREATE TABLE bridge_config (
            id INTEGER PRIMARY KEY, bridge_id TEXT NOT NULL, rid TEXT NOT NULL,
            ip_address TEXT NOT NULL, username TEXT NOT NULL,
            hue_app_id TEXT NOT NULL, client_key TEXT NOT NULL,
            swversion INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE entertainment_configs (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            channel_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE camera_last_zone (
            camera_stable_id TEXT PRIMARY KEY,
            entertainment_config_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE ha_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_config_id TEXT, active_camera_stable_id TEXT,
            updated_at TEXT
        );
    """)
    await conn.commit()
    return conn
```

#### Coordinator wiring — copy from `test_phase17_e2e.py:109-188`

```python
# Source: Backend/tests/test_phase17_e2e.py:109-129
class _MockRegistry:
    def __init__(self, capture):
        self._capture = capture
    def acquire(self, path):
        return self._capture
    def release(self, path):
        pass


def _make_mock_hue():
    mock = MagicMock()
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    mock.render = AsyncMock()
    mock.handle_bridge_error = AsyncMock(return_value=True)
    return mock
```

```python
# Source: Backend/tests/test_phase17_e2e.py:175-188
broadcaster = StatusBroadcaster()
mock_hue = _make_mock_hue()
capture = make_mock_capture()
registry = _MockRegistry(capture)
real_wled = WledStreamer(udp_port=41324)

coord = StreamingCoordinator(
    db=db,
    capture_registry=registry,
    broadcaster=broadcaster,
    hue_streamer=mock_hue,
    wled_streamer=real_wled,
)
```

For Phase 18 e2e — RESEARCH.md §Integration-test template recommends using a `MagicMock` `WledStreamer` instead of a real loopback streamer (we're not asserting WLED packet shape here):

```python
# Phase 18 — replace real_wled with a MagicMock
mock_wled = MagicMock()
mock_wled.start = AsyncMock()
mock_wled.stop = AsyncMock()
mock_wled.render = AsyncMock()
mock_wled.set_enabled = MagicMock()
mock_wled.health_snapshot = MagicMock(return_value={})

coord = StreamingCoordinator(
    db=db, capture_registry=_MockRegistry(make_mock_capture()),
    broadcaster=broadcaster, hue_streamer=_make_mock_hue(),
    wled_streamer=mock_wled,
)
```

#### Mount the HA router with the real coordinator — copy from `test_phase17_e2e.py:258-273`

```python
# Source: Backend/tests/test_phase17_e2e.py:258-273
@asynccontextmanager
async def _lifespan(app):
    app.state.db = db
    app.state.coordinator = coord
    yield

app = FastAPI(lifespan=_lifespan)
app.include_router(wled_router)

with TestClient(app) as client:
    r = client.delete("/api/wled/devices/d1")
    assert r.status_code == 204
```

For Phase 18 the lifespan also needs `app.state.broadcaster = broadcaster` so `_build_status_response` can read `_metrics`. Mount `routers.ha.router` + `patch("routers.ha.list_entertainment_configs", AsyncMock(return_value=[{"id":"cfg1","name":"TV-Bereich","status":"active","channel_count":6}]))` so `GET /api/ha/status` resolves friendly names without hitting a real bridge.

#### Test flow — adapted from CONTEXT.md test-strategy line

```
1. Seed bridge_config (id=1), entertainment_configs(id="cfg1",name="TV-Bereich"),
   known_cameras(stable_id="cam1", last_device_path="/dev/video10")
2. PUT /api/ha/zone {"zone_id": "cfg1"}                 -> assert 200
3. PUT /api/ha/camera {"stable_id": "cam1"}             -> assert 200
4. POST /api/ha/start (empty body)                       -> assert 200
5. await asyncio.sleep(0.5) (let coord reach streaming)
6. GET /api/ha/status                                    -> assert state="streaming",
                                                            active_config_id="cfg1",
                                                            active_camera_stable_id="cam1",
                                                            active_camera_name="..."
7. POST /api/ha/stop                                     -> assert 200, state="idle"
```

Use `@pytest.mark.asyncio` per `test_phase17_e2e.py:132`. Mock `routers.ha.list_entertainment_configs` to return the seeded configs so friendly-name resolution succeeds.

---

### `Backend/database.py` (config / schema)

**Analog (self-analog):** `database.py:17-29` (the `bridge_config` block).

#### Schema add — append after line 91, before the WLED block at line 92

```python
# Source: Backend/database.py:17-29 — the bridge_config single-row pattern
await db.execute("""
    CREATE TABLE IF NOT EXISTS bridge_config (
        id INTEGER PRIMARY KEY,
        bridge_id TEXT NOT NULL,
        rid TEXT NOT NULL,
        ip_address TEXT NOT NULL,
        username TEXT NOT NULL,
        hue_app_id TEXT NOT NULL,
        client_key TEXT NOT NULL,
        swversion INTEGER NOT NULL DEFAULT 0,
        name TEXT NOT NULL DEFAULT ''
    )
""")
```

For Phase 18 — add the `CHECK (id = 1)` constraint (D-04) and only the four columns:

```python
# Phase 18 D-04 — append at Backend/database.py line ~91 (between camera_last_zone and wled_devices)
await db.execute("""
    CREATE TABLE IF NOT EXISTS ha_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        active_config_id TEXT,
        active_camera_stable_id TEXT,
        updated_at TEXT
    )
""")
```

**Important — D-05 lazy seed:** Do NOT add an `INSERT OR IGNORE INTO ha_state (id) VALUES (1)` seed after the CREATE. RESEARCH.md §Anti-Patterns explicitly forbids eager seeding.

---

### `Backend/main.py` (config / wiring)

**Analog (self-analog):** `main.py:17` (import) + `main.py:83` (include_router for wled).

#### Import — copy line 17 pattern

```python
# Source: Backend/main.py:17
from routers.wled import router as wled_router
```

Add as a sibling import:

```python
# Phase 18 — add at Backend/main.py line ~17 (alphabetical with the rest)
from routers.ha import router as ha_router
```

#### Include — copy line 83 pattern

```python
# Source: Backend/main.py:79-86 — full include block
app.include_router(health_router)
app.include_router(hue_router)
app.include_router(capture_router)
app.include_router(cameras_router)
app.include_router(wled_router)
app.include_router(regions_router)
app.include_router(streaming_ws_router)
app.include_router(preview_ws_router)
```

Add one line:

```python
# Phase 18 — append in Backend/main.py router-include block (after line 83 wled_router)
app.include_router(ha_router)
```

No changes to the lifespan — Phase 18 uses the existing `app.state.db`, `app.state.coordinator`, `app.state.broadcaster`.

---

### `Backend/services/streaming_coordinator.py` (service — OPTIONAL modification)

**Analog (self-analog):** `streaming_coordinator.py:97-138` (the existing `start` method).

Only modified **if** the planner accepts RESEARCH.md §A1 Option C. Two-line change.

#### Existing signature — `streaming_coordinator.py:97`

```python
# Source: Backend/services/streaming_coordinator.py:97-105
async def start(self, config_id: str, target_hz: int = DEFAULT_HZ) -> None:
    """Start the streaming loop for the given entertainment config ID.

    No-op if already streaming (state not idle or error).

    Transitions: idle/error -> starting -> streaming (inside run loop).
    """
    if self._state not in ("idle", "error"):
        return
    self._target_hz = max(1, min(100, target_hz))
    ...
    device_path = await self._resolve_device_path(config_id)
```

#### Phase 18 Option C change — add `device_path_override` parameter

```python
# Phase 18 (Option C) — Backend/services/streaming_coordinator.py:97-113
async def start(
    self,
    config_id: str,
    target_hz: int = DEFAULT_HZ,
    device_path_override: str | None = None,  # NEW
) -> None:
    """Start the streaming loop for the given entertainment config ID.

    No-op if already streaming (state not idle or error).

    ``device_path_override`` (Phase 18 D-08): when non-None, bypasses the
    camera_assignments -> known_cameras -> CAPTURE_DEVICE resolution chain
    and uses the provided path directly. HA's PUT /api/ha/camera writes
    ha_state.active_camera_stable_id; routers/ha.py resolves the path and
    passes it here so D-07 (HA does not touch camera_assignments) stays clean.

    Transitions: idle/error -> starting -> streaming (inside run loop).
    """
    if self._state not in ("idle", "error"):
        return
    self._target_hz = max(1, min(100, target_hz))
    self._period = 1.0 / self._target_hz
    self._config_id = config_id
    self._state = "starting"

    # Resolve device path BEFORE broadcasting "starting" so the WS payload
    # carries the resolved active_device_path (Phase 16 D-05/D-06).
    device_path = device_path_override or await self._resolve_device_path(config_id)  # CHANGED
    self._device_path = device_path
    ...
```

Lines changed: `start` signature (+1 param), the `device_path = ...` line (replace with `device_path_override or ...`). No tests in `test_streaming_coordinator.py` need updates — the param has a default of `None` and the existing chain is preserved.

If planner rejects Option C → Option B (router-side temp `camera_assignments` upsert) — but RESEARCH.md §A1 recommends Option C. Decision belongs to the planner; this PATTERNS.md documents both paths so the planner can pick.

---

## Shared Patterns

### Pattern S-1: ISO timestamp format

**Source:** `Backend/routers/cameras.py:281, 348, 439` and `Backend/routers/wled.py:226`

```python
now = datetime.now(timezone.utc).isoformat()
```

**Apply to:** Every `INSERT INTO ha_state ... updated_at = ?` and every `camera_last_zone ... updated_at = ?` write in `routers/ha.py`. Use `now` once per handler and pass to both writes in a dual-write so they get the same timestamp.

### Pattern S-2: `request.app.state.db` direct read (no `Depends`)

**Source:** Every existing router (`cameras.py:174`, `wled.py:153`, `hue.py:30`, `capture.py:47`)

```python
db = request.app.state.db
```

**Apply to:** Every handler in `routers/ha.py`. Project convention — no FastAPI `Depends(get_db)` factory anywhere in the codebase.

### Pattern S-3: `getattr(request.app.state, "coordinator", None)` for test tolerance

**Source:** `Backend/routers/wled.py:126-142, 329-338`

```python
coordinator = getattr(request.app.state, "coordinator", None)
if coordinator is None:
    # test path
else:
    # production path
```

**Apply to:** `POST /api/ha/start`, `POST /api/ha/stop`. CONTEXT.md Claude's Discretion explicitly locks this pattern. Same for `broadcaster` lookup inside `_build_status_response`.

### Pattern S-4: `ON CONFLICT DO UPDATE` over `INSERT OR REPLACE`

**Source:** `Backend/routers/cameras.py:142-153, 286-292, 337-345, 442-450`

```sql
INSERT INTO known_cameras (stable_id, display_name, last_seen_at, last_device_path)
VALUES (?, ?, ?, ?)
ON CONFLICT(stable_id) DO UPDATE SET
    display_name = excluded.display_name,
    last_seen_at = excluded.last_seen_at,
    last_device_path = excluded.last_device_path
```

**Apply to:** Both `ha_state` upsert sites (`PUT /api/ha/zone`, `PUT /api/ha/camera`) — avoids the SQLite REPLACE-drops-columns pitfall (RESEARCH.md §Pitfall 1). The only `INSERT OR REPLACE` in the codebase is `routers/hue.py:47-64` (bridge_config) — newer code in `cameras.py` switched to ON CONFLICT.

### Pattern S-5: Parameterized SQL — never f-string interpolation

**Source:** Every existing router. Verified across `cameras.py`, `wled.py`, `hue.py`, `capture.py`.

```python
await db.execute("SELECT ... WHERE id = ?", (some_var,))
# or named: await db.execute("...", {"name": some_var})
```

**Apply to:** All Phase 18 SQL writes. RESEARCH.md §Security Domain confirms — never use f-string. Never use `+` to concatenate query strings with user input.

### Pattern S-6: response_model_exclude_none for additive optional fields

**Source:** No existing direct codebase example uses `response_model_exclude_none` (project hasn't needed it before). Pydantic v2 + FastAPI standard idiom.

```python
@router.get("/status", response_model=HaStatusResponse, response_model_exclude_none=True)
```

**Apply to:** `GET /api/ha/status` — keeps the optional `error` field out of the happy-path payload (D-09 Claude's Discretion). Apply also to `POST /api/ha/start` and `POST /api/ha/stop` since they return the same response model.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| _(none)_ | — | — | All Phase 18 files have strong analogs in the codebase. RESEARCH.md §Don't Hand-Roll confirms "zero new services, zero new external integrations, and zero new dependencies." |

---

## Metadata

**Analog search scope:** `Backend/routers/*.py`, `Backend/tests/test_*.py`, `Backend/services/streaming_coordinator.py`, `Backend/services/hue_client.py`, `Backend/services/status_broadcaster.py`, `Backend/database.py`, `Backend/main.py`, `Backend/tests/conftest.py`

**Files read in this pass:**
- `Backend/routers/wled.py` (full, 359 lines)
- `Backend/routers/cameras.py` (full, 464 lines)
- `Backend/routers/hue.py` (full, 226 lines)
- `Backend/routers/capture.py` (full, 129 lines)
- `Backend/services/streaming_coordinator.py` (lines 1-250)
- `Backend/services/status_broadcaster.py` (full, 132 lines)
- `Backend/services/hue_client.py` (lines 1-110)
- `Backend/database.py` (full, 134 lines)
- `Backend/main.py` (full, 91 lines)
- `Backend/tests/test_wled_router.py` (full, 393 lines)
- `Backend/tests/test_phase17_e2e.py` (full, 365 lines)
- `Backend/tests/conftest.py` (full, 246 lines)

**Pattern extraction date:** 2026-05-11

**Key planner takeaways:**
1. `routers/wled.py` is the freshest router and locks the test-tolerance + coordinator-access conventions — use it as the **primary structural template**.
2. `routers/cameras.py::put_last_zone` (lines 393-463) is the **only** existing dual-write transactional pattern — D-06 follows it conditionally.
3. `routers/cameras.py::put_assignment` (lines 308-359) is the canonical validation-then-write 404 chain.
4. `tests/test_wled_router.py` (full) is the unit-test template — copy `_make_db`, `_wled_app_lifespan`, `_make_client`, `_make_app`, the `patch("routers.wled.X")` form, and the `asyncio.run(_check_row())` direct-DB-poke idiom.
5. `tests/test_phase17_e2e.py` (full) is the integration template — copy `_MockRegistry`, `_make_mock_hue`, the `WledStreamer(udp_port=41324)` constructor (or for Phase 18 swap for `MagicMock`), and the `@pytest.mark.asyncio` + `for _ in range(50): if state == 'streaming': break` warm-up loop.
6. The Option C coordinator change is **one signature line + one resolution line** in `streaming_coordinator.py::start` (lines 97 + 113).
