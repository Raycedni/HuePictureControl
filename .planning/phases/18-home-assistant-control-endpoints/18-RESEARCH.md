# Phase 18: Home Assistant Control Endpoints - Research

**Researched:** 2026-05-11
**Domain:** Backend REST router on top of existing StreamingCoordinator; thin adapter for inbound Home Assistant `rest_command:` calls
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Endpoint shape**
- **D-01:** Seven endpoints in new `routers/ha.py` (prefix `/api/ha`, tag `ha`):
  - `POST /api/ha/start` — empty body
  - `POST /api/ha/stop` — empty body
  - `GET  /api/ha/status` — curated JSON (D-09)
  - `PUT  /api/ha/zone` — body `{zone_id: string}`
  - `PUT  /api/ha/camera` — body `{stable_id: string}`
  - `GET  /api/ha/zones` — discovery wrapper (D-11)
  - `GET  /api/ha/cameras` — discovery wrapper (D-11)
- **D-02:** Selectors use **PUT with JSON body**.
- **D-03:** `POST /api/ha/start` is **strict** — empty body, uses `ha_state`. No inline `target_hz` override. Coordinator default (60 Hz) applies.

**Selection persistence**
- **D-04:** New single-row `ha_state` table:
  ```sql
  CREATE TABLE IF NOT EXISTS ha_state (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      active_config_id TEXT,
      active_camera_stable_id TEXT,
      updated_at TEXT
  );
  ```
  All writes are `INSERT OR REPLACE` against `id = 1`.
- **D-05:** Row creation is **lazy** — no eager seed. `GET /api/ha/status` and `POST /api/ha/start` tolerate the missing row (treat as NULL).
- **D-06:** `PUT /api/ha/zone {zone_id}` semantics:
  1. Validate `zone_id` exists in `entertainment_configs` → 404.
  2. `INSERT OR REPLACE` into `ha_state` setting `active_config_id`, preserving `active_camera_stable_id`, updating `updated_at`.
  3. **If** `ha_state.active_camera_stable_id` is non-null **after the write**, **also** write `camera_last_zone[active_camera_stable_id] = zone_id` in the same transaction.
  4. If `active_camera_stable_id` is NULL, **skip** the `camera_last_zone` write.
- **D-07:** `PUT /api/ha/camera {stable_id}` semantics:
  1. Validate `stable_id` exists in `known_cameras` → 404.
  2. `INSERT OR REPLACE` into `ha_state`, preserving `active_config_id`.
  3. **Does NOT touch `camera_assignments`.**
- **D-08:** `POST /api/ha/start` preconditions and resolution order:
  1. `ha_state.active_config_id` must be non-null → `400 "no zone selected"`.
  2. `active_config_id` must still exist in `entertainment_configs` → `404 "zone not found"`.
  3. Camera resolution chain:
     a. If `ha_state.active_camera_stable_id` set → resolve via `known_cameras.last_device_path`.
     b. Else fall back to `camera_assignments[active_config_id]`.
     c. Else fall back to default `CAPTURE_DEVICE` env var.
  4. Call `coordinator.start(active_config_id)`.

**Status & discovery**
- **D-09:** `GET /api/ha/status` curated flat JSON shape (locked):
  ```json
  {
    "state": "idle|starting|streaming|stopping|error|reconnecting",
    "active_config_id": "..." | null,
    "active_config_name": "TV-Bereich" | null,
    "active_camera_stable_id": "..." | null,
    "active_camera_name": "..." | null,
    "active_device_path": "/dev/video0" | null,
    "fps": 60,
    "latency_ms": 12.3,
    "ha_selected_config_id": "..." | null,
    "ha_selected_config_name": "..." | null,
    "ha_selected_camera_stable_id": "..." | null,
    "ha_selected_camera_name": "..." | null,
    "bridge_paired": true
  }
  ```
  Stable contract — does NOT leak `_metrics` internals (`packets_sent`, `seq`, `wled_devices`).
- **D-10:** Both `active_*` (from broadcaster `_metrics`) AND `ha_selected_*` (from `ha_state`) exposed.
- **D-11:** Two dedicated discovery wrappers:
  - `GET /api/ha/cameras` → `[{stable_id, name, connected}]` only.
  - `GET /api/ha/zones` → `[{id, name}]` only.

### Claude's Discretion

- **Idempotency:** `POST /api/ha/start` when state not `idle`/`error` → `200` no-op. `POST /api/ha/stop` when state is `idle` → `200` no-op. Both return current `status` payload.
- **HTTP status map:** 400 (precondition missing), 404 (unknown zone/camera), 502 (Hue bridge HTTP error), 503 (bridge unpaired/unreachable).
- **Coordinator access pattern:** `getattr(request.app.state, "coordinator", None)`.
- **Pydantic model naming:** `HaZoneRequest`, `HaCameraRequest`, `HaStatusResponse`, `HaCameraListResponse`, `HaZoneListResponse`. All in `routers/ha.py`.
- **Friendly-name caching:** Not in this phase. Hit Hue Bridge once per `/api/ha/status` call (Bridge already caches).
- **Status `error` field:** If broadcaster `_metrics["error"]` is set, surface as `status.error: string`. Otherwise omit.
- **Test strategy:** Unit tests per endpoint (mock coordinator + mock DB). One integration test wiring real `StreamingCoordinator` with mocked sinks: `PUT zone → PUT camera → POST start → GET status → POST stop`.
- **OpenAPI:** `tags=["ha"]` on the router.

### Deferred Ideas (OUT OF SCOPE)

- HA YAML snippet documentation
- `/api/ha/restart` convenience endpoint
- Inline body on `/start` (zone/camera overrides)
- `target_hz` tuning via `/start` body
- HA WebSocket push for status changes
- Per-device WLED health in `/api/ha/status` (deferred to Phase 19/follow-up)
- Live device probing in `/api/ha/cameras` (uses on-demand `_scan_devices`)
- Friendly-name caching layer
- HA long-lived access token storage in HPC
- Authentication on HA endpoints
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HASS-01 | HA can start streaming via REST endpoint (POST /api/ha/start) | `routers/capture.py::start_capture` template + `coordinator.start(config_id)` contract (§StreamingCoordinator API) + D-08 resolution chain |
| HASS-02 | HA can stop streaming via REST endpoint (POST /api/ha/stop) | `routers/capture.py::stop_capture` template + `coordinator.stop()` contract + idempotent no-op when state is `idle` |
| HASS-03 | HA can select the active camera via REST endpoint | `routers/cameras.py::put_assignment` pattern; new `ha_state` table; lazy upsert; 404 on unknown `stable_id` |
| HASS-04 | HA can select the entertainment zone via REST endpoint | `routers/cameras.py::put_last_zone` pattern for transactional dual-write; `entertainment_configs` validation; D-06 conditional `camera_last_zone` propagation |
| HASS-05 | HA can query current streaming status via GET endpoint | `status_broadcaster._metrics` for `active_*`; `ha_state` for `ha_selected_*`; `list_entertainment_configs` for friendly names; D-09 locked schema |

**Source:** `.planning/milestones/v1.1-REQUIREMENTS.md` §"Home Assistant Control" lines 172-178. (Note: HASS-* requirements live in the v1.1 REQUIREMENTS file because v1.3 inherits the same requirement list; no top-level `.planning/REQUIREMENTS.md` exists in this repo.) [VERIFIED: file read]
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **No-auth design:** Web UI and all REST endpoints are unauthenticated — local network is the trust boundary. HA endpoints inherit this. [VERIFIED: CLAUDE.md + PROJECT.md §Constraints]
- **No HA token storage:** Direction is HA → HPC only via HA's `rest_command:` integration. Storing an HA long-lived access token in HPC is **explicitly rejected** in CLAUDE.md §"What NOT to Use". [VERIFIED: CLAUDE.md]
- **No `python-wled` / third-party HA library:** N/A here (this is the inbound HA-controls-HPC direction; HA itself uses `rest_command:`). HPC does NOT call HA. [VERIFIED: CLAUDE.md §"Alternatives Considered"]
- **REST, not WebSocket:** Status endpoint is GET-only REST per D-09; HA polling (10–30s) is the intended cadence. [VERIFIED: CONTEXT.md Deferred]
- **No Docker (v1.2+):** Backend runs natively on Linux. No mDNS/multicast caveat applies. HA reaches HPC via direct LAN HTTP. [VERIFIED: MEMORY.md project_no_docker.md]
- **Python 3.12 pinned** (`hue-entertainment-pykit` incompatible with 3.13+). [VERIFIED: CLAUDE.md]
- **Test commands:** `python -m pytest` (backend, 167+ tests), `npx vitest run` (frontend, 30+ tests). [VERIFIED: CLAUDE.md]
- **GSD workflow enforcement:** All file edits must go through a GSD command. Don't make direct repo edits outside `/gsd-execute-phase`. [VERIFIED: CLAUDE.md]

## Summary

Phase 18 adds a thin Home Assistant control surface as a new router (`Backend/routers/ha.py`) on top of the already-built `StreamingCoordinator` (Phase 17) and `StatusBroadcaster` (Phase 16/17). Every endpoint is a CRUD-style wrapper or a delegation to an existing coordinator method — there are **zero new services, zero new external integrations, and zero new dependencies**. The only schema addition is a single-row `ha_state` table mirroring the established `bridge_config (id INTEGER PRIMARY KEY CHECK (id=1))` pattern.

All technical decisions are locked in 18-CONTEXT.md. The remaining open work is mechanical: writing the router, the DB schema block, the response models, friendly-name resolution helpers, and the test matrix. The codebase already provides every primitive needed — confirmed by direct file reads of `routers/wled.py`, `routers/cameras.py`, `routers/capture.py`, `routers/hue.py`, `services/streaming_coordinator.py`, `services/status_broadcaster.py`, `services/hue_client.py`, and `database.py`.

**Primary recommendation:** Treat Phase 18 as four small mechanical sub-tasks: (1) schema add to `database.py`, (2) new `routers/ha.py` with seven handlers, (3) `main.py` router-include line, (4) test file `Backend/tests/test_ha_router.py` mirroring the structure of `test_wled_router.py` plus one integration test mirroring `test_phase17_e2e.py`. No research-driven design decisions remain.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HA `rest_command:` HTTP entry | API / Backend | — | HA-side YAML is user config, not shipped here; we expose the receiving HTTP surface |
| Streaming control (start/stop) | API / Backend | — | Delegates to `StreamingCoordinator` already on `app.state.coordinator` |
| Selection persistence (`ha_state`) | Database / Storage | API / Backend | Single-row SQLite table; written by router PUT handlers |
| Status payload assembly | API / Backend | Database / Storage | Reads `broadcaster._metrics` (in-memory) + `ha_state` + `entertainment_configs` join |
| Friendly-name resolution | API / Backend | External (Hue Bridge HTTP) | Bridge call to `list_entertainment_configs` per `/status` invocation (D-09 Claude's Discretion) |
| Camera/zone discovery wrappers | API / Backend | — | Reuses `_scan_devices` (V4L2) and `list_entertainment_configs` (Hue Bridge) |

## Standard Stack

### Core (already in use — NO new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | `>=0.115` | Router and request handling | Already the framework for every existing router [VERIFIED: Backend/requirements.txt via CLAUDE.md] |
| aiosqlite | `>=0.20` | Async SQLite for `ha_state` table | Existing DB layer in `database.py` and every router |
| Pydantic v2 | `>=2.0` (FastAPI dependency) | Request/response models | Used by every other router (`HaZoneRequest`, etc.) |
| httpx | `>=0.27` | Indirect via `services/hue_client.list_entertainment_configs` | Already used; no new direct calls in Phase 18 |
| Python `datetime` (stdlib) | 3.12 | `updated_at` ISO timestamps | Pattern matches `routers/cameras.py` (`datetime.now(timezone.utc).isoformat()`) |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `unittest.mock` (stdlib) | 3.12 | `AsyncMock`/`MagicMock` for coordinator stubs in unit tests | Per-endpoint unit tests (mirror `test_wled_router.py`) |
| `fastapi.testclient.TestClient` | bundled | Synchronous HTTP driver | Every existing router test uses this pattern |
| `pytest-asyncio` | already in use | Integration test that awaits `coordinator.start/stop` | Mirror `test_phase17_e2e.py` |

### Alternatives Considered

| Instead of | Could Use | Why Rejected |
|------------|-----------|--------------|
| Custom router file `routers/ha.py` | Add HA endpoints to `routers/capture.py` | Mixes concerns; `routers/wled.py` precedent set per-domain routers — CONTEXT.md D-01 locked |
| Separate `models/ha.py` for Pydantic | Inline in `routers/ha.py` | CONTEXT.md Claude's Discretion explicitly says "all in `routers/ha.py`; no separate `models/ha.py` unless cross-router reuse emerges" |
| Eager seed of `ha_state` row at startup | Add `INSERT OR IGNORE INTO ha_state (id) VALUES (1)` to `init_db` | CONTEXT.md D-05 explicitly LOCKED on lazy creation |
| Cache `list_entertainment_configs` in-memory | New `LRU cache(ttl=5s)` wrapper | CONTEXT.md Claude's Discretion: defer caching to follow-up if needed |
| Single `/api/ha/select` verb with `{zone_id, stable_id}` | One verb-per-URL | CONTEXT.md D-01 LOCKED: separate URLs for HA `rest_command:` ergonomics |

**Installation:**

```bash
# No new packages. All dependencies already in Backend/requirements.txt.
```

**Version verification:** Not applicable — no new dependencies added. Existing pinned versions (FastAPI >=0.115, aiosqlite >=0.20, httpx >=0.27) are unchanged. [VERIFIED: CLAUDE.md technology table]

## Architecture Patterns

### System Architecture Diagram

```
                                  +-----------------------------------+
HA rest_command: --HTTP--->  POST /api/ha/start                       |
HA template_sensor --HTTP-->  GET  /api/ha/status                     |
HA input_select  --HTTP--->  PUT  /api/ha/zone   {zone_id}            |
                              PUT  /api/ha/camera {stable_id}         |
                              GET  /api/ha/zones                      |
                              GET  /api/ha/cameras                    |
                              POST /api/ha/stop                       |
                                  +-----------------+-----------------+
                                                    |
                                                    | FastAPI routing (routers/ha.py)
                                                    v
            +-----------------+        +------------+-----------+        +---------------------+
            |  ha_state       |<------>|  Phase 18 router      |<------>|  StreamingCoordinator|
            |  (single-row    |  R/W   |  handlers              |  call  |  (Phase 17)         |
            |  SQLite table)  |        |                        |        |  - start(config_id) |
            +-----------------+        |  - PUT zone validates  |        |  - stop()           |
                                       |    entertainment_configs       |  - state property   |
            +-----------------+   read  |    + dual-writes               +-----------+---------+
            | camera_last_zone|<-------+    camera_last_zone (D-06)                 |
            +-----------------+        |                                            |
            +-----------------+   read |  - PUT camera validates known_cameras      |
            | known_cameras   |<-------+                                            |
            +-----------------+        |  - POST start enforces preconditions       v
            +-----------------+        |    (D-08) then calls coordinator   +---------------+
            | entertainment_  |<-------+                                    | broadcaster   |
            | configs         |  read  |  - GET status assembles from       |  ._metrics    |
            +-----------------+        |    broadcaster + ha_state + Hue   |  (active_*)   |
            +-----------------+        |    list_entertainment_configs     +---------------+
            | camera_         |<-------+                                            ^
            | assignments     |  read  |  - GET zones -> Hue Bridge HTTP            |
            +-----------------+        |  - GET cameras -> _scan_devices            |
                                       +------------+-----------------+             |
                                                    |                               |
                                            httpx GET (verify=False, timeout=10)    |
                                                    v                               |
                                       +-----------------------------+              |
                                       |  Hue Bridge v2 (LAN)        |              |
                                       |  /clip/v2/resource/         |              |
                                       |    entertainment_configuration            |
                                       +-----------------------------+              |
                                                                                    |
                                       +-----------------------------+              |
                                       |  V4L2 capture probe         +--------------+
                                       |  (Linux ioctl via           |
                                       |  enumerate_capture_devices) |  (existing pipeline,
                                       +-----------------------------+   unchanged)
```

The router is a **read-mostly aggregator**: it owns no state itself, never spawns tasks, never opens sockets. It reads from four DB tables and one in-memory dict (`broadcaster._metrics`), and delegates lifecycle to the coordinator.

### Recommended Project Structure

```
Backend/
├── database.py                            # MODIFY — add CREATE TABLE IF NOT EXISTS ha_state (1 block)
├── main.py                                # MODIFY — add `app.include_router(ha_router)` (1 line)
├── routers/
│   ├── ha.py                              # NEW — 7 handlers + Pydantic models + helpers
│   ├── cameras.py                         # READ-ONLY reference (PUT last-zone dual-write pattern)
│   ├── wled.py                            # READ-ONLY reference (_coord_health, getattr pattern)
│   ├── capture.py                         # READ-ONLY reference (coordinator wiring template)
│   └── hue.py                             # READ-ONLY reference (Bridge-not-paired error)
├── services/
│   ├── streaming_coordinator.py           # READ-ONLY reference (start/stop/state contract)
│   ├── status_broadcaster.py              # READ-ONLY reference (_metrics shape)
│   └── hue_client.py                      # READ-ONLY reference (list_entertainment_configs)
└── tests/
    ├── test_ha_router.py                  # NEW — per-endpoint unit tests (mirror test_wled_router.py)
    └── test_phase18_e2e.py                # NEW — integration test (mirror test_phase17_e2e.py)
```

### Pattern 1: APIRouter declaration

**What:** New file `Backend/routers/ha.py` declares `router = APIRouter(prefix="/api/ha", tags=["ha"])` at module scope. Wired in `main.py` via `app.include_router(ha_router)`. Mirrors every existing router.

**Verified excerpts:**

```python
# Backend/routers/wled.py:47
router = APIRouter(prefix="/api/wled", tags=["wled"])
```

```python
# Backend/routers/cameras.py:29
router = APIRouter(prefix="/api/cameras", tags=["cameras"])
```

```python
# Backend/routers/hue.py:24
router = APIRouter(prefix="/api/hue", tags=["hue"])
```

```python
# Backend/routers/capture.py:17
router = APIRouter(prefix="/api/capture", tags=["capture"])
```

**For Phase 18:**

```python
# Backend/routers/ha.py (NEW)
router = APIRouter(prefix="/api/ha", tags=["ha"])
```

Source: direct file read of all four routers, lines cited inline.

### Pattern 2: Pydantic request/response models inline

**What:** Models declared at the top of the router file, immediately after the `router = ...` line. Use `BaseModel` from `pydantic`. Use `Field(..., pattern=...)` for regex validation (see `WledDeviceIn.ip`).

**Verified excerpts:**

```python
# Backend/routers/wled.py:55-86
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

class WledScanResponse(BaseModel):
    candidates: list[WledScanCandidate]
```

```python
# Backend/routers/cameras.py:82-89
class LastZoneRequest(BaseModel):
    entertainment_config_id: str

class LastZoneResponse(BaseModel):
    camera_stable_id: str
    entertainment_config_id: str
    updated_at: str
```

**For Phase 18** (recommended naming per CONTEXT.md Claude's Discretion):

```python
class HaZoneRequest(BaseModel):
    zone_id: str

class HaCameraRequest(BaseModel):
    stable_id: str

class HaZoneOut(BaseModel):
    id: str
    name: str

class HaZonesResponse(BaseModel):
    zones: list[HaZoneOut]

class HaCameraOut(BaseModel):
    stable_id: str
    name: str
    connected: bool

class HaCamerasResponse(BaseModel):
    cameras: list[HaCameraOut]

class HaStatusResponse(BaseModel):
    state: str
    active_config_id: str | None
    active_config_name: str | None
    active_camera_stable_id: str | None
    active_camera_name: str | None
    active_device_path: str | None
    fps: float
    latency_ms: float
    ha_selected_config_id: str | None
    ha_selected_config_name: str | None
    ha_selected_camera_stable_id: str | None
    ha_selected_camera_name: str | None
    bridge_paired: bool
    error: str | None = None  # D-09 additive — omitted from happy path
```

### Pattern 3: Coordinator access via `getattr` (test tolerance)

**What:** `coordinator = getattr(request.app.state, "coordinator", None)`. Allows unit tests to mount the router without wiring a coordinator.

**Verified excerpt:**

```python
# Backend/routers/wled.py:126-142
def _coord_health(request: Request) -> dict:
    """Best-effort live WLED health from the coordinator. Returns `{}` if idle.

    Tolerates a missing coordinator (e.g. tests that don't wire one) and
    a streamer that has not yet been started (`_wled` is always present
    on a real coordinator but defensive `getattr` keeps tests simple).
    """
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is None:
        return {}
    ...
```

```python
# Backend/routers/wled.py:329-338 — PUT enabled handler showing graceful fallback
coordinator = getattr(request.app.state, "coordinator", None)
if coordinator is not None:
    await coordinator.set_wled_device_enabled(device_id, body.enabled)
else:
    # Test mode without coordinator — direct DB update (no live gate).
    await db.execute(...)
    await db.commit()
```

**For Phase 18 `POST /api/ha/start`:** When the coordinator is absent (test path) and we still want to surface preconditions cleanly:

```python
coordinator = getattr(request.app.state, "coordinator", None)
if coordinator is None:
    raise HTTPException(status_code=503, detail="Coordinator unavailable")
await coordinator.start(active_config_id)
```

For `GET /api/ha/status` the `getattr(..., None)` path returns `state="idle"` and all `active_*` fields as `None` so the endpoint still works in CRUD-only test contexts.

### Pattern 4: `INSERT OR REPLACE` for single-row tables

**What:** Single-row tables (`bridge_config`, soon `ha_state`) use SQLite's `INSERT OR REPLACE INTO ... VALUES (1, ...)` against the fixed primary key.

**Verified excerpts:**

```python
# Backend/routers/hue.py:47-64 — bridge_config single-row upsert
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

**For Phase 18** `ha_state` table writes use the same form against `id = 1`:

```python
# PUT /api/ha/zone
await db.execute(
    """
    INSERT OR REPLACE INTO ha_state (id, active_config_id, active_camera_stable_id, updated_at)
    VALUES (
        1,
        :new_config_id,
        COALESCE((SELECT active_camera_stable_id FROM ha_state WHERE id=1), NULL),
        :now
    )
    """,
    {"new_config_id": body.zone_id, "now": now_iso},
)
```

The `COALESCE((SELECT … FROM ha_state WHERE id=1), NULL)` is the project-preferred way to preserve the un-touched column on REPLACE (since SQLite REPLACE deletes-then-inserts and would otherwise drop existing values). The dual-write to `camera_last_zone` follows the existing `routers/cameras.py::put_last_zone` pattern.

### Pattern 5: Transactional dual-write (for D-06)

**What:** `routers/cameras.py::put_last_zone` already establishes the pattern for "validate, then write to two tables in one transaction." D-06 follows the identical structure.

**Verified excerpt:**

```python
# Backend/routers/cameras.py:439-457
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

**For Phase 18 `PUT /api/ha/zone`** the flow is:

1. Validate `zone_id` in `entertainment_configs` → 404.
2. Read current `ha_state.active_camera_stable_id` (may be NULL).
3. `INSERT OR REPLACE INTO ha_state` (preserving camera stable id).
4. **If** step-2 camera stable id is non-null, `INSERT … ON CONFLICT DO UPDATE` into `camera_last_zone`.
5. Single `await db.commit()` after all writes.

### Pattern 6: Validation-then-write 404 chain

**What:** Routers validate every foreign-key-like reference in the request body with a `SELECT … WHERE … = ?` and raise `HTTPException(404, ...)` BEFORE any INSERT/UPDATE. Pattern is uniform across `cameras.py` (stable_id + entertainment_config_id) and `wled.py` (device_id).

**Verified excerpts:**

```python
# Backend/routers/cameras.py:412-437 — two-step validation chain
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
    raise HTTPException(status_code=404, detail=...)
```

**For Phase 18:** `PUT /api/ha/zone` validates `zone_id` in `entertainment_configs`; `PUT /api/ha/camera` validates `stable_id` in `known_cameras`; `POST /api/ha/start` validates `ha_state.active_config_id` is non-null (400) then re-validates against `entertainment_configs` (404 if since-deleted).

### Anti-Patterns to Avoid

- **Eager-seeding `ha_state`:** CONTEXT.md D-05 forbids. Do NOT add `INSERT OR IGNORE INTO ha_state (id) VALUES (1)` in `init_db`.
- **Writing `camera_assignments` from `PUT /api/ha/camera`:** CONTEXT.md D-07 forbids. HA's camera choice is decoupled from the per-zone UI assignment.
- **Writing `camera_last_zone` when HA only set zone (camera is still NULL):** CONTEXT.md D-06 step 4 forbids. Only dual-write when both selectors are set.
- **Exposing `_metrics["packets_sent"]`, `_metrics["seq"]`, or `_metrics["wled_devices"]` in `/api/ha/status`:** Breaks the locked D-09 contract. HA template sensors must not see internal metrics that change shape across phases.
- **Inline `target_hz` override on `/start` body:** CONTEXT.md D-03 + Deferred Ideas forbid. Coordinator default (60 Hz) applies. Accept empty body; don't add Pydantic model for `/start`.
- **Calling `coordinator.start()` synchronously without prior preconditions:** D-08 enforces preconditions before delegation; bypassing them lets HA trigger streaming on a deleted zone.
- **Mounting `routers/ha.py` BEFORE testing the schema migration:** `init_db` must create `ha_state` first, or the first PUT will hit `OperationalError: no such table`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HA → HPC auth | Token validation middleware | Nothing (LAN is trust boundary) | Per PROJECT.md §Constraints and CLAUDE.md §"What NOT to Use" |
| HA-bound REST client | New `services/ha_client.py` | Nothing — direction is inbound only | Per CLAUDE.md §"Alternatives Considered" |
| Custom config-name cache | Decorator/TTL cache | Hit Bridge per `/status` call (defer caching) | Per CONTEXT.md Claude's Discretion; Bridge caches internally |
| New status WS for HA | `routers/ha_ws.py` | GET REST polling | Per CONTEXT.md Deferred Ideas; HA REST is sufficient |
| Generic "select" endpoint with mode parameter | Polymorphic verb | Two separate PUT URLs per D-01 | HA `rest_command:` ergonomics — one URL per command |
| Schema migrations | Alembic | `CREATE TABLE IF NOT EXISTS` at startup | Established convention in `database.py` (see lines 17-126) |
| ISO timestamp formatting | Custom function | `datetime.now(timezone.utc).isoformat()` | Used by `routers/cameras.py:281, 348, 439` and `routers/wled.py:226` |
| FastAPI dependency injection for `db` | `Depends(get_db)` factory | `request.app.state.db` direct read | Established convention; every existing handler uses `request.app.state` |

**Key insight:** Phase 18 is **pure composition** — it stitches together five existing primitives (`coordinator`, `broadcaster._metrics`, `_scan_devices`, `list_entertainment_configs`, `known_cameras`/`entertainment_configs` tables). The only new artifact is one DB table and one router file. Anything that smells like a new abstraction is over-engineering.

## StreamingCoordinator API Contract

This is the read-only API the Phase 18 router calls. All quotes are from `Backend/services/streaming_coordinator.py`.

### `state` property

```python
# streaming_coordinator.py:92-95
@property
def state(self) -> str:
    """Current streaming state: idle | starting | streaming | stopping | error."""
    return self._state
```

**Possible values** (verified from `_run_loop` and `start`/`stop`):
- `"idle"` (initial; after `stop` completes)
- `"starting"` (set inside `start` before capture acquire)
- `"streaming"` (set inside `_run_loop` after Hue + WLED sinks start)
- `"stopping"` (set at start of `stop`)
- `"error"` (set on capture acquire failure or unhandled exception)
- `"reconnecting"` (set inside `_capture_reconnect_loop`)

[VERIFIED: lines 109, 149, 160, 410, 429, 439, 467, 556]

**D-09 maps these 1:1 to the status payload `state` field.**

### `start(config_id, target_hz=60)` semantics

```python
# streaming_coordinator.py:97-138
async def start(self, config_id: str, target_hz: int = DEFAULT_HZ) -> None:
    """Start the streaming loop for the given entertainment config ID.

    No-op if already streaming (state not idle or error).

    Transitions: idle/error -> starting -> streaming (inside run loop).
    """
    if self._state not in ("idle", "error"):
        return  # <-- IDEMPOTENT NO-OP
    ...
```

**Key facts:**
- **Idempotent:** Calling `start` when state is `starting`, `streaming`, `stopping`, or `reconnecting` is a silent no-op (returns without error). This satisfies CONTEXT.md Claude's Discretion "idempotent /start when not idle/error → 200 no-op".
- **Resolves device path internally:** `_resolve_device_path` (lines 209-236) walks `camera_assignments` → `known_cameras` → `CAPTURE_DEVICE` env. **This means Phase 18's D-08 step 3b/3c is already implemented inside the coordinator — Phase 18 only needs to override step 3a by stashing the camera resolution result somewhere the coordinator sees.**
- **Default `target_hz=60`:** Per D-03 we do not pass `target_hz` and the default applies.
- **`config_id` is the entertainment configuration UUID**, e.g. `"6cef1edb-9e0e-485d-9614-65d59cf48dad"`.

### `_resolve_device_path` chain

```python
# streaming_coordinator.py:209-236
async def _resolve_device_path(self, config_id: str) -> str:
    """Resolve the device path for the given entertainment config.

    Looks up camera_assignments for the config_id, then finds the
    last_device_path in known_cameras. Falls back to CAPTURE_DEVICE
    if no assignment exists or the camera is unknown.
    """
    async with await self._db.execute(
        "SELECT camera_stable_id FROM camera_assignments WHERE entertainment_config_id = ?",
        (config_id,),
    ) as cursor:
        assign_row = await cursor.fetchone()

    if assign_row is None:
        return CAPTURE_DEVICE

    stable_id = assign_row["camera_stable_id"]

    async with await self._db.execute(
        "SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
        (stable_id,),
    ) as cursor:
        cam_row = await cursor.fetchone()

    if cam_row is None or not cam_row["last_device_path"]:
        return CAPTURE_DEVICE

    return cam_row["last_device_path"]
```

**Critical implication for D-08 step 3a (HA camera override):**

The existing coordinator does NOT know about `ha_state`. There are two clean ways to make `ha_state.active_camera_stable_id` win over `camera_assignments`:

**Option A (recommended):** The HA router computes the device path locally and **rewrites `camera_assignments[active_config_id]` immediately before calling `coordinator.start`**. This is cleaner but contradicts D-07's "PUT camera does NOT touch `camera_assignments`."

**Option B (recommended given D-07):** Don't touch `camera_assignments`. Instead, in `POST /api/ha/start`, **temporarily upsert `camera_assignments[active_config_id]` from `ha_state` only when `ha_state.active_camera_stable_id` is set, but treat this as a transient resolution write, not a UI persistence**. Then call `coordinator.start`.

**Option C (cleanest — recommended primary):** Add a new optional parameter to `StreamingCoordinator.start(config_id, *, device_path_override: str | None = None)` so the HA router can pass the resolved path directly. The coordinator's `_resolve_device_path` returns `device_path_override or <existing chain result>`. Minimal change, preserves D-07 semantics exactly.

**Planner must choose** between Option B (no coordinator change, two-table-write) and Option C (small coordinator API addition, single-call). I recommend **Option C** because:
- It mirrors how `start(config_id, target_hz=60)` already takes an override.
- Single source of truth: device path is resolved in one place.
- D-07 stays clean: `camera_assignments` is never touched by HA.
- The change is `+1 parameter, +1 line` in `_resolve_device_path`.

[ASSUMED] The planner will accept Option C. If the planner prefers Option B, the test matrix below still applies but with an extra integration test asserting `camera_assignments` is unchanged after a HA `/start`.

### `stop()` semantics

```python
# streaming_coordinator.py:140-166
async def stop(self) -> None:
    """Stop the streaming loop cleanly.

    No-op if already idle. Clears the run event and awaits the task.
    """
    if self._state == "idle":
        return  # <-- IDEMPOTENT NO-OP
    ...
```

**Key facts:**
- **Idempotent:** Calling `stop` when state is `idle` is a silent no-op. Satisfies "idempotent /stop when idle → 200 no-op".
- **Pushes `idle` state with cleared `active_config_id`/`active_device_path`** at line 162-166 — so after `stop()` the broadcaster's metrics are reset and the next `/api/ha/status` reflects idle.

[VERIFIED: lines 140-166]

## StatusBroadcaster._metrics Shape (verified)

```python
# status_broadcaster.py:27-37
self._metrics: dict = {
    "state": "idle",
    "fps": 0,
    "latency_ms": 0,
    "packets_sent": 0,
    "packets_dropped": 0,
    "seq": 0,
    "active_config_id": None,
    "active_device_path": None,
    "wled_devices": {},
}
```

**Plus, conditionally:** `_metrics["error"]: str` is added by `push_state(..., error="...")` (line 89-92) when state transitions to `error`. It is **deleted** when state transitions back to a non-error state.

### D-09 → `_metrics` field map

| D-09 status field | Source | Verified location |
|---|---|---|
| `state` | `_metrics["state"]` | `status_broadcaster.py:88` |
| `active_config_id` | `_metrics["active_config_id"]` | `status_broadcaster.py:34` |
| `active_device_path` | `_metrics["active_device_path"]` | `status_broadcaster.py:35` |
| `fps` | `_metrics["fps"]` | `status_broadcaster.py:29`, `streaming_coordinator.py:532` |
| `latency_ms` | `_metrics["latency_ms"]` | `status_broadcaster.py:30`, `streaming_coordinator.py:533` |
| `error` (additive) | `_metrics.get("error")` | `status_broadcaster.py:89-92` |
| `active_config_name` | DERIVED — see Friendly-name resolution | n/a |
| `active_camera_stable_id` | DERIVED — `known_cameras` reverse lookup from `active_device_path` | n/a |
| `active_camera_name` | DERIVED — `known_cameras.display_name` | n/a |
| `bridge_paired` | DERIVED — `SELECT 1 FROM bridge_config WHERE id=1` | `routers/hue.py:78-88` |
| `ha_selected_config_id` | `ha_state.active_config_id` | NEW table |
| `ha_selected_config_name` | DERIVED — join with `list_entertainment_configs` | n/a |
| `ha_selected_camera_stable_id` | `ha_state.active_camera_stable_id` | NEW table |
| `ha_selected_camera_name` | DERIVED — `SELECT display_name FROM known_cameras WHERE stable_id=?` | n/a |

**Fields NOT exposed** (per D-09): `packets_sent`, `packets_dropped`, `seq`, `wled_devices`. These remain in `_metrics` for the existing `/ws/status` consumers but never appear in `/api/ha/status`.

## Friendly-Name Resolution Paths

### Active config name

Given `_metrics["active_config_id"]`:

```python
# Path 1 — via Hue Bridge (current source of truth for config names)
async with db.execute(
    "SELECT ip_address, username FROM bridge_config WHERE id=1"
) as cursor:
    row = await cursor.fetchone()
if row is None:
    bridge_paired = False
    configs = []
else:
    bridge_paired = True
    configs = await list_entertainment_configs(row["ip_address"], row["username"])
config_name_by_id = {c["id"]: c["name"] for c in configs}
active_config_name = config_name_by_id.get(active_config_id) if active_config_id else None
ha_selected_config_name = config_name_by_id.get(ha_selected_config_id) if ha_selected_config_id else None
```

[VERIFIED: `services/hue_client.py:75-100` returns `{id, name, status, channel_count}`; `routers/hue.py:99-113` shows the bridge-paired check pattern]

**Bridge-unpaired fallback:** If `bridge_config` is empty, return `active_config_name = None`, `bridge_paired = False`, and **do not raise**. `/api/ha/status` must still return a sensible payload so HA template sensors stay healthy even before bridge pairing.

**Bridge HTTP error handling:** Wrap `list_entertainment_configs` in `try / except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError)`. On error, set `active_config_name = None` and surface as `bridge_paired = True` (we have credentials) but log a warning. Do NOT 502 the status endpoint — HA polling shouldn't break because the bridge had a transient glitch. [VERIFIED pattern: `routers/wled.py:194-215` shows exception mapping]

### Active camera name

Given `_metrics["active_device_path"]`:

```python
async with db.execute(
    "SELECT stable_id, display_name FROM known_cameras "
    "WHERE last_device_path = ? "
    "ORDER BY last_seen_at DESC LIMIT 1",
    (active_device_path,),
) as cursor:
    row = await cursor.fetchone()
active_camera_stable_id = row["stable_id"] if row else None
active_camera_name     = row["display_name"] if row else None
```

[VERIFIED: `known_cameras` columns `stable_id, display_name, last_seen_at, last_device_path` per `database.py:71-77`]

**Edge case:** Two cameras may share a `last_device_path` if `/dev/video0` got reassigned. `ORDER BY last_seen_at DESC LIMIT 1` picks the most recent. Acceptable approximation — HA users care about a human-readable label, not perfect uniqueness in a degraded state.

### HA-selected camera name

Given `ha_state.active_camera_stable_id`:

```python
async with db.execute(
    "SELECT display_name FROM known_cameras WHERE stable_id = ?",
    (ha_selected_camera_stable_id,),
) as cursor:
    row = await cursor.fetchone()
ha_selected_camera_name = row["display_name"] if row else None
```

Simple PK lookup. If `stable_id` was deleted from `known_cameras` between the `PUT /api/ha/camera` and the `GET /api/ha/status`, `ha_selected_camera_name` is `None` but `ha_selected_camera_stable_id` still returns the dangling string. HA dashboards can show "Selected camera not found" if name is None and id is non-null.

### `bridge_paired` flag

```python
async with db.execute(
    "SELECT 1 FROM bridge_config WHERE id = 1"
) as cursor:
    row = await cursor.fetchone()
bridge_paired = row is not None
```

[VERIFIED: `routers/hue.py:78-88` returns `BridgeStatusResponse(paired=False)` when row is None]

## Test Patterns (existing — to be mirrored)

### Unit-test template: `Backend/tests/test_wled_router.py`

[VERIFIED: full read of file] — establishes the template Phase 18 should mirror exactly.

**Key structural points:**

1. **In-memory aiosqlite per test** — `_make_db()` creates a fresh `:memory:` connection with only the tables this router touches (do NOT create the full `database.py` schema; just `ha_state` + the FK-target tables `entertainment_configs`, `known_cameras`, `camera_last_zone`).

2. **Lifespan injection via `@asynccontextmanager`** — `_wled_app_lifespan(app)` sets `app.state.db = db` and yields. Phase 18 should add `app.state.coordinator = MagicMock()` to the integration test path; CRUD unit tests skip coordinator entirely (uses `getattr(..., None)` fallback).

3. **`patch("routers.ha.list_entertainment_configs", AsyncMock(return_value=...))`** — patch at the import path inside the router, NOT at `services.hue_client.list_entertainment_configs`. Verified pattern: `routers/wled.py:42-43` imports as `from services.wled_client import fetch_wled_info` then tests patch `routers.wled.fetch_wled_info` (line 128 of test).

4. **`TestClient(app)` inside `with` block** — synchronous request driver. Sufficient for all unit tests.

5. **Direct DB poke via `asyncio.run`** — for assertions that the DB row was actually written:

   ```python
   async def _check_row():
       db = app.state.db
       async with db.execute("SELECT ... FROM ha_state WHERE id=1") as cur:
           ...
   asyncio.run(_check_row())
   ```

   Pattern: `test_wled_router.py:175-189`.

### Integration-test template: `Backend/tests/test_phase17_e2e.py`

[VERIFIED: lines 1-251] — wires a **real** `StreamingCoordinator` with a **mocked** Hue sink, real WLED streamer pinned to loopback, and a `MagicMock` capture. Phase 18 integration test should:

- Wire the real coordinator
- Pass a **mocked** `HueStreamer` (`MagicMock` with `start`/`stop`/`render`/`handle_bridge_error` as `AsyncMock`)
- Pass a **MagicMock** `WledStreamer` (cleaner than loopback — we're not asserting WLED packet shape in Phase 18)
- Use `make_mock_capture()` from `tests/fixtures/mock_capture.py` (already exists)
- Drive the full `PUT zone → PUT camera → POST start → assert state=streaming → GET status → POST stop → assert state=idle` sequence

### Frontend tests

**Out of scope for Phase 18.** No frontend changes — confirmed by CONTEXT.md `<code_context>` "No frontend changes. The web UI is unaware of HA." Vitest test files are not added.

## HA Error Semantics (verified)

| HTTP Status | Used By | Source File:Line | Phase 18 Reuse |
|---|---|---|---|
| 400 | `routers/hue.py:110` "Bridge not paired" | `routers/hue.py:99-110` (currently used at `/api/hue/configs`) | `POST /api/ha/start` when `ha_state.active_config_id` is NULL → `400 "no zone selected"` |
| 403 | `routers/hue.py:35` Hue pairing button not pressed | `routers/hue.py:32-35` | NOT used in Phase 18 |
| 404 | `routers/cameras.py:273, 333, 421, 432`, `routers/wled.py:277, 311, 326` | universally used for "row not found" | All Phase 18 404s: unknown zone in PUT/start, unknown camera in PUT |
| 409 | `routers/wled.py:188` "already registered" | `routers/wled.py:187-191` | NOT used in Phase 18 |
| 410 | `routers/capture.py:96` deprecated endpoint | `routers/capture.py:92-98` | NOT used in Phase 18 |
| 422 | `routers/wled.py:213, 220` malformed payload shape | `routers/wled.py:210-222` | Pydantic-level — automatic for malformed `{zone_id}` / `{stable_id}` |
| 502 | `routers/hue.py:37, 45` Bridge unreachable; `routers/wled.py:199, 204, 209` | upstream HTTP error | `GET /api/ha/zones` when bridge HTTP fails; `GET /api/ha/status` does NOT 502 (degrades gracefully) |
| 503 | `routers/capture.py:77, 83, 87, 114, 119` capture unavailable | `routers/capture.py` | `POST /api/ha/start` when bridge is unpaired entirely (no `bridge_config` row) |

**Phase 18 error mapping (locked per CONTEXT.md Claude's Discretion):**

| Endpoint | Condition | Status | Detail |
|---|---|---|---|
| `POST /api/ha/start` | `ha_state.active_config_id` is NULL or `ha_state` row missing | 400 | "no zone selected — call PUT /api/ha/zone first" |
| `POST /api/ha/start` | `active_config_id` not in `entertainment_configs` | 404 | "zone not found — it may have been deleted on the Bridge" |
| `POST /api/ha/start` | `bridge_config` empty (un-paired) | 503 | "Hue bridge not paired" |
| `POST /api/ha/start` | Already streaming | 200 | Returns current status payload (idempotent no-op) |
| `POST /api/ha/stop` | Already idle | 200 | Returns current status payload (idempotent no-op) |
| `PUT /api/ha/zone` | `zone_id` not in `entertainment_configs` | 404 | "zone not found" |
| `PUT /api/ha/zone` | Pydantic missing/empty `zone_id` | 422 | Auto |
| `PUT /api/ha/camera` | `stable_id` not in `known_cameras` | 404 | "camera not found" |
| `PUT /api/ha/camera` | Pydantic missing/empty `stable_id` | 422 | Auto |
| `GET /api/ha/zones` | `bridge_config` empty | 503 | "Hue bridge not paired" |
| `GET /api/ha/zones` | Bridge HTTP error (timeout/connect) | 502 | "Hue bridge unreachable: <exc>" |
| `GET /api/ha/cameras` | Always succeeds | 200 | Empty list if no cameras |
| `GET /api/ha/status` | Always succeeds (degrades gracefully) | 200 | `bridge_paired=false` if unpaired, `active_*` all None if idle |

**Note on `/api/hue/configs`:** Currently returns 400 when unpaired (line 110). CONTEXT.md Existing Code Insights observes "possibly bump to 503 for consistency — but keep `/api/hue/configs` unchanged." Phase 18 uses 503 for `/api/ha/zones`/`/api/ha/start` while leaving `/api/hue/configs` at 400. The asymmetry is documented and intentional.

## Common Pitfalls

### Pitfall 1: SQLite REPLACE drops un-touched columns

**What goes wrong:** `INSERT OR REPLACE INTO ha_state (id, active_config_id) VALUES (1, 'cfg1')` deletes the existing row and inserts a new one. Any column **not** in the VALUES list (e.g. `active_camera_stable_id`) becomes NULL.

**Why it happens:** SQLite `REPLACE` = `DELETE` + `INSERT`. The deleted row's other columns are gone.

**How to avoid:** Always include the preserved columns explicitly with `COALESCE`:

```sql
INSERT OR REPLACE INTO ha_state (id, active_config_id, active_camera_stable_id, updated_at)
VALUES (
    1,
    :new_zone,
    COALESCE((SELECT active_camera_stable_id FROM ha_state WHERE id=1), NULL),
    :now
)
```

Or use `INSERT ... ON CONFLICT(id) DO UPDATE SET` (cleaner, used by `cameras.py:443-450`):

```sql
INSERT INTO ha_state (id, active_config_id, updated_at)
VALUES (1, :new_zone, :now)
ON CONFLICT(id) DO UPDATE SET
    active_config_id = excluded.active_config_id,
    updated_at = excluded.updated_at
```

**Recommendation:** Use `ON CONFLICT DO UPDATE` — matches the established `routers/cameras.py::put_last_zone` pattern (lines 442-451) and avoids the COALESCE subquery.

**Warning signs:** A `PUT /api/ha/zone` after a previous `PUT /api/ha/camera` shows `active_camera_stable_id = null` in `GET /api/ha/status`.

### Pitfall 2: `ha_state` table missing on first call

**What goes wrong:** Calling `PUT /api/ha/zone` before `init_db` ran throws `OperationalError: no such table: ha_state`.

**Why it happens:** Test paths or partial-schema fixtures may skip the `ha_state` CREATE block.

**How to avoid:** Add the `CREATE TABLE IF NOT EXISTS ha_state` block to `database.py` alongside the existing tables (lines 17-126). The `GET /api/ha/status` handler **should also tolerate a missing row** (D-05 lazy creation): `SELECT … FROM ha_state WHERE id=1` returning `None` is the expected pre-first-write state and maps to all `ha_selected_*` fields = None.

**Warning signs:** Test failure `OperationalError: no such table: ha_state` in CI.

### Pitfall 3: Forgetting D-06's `camera_last_zone` dual-write

**What goes wrong:** HA sets a zone via `PUT /api/ha/zone`. Web UI is opened in another tab. UI's 3-tier zone selection cascade (Phase 16 D-09) does NOT see HA's choice because `camera_last_zone` was not updated.

**Why it happens:** Implementer reads "PUT /api/ha/zone writes ha_state" and stops there.

**How to avoid:** Implement D-06's conditional dual-write strictly:
1. Read current `ha_state.active_camera_stable_id`.
2. If it is non-null (set by an earlier `PUT /api/ha/camera`), also write `camera_last_zone[that_camera] = new_zone_id` in the same transaction.
3. If it is null, skip the second write.

**Warning signs:** Integration test fails: after `PUT /api/ha/camera + PUT /api/ha/zone`, querying `camera_last_zone` returns 0 rows.

### Pitfall 4: Bridge HTTP errors propagate from `GET /api/ha/status`

**What goes wrong:** `list_entertainment_configs` times out → `httpx.TimeoutException` bubbles up → `/api/ha/status` returns 500.

**Why it happens:** No try/except around the Hue Bridge call in the status assembly.

**How to avoid:** Wrap the bridge call in a try/except that catches `httpx.HTTPError` (parent of TimeoutException, ConnectError, HTTPStatusError) and falls back to `config_name_by_id = {}` with `active_config_name = None`, `bridge_paired = True` (we still have credentials). Log the warning.

**Warning signs:** HA template sensors go to "unavailable" the moment the Bridge takes >10s to respond.

### Pitfall 5: Coordinator's `_resolve_device_path` ignores `ha_state.active_camera_stable_id`

**What goes wrong:** HA does `PUT /api/ha/camera {stable_id}` then `POST /api/ha/start`. Coordinator resolves device path via `camera_assignments` (which HA didn't touch per D-07), ignoring HA's camera choice.

**Why it happens:** D-08's resolution chain ordering is **router-side logic, not coordinator-side**. The coordinator only knows about `camera_assignments` → `known_cameras` → env.

**How to avoid (recommended Option C):** Add `device_path_override` parameter to `StreamingCoordinator.start`. The HA router resolves the override path from `ha_state.active_camera_stable_id` → `known_cameras.last_device_path` and passes it explicitly.

```python
# coordinator change
async def start(self, config_id: str, target_hz: int = DEFAULT_HZ, device_path_override: str | None = None) -> None:
    ...
    device_path = device_path_override or await self._resolve_device_path(config_id)

# routers/ha.py
if ha_state.active_camera_stable_id:
    async with db.execute("SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
                          (ha_state.active_camera_stable_id,)) as cur:
        row = await cur.fetchone()
    device_path_override = row["last_device_path"] if row and row["last_device_path"] else None
else:
    device_path_override = None
await coordinator.start(ha_state.active_config_id, device_path_override=device_path_override)
```

**Warning signs:** Integration test seeds `ha_state.active_camera_stable_id` to camera B but `camera_assignments[active_config_id]` points to camera A. After `POST /api/ha/start`, broadcaster's `_metrics["active_device_path"]` is camera A's path, not camera B's.

### Pitfall 6: Pydantic v2 schema for `POST /start` with empty body

**What goes wrong:** Declaring `POST /api/ha/start` with no body parameter works in FastAPI, but accidentally adding `body: Optional[SomeModel] = None` then expecting "empty body OK" — Pydantic returns 422 on `null` POST.

**Why it happens:** D-03 says empty body. Implementer adds a model just in case.

**How to avoid:** **Do not declare a body parameter** for `POST /start` and `POST /stop`. Function signature is:

```python
@router.post("/start", response_model=HaStatusResponse)
async def ha_start(request: Request) -> HaStatusResponse:
    ...
```

HA's `rest_command:` sends `Content-Length: 0` for `payload`-less calls. FastAPI handles this natively.

**Warning signs:** Calling `/api/ha/start` with `curl -X POST http://host:8000/api/ha/start` (no `-d`) returns 422.

## Code Examples

### Example 1: Schema add (`database.py`)

```python
# Backend/database.py — append alongside existing CREATE TABLE blocks (after line 91)
await db.execute("""
    CREATE TABLE IF NOT EXISTS ha_state (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        active_config_id TEXT,
        active_camera_stable_id TEXT,
        updated_at TEXT
    )
""")
```

Source: CONTEXT.md D-04; established pattern across `database.py:17-126`.

### Example 2: Router include (`main.py`)

```python
# Backend/main.py — add to import block (after line 17)
from routers.ha import router as ha_router

# Backend/main.py — add to router-include block (after line 86)
app.include_router(ha_router)
```

Source: mirror lines 17, 83 (existing wled_router include).

### Example 3: `PUT /api/ha/zone` handler skeleton

```python
@router.put("/zone", response_model=HaStatusResponse)
async def ha_put_zone(body: HaZoneRequest, request: Request) -> HaStatusResponse:
    db = request.app.state.db

    # 1. Validate zone exists (D-06 step 1)
    async with db.execute(
        "SELECT id FROM entertainment_configs WHERE id = ?",
        (body.zone_id,),
    ) as cur:
        if (await cur.fetchone()) is None:
            raise HTTPException(404, detail=f"zone_id '{body.zone_id}' not found")

    # 2. Read current camera (D-06 step 3 decision)
    async with db.execute(
        "SELECT active_camera_stable_id FROM ha_state WHERE id = 1"
    ) as cur:
        row = await cur.fetchone()
    current_camera = row["active_camera_stable_id"] if row else None

    now_iso = datetime.now(timezone.utc).isoformat()

    # 3. Upsert ha_state (D-06 step 2)
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

    # 4. D-06 conditional dual-write
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
```

### Example 4: `GET /api/ha/status` assembly

```python
@router.get("/status", response_model=HaStatusResponse)
async def ha_status(request: Request) -> HaStatusResponse:
    return await _build_status_response(request)


async def _build_status_response(request: Request) -> HaStatusResponse:
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
    bridge_paired = bridge_row is not None
    config_name_by_id: dict[str, str] = {}
    if bridge_paired:
        try:
            configs = await list_entertainment_configs(
                bridge_row["ip_address"], bridge_row["username"]
            )
            config_name_by_id = {c["id"]: c["name"] for c in configs}
        except httpx.HTTPError as exc:
            logger.warning("Hue bridge unreachable in /api/ha/status: %s", exc)

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

    return HaStatusResponse(
        state=metrics.get("state", "idle"),
        active_config_id=metrics.get("active_config_id"),
        active_config_name=config_name_by_id.get(metrics.get("active_config_id")) if metrics.get("active_config_id") else None,
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
        error=metrics.get("error"),  # None when absent — Pydantic serializes as null
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| HPC calls HA REST API (outbound, requires token storage) | HA calls HPC via `rest_command:` (inbound, no token) | CLAUDE.md v1.3 design (Apr 2026) | No secret management; Phase 18 stays auth-free |
| Custom WebSocket for HA push | REST polling at 10–30s | CONTEXT.md Phase 18 (May 2026) | One fewer surface; HA template sensors handle REST cleanly |
| `streaming_service.py` as monolithic capture+stream class | `StreamingCoordinator` + `HueStreamer` + `WledStreamer` sinks | Phase 17 Plan 05 (Apr 2026) | Phase 18 has a clean delegation target with stable `start`/`stop`/`state` API |
| `_metrics` exposed raw via `/ws/status` | `_metrics` exposed raw to existing consumers; `/api/ha/status` projects a curated subset | Phase 18 D-09 (May 2026) | HA dashboards insulated from internal metric churn |

**Deprecated/outdated:**

- **PUT /api/capture/device** (`routers/capture.py:92-98`) — returns 410, supplanted by `PUT /api/cameras/assignments/{config_id}`. Do NOT reintroduce this verb shape for HA endpoints.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The planner will accept Option C (add `device_path_override` to `StreamingCoordinator.start`) over Option B (router-side temp `camera_assignments` write) for D-08 step 3a. | StreamingCoordinator API → `_resolve_device_path` chain | Planner must choose B; integration tests need to assert `camera_assignments` unchanged. Recommended Option C is the cleaner one but it requires a one-line coordinator API change which may not be desired this late in v1.3. |
| A2 | `httpx.HTTPError` is the right base exception to catch in `_build_status_response` to gracefully degrade when the bridge times out. | Friendly-Name Resolution Paths | If `httpx` v0.28 changes the hierarchy, may need to catch broader `Exception` — easy fix. [VERIFIED via routers/wled.py:206 already uses `httpx.HTTPError`] |
| A3 | HA's `rest_command:` will send `Content-Length: 0` for payload-less POSTs (so we declare no body model on `/start` / `/stop`). | Pitfall 6 | If HA sends `Content-Type: application/json` with `{}`, FastAPI still accepts an unparameterized handler — no risk in practice. |
| A4 | The two cameras can share a `last_device_path` edge case is rare enough that `ORDER BY last_seen_at DESC LIMIT 1` is acceptable. | Friendly-Name Resolution Paths → Active camera name | If users hot-swap cameras on the same path, status may briefly show the wrong friendly name. Self-corrects on next `/api/cameras` scan. |
| A5 | No additional test file exists for `test_ha_*` already. | Test Patterns | Verified by Glob — only `test_wled_router.py` and `test_cameras_router.py` exist as routerXXX_router.py shaped fixtures. [VERIFIED] |
| A6 | Existing `pytest-asyncio` config supports `@pytest.mark.asyncio` integration tests. | Test Patterns → Integration | `test_phase17_e2e.py:132` uses the marker and is shipped/passing per STATE.md "Phase 17 complete". [VERIFIED] |

## Open Questions (RESOLVED)

1. **Resolution of D-08 step 3a (coordinator-vs-router):**
   - What we know: D-07 says HA's PUT camera must NOT write `camera_assignments`. D-08 says HA's `/start` must honor `ha_state.active_camera_stable_id` over `camera_assignments`.
   - What's unclear: Should the coordinator gain a `device_path_override` param (clean) or should the router temporarily write+revert `camera_assignments` around the `coordinator.start` call (ugly)?
   - **Recommendation:** RESOLVED: Pick Option C (add `device_path_override` parameter). Planner can choose to defer if the API change feels too invasive — but Option B is messier under concurrent calls (the temp-write window leaks if `/start` is called twice quickly).

2. **`POST /api/ha/stop` response body when already idle:**
   - What we know: CONTEXT.md says "returns current status payload in body so HA gets immediate post-action state."
   - What's unclear: Should the response shape be `HaStatusResponse` (same as `GET /api/ha/status`) or a simpler `{"status": "ok"}`?
   - **Recommendation:** RESOLVED: Return `HaStatusResponse` for all three control endpoints (`/start`, `/stop`, plus `/zone`, `/camera` if helpful). HA can render the same template sensor from any response. Single response model = simpler HA-side YAML. This is implicit in CONTEXT.md Claude's Discretion "Both return the current status payload".

3. **Bridge pairing detection for `/api/ha/zones`:**
   - What we know: 503 if `bridge_config` is empty.
   - What's unclear: Should we also 503 if the bridge HTTP call times out, or stay 502?
   - **Recommendation:** RESOLVED: 503 for "unpaired" (no credentials), 502 for "paired but unreachable/timeout" (have credentials, can't connect). This matches `routers/hue.py` semantics by precedent (currently uses 400/502 — Phase 18 upgrades 400 → 503 for consistency).

4. **Should `/api/ha/cameras` include disconnected cameras?**
   - What we know: D-11 says `[{stable_id, name, connected}]`.
   - What's unclear: Does "connected: false" cameras appear in the list, or is the list filtered to only connected?
   - **Recommendation:** RESOLVED: Include disconnected ones, expose `connected: false`. Mirrors `GET /api/cameras` (line 194-215 of `routers/cameras.py`) which includes previously-seen-but-gone devices. HA users can filter on their side via templating.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Backend runtime | ✓ | 3.12 (pinned) | — |
| FastAPI | Router | ✓ | >=0.115 | — |
| aiosqlite | DB layer | ✓ | >=0.20 | — |
| httpx | Indirect via hue_client | ✓ | >=0.27 | — |
| pytest | Test runner | ✓ | (per requirements.txt) | — |
| pytest-asyncio | Async test marker | ✓ | (used by test_phase17_e2e.py) | — |
| Hue Bridge v2 (192.168.178.23) | `/api/ha/zones`, `/api/ha/status` friendly names | ✓ at runtime | paired | Endpoint degrades to `bridge_paired=false`, names=null |
| USB capture / virtual V4L2 | `/api/ha/cameras` device scan | ✓ at runtime | /dev/video0 or /dev/video10 | Empty list returned if no devices |
| HA instance | The actual user-side caller | not required for backend tests | — | Backend tests use TestClient; HA integration is out of automated scope |

**Missing dependencies with no fallback:** None. The phase only requires the existing stack.

**Missing dependencies with fallback:**
- Hue Bridge unreachable at test time → `/api/ha/status` gracefully degrades; `/api/ha/zones` returns 502/503 (correct behavior).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 7.x + pytest-asyncio (existing) |
| Config file | `Backend/pyproject.toml` or `Backend/pytest.ini` (existing; pytest discovers from `Backend/` cwd) |
| Quick run command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_ha_router.py -x` |
| Full suite command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HASS-01 | `POST /api/ha/start` starts streaming when preconditions met | unit + integration | `pytest tests/test_ha_router.py::test_start_calls_coordinator_with_resolved_path -x` | ❌ Wave 0 |
| HASS-01 | `POST /api/ha/start` returns 400 when no zone in ha_state | unit | `pytest tests/test_ha_router.py::test_start_400_when_no_zone_selected -x` | ❌ Wave 0 |
| HASS-01 | `POST /api/ha/start` returns 404 when stored zone was deleted on bridge | unit | `pytest tests/test_ha_router.py::test_start_404_when_zone_deleted -x` | ❌ Wave 0 |
| HASS-01 | `POST /api/ha/start` is idempotent (200 no-op when already streaming) | unit | `pytest tests/test_ha_router.py::test_start_idempotent_when_streaming -x` | ❌ Wave 0 |
| HASS-02 | `POST /api/ha/stop` calls coordinator.stop() | unit | `pytest tests/test_ha_router.py::test_stop_calls_coordinator -x` | ❌ Wave 0 |
| HASS-02 | `POST /api/ha/stop` is idempotent (200 no-op when already idle) | unit | `pytest tests/test_ha_router.py::test_stop_idempotent_when_idle -x` | ❌ Wave 0 |
| HASS-03 | `PUT /api/ha/camera` persists to ha_state, lazy row create | unit | `pytest tests/test_ha_router.py::test_put_camera_persists_lazy -x` | ❌ Wave 0 |
| HASS-03 | `PUT /api/ha/camera` returns 404 for unknown stable_id | unit | `pytest tests/test_ha_router.py::test_put_camera_404_unknown -x` | ❌ Wave 0 |
| HASS-03 | `PUT /api/ha/camera` does NOT touch camera_assignments (D-07) | unit | `pytest tests/test_ha_router.py::test_put_camera_does_not_touch_assignments -x` | ❌ Wave 0 |
| HASS-04 | `PUT /api/ha/zone` persists to ha_state, lazy row create | unit | `pytest tests/test_ha_router.py::test_put_zone_persists_lazy -x` | ❌ Wave 0 |
| HASS-04 | `PUT /api/ha/zone` returns 404 for unknown zone_id | unit | `pytest tests/test_ha_router.py::test_put_zone_404_unknown -x` | ❌ Wave 0 |
| HASS-04 | `PUT /api/ha/zone` dual-writes camera_last_zone WHEN camera set (D-06) | unit | `pytest tests/test_ha_router.py::test_put_zone_dual_writes_camera_last_zone -x` | ❌ Wave 0 |
| HASS-04 | `PUT /api/ha/zone` does NOT write camera_last_zone WHEN camera NULL (D-06) | unit | `pytest tests/test_ha_router.py::test_put_zone_skips_dual_write_when_no_camera -x` | ❌ Wave 0 |
| HASS-04 | `PUT /api/ha/zone` preserves active_camera_stable_id across REPLACE | unit | `pytest tests/test_ha_router.py::test_put_zone_preserves_camera -x` | ❌ Wave 0 |
| HASS-05 | `GET /api/ha/status` returns full D-09 schema with active_* from broadcaster | unit | `pytest tests/test_ha_router.py::test_status_schema_when_streaming -x` | ❌ Wave 0 |
| HASS-05 | `GET /api/ha/status` returns ha_selected_* from ha_state | unit | `pytest tests/test_ha_router.py::test_status_includes_ha_selected -x` | ❌ Wave 0 |
| HASS-05 | `GET /api/ha/status` resolves friendly names from Bridge | unit (mocked) | `pytest tests/test_ha_router.py::test_status_resolves_friendly_names -x` | ❌ Wave 0 |
| HASS-05 | `GET /api/ha/status` degrades gracefully when bridge unpaired | unit | `pytest tests/test_ha_router.py::test_status_bridge_unpaired -x` | ❌ Wave 0 |
| HASS-05 | `GET /api/ha/status` degrades gracefully when bridge HTTP errors | unit | `pytest tests/test_ha_router.py::test_status_bridge_http_error -x` | ❌ Wave 0 |
| HASS-05 | `GET /api/ha/status` does NOT leak `packets_sent`, `seq`, `wled_devices` | unit | `pytest tests/test_ha_router.py::test_status_curated_payload_shape -x` | ❌ Wave 0 |
| HASS-05 | `GET /api/ha/status` includes `error` field only when present | unit | `pytest tests/test_ha_router.py::test_status_error_field_optional -x` | ❌ Wave 0 |
| D-11 | `GET /api/ha/zones` returns `[{id, name}]` only | unit | `pytest tests/test_ha_router.py::test_zones_curated_shape -x` | ❌ Wave 0 |
| D-11 | `GET /api/ha/cameras` returns `[{stable_id, name, connected}]` only | unit | `pytest tests/test_ha_router.py::test_cameras_curated_shape -x` | ❌ Wave 0 |
| HASS-01..05 | End-to-end: PUT zone → PUT camera → POST start → GET status → POST stop | integration | `pytest tests/test_phase18_e2e.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd Backend && python -m pytest tests/test_ha_router.py -x` (~10s)
- **Per wave merge:** `cd Backend && python -m pytest tests/test_ha_router.py tests/test_phase18_e2e.py -x` (~30s)
- **Phase gate:** Full suite green — `cd Backend && python -m pytest` (~3 min, 167+ tests)

### Wave 0 Gaps

- [ ] `Backend/tests/test_ha_router.py` — covers HASS-01..05 per-endpoint unit tests
- [ ] `Backend/tests/test_phase18_e2e.py` — covers full HA flow end-to-end (mirror `test_phase17_e2e.py`)
- [ ] **No fixture additions needed** — existing `tests/fixtures/mock_capture.py` is reused; `_make_db()` helper is local-per-file (same pattern as `test_wled_router.py`)
- [ ] **No new conftest entries needed** — Phase 18 tests mock the coordinator inline with `MagicMock`; the existing `_make_coordinator_mock` helper (conftest.py:171-177) is sufficient.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | **no** | Explicitly out of scope per PROJECT.md §Constraints "No auth: Web UI is unauthenticated — local network tool only". HA endpoints inherit. |
| V3 Session Management | no | No sessions; stateless REST. |
| V4 Access Control | no | LAN is trust boundary; no per-caller authorization. |
| V5 Input Validation | **yes** | Pydantic v2 models with `Field` regex for IPs (precedent: `routers/wled.py:55-56`); FastAPI's automatic 422 on shape mismatch. All foreign-key references validated against DB before write (precedent: `routers/cameras.py:412-437`). |
| V6 Cryptography | no | No new crypto. Hue Bridge `verify=False` is an existing accepted risk per the v1.0 spike. |
| V7 Error Handling | **yes** | All endpoints map exceptions to standard HTTP codes (400/404/422/502/503). `GET /api/ha/status` degrades gracefully on Bridge errors instead of bubbling 500. |
| V8 Data Protection | **yes (minor)** | `ha_state` stores no secrets — only entertainment config UUIDs and camera stable IDs. No PII; no tokens. |
| V9 Communications | no | LAN-only by design; HTTPS to Hue Bridge already in use (with `verify=False` — local self-signed certs). |
| V10 Malicious Code | no | No new external dependencies. |
| V11 Business Logic | **yes** | D-06 conditional dual-write must be atomic (single transaction); idempotency of `/start` and `/stop` must hold. |
| V12 Files & Resources | no | No file I/O introduced. |
| V13 API & Web Service | **yes** | All endpoints declared with explicit `response_model`. No unconstrained dict returns. OpenAPI tags=["ha"] for discoverability. |
| V14 Configuration | no | No config changes beyond a new DB table. |

### Known Threat Patterns for FastAPI + SQLite + LAN-trusted

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via `zone_id` or `stable_id` | Tampering | All DB writes use parameterized queries (`?` and `:name` placeholders) — established convention in every existing handler. **Never** use f-string interpolation. |
| Path traversal via `stable_id` | Tampering | N/A — stable_id is opaque text, never used as a filesystem path. |
| SSRF via Hue Bridge URL | Tampering / EoP | Bridge IP loaded from DB (set during user-driven pairing), not from request body. HA endpoints do not accept Bridge IPs as input. |
| DoS via HA polling storm | Denial of Service | `GET /api/ha/status` queries Bridge `list_entertainment_configs` once per call — if HA polls every second this is ~1 req/s to Bridge. Bridge tolerates this. **Caching is the planned mitigation IF needed** (CONTEXT.md Claude's Discretion). |
| Stale `ha_state.active_config_id` causing 500 on `/start` | Reliability | D-08 validates against `entertainment_configs` before delegation → 404, not 500. |
| Concurrent `PUT /api/ha/zone` and `POST /api/ha/start` race | Reliability | Single `db.commit()` per handler; SQLite's serial writer eliminates split-read. Coordinator `start` already idempotent. |
| Malformed JSON body | DoS | FastAPI's automatic 422 (Pydantic) — no handler code reached. |
| Empty `zone_id` / empty `stable_id` strings | Tampering | Pydantic v2: `str` accepts empty by default. Add `Field(..., min_length=1)` on both fields. (Not mandated by CONTEXT.md but recommended.) |

[ASSUMED] Including `Field(..., min_length=1)` on `HaZoneRequest.zone_id` and `HaCameraRequest.stable_id` is acceptable to the planner. CONTEXT.md doesn't specify, but this is a tiny hardening that prevents `{"zone_id": ""}` from being upserted as a literal empty string and later failing the 404 lookup unnecessarily.

## Sources

### Primary (HIGH confidence) — direct file reads in this repo

- `C:/Users/Lukas/IdeaProjects/HuePictureControl/.planning/phases/18-home-assistant-control-endpoints/18-CONTEXT.md` (full read — all 250 lines)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/.planning/phases/17-wled-backend-and-streaming/17-CONTEXT.md` (full read)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/.planning/phases/16-zone-persistence-bug-fixes/16-CONTEXT.md` (full read)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/.planning/ROADMAP.md` (full read — Phase 18 §164)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/.planning/STATE.md` (full read)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/.planning/PROJECT.md` (first 80 lines — §Constraints, §Active v1.3)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/.planning/milestones/v1.1-REQUIREMENTS.md` (HASS-01..05 lines 172-178)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/CLAUDE.md` (full read — §Constraints, §"What NOT to Use", §"Alternatives Considered", §"Home Assistant REST API")
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/database.py` (full read — schema patterns)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/main.py` (full read — lifespan + router includes)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/services/streaming_coordinator.py` (full read — start/stop/state/_resolve_device_path)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/services/status_broadcaster.py` (full read — `_metrics` shape)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/services/hue_client.py` (full read — `list_entertainment_configs`)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/routers/cameras.py` (full read — put_last_zone dual-write pattern)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/routers/wled.py` (full read — coord_health, getattr pattern, Pydantic style)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/routers/capture.py` (full read — coordinator wiring)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/routers/hue.py` (full read — bridge_paired pattern, error semantics)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/tests/conftest.py` (full read — `_make_coordinator_mock`, `_make_broadcaster_mock`)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/tests/test_wled_router.py` (full read — unit test template)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/tests/test_cameras_router.py` (first 120 lines — fixture pattern)
- `C:/Users/Lukas/IdeaProjects/HuePictureControl/Backend/tests/test_phase17_e2e.py` (first 250 lines — integration test template)

### Secondary (MEDIUM confidence)

- [Home Assistant REST API developer docs](https://developers.home-assistant.io/docs/api/rest/) — confirms `rest_command:` is the standard inbound integration. Cited by CLAUDE.md.
- HA `rest_command:` integration docs — confirms HA POSTs/PUTs with `application/json` and captures responses.

### Tertiary (LOW confidence)

- None. All claims in this research are either verified against repo files (HIGH) or against CLAUDE.md/CONTEXT.md (HIGH — they're the locked source of truth for this project).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every dependency is already in use and verified via direct file read
- Architecture: HIGH — all referenced files exist and match the described patterns; CONTEXT.md decisions are locked
- Pitfalls: HIGH — all pitfalls derive from verified language/library semantics (SQLite REPLACE, FastAPI body handling, httpx exception hierarchy) or from CONTEXT.md locked decisions
- Test patterns: HIGH — `test_wled_router.py` and `test_phase17_e2e.py` are the verified templates
- HA error semantics: HIGH — error status codes traced to specific files+lines

**Research date:** 2026-05-11
**Valid until:** 2026-06-10 (30 days — stable phase, well-defined contracts, no fast-moving deps)
