---
phase: 19-wled-strip-paint-ui
plan: 07
subsystem: api
tags: [phase-19, wled, frontend-api, typescript, wave-2]

# Dependency graph
requires:
  - phase: 19-02
    provides: backend channel/assignment/orientation endpoints that these clients call

provides:
  - WledOrientation type (5-value union: auto, horizontal-LTR/RTL, vertical-TTB/BTT)
  - WledChannel interface (id, device_id, name, start_led, end_led)
  - WledChannelsResponse and WledAssignment interfaces
  - listWledChannels — GET /api/wled/devices/{id}/channels
  - createWledChannel — POST /api/wled/devices/{id}/channels
  - updateWledChannel — PUT /api/wled/devices/{id}/channels/{cid}
  - resizeWledChannelBoundary — PUT /api/wled/devices/{id}/channels/boundary
  - deleteWledChannel — DELETE /api/wled/devices/{id}/channels/{cid}
  - upsertWledAssignment — PUT /api/wled/assignments
  - deleteWledAssignment — DELETE /api/wled/assignments
  - patchRegionOrientation — PATCH /api/wled/regions/{rid}/orientation?config=
  - listWledAssignments — GET /api/wled/assignments?config=

affects:
  - 19-08 (WledStripPainter, LightPanel WLED section, OrientationSegmentedControl)
  - 19-09 (EditorCanvas drop branch — upsertWledAssignment, deleteWledAssignment)
  - 19-10 (popover — listWledAssignments to hydrate store)
  - 19-11 (integration wiring)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "All path params wrapped in encodeURIComponent (T-19-09 threat mitigation)"
    - "snake_case field names in TypeScript interfaces to mirror Pydantic response JSON"
    - "WledApiError re-thrown for every non-ok response — same as Phase 17 device CRUD"

key-files:
  created: []
  modified:
    - Frontend/src/api/wled.ts

key-decisions:
  - "Keep 8 functions total (7 planned + listWledAssignments) — popover (Plan 19-10) needs it for store hydration on EditorCanvas mount"
  - "snake_case field names in TypeScript interfaces for direct JSON parity with backend Pydantic models"
  - "resizeWledChannelBoundary fires once on drag end only, never per onDragMove — documented in JSDoc"

patterns-established:
  - "Path param encoding: every dynamic segment uses encodeURIComponent regardless of expected content"
  - "Phase 19 channel API appended to existing Phase 17 wled.ts module rather than split across files"

requirements-completed: [WMAP-01, WMAP-04, WMAP-05]

# Metrics
duration: 5min
completed: 2026-05-14
---

# Phase 19 Plan 07: WLED API Client Extension Summary

**8 typed fetch functions + 3 new interfaces appended to api/wled.ts covering channel CRUD, assignment upsert/delete, and per-region orientation PATCH with full encodeURIComponent path encoding**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-14T13:06:21Z
- **Completed:** 2026-05-14T13:11:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Extended `Frontend/src/api/wled.ts` with 3 new exported types and 8 new async client functions
- TypeScript compiles with `tsc --noEmit` — exit 0, no errors
- Full vitest suite passes: 65 tests in 9 files, no regressions
- All path parameters wrapped in `encodeURIComponent` per T-19-09 threat mitigation
- Phase 17 device CRUD functions (`getWledDevices`, `addWledDevice`, `deleteWledDevice`, `setWledDeviceEnabled`, `scanWledDevices`) remain byte-for-byte unchanged

## Task Commits

1. **Task 1: Append channel + assignment + orientation types and 8 client functions** - `387cf5e` (feat)

**Plan metadata:** committed below with SUMMARY.md

## Files Created/Modified

- `Frontend/src/api/wled.ts` — Appended 183 lines: WledOrientation type, WledChannel/WledChannelsResponse/WledAssignment interfaces, and 8 async functions

## New Exports Added

| Export | Kind | Endpoint |
|--------|------|----------|
| `WledOrientation` | type | — |
| `WledChannel` | interface | — |
| `WledChannelsResponse` | interface | — |
| `WledAssignment` | interface | — |
| `listWledChannels` | function | GET /api/wled/devices/{id}/channels |
| `createWledChannel` | function | POST /api/wled/devices/{id}/channels |
| `updateWledChannel` | function | PUT /api/wled/devices/{id}/channels/{cid} |
| `resizeWledChannelBoundary` | function | PUT /api/wled/devices/{id}/channels/boundary |
| `deleteWledChannel` | function | DELETE /api/wled/devices/{id}/channels/{cid} |
| `upsertWledAssignment` | function | PUT /api/wled/assignments |
| `deleteWledAssignment` | function | DELETE /api/wled/assignments |
| `patchRegionOrientation` | function | PATCH /api/wled/regions/{rid}/orientation?config= |
| `listWledAssignments` | function | GET /api/wled/assignments?config= |

## Decisions Made

- Retained `listWledAssignments` as the 8th function (plan noted 7 planned + 1 extra) — Plan 19-10 popover needs it to hydrate `useRegionStore.wledAssignments` on EditorCanvas mount
- Used snake_case field names in TypeScript interfaces to match Pydantic JSON response directly — no camelCase transform layer needed

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The worktree lacked `node_modules/` so `npm install` ran first before `tsc --noEmit` and `vitest run`. This is normal for a fresh worktree.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plans 19-08, 19-09, 19-10, 19-11 can now import all typed functions without further API plumbing
- Phase 17 device CRUD path remains green (65 tests pass)

---
*Phase: 19-wled-strip-paint-ui*
*Completed: 2026-05-14*
