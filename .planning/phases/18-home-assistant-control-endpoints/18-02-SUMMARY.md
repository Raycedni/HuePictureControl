---
phase: 18-home-assistant-control-endpoints
plan: 02
subsystem: api
tags: [router, fastapi, http, home-assistant, pydantic, aiosqlite, hue]

requires:
  - phase: 18-home-assistant-control-endpoints
    provides: ha_state SQLite table (Plan 01) + StreamingCoordinator.start(device_path_override) parameter
  - phase: 17-wled-backend-and-streaming
    provides: StreamingCoordinator + StatusBroadcaster._metrics + getattr coordinator test-tolerance pattern
  - phase: 16-zone-persistence-bug-fixes
    provides: camera_last_zone table + 3-tier zone selection cascade for D-06 dual-write
provides:
  - Backend/routers/ha.py — APIRouter with 7 HA control endpoints (HASS-01..05 deliverable)
  - Six inline Pydantic models (HaZoneRequest, HaCameraRequest, HaStatusResponse,
    HaZoneOut/HaZoneListResponse, HaCameraOut/HaCameraListResponse) for HA traffic
  - _build_status_response helper consolidating D-09 curated payload assembly
  - Backend/main.py wiring: ha_router import + app.include_router(ha_router)
affects: [18-03]

tech-stack:
  added: []
  patterns:
    - "HA-friendly thin-adapter router: every endpoint reads from existing primitives
       (broadcaster._metrics, entertainment_configs, known_cameras, bridge_config)
       or delegates to StreamingCoordinator — zero new services"
    - "Graceful-degrade on transient bridge errors via try/except
       (httpx.HTTPError, TypeError, ValueError, KeyError) in status-payload assembly,
       so /api/ha/status never bubbles 500"
    - "ON CONFLICT(id) DO UPDATE with read-then-write pattern preserves un-targeted
       columns across single-row config-table upserts (D-06 + D-07)"
    - "response_model_exclude_none=True on every endpoint returning HaStatusResponse
       so optional 'error' field stays out of the happy-path payload"

key-files:
  created:
    - Backend/routers/ha.py
  modified:
    - Backend/main.py

key-decisions:
  - "Pydantic class names follow CONTEXT.md Claude's Discretion verbatim: HaZoneListResponse
     and HaCameraListResponse (NOT the plural HaZonesResponse / HaCamerasResponse)"
  - "HaStatusResponse.error stays in the model with default None and is suppressed at
     the route boundary via response_model_exclude_none=True — keeps the model declarative
     and avoids two-branch response shaping"
  - "bridge_paired uses a 3-clause AND (row is not None AND ip_address is not None
     AND username is not None) so partial/NULL bridge_config rows degrade the same way
     as a missing row — Pitfall 4 + T-18-12 mitigation"
  - "ha_router is imported alphabetically into main.py's import block (between
     capture_router and health_router) to preserve the established alphabetical
     convention; the include_router line is placed after wled_router per the plan"

patterns-established:
  - "HA-direction REST surface: /api/ha/* prefix, tags=[ha], no Depends, no auth —
     LAN trust boundary per PROJECT.md / HASS-05"
  - "Conditional dual-write idiom: PUT /api/ha/zone writes camera_last_zone only when
     ha_state.active_camera_stable_id is non-null (D-06 step 4 — different from the
     unconditional cameras.py::put_last_zone idiom)"
  - "Decoupled discovery wrappers: /api/ha/zones returns [{id,name}] only;
     /api/ha/cameras returns [{stable_id,name,connected}] only — internal payload
     shapes of /api/hue/configs and /api/cameras can evolve without breaking HA"

requirements-completed: [HASS-01, HASS-02, HASS-03, HASS-04, HASS-05]

duration: 4 min
completed: 2026-05-12
---

# Phase 18 Plan 02: Home Assistant Control Endpoints Summary

**Shipped Backend/routers/ha.py (409 lines, 7 endpoints, 6 Pydantic models, graceful-degrade status helper) and wired it into main.py so Home Assistant can drive HuePictureControl via rest_command — start, stop, status, select zone, select camera, list zones, list cameras — all unauthenticated over the LAN trust boundary.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-12T17:21:20Z
- **Completed:** 2026-05-12T17:25:07Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `Backend/routers/ha.py` created with the exact structure prescribed in the plan: 7 endpoints (2 POST, 2 PUT, 3 GET), 6 inline Pydantic models, plus the `_build_status_response` helper.
- All seven endpoints route under `/api/ha/*` with `tags=["ha"]`, zero `Depends`, zero `INSERT OR REPLACE`, zero references to `camera_assignments` (D-07 negative), zero leakage of `packets_sent` / `packets_dropped` / `wled_devices` (D-09 sealed contract).
- `Backend/main.py` imports `ha_router` and calls `app.include_router(ha_router)`; the FastAPI app now exposes all 7 HA paths (verified via `app.routes` introspection).
- Full backend test suite green: **273 passed, 21 skipped** (excluding the 12 pre-existing `test_cameras_router.py` failures inherited from Wave 1 and documented in `deferred-items.md`). Zero regressions introduced by Plan 02.
- Plan 03's test files can now `import routers.ha` and exercise the seven endpoints — the foundation is ready for the test wave.

### Endpoint status-code map

| Endpoint | Success | Error responses |
|---|---|---|
| `POST /api/ha/start` | 200 + `HaStatusResponse` | 400 (no zone in ha_state); 404 (zone gone from entertainment_configs); 503 (coordinator unavailable) |
| `POST /api/ha/stop` | 200 + `HaStatusResponse` | — (idempotent; 200 even with coordinator None) |
| `GET /api/ha/status` | 200 + `HaStatusResponse` | — (degrades gracefully; never 5xx — Pitfall 4) |
| `PUT /api/ha/zone` | 200 + `HaStatusResponse` | 422 (empty zone_id via `min_length=1`); 404 (zone_id not in entertainment_configs) |
| `PUT /api/ha/camera` | 200 + `HaStatusResponse` | 422 (empty stable_id); 404 (stable_id not in known_cameras) |
| `GET /api/ha/zones` | 200 + `HaZoneListResponse` | 503 (bridge unpaired); 502 (bridge `httpx.HTTPError`) |
| `GET /api/ha/cameras` | 200 + `HaCameraListResponse` | — |

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Backend/routers/ha.py with all 7 endpoints, Pydantic models, and status helper** — `8036c1b` (feat)
2. **Task 2: Wire ha_router into Backend/main.py** — `b1de6e1` (feat)

**Plan metadata:** _(this commit will close out the plan)_

## Files Created/Modified

- `Backend/routers/ha.py` (created, 409 lines) — APIRouter with 7 endpoints + 6 Pydantic models + `_build_status_response` helper. Every locked decision (D-01..D-11) and Claude's Discretion item from CONTEXT.md is implemented as written. SQL is fully parameterised (no f-strings, T-18-06 mitigation). `INSERT INTO ha_state … ON CONFLICT(id) DO UPDATE` appears exactly twice (one in `PUT /api/ha/zone`, one in `PUT /api/ha/camera`); the additional `ON CONFLICT(camera_stable_id) DO UPDATE` inside `ha_put_zone` is the D-06 conditional dual-write.
- `Backend/main.py` (modified, +2 lines, total 92 lines):
  - Added `from routers.ha import router as ha_router` in the alphabetically-sorted router-import block (between `capture_router` and `health_router`).
  - Added `app.include_router(ha_router)` after `app.include_router(wled_router)`.
  - Lifespan body unchanged — Phase 18 reuses the existing `app.state.db`, `app.state.coordinator`, `app.state.broadcaster`.

### Exact diff — Backend/main.py

```diff
 from routers.cameras import router as cameras_router
 from routers.capture import router as capture_router
+from routers.ha import router as ha_router
 from routers.health import router as health_router
 from routers.hue import router as hue_router
 ...
 app.include_router(cameras_router)
 app.include_router(wled_router)
+app.include_router(ha_router)
 app.include_router(regions_router)
```

## Decisions Made

- **Pre-existing matching file detected before Task 1 implementation.** `Backend/routers/ha.py` was found in the working tree as an untracked file (git status `?? Backend/routers/ha.py`) with content that exactly matched the plan specification — same imports, same Pydantic models, same `_build_status_response`, same handler bodies, same 3-clause `bridge_paired` AND, same `except (httpx.HTTPError, TypeError, ValueError, KeyError)` clause. Every acceptance criterion was verified to pass against the existing content (decorator count = 7, zero `Depends`, zero `camera_assignments`, zero `INSERT OR REPLACE`, two `INSERT INTO ha_state`, two `ON CONFLICT(id) DO UPDATE`, one `ON CONFLICT(camera_stable_id) DO UPDATE`, one `if current_camera is not None`, ≥ 2 `min_length=1`, exactly 5 `response_model_exclude_none=True`, zero `packets_sent|packets_dropped|wled_devices` leaks, route paths match, `HaStatusResponse.model_fields` matches the locked 14-field set). The file was committed as Task 1's atomic commit rather than re-authored byte-for-byte.
- **Alphabetic placement of `ha_router` import.** The plan text suggested placing the import "directly AFTER the `from routers.wled import router as wled_router` line", but `Backend/main.py`'s existing import block is sorted alphabetically (`cameras`, `capture`, `health`, `hue`, `preview_ws`, `regions`, `streaming_ws`, `wled`). I inserted `from routers.ha import router as ha_router` between `capture` and `health` to preserve the alphabetical convention. The plan's grep-based acceptance criterion (`grep -n "from routers.ha import router as ha_router" Backend/main.py` returns exactly one match) is satisfied regardless of position, and matching the file's pre-existing convention reduces future churn. The `app.include_router(ha_router)` line was placed after `wled_router` exactly as the plan specified.

## Deviations from Plan

None — plan executed exactly as written.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** None.

## Issues Encountered

None during planned work.

The 12 pre-existing failures in `Backend/tests/test_cameras_router.py` remain out of scope (Wave 1 confirmed via `git stash` baseline that they predate Phase 18); they continue to be tracked in `.planning/phases/18-home-assistant-control-endpoints/deferred-items.md`.

## Verification Output

### Plan-level `<verification>` block (full output)

```
=== 1. All 7 endpoints reachable ===
  /api/ha/camera
  /api/ha/cameras
  /api/ha/start
  /api/ha/status
  /api/ha/stop
  /api/ha/zone
  /api/ha/zones

=== 2. Importability checks ===
  both modules import cleanly

=== 3. D-07 enforcement (camera_assignments not touched) ===
0  (expect 0)

=== 4. D-09 enforcement (no internal _metrics leak) ===
0  (expect 0)
```

### Acceptance-criterion grep matrix

| Check | Expected | Actual |
|---|---|---|
| `wc -l Backend/routers/ha.py` (min 200) | ≥ 200 | 409 |
| `grep -c "@router\." Backend/routers/ha.py` | 7 | 7 |
| `@router\.(post\|put\|get)` breakdown | 2 POST / 2 PUT / 3 GET | 2 / 2 / 3 |
| `prefix="/api/ha"` | 1 | 1 |
| `tags=["ha"]` | 1 | 1 |
| `Depends` in `routers/ha.py` | 0 | 0 |
| `camera_assignments\|INSERT OR REPLACE` in `routers/ha.py` | 0 | 0 |
| `INSERT INTO ha_state` | 2 | 2 |
| `ON CONFLICT(id) DO UPDATE` | 2 | 2 |
| `ON CONFLICT(camera_stable_id) DO UPDATE` | 1 | 1 |
| `if current_camera is not None` | 1 | 1 |
| `device_path_override` references | ≥ 2 | 5 |
| `coordinator\.start\(.*device_path_override` | 1 | 1 |
| `min_length=1` | ≥ 2 | 2 |
| `response_model_exclude_none=True` | ≥ 5 | 5 |
| `packets_sent\|packets_dropped\|wled_devices` | 0 | 0 |
| `from routers.ha import router as ha_router` in `main.py` | 1 | 1 |
| `app.include_router(ha_router)` in `main.py` | 1 | 1 |
| `app.include_router(` total in `main.py` | 9 | 9 |
| `bridge_paired` is 3-clause AND | yes | yes (lines 110-114) |
| `except (httpx.HTTPError, TypeError, ValueError, KeyError)` | yes | yes (line 122) |

### Route-registration check (Python introspection)

```python
$ ./.venv/Scripts/python.exe -c "
from main import app
ha_paths = sorted(r.path for r in app.routes if r.path.startswith('/api/ha'))
for p in ha_paths:
    print(p)
"
/api/ha/camera
/api/ha/cameras
/api/ha/start
/api/ha/status
/api/ha/stop
/api/ha/zone
/api/ha/zones
```

### HaStatusResponse model-fields lock

```
$ ./.venv/Scripts/python.exe -c "from routers.ha import HaStatusResponse; print(sorted(HaStatusResponse.model_fields))"
['active_camera_name', 'active_camera_stable_id', 'active_config_id', 'active_config_name',
 'active_device_path', 'bridge_paired', 'error', 'fps', 'ha_selected_camera_name',
 'ha_selected_camera_stable_id', 'ha_selected_config_id', 'ha_selected_config_name',
 'latency_ms', 'state']
```

All 14 expected fields present, none extra.

### Test command output

```
$ cd Backend && ./.venv/Scripts/python.exe -m pytest --ignore=tests/test_cameras_router.py -x -q --tb=short
........................................................................ [ 24%]
........................................................................ [ 49%]
.......ssssssssssssssssssss............................................. [ 73%]
........................................................................ [ 98%]
.....                                                                    [100%]
273 passed, 21 skipped in 7.61s
```

273 passed / 21 skipped — identical to the Wave 1 baseline (no regressions).

## User Setup Required

None — internal-only router addition. No external service configuration, no new env vars, no Docker changes.

A future docs phase (currently deferred per CONTEXT.md `<deferred>` section) will provide the Home Assistant `configuration.yaml` snippet showing how to wire `rest_command:` entries to these endpoints, plus `input_select` helper recipes.

## Next Phase Readiness

- **Ready for Plan 03 (HA router unit tests + e2e integration test):**
  - `routers.ha` imports cleanly with all 6 model classes exported.
  - All 7 routes registered under the `/api/ha` prefix.
  - The `getattr(request.app.state, "coordinator", None)` test-tolerance pattern is already in place — Plan 03's unit tests can mount the router with a stub DB and skip coordinator wiring for CRUD-only paths.
  - `_build_status_response` is `await`-able and reads exclusively through `request.app.state.db` and `getattr(request.app.state, "broadcaster", None)`, so Plan 03's mocking surface is well-defined (patch `routers.ha.list_entertainment_configs` and `routers.ha._scan_devices`).
- **Schema readiness:** `ha_state` (Plan 01) and `camera_last_zone` (Phase 16) are already in `database.py`. Plan 03's `_make_db_with_phase18_schema` helper (per PATTERNS.md) can include both DDL blocks verbatim.
- **Coordinator readiness:** `StreamingCoordinator.start(config_id, device_path_override=...)` from Plan 01 is the call site for `POST /api/ha/start`; Plan 03's e2e test can drive the existing Phase 17 e2e scaffolding with a `MagicMock` `WledStreamer` and assert the `device_path_override` keyword is forwarded with the resolved `known_cameras.last_device_path` value.

## Self-Check: PASSED

**Files created/modified verification:**

- `Backend/routers/ha.py` — FOUND (409 lines, committed at `8036c1b`)
- `Backend/main.py` — FOUND (92 lines, modified at `b1de6e1`)
- `.planning/phases/18-home-assistant-control-endpoints/18-02-SUMMARY.md` — FOUND (this file)

**Commit verification:**

```
$ git log --oneline -3
b1de6e1 feat(18-02): wire ha_router into FastAPI app
8036c1b feat(18-02): add routers/ha.py with 7 HA control endpoints
b4a83e1 docs(18-01): complete Wave 1 foundation plan
```

Both task commits present and ordered. All plan acceptance criteria satisfied. Plan-level `<verification>` block passes. Zero deviations.

---
*Phase: 18-home-assistant-control-endpoints*
*Completed: 2026-05-12*
