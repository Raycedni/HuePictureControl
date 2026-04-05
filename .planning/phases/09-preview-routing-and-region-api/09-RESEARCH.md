# Phase 9: Preview Routing and Region API - Research

**Researched:** 2026-04-05
**Domain:** FastAPI WebSocket query params, SQLite JOIN migrations, TypeScript type updates
**Confidence:** HIGH

## Summary

Phase 9 is a precision wiring phase — no new libraries are needed. All components
(CaptureRegistry, cameras table, regions table) exist from Phases 7 and 8. The work
is: (1) add a read-only `get(device_path)` method to `CaptureRegistry`, (2) update
`/ws/preview` to parse a required `?device=` query param and route to the right
backend, (3) extend `GET /api/cameras` with `zone_health` and `cameras_available`
fields derived from `camera_assignments` + `known_cameras` tables, (4) add
`entertainment_config_id` column to `regions` table (schema migration), (5) derive
`camera_device` in `GET /api/regions` via LEFT JOIN, and (6) update frontend
TypeScript types and the `usePreviewWS` hook.

The biggest architectural gap identified by code inspection: `CaptureRegistry` does
NOT have a `get(device_path)` method. It only has `get_default()`. D-01 explicitly
requires a non-ref-counted peek path, so this method must be added to
`capture_service.py` as part of Wave 1.

**Primary recommendation:** Add `CaptureRegistry.get(device_path)` first — it
unblocks both the preview WebSocket implementation and its tests.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Preview WebSocket uses read-only peek — calls `registry.get(device_path)` to read
frames but does NOT acquire/release (no ref counting). Preview is a passive observer; only
streaming sessions own device lifecycle.

**D-02:** When the requested device is unavailable, the WebSocket stays open and retries every 1
second (same as current behavior). No close-with-error or fallback to a different device.

**D-03:** The `?device=` param accepts both device paths (`/dev/video0`) and stable IDs
(`vid:pid:serial`). If the param looks like a path (starts with `/dev/`), use directly.
Otherwise, treat as stable_id and resolve to current device path via `known_cameras` lookup.

**D-04:** Opening the preview WebSocket WITHOUT `?device=` param returns an error (close the
connection). The param is required — no fallback to default device. This is a breaking change
for the existing frontend, which Phase 9's frontend type updates will account for.

**D-05:** Per-zone camera health (CAMA-04) is exposed by extending the existing `GET /api/cameras`
response with a `zone_health` section. Each entry is keyed by `entertainment_config_id` and
includes `camera_name`, `camera_stable_id`, `connected` boolean, and `device_path`.

**D-06:** `GET /api/cameras` response adds a top-level `cameras_available: bool` field. When
`devices` is empty, this is `false`. Frontend can use this to show a "No cameras detected"
banner.

**D-07:** `camera_device` is a read-only derived field on `GET /api/regions` responses. It is
NOT stored in the `regions` table. The join path is: region -> `entertainment_config_id`
(stored on region) -> `camera_assignments` -> `known_cameras.last_device_path`.

**D-08:** Add `entertainment_config_id` column to the `regions` table (schema migration). This
provides a direct link from region to zone, simplifying the join. Keeps it in sync via the
existing region creation/update flow.

**D-09:** `PUT /api/regions/{id}` does NOT accept `camera_device`. Camera assignment is managed
exclusively via `PUT /api/cameras/assignments/{config_id}` (Phase 7).

**D-10:** Phase 9 updates TypeScript types and API functions only — no new UI components.
`Region` interface gains `camera_device: string | null`. `usePreviewWS` hook gains optional
`device` parameter for the WebSocket URL.

**D-11:** No camera dropdown, no new components. Phase 10 handles all UI work.

### Claude's Discretion

- How to handle the `entertainment_config_id` migration for existing regions (nullable column, backfill strategy)
- The exact WebSocket close code when `?device=` is missing
- Whether `zone_health` includes zones with no camera assignment (with a default camera fallback indicator)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCAP-02 | Preview WebSocket serves frames from the zone's assigned camera, not a global device | Implemented via `?device=` query param on `/ws/preview` + `registry.get(device_path)` peek |
| CAMA-04 | UI shows camera health status (connected/disconnected) per entertainment zone | Implemented via `zone_health` section on `GET /api/cameras` response |
</phase_requirements>

---

## Standard Stack

No new libraries required. All dependencies already installed.

### Core (already installed)
| Library | Version | Purpose |
|---------|---------|---------|
| FastAPI | >=0.115 | WebSocket routing, query param parsing, Pydantic models |
| aiosqlite | >=0.20 | Async SQLite for LEFT JOIN query and schema migration |

### Key FastAPI Patterns for This Phase

**WebSocket query param (FastAPI built-in):**
```python
# Source: FastAPI docs — https://fastapi.tiangolo.com/advanced/websockets/
from fastapi import WebSocket, Query
from typing import Optional

@router.websocket("/ws/preview")
async def ws_preview(websocket: WebSocket, device: Optional[str] = Query(default=None)):
    if device is None:
        await websocket.close(code=1008)  # Policy Violation — missing required param
        return
    await websocket.accept()
    ...
```

FastAPI injects Query params into WebSocket handlers identically to HTTP endpoints.
Confidence: HIGH — verified against FastAPI WebSocket docs pattern.

**WebSocket close before accept:** FastAPI/Starlette requires `websocket.close()` can be
called without `websocket.accept()` first. Sending close code 1008 (Policy Violation) is the
correct RFC 6455 code for protocol/parameter violations. Confidence: HIGH.

### Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| WebSocket query params | Manual URL parsing of `scope['query_string']` | FastAPI `Query()` dependency injection |
| Schema migration | DROP/recreate table | `ALTER TABLE regions ADD COLUMN entertainment_config_id TEXT` in try/except (established pattern in `database.py`) |
| Stable ID resolution | New lookup service | Direct `db.execute("SELECT last_device_path FROM known_cameras WHERE stable_id=?")` — the table exists |
| Zone health join | New service/cache | Single SQL query joining `camera_assignments` with `known_cameras` |

---

## Architecture Patterns

### CaptureRegistry.get() — the missing method

`CaptureRegistry` currently has: `acquire()`, `release()`, `get_default()`, `shutdown()`.

It does NOT have `get(device_path)`. The preview WebSocket needs a non-ref-counted peek.

**Pattern to add to `capture_service.py`:**
```python
def get(self, device_path: str) -> Optional[CaptureBackend]:
    """Return the backend for *device_path* if already acquired, else None.

    Does NOT increment reference count. Preview/peek callers use this to
    read frames without affecting device lifecycle ownership.
    """
    with self._lock:
        return self._backends.get(device_path)
```

This mirrors `get_default()` but takes an arbitrary path. Confidence: HIGH — pattern
is directly derived from existing `get_default()` implementation.

### Preview WebSocket Routing Logic

```
ws_preview(device: str | None):
  1. if device is None: websocket.close(1008); return
  2. await websocket.accept()
  3. resolve device_path:
       if device.startswith("/dev/"): device_path = device
       else: device_path = await lookup_stable_id(db, device)  # known_cameras table
  4. loop:
       backend = registry.get(device_path)
       if backend is None: sleep(1); continue
       try:
           jpeg = await backend.get_jpeg()
           await websocket.send_bytes(jpeg)
           await asyncio.sleep(0.016)
       except RuntimeError:
           sleep(1)
```

The stable_id lookup is a one-time resolution at connection time, not per-frame.
If stable_id is not found in `known_cameras`, treat as device unavailable (sleep/retry loop).

### Regions GET — SQL join for camera_device

After migration adds `entertainment_config_id` to `regions`:

```sql
SELECT
    r.id, r.name, r.polygon, r.order_index, r.light_id,
    kc.last_device_path AS camera_device
FROM regions r
LEFT JOIN camera_assignments ca ON ca.entertainment_config_id = r.entertainment_config_id
LEFT JOIN known_cameras kc ON kc.stable_id = ca.camera_stable_id
ORDER BY r.order_index
```

- LEFT JOIN ensures regions without a zone assignment still appear (camera_device = NULL)
- `entertainment_config_id` on region may be NULL (pre-migration rows, or regions not yet
  assigned to a zone) — the LEFT JOIN handles this correctly

### cameras.py — zone_health Extension

The `CamerasResponse` Pydantic model gains two new fields:

```python
class ZoneHealth(BaseModel):
    entertainment_config_id: str
    camera_name: str
    camera_stable_id: str
    connected: bool
    device_path: str | None

class CamerasResponse(BaseModel):
    devices: list[CameraDevice]
    identity_mode: str            # existing field
    cameras_available: bool       # NEW — False when devices is empty
    zone_health: list[ZoneHealth] # NEW — one entry per camera_assignments row
```

The `zone_health` list is built by joining `camera_assignments` with the current scan
results (scan_results dict built in the same request):

```python
# After existing scan_results and known_rows are built:
async with db.execute(
    "SELECT entertainment_config_id, camera_stable_id, camera_name FROM camera_assignments"
) as cursor:
    assignment_rows = await cursor.fetchall()

zone_health = []
for row in assignment_rows:
    sid = row["camera_stable_id"]
    if sid in scan_results:
        connected = True
        device_path = scan_results[sid]["device_path"]
    else:
        # Check known_cameras for last known path
        connected = False
        device_path = None  # or last_device_path from known_cameras
    zone_health.append(ZoneHealth(
        entertainment_config_id=row["entertainment_config_id"],
        camera_name=row["camera_name"],
        camera_stable_id=sid,
        connected=connected,
        device_path=device_path,
    ))
```

Regarding Claude's Discretion — "whether zone_health includes zones with no camera
assignment": recommendation is NO — `zone_health` only lists zones that have an explicit
assignment row. Zones with no assignment are simply absent. The frontend can infer "no
assignment" from the absence of the zone ID in the list.

### Schema Migration — entertainment_config_id on regions

Follow the existing pattern in `database.py` (line 48-54):

```python
# In init_db(), after the regions CREATE TABLE:
try:
    await db.execute(
        "ALTER TABLE regions ADD COLUMN entertainment_config_id TEXT"
    )
    await db.commit()
except Exception:
    # Column already exists — safe to ignore
    pass
```

Backfill strategy (Claude's Discretion): Do NOT backfill. Existing regions have
`entertainment_config_id = NULL` which is handled correctly by the LEFT JOIN — they
get `camera_device = NULL`. The auto-map flow sets `entertainment_config_id` on new
regions; the `PUT /api/regions/{id}` endpoint already accepts `entertainment_config_id`
in `UpdateRegionRequest` (it currently writes to `light_assignments`). Phase 9 must
also write it to the `regions` table itself when present in the update body.

### conftest.py — needs entertainment_config_id in regions schema

The `conftest.py` `db` fixture builds the `regions` table WITHOUT `entertainment_config_id`
(it predates this migration). The fixture must be updated to match:

```python
await conn.execute("""
    CREATE TABLE IF NOT EXISTS regions (
        id TEXT PRIMARY KEY,
        name TEXT,
        polygon TEXT NOT NULL,
        order_index INTEGER DEFAULT 0,
        light_id TEXT,
        entertainment_config_id TEXT        -- add this
    )
""")
```

This is a test-infra gap that must be closed in Wave 0.

### Frontend — usePreviewWS hook signature change

Current signature: `usePreviewWS(enabled: boolean): string | null`

New signature (D-10): `usePreviewWS(enabled: boolean, device?: string): string | null`

The hook constructs the WebSocket URL. When `device` is provided:
```typescript
const url = device
  ? `ws://${location.host}/ws/preview?device=${encodeURIComponent(device)}`
  : null  // or: don't connect if no device
```

Per D-04, the backend requires `?device=` and closes without it. The hook should only
open a connection when `device` is defined. If `enabled=true` but `device` is undefined,
the hook stays disconnected (returns null). This avoids immediate close-cycle churn.

The `useEffect` dependency array gains `device`:
```typescript
useEffect(() => { ... }, [enabled, device])
```

### Frontend — Region interface

```typescript
export interface Region {
  id: string
  name: string
  polygon: number[][]
  order_index: number
  light_id: string | null
  camera_device: string | null  // NEW — derived from zone assignment
}
```

No change to `updateRegion()` — `camera_device` is read-only per D-09.

---

## Common Pitfalls

### Pitfall 1: WebSocket close before accept
**What goes wrong:** Calling `websocket.close()` on a WebSocket that has already been
`accept()`-ed uses different semantics than closing before accept. FastAPI/Starlette
handles pre-accept close via `websocket.close(code=1008)` without a prior `accept()`.
**How to avoid:** Close BEFORE accept when rejecting due to missing param. Do not accept
first then immediately close.
**Note:** The current `preview_ws.py` does `await websocket.accept()` immediately. Phase 9
must check the `device` param before calling accept.

### Pitfall 2: CaptureRegistry.get() vs get_default() confusion
**What goes wrong:** Calling `get_default()` always returns the backend for `CAPTURE_DEVICE`
env var, ignoring the requested device path. Phase 9 must use the new `get(device_path)`.
**How to avoid:** Add `get(device_path)` to CaptureRegistry first, verify tests cover it,
then use it in the WebSocket handler.

### Pitfall 3: Stable ID resolution — missing vs unavailable
**What goes wrong:** When `?device=` is a stable_id that exists in `known_cameras` but the
device is currently disconnected, `last_device_path` is still present. The WebSocket should
use `last_device_path` but expect the registry `get()` to return None (device not acquired),
entering the retry loop.
**How to avoid:** Resolution returns the last known device path regardless of connection
state. The `registry.get()` returns None if the device isn't actively acquired, triggering
the retry sleep.

### Pitfall 4: conftest.py regions table schema mismatch
**What goes wrong:** Test helper in `conftest.py` creates the `regions` table without the
`entertainment_config_id` column. Any test that exercises the new LEFT JOIN will fail with
"no such column" or get wrong results.
**How to avoid:** Update `conftest.py` in Wave 0 (test infrastructure gap).

### Pitfall 5: cameras_router tests break on new CamerasResponse fields
**What goes wrong:** The existing `test_cameras_router.py` tests check for specific fields
in the response. Adding `cameras_available` and `zone_health` should not break them (extra
fields are additive), but Pydantic's `response_model=CamerasResponse` will fail at runtime
if the model change is incomplete.
**How to avoid:** Update the Pydantic model and all tests that construct `CamerasResponse`
assertions before changing the router implementation.

### Pitfall 6: usePreviewWS dependency array — stale closure
**What goes wrong:** If `device` is added to the hook's param but not to the `useEffect`
dependency array, changing the device won't reconnect the WebSocket.
**How to avoid:** Add `device` to `useEffect([enabled, device])` and ensure reconnect
logic is triggered when device changes.

---

## Code Examples

### CaptureRegistry.get() — add to capture_service.py
```python
def get(self, device_path: str) -> Optional[CaptureBackend]:
    """Return the already-acquired backend for *device_path*, or None.

    Does NOT increment reference count. Used by peek/preview callers.
    """
    with self._lock:
        return self._backends.get(device_path)
```

### Preview WebSocket — full routing logic
```python
@router.websocket("/ws/preview")
async def ws_preview(
    websocket: WebSocket,
    device: Optional[str] = Query(default=None),
):
    if device is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    registry = websocket.app.state.capture_registry
    db = websocket.app.state.db

    # Resolve stable_id to device_path if needed
    device_path: Optional[str] = None
    if device.startswith("/dev/"):
        device_path = device
    else:
        # Treat as stable_id — look up last known device path
        async with db.execute(
            "SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
            (device,),
        ) as cursor:
            row = await cursor.fetchone()
        device_path = row["last_device_path"] if row else None

    try:
        while True:
            if device_path is None:
                await asyncio.sleep(1.0)
                continue
            backend = registry.get(device_path)
            if backend is None:
                await asyncio.sleep(1.0)
                continue
            try:
                jpeg_bytes = await backend.get_jpeg()
                await websocket.send_bytes(jpeg_bytes)
                await asyncio.sleep(0.016)
            except RuntimeError:
                logger.debug("ws_preview: capture device unavailable, retrying in 1s")
                await asyncio.sleep(1.0)
    except (WebSocketDisconnect, Exception):
        logger.debug("ws_preview: client disconnected")
```

### Regions SQL — LEFT JOIN for camera_device
```sql
SELECT
    r.id,
    r.name,
    r.polygon,
    r.order_index,
    r.light_id,
    r.entertainment_config_id,
    kc.last_device_path AS camera_device
FROM regions r
LEFT JOIN camera_assignments ca
    ON ca.entertainment_config_id = r.entertainment_config_id
LEFT JOIN known_cameras kc
    ON kc.stable_id = ca.camera_stable_id
ORDER BY r.order_index
```

### usePreviewWS hook — updated signature
```typescript
export function usePreviewWS(enabled: boolean, device?: string): string | null {
  const [imgSrc, setImgSrc] = useState<string | null>(null)
  // ... existing refs ...

  useEffect(() => {
    if (!enabled || !device) {
      // Clean up any existing connection
      destroyedRef.current = true
      wsRef.current?.close()
      wsRef.current = null
      setImgSrc(null)
      return
    }

    destroyedRef.current = false
    // ...

    function connect() {
      if (destroyedRef.current) return
      const wsUrl = `ws://${location.host}/ws/preview?device=${encodeURIComponent(device!)}`
      const ws = new WebSocket(wsUrl)
      // ... rest unchanged ...
    }

    connect()
    return () => { /* cleanup unchanged */ }
  }, [enabled, device])   // ← device added to deps

  return imgSrc
}
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| `registry.get_default()` — global device only | `registry.get(device_path)` — arbitrary device | New method, must be added |
| `ws://.../ws/preview` — no param | `ws://.../ws/preview?device=...` — required param | Breaking change, D-04 |
| `regions` has no zone link | `regions.entertainment_config_id` FK to zone | Migration, D-08 |
| `CamerasResponse` — devices + identity_mode | Adds `cameras_available` + `zone_health` | Additive extension |

---

## Open Questions

1. **Should zone_health include zones with no camera assignment?**
   - What we know: D-05 says "each entry is keyed by entertainment_config_id" from the
     `camera_assignments` table
   - Recommendation: Only include zones with an explicit assignment row. Zones without an
     assignment are absent from `zone_health`. Frontend infers "not configured".
   - Confidence: MEDIUM — could go either way; this is Claude's Discretion

2. **What WebSocket close code for missing `?device=` param?**
   - RFC 6455 close codes: 1000 (normal), 1001 (going away), 1008 (policy violation),
     4000-4999 (application-defined)
   - Recommendation: Use 1008 (Policy Violation) — semantically correct for a missing
     required parameter. This is a client error in the request protocol.
   - Confidence: MEDIUM — 4000 is also defensible for app-level errors

3. **Backfill strategy for existing regions after `entertainment_config_id` migration?**
   - Recommendation: No backfill. Existing rows get NULL, LEFT JOIN returns NULL camera_device.
     This is correct behavior — old regions without a zone assignment have no camera.
   - Confidence: HIGH — matches established migration pattern in the codebase

---

## Environment Availability

Step 2.6: SKIPPED — Phase 9 is code/config-only changes with no new external dependencies.
All required tools (FastAPI, aiosqlite, Python 3.12, Node 20) are already installed and
verified by prior phases.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Backend framework | pytest (in `/tmp/hpc-venv`) |
| Config file | `Backend/pytest.ini` (or implicit) |
| Quick run command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_capture_registry.py tests/test_cameras_router.py tests/test_preview_ws.py tests/test_regions_router.py -x -q` |
| Full suite command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |
| Frontend framework | Vitest + jsdom |
| Frontend run | `cd Frontend && npx vitest run` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MCAP-02 | `?device=` routes to correct backend | unit | `pytest tests/test_preview_ws.py -x` | ✅ (skipped, needs update) |
| MCAP-02 | Missing `?device=` closes with 1008 | unit | `pytest tests/test_preview_ws.py -x` | ✅ (new test needed) |
| MCAP-02 | stable_id resolved to device_path | unit | `pytest tests/test_preview_ws.py -x` | ❌ Wave 0 |
| MCAP-02 | `registry.get()` returns None when not acquired | unit | `pytest tests/test_capture_registry.py -x` | ❌ Wave 0 |
| CAMA-04 | `GET /api/cameras` includes `zone_health` field | unit | `pytest tests/test_cameras_router.py -x` | ✅ (needs new test) |
| CAMA-04 | `zone_health` connected=True when device in scan | unit | `pytest tests/test_cameras_router.py -x` | ❌ Wave 0 |
| D-07 | `GET /api/regions` returns `camera_device` field | unit | `pytest tests/test_regions_router.py -x` | ✅ (skipped, needs update) |
| D-08 | `entertainment_config_id` migration is idempotent | unit | `pytest tests/test_database.py -x` | ✅ (needs new test) |

### Sampling Rate
- **Per task commit:** `pytest tests/test_capture_registry.py tests/test_cameras_router.py tests/test_preview_ws.py tests/test_regions_router.py -x -q`
- **Per wave merge:** `python -m pytest` (full backend) + `npx vitest run` (frontend)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_capture_registry.py` — add tests for new `CaptureRegistry.get(device_path)` method
- [ ] `tests/test_preview_ws.py` — unskip/rewrite tests for `?device=` routing (note: existing tests are all `@pytest.mark.skip` due to websocket hang issue — keep as unit-style with mocked registry, don't use TestClient websocket)
- [ ] `tests/test_regions_router.py` — update skipped tests to include `camera_device` field; update conftest region schema
- [ ] `tests/test_cameras_router.py` — add tests for `cameras_available` and `zone_health` fields
- [ ] `tests/test_database.py` — add test that `entertainment_config_id` migration is idempotent (run init_db twice on same connection)
- [ ] `tests/conftest.py` — add `entertainment_config_id TEXT` to `regions` table in `db` fixture
- [ ] `Frontend/src/hooks/usePreviewWS.test.ts` — tests for hook with device param (if file exists; otherwise new file)

---

## Project Constraints (from CLAUDE.md)

- Python 3.12 pinned — no 3.13+ features
- FastAPI >=0.115, aiosqlite >=0.20 (already installed)
- No new library introductions needed for this phase
- Backend test command: `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest`
- Frontend test command: `cd Frontend && npx vitest run`
- Use Docker for integration verification; use Playwright MCP for visual frontend verification at http://localhost:8091
- GSD workflow enforcement: all edits go through a GSD command
- No direct repo edits outside a GSD workflow

---

## Sources

### Primary (HIGH confidence)
- Direct code reading of `Backend/services/capture_service.py` — CaptureRegistry API surface confirmed (no `get()` method exists)
- Direct code reading of `Backend/routers/preview_ws.py` — current `registry.get_default()` usage identified
- Direct code reading of `Backend/routers/cameras.py` — `CamerasResponse` model, `_scan_devices()` helper
- Direct code reading of `Backend/routers/regions.py` — `list_regions()` SQL, `UpdateRegionRequest` model
- Direct code reading of `Backend/database.py` — schema (no `entertainment_config_id` on regions), migration pattern
- Direct code reading of `Backend/tests/conftest.py` — regions table missing `entertainment_config_id`
- FastAPI docs pattern for WebSocket Query params — confirmed via training knowledge (HIGH for stable API)
- RFC 6455 WebSocket close codes — 1008 is Policy Violation, correct for missing required params

### Secondary (MEDIUM confidence)
- `.planning/phases/09-preview-routing-and-region-api/09-CONTEXT.md` — locked decisions D-01 through D-11

---

## Metadata

**Confidence breakdown:**
- CaptureRegistry.get() design: HIGH — directly derived from existing get_default() pattern
- WebSocket query param routing: HIGH — standard FastAPI Query() pattern, stable API
- Schema migration pattern: HIGH — existing pattern in database.py verified by code reading
- SQL LEFT JOIN for camera_device: HIGH — straightforward JOIN on existing tables
- Frontend hook changes: HIGH — TypeScript type changes are mechanical
- Test infrastructure gaps: HIGH — confirmed by code reading of test files

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable tech, no fast-moving dependencies)
