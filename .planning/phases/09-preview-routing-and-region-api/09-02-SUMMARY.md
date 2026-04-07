---
phase: 09-preview-routing-and-region-api
plan: 02
subsystem: api
tags: [fastapi, aiosqlite, typescript, react, websocket, camera, regions]

# Dependency graph
requires:
  - phase: 09-01
    provides: preview WebSocket with ?device= param routing; CaptureRegistry.get() peek method
  - phase: 07-device-enumeration-and-schema
    provides: known_cameras and camera_assignments tables; stable device identity
provides:
  - cameras_available bool and zone_health list in GET /api/cameras
  - camera_device derived field in GET /api/regions via LEFT JOIN
  - entertainment_config_id migration on regions table (idempotent)
  - update_region writes entertainment_config_id to regions table
  - Frontend Region interface with camera_device: string | null
  - usePreviewWS hook with optional device param and ?device= URL building
affects: [10-frontend-camera-selector]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - LEFT JOIN camera_assignments + known_cameras for derived camera_device field
    - Idempotent ALTER TABLE migrations with try/except pattern
    - ZoneHealth model: per-zone connected/disconnected status from camera_assignments

key-files:
  created:
    - Backend/tests/test_database.py (extended with idempotent migration test)
  modified:
    - Backend/database.py
    - Backend/routers/cameras.py
    - Backend/routers/regions.py
    - Backend/tests/test_cameras_router.py
    - Backend/tests/test_regions_router.py
    - Frontend/src/api/regions.ts
    - Frontend/src/hooks/usePreviewWS.ts

key-decisions:
  - "camera_device is read-only derived field — computed via LEFT JOIN, not stored; write path uses entertainment_config_id column"
  - "update_region now writes entertainment_config_id to regions table (previously only wrote to light_assignments)"
  - "usePreviewWS stays disconnected (returns null) when device param is undefined — Phase 10 call sites will wire device"

patterns-established:
  - "LEFT JOIN camera_assignments ca ON ca.entertainment_config_id = r.entertainment_config_id + LEFT JOIN known_cameras kc ON kc.stable_id = ca.camera_stable_id — use for any region query needing camera info"
  - "Idempotent ALTER TABLE: try/except wrapping each migration; safe to run init_db multiple times on same DB"

requirements-completed: [MCAP-02, CAMA-04]

# Metrics
duration: 18min
completed: 2026-04-07
---

# Phase 09 Plan 02: cameras zone_health + regions camera_device + Frontend types Summary

**Extended cameras API with per-zone health status, regions API with LEFT JOIN camera_device derivation, idempotent entertainment_config_id migration, and frontend TypeScript types updated for Phase 10 camera selector**

## Performance

- **Duration:** 18 min
- **Started:** 2026-04-07T18:40:00Z
- **Completed:** 2026-04-07T18:58:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Added ZoneHealth model and cameras_available field to GET /api/cameras with real-time connected/disconnected status per assignment
- Added entertainment_config_id migration to regions table and updated list_regions with LEFT JOIN to derive camera_device
- Updated frontend Region interface with camera_device field and usePreviewWS to accept optional device param with ?device= URL encoding

## Task Commits

Each task was committed atomically:

1. **Task 1: DB migration + cameras zone_health + regions camera_device join** - `678a911` (feat)
2. **Task 2: Frontend TypeScript type updates and usePreviewWS device param** - `e7e6c72` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified

- `Backend/database.py` - Added idempotent entertainment_config_id migration after light_id migration
- `Backend/routers/cameras.py` - Added ZoneHealth model, cameras_available + zone_health fields to CamerasResponse, zone_health query in list_cameras
- `Backend/routers/regions.py` - Updated list_regions with LEFT JOIN for camera_device, update_region writes entertainment_config_id, create/update return camera_device: null
- `Backend/tests/test_cameras_router.py` - Added cameras_available true/false tests and zone_health connected/disconnected tests
- `Backend/tests/test_regions_router.py` - Added TestListRegionsCameraDevice class with 3 tests: camera_device via JOIN, null when no assignment, update writes entertainment_config_id
- `Backend/tests/test_database.py` - Added test_entertainment_config_id_migration_idempotent
- `Frontend/src/api/regions.ts` - Added camera_device: string | null to Region interface
- `Frontend/src/hooks/usePreviewWS.ts` - Added device?: string param, guard on !device, ?device= URL param, updated dependency array

## Decisions Made

- camera_device is a read-only derived field computed via LEFT JOIN; it is not stored directly on the regions table. The write path uses entertainment_config_id, and the join derives the current device path from known_cameras.
- update_region now writes entertainment_config_id to the regions table directly (previously entertainment_config_id was only written to light_assignments). This enables the camera_device derivation join.
- usePreviewWS remains disconnected (returns null) when device param is undefined. This is intentional for Phase 9 — existing call sites (EditorCanvas, PreviewPage) continue to work without a device param, and Phase 10 will wire actual device values.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- GET /api/cameras returns cameras_available and zone_health — ready for Phase 10 camera selector UI
- GET /api/regions returns camera_device — ready for Phase 10 to display current assignment
- Frontend Region interface and usePreviewWS hook are Phase 10 ready
- EditorCanvas.tsx and PreviewPage.tsx still call usePreviewWS without device param (correct Phase 9 behavior — Phase 10 will update these call sites)

---
*Phase: 09-preview-routing-and-region-api*
*Completed: 2026-04-07*
