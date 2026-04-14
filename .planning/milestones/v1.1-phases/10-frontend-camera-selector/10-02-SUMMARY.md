---
phase: 10-frontend-camera-selector
plan: 02
subsystem: ui
tags: [react, typescript, konva, camera-selector, websocket, hue-entertainment]

# Dependency graph
requires:
  - phase: 10-01
    provides: cameras.ts API layer, useCameras hook, putCameraAssignment, CamerasResponse types
  - phase: 04-frontend-canvas-editor
    provides: EditorCanvas, EditorPage, LightPanel, usePreviewWS hook
provides:
  - Zone selector (entertainment config) at top of LightPanel sidebar
  - Camera dropdown per zone with "display_name (device_path)" format
  - Live preview switching via usePreviewWS device prop
  - Auto-save camera assignment on dropdown change via putCameraAssignment
  - Disconnected badge indicator on selected camera
  - No-cameras warning banner in EditorPage
  - State lifted to EditorPage: selectedConfigId + selectedDevice
affects: [11-streaming-multi-device, future-camera-management]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - State lift pattern: selectedConfigId + selectedDevice owned by EditorPage, passed down to LightPanel and EditorCanvas as props
    - Zone-health-driven initialization: useEffect syncs selectedDevice from camerasData.zone_health when selectedConfigId changes
    - Auto-save on change: camera dropdown change immediately calls putCameraAssignment fire-and-forget

key-files:
  created: []
  modified:
    - Frontend/src/components/EditorPage.tsx
    - Frontend/src/components/EditorCanvas.tsx
    - Frontend/src/components/LightPanel.tsx
    - Frontend/src/components/LightPanel.test.tsx

key-decisions:
  - "LightPanel switches from fetchConfigs (regions) to getEntertainmentConfigs (hue) — aligns with test mock structure from Wave 0 tests"
  - "Zone-health useEffect includes onDeviceChange in dependency array (stable useState setter, safe to include)"
  - "D-02 order enforced: Zone -> Camera -> Streaming -> Lights sections in sidebar"

patterns-established:
  - "Props-down pattern: EditorPage owns camera state, LightPanel and EditorCanvas consume via props"
  - "Auto-refresh on focus: camera select onFocus calls onCamerasRefresh to trigger GET /api/cameras re-scan"

requirements-completed: [CMUI-01, CMUI-02, CMUI-03]

# Metrics
duration: 25min
completed: 2026-04-07
---

# Phase 10 Plan 02: Frontend Camera Selector Summary

**Zone selector + camera dropdown wired to EditorPage state with live preview switching and auto-save via putCameraAssignment**

## Performance

- **Duration:** 25 min
- **Started:** 2026-04-07T19:58:26Z
- **Completed:** 2026-04-07T20:23:00Z
- **Tasks:** 2 auto + 1 checkpoint (auto-approved)
- **Files modified:** 4

## Accomplishments

- State lifted to EditorPage: `selectedConfigId` and `selectedDevice` managed at page level, passed as props to LightPanel and EditorCanvas
- LightPanel refactored with Zone selector (top) -> Camera dropdown (middle) -> Streaming -> Lights (bottom) per D-02
- Camera dropdown shows "USB Capture Card (/dev/video0)" format (CMUI-02) with onFocus refresh (D-08)
- Live preview switches immediately when camera selected — EditorCanvas passes `device` to `usePreviewWS(true, device)` (CMUI-03)
- Assignment auto-saves via `putCameraAssignment` on dropdown change (D-05)
- Zone-health-driven camera initialization: selecting zone auto-updates camera from zone_health (D-06)
- Disconnected Badge indicator when selected camera goes offline (D-10)
- No-cameras banner in EditorPage when `cameras_available=false` (D-09)
- LightPanel.test.tsx passes GREEN: all 5 tests (CMUI-01 zone/camera ordering, CMUI-02 option format, empty states)

## Task Commits

Each task was committed atomically:

1. **Task 1: Lift state to EditorPage and wire EditorCanvas device prop** - `9404607` (feat)
2. **Task 2: Add zone selector, camera dropdown, and status indicators to LightPanel** - `d1080ba` (feat)
3. **Task 3: Verify camera selector end-to-end** - auto-approved (checkpoint:human-verify, auto mode)

## Files Created/Modified

- `Frontend/src/components/EditorPage.tsx` — Added useCameras hook, lifted selectedConfigId/selectedDevice state, no-cameras banner, props to LightPanel and EditorCanvas
- `Frontend/src/components/EditorCanvas.tsx` — Added `device?: string` to EditorCanvasProps, wired to `usePreviewWS(true, device)`
- `Frontend/src/components/LightPanel.tsx` — Full refactor: LightPanelProps interface, Zone+Camera sections, handleCameraChange with auto-save, disconnected badge, zone-health useEffect
- `Frontend/src/components/LightPanel.test.tsx` — Added missing mock entries (fetchConfigChannels, fetchRegions, startStreaming, stopStreaming, clearAllAssignments) and @testing-library/jest-dom import

## Decisions Made

- Switched LightPanel from `fetchConfigs` (api/regions) to `getEntertainmentConfigs` (api/hue) — both hit same endpoint but the Wave 0 test file mocks `@/api/hue`, requiring the component to import from there
- Zone-health `useEffect` depends on `[selectedConfigId, camerasData, onDeviceChange]` — `onDeviceChange` is a stable `useState` setter, safe without eslint-disable

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] LightPanel test mock missing fetchConfigChannels, fetchRegions, and other exports**
- **Found during:** Task 2 (verify LightPanel tests pass)
- **Issue:** Wave 0 test file mocked `@/api/hue` without `fetchConfigChannels` and `@/api/regions` without `fetchRegions`/`startStreaming`/`stopStreaming`/`clearAllAssignments`. Vitest throws "No export defined on mock" error.
- **Fix:** Added missing mock exports to both vi.mock() calls in LightPanel.test.tsx
- **Files modified:** `Frontend/src/components/LightPanel.test.tsx`
- **Verification:** All 5 LightPanel tests pass
- **Committed in:** d1080ba (Task 2 commit)

**2. [Rule 1 - Bug] Missing @testing-library/jest-dom import in LightPanel.test.tsx**
- **Found during:** Task 2 (verify LightPanel tests pass)
- **Issue:** Test used `toBeInTheDocument()` but no jest-dom import — "Invalid Chai property: toBeInTheDocument" error
- **Fix:** Added `import '@testing-library/jest-dom'` following the pattern established in PairingFlow.test.tsx
- **Files modified:** `Frontend/src/components/LightPanel.test.tsx`
- **Verification:** All `toBeInTheDocument()` assertions pass
- **Committed in:** d1080ba (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs in Wave 0 test file)
**Impact on plan:** Both fixes necessary for test suite correctness. No scope creep.

## Issues Encountered

- Wave 0 LightPanel.test.tsx was written expecting `getEntertainmentConfigs` from `@/api/hue` but original LightPanel used `fetchConfigs` from `@/api/regions` — resolved by switching LightPanel import to `@/api/hue` (same endpoint, cleaner alignment)

## Known Stubs

None — all camera selection UI is fully wired to real API data.

## Next Phase Readiness

- Camera selector UI complete and functional for Phase 10 v1.1 milestone
- EditorPage state management ready for streaming start/stop to consume `selectedConfigId`
- Task 3 checkpoint (human-verify) auto-approved in auto mode — visual end-to-end verification can be done manually before shipping

---
*Phase: 10-frontend-camera-selector*
*Completed: 2026-04-07*
