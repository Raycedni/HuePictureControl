---
phase: 04-frontend-canvas-editor
plan: "04"
subsystem: ui
tags: [react, konva, drag-and-drop, hue, streaming, light-assignment]

# Dependency graph
requires:
  - phase: 04-03
    provides: EditorCanvas with wrapper div onDrop placeholder, RegionPolygon, EditorPage layout
  - phase: 04-01
    provides: regions API with light_id support and updateRegion endpoint
provides:
  - LightPanel component with draggable light list, config selector, and start/stop toggle
  - Drag-to-assign interaction: drop light from panel onto canvas region assigns it via updateRegion API
  - Region polygon shows assigned light name as yellow label at centroid
  - Complete end-to-end editor workflow: draw, edit, delete, assign lights, stream, persist
affects:
  - phase: 05-segment-support
  - phase: 06-polished-ui

# Tech tracking
tech-stack:
  added: []
  patterns:
    - drag-and-drop via HTML5 dataTransfer API (no library needed)
    - Konva setPointersPositions to bridge DOM drag events to canvas coordinate system
    - lightMap built from getLights() on mount to resolve light IDs to names for labels

key-files:
  created:
    - Frontend/src/components/LightPanel.tsx
  modified:
    - Frontend/src/components/EditorCanvas.tsx
    - Frontend/src/components/EditorPage.tsx
    - Frontend/src/components/RegionPolygon.tsx

key-decisions:
  - "onDrop handler lives on EditorCanvas wrapper div (not EditorPage) because stageRef.current.setPointersPositions(e) requires access to stageRef local to EditorCanvas"
  - "lightMap built from getLights() on mount in EditorCanvas to show light names in polygon labels without storing name on region model"
  - "HTML5 dataTransfer used for drag-and-drop (no library): lightId and lightName passed via setData/getData"
  - "RegionPolygon shows yellow Text label when light_id assigned; dim region name when unassigned"

patterns-established:
  - "Drag-to-canvas pattern: HTML5 drag on panel item, setPointersPositions in canvas onDrop, pointInPolygon hit-test, updateRegion API call"
  - "LightPanel reads isStreaming from useStatusStore; calls startStreaming/stopStreaming from regions API"

requirements-completed: [REGN-03, UI-05]

# Metrics
duration: ~15min
completed: 2026-03-24
---

# Phase 4 Plan 04: LightPanel with Drag-to-Assign Light Assignment Summary

**Draggable light panel with HTML5 drag-and-drop to assign Hue lights to canvas regions, with start/stop streaming toggle completing the full interactive editor workflow**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-24T22:30:00Z
- **Completed:** 2026-03-24T22:43:00Z
- **Tasks:** 2 (1 auto + 1 hardware checkpoint approved)
- **Files modified:** 4

## Accomplishments
- Created LightPanel.tsx with draggable light list, entertainment config selector, and start/stop streaming toggle
- Wired onDrop handler in EditorCanvas using Konva setPointersPositions + pointInPolygon hit-test + updateRegion API call
- Updated RegionPolygon.tsx to show assigned light name as yellow Konva Text label at polygon centroid
- Hardware verification approved: full editor workflow confirmed working end-to-end including draw, edit, delete, assign lights, stream, and persist across refresh

## Task Commits

Each task was committed atomically:

1. **Task 1: Create LightPanel and wire drag-to-assign to EditorCanvas** - `b0590b9` (feat)
2. **Task 2: Verify complete canvas editor end-to-end** - checkpoint approved by user (no code commit)

**Plan metadata:** (docs commit to follow)

## Files Created/Modified
- `Frontend/src/components/LightPanel.tsx` - New: draggable light list panel, config selector, start/stop streaming toggle, currently-assigned section
- `Frontend/src/components/EditorCanvas.tsx` - Added onDrop handler with setPointersPositions, pointInPolygon hit-test, updateRegion API; fetches lightMap on mount
- `Frontend/src/components/EditorPage.tsx` - Replaced "Light Panel" placeholder with `<LightPanel />`
- `Frontend/src/components/RegionPolygon.tsx` - Added yellow Text label for assigned light name, dim region name when unassigned

## Decisions Made
- onDrop handler placed in EditorCanvas (not EditorPage) because `stageRef.current.setPointersPositions(e)` requires the stageRef that is local to EditorCanvas
- lightMap built from getLights() on mount in EditorCanvas to resolve light IDs to display names without adding a name field to the region model
- HTML5 dataTransfer API used for drag-and-drop (lightId, lightName) — no additional drag library needed
- RegionPolygon uses Konva Text node at polygon centroid for the light label, colored yellow for visibility

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None — TypeScript compiled cleanly, tests passed, and hardware verification confirmed all 17 verification steps.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 4 (frontend-canvas-editor) is fully complete: draw, edit, delete, assign lights, stream, persist
- Phase 5 (segment support) can now build on the complete editor foundation with light assignment in place
- LightPanel's config selector and start/stop controls are already wired — segment count display (BRDG-04) is the main Phase 5 addition

---
*Phase: 04-frontend-canvas-editor*
*Completed: 2026-03-24*

## Self-Check: PASSED

- FOUND: Frontend/src/components/LightPanel.tsx
- FOUND: Frontend/src/components/EditorCanvas.tsx
- FOUND: Frontend/src/components/EditorPage.tsx
- FOUND: Frontend/src/components/RegionPolygon.tsx
- FOUND: commit b0590b9
