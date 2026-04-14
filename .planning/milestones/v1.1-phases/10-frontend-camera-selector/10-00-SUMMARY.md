---
phase: 10-frontend-camera-selector
plan: "00"
subsystem: testing
tags: [vitest, react-testing-library, cameras-api, LightPanel, tdd, wave-0]

requires:
  - phase: 09-preview-routing-and-region-api
    provides: camera_device field on regions, zone_health API shape

provides:
  - cameras.test.ts with RED stubs for getCameras and putCameraAssignment
  - LightPanel.test.tsx with RED stubs for CMUI-01 zone/camera ordering and CMUI-02 option label format

affects:
  - 10-01 (cameras API implementation must satisfy cameras.test.ts)
  - 10-02 (LightPanel refactor must satisfy LightPanel.test.tsx)

tech-stack:
  added: []
  patterns:
    - "Wave 0 test scaffolding: write RED tests before implementation exists, using dynamic import() for module-not-found RED state"
    - "vi.mock('@/api/cameras') pattern established for LightPanel test isolation"

key-files:
  created:
    - Frontend/src/api/cameras.test.ts
    - Frontend/src/components/LightPanel.test.tsx
  modified: []

key-decisions:
  - "Dynamic import('./cameras') used in cameras.test.ts so test file can be created before implementation — module-not-found is the expected RED state until Plan 01"
  - "LightPanel.test.tsx mocks @/api/hue, @/api/cameras, @/api/regions to isolate rendering from network calls"

patterns-established:
  - "Wave 0 pattern: test files written before implementation using dynamic import() for deferred module resolution"
  - "LightPanel test isolation: mock all three API modules (hue, cameras, regions) to prevent network calls in component tests"

requirements-completed:
  - CMUI-01
  - CMUI-02

duration: 2min
completed: 2026-04-07
---

# Phase 10 Plan 00: Frontend Camera Selector — Wave 0 Test Stubs Summary

**RED-state test scaffolds for cameras API (getCameras/putCameraAssignment) and LightPanel camera selector UI (CMUI-01 zone ordering, CMUI-02 display_name format)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-07T19:30:47Z
- **Completed:** 2026-04-07T19:32:30Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Created `cameras.test.ts` with 4 tests covering GET /api/cameras response shape, error throwing, PUT /api/cameras/assignments request body, and error throwing
- Created `LightPanel.test.tsx` with 5 tests covering CMUI-01 (Zone heading exists, Zone appears before Camera in DOM), CMUI-02 (display_name + device_path option format), and empty states (no cameras, no selection)
- Both files intentionally in RED state — implementations don't exist yet, providing a clear behavioral contract for Plans 01 and 02

## Task Commits

1. **Task 1: Create cameras API test stubs and LightPanel component test stubs** - `c22a7ab` (test)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `Frontend/src/api/cameras.test.ts` — 4 tests for getCameras and putCameraAssignment API wrappers
- `Frontend/src/components/LightPanel.test.tsx` — 5 tests for CMUI-01 and CMUI-02 behavioral contracts

## Decisions Made

- Dynamic `import('./cameras')` used in cameras.test.ts so the test can exist before `cameras.ts` is created — module-not-found error is the expected RED state until Plan 01 Task 1 runs
- LightPanel.test.tsx mocks `@/api/hue`, `@/api/cameras`, and `@/api/regions` — matching the isolation pattern from usePreviewWS.test.ts

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Wave 0 complete — Plans 01 and 02 can reference these test files in their verify commands
- Plan 01 (cameras.ts API wrapper) must make cameras.test.ts GREEN
- Plan 02 (LightPanel refactor) must make LightPanel.test.tsx GREEN

---
*Phase: 10-frontend-camera-selector*
*Completed: 2026-04-07*
