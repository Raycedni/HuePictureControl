---
phase: 04-frontend-canvas-editor
plan: 01
subsystem: api
tags: [fastapi, websocket, sqlite, aiosqlite, opencv, regions, crud]

# Dependency graph
requires:
  - phase: 03.1-auto-mapping-from-entertainment-config
    provides: regions table, auto-map endpoint, GET /api/regions
provides:
  - POST /api/regions/ - create region with UUID id, polygon, and optional light_id
  - PUT /api/regions/{id} - update polygon and/or light_id with 404 on missing
  - DELETE /api/regions/{id} - remove region and cleanup light_assignments
  - GET /api/regions/ now includes light_id field (null if unassigned)
  - /ws/preview WebSocket endpoint sending binary JPEG frames at ~10fps
  - light_id TEXT column on regions table with ALTER TABLE migration
affects:
  - 04-02-canvas-editor-frontend (consumes all new endpoints)
  - 04-03-light-assignment-ui (light_id field on regions required)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - TDD (RED/GREEN) for all new endpoints
    - Dynamic SQL SET clause construction for partial updates
    - ALTER TABLE migration with try/except for safe column addition
    - WebSocket binary send (send_bytes) for JPEG streaming
    - RuntimeError retry loop in WebSocket to handle unavailable capture device

key-files:
  created:
    - Backend/routers/preview_ws.py
    - Backend/tests/test_preview_ws.py
  modified:
    - Backend/database.py
    - Backend/routers/regions.py
    - Backend/main.py
    - Backend/tests/test_regions_router.py

key-decisions:
  - "ALTER TABLE migration wraps in try/except (not OperationalError specifically) for portability across aiosqlite versions"
  - "PUT /api/regions/{id} uses dynamic SET clause — only non-None fields from UpdateRegionRequest are applied"
  - "DELETE /api/regions/{id} also cleans up light_assignments for the deleted region to avoid orphaned rows"
  - "/ws/preview uses quality 70 JPEG (vs 85 in capture snapshot) for streaming speed"
  - "WebSocket keep-alive via RuntimeError retry (1s sleep) rather than closing connection when device unavailable"

patterns-established:
  - "CRUD router pattern: POST returns 201, PUT returns 200, DELETE returns 204 (Response(status_code=204))"
  - "WebSocket streaming pattern: accept() -> loop(get_frame -> encode -> send_bytes -> sleep) -> except WebSocketDisconnect"

requirements-completed: [REGN-04, REGN-05, REGN-06]

# Metrics
duration: 3min
completed: 2026-03-24
---

# Phase 04 Plan 01: Backend Region CRUD and WebSocket Preview Summary

**Region CRUD API (POST/PUT/DELETE) with light_id field, plus /ws/preview WebSocket for binary JPEG streaming at 10fps**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-24T21:24:15Z
- **Completed:** 2026-03-24T21:29:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Extended regions router with full CRUD: POST creates regions with UUID id, PUT does partial updates, DELETE removes with light_assignments cleanup
- Added light_id TEXT column to regions DB schema with backwards-compatible ALTER TABLE migration
- Created /ws/preview WebSocket endpoint that streams binary JPEG frames from capture device at ~10fps
- 11 new tests for CRUD endpoints, 4 new tests for preview WebSocket (all pass, 153 total in suite)

## Task Commits

Each task was committed atomically (TDD with separate RED/GREEN commits):

1. **Task 1 RED: Region CRUD tests** - `9222a46` (test)
2. **Task 1 GREEN: Region CRUD implementation** - `7a6768d` (feat)
3. **Task 2 RED: /ws/preview tests** - `2486d58` (test)
4. **Task 2 GREEN: /ws/preview implementation** - `e3ac667` (feat)

## Files Created/Modified
- `Backend/database.py` - Added light_id TEXT column to regions table + ALTER TABLE migration
- `Backend/routers/regions.py` - Added POST/PUT/DELETE endpoints, CreateRegionRequest/UpdateRegionRequest models, updated GET to include light_id
- `Backend/routers/preview_ws.py` - NEW: WebSocket /ws/preview endpoint with binary JPEG streaming
- `Backend/main.py` - Added import and include_router for preview_ws_router
- `Backend/tests/test_regions_router.py` - Added 11 new tests for CRUD (TestCreateRegion, TestUpdateRegion, TestDeleteRegion, TestListRegionsIncludesLightId)
- `Backend/tests/test_preview_ws.py` - NEW: 4 tests for /ws/preview binary streaming

## Decisions Made
- ALTER TABLE migration wraps in generic `except Exception` (not specific OperationalError) for portability across aiosqlite versions
- PUT endpoint only updates non-None fields from UpdateRegionRequest — fully partial update semantics
- DELETE also cleans up light_assignments rows to prevent orphaned data
- JPEG quality 70 (vs 85 in capture snapshot) for preview streaming to prioritize throughput over quality

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All backend APIs are ready for the frontend canvas editor (04-02)
- POST /api/regions/, PUT /api/regions/{id}, DELETE /api/regions/{id} are live
- GET /api/regions/ returns light_id in each region object
- /ws/preview streams binary JPEG and is wired into the running app

---
*Phase: 04-frontend-canvas-editor*
*Completed: 2026-03-24*
