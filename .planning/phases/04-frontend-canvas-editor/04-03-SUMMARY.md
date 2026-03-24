---
phase: 04-frontend-canvas-editor
plan: "03"
subsystem: frontend
tags: [react, konva, react-konva, zustand, use-image, typescript, canvas, polygon, drawing]
dependency_graph:
  requires:
    - phase: 04-02
      provides: useRegionStore, usePreviewWS, geometry utils, Region API CRUD
  provides:
    - EditorPage (70/30 canvas + light panel layout with ResizeObserver)
    - DrawingToolbar (Rectangle/Polygon/Select/Delete mode buttons)
    - EditorCanvas (Konva Stage with live camera preview + drawing tools)
    - RegionPolygon (interactive polygon with vertex handles and body drag)
  affects:
    - Frontend/src/App.tsx (editor tab now renders EditorPage)
    - Phase 04-04 (LightPanel wires into EditorPage right panel)
tech_stack:
  added: []
  patterns:
    - Konva Stage with 3 layers (preview listening=false, regions, handles) for correct event separation
    - Group position drift prevention by resetting e.target.position({x:0, y:0}) after dragEnd
    - Debounced auto-save (400ms timeout via ref) on vertex/body drag
    - handleEditorDelete as standalone async function for sharing between keyboard and toolbar
    - ResizeObserver on container div for responsive canvas sizing maintaining 4:3 aspect ratio
key_files:
  created:
    - Frontend/src/components/DrawingToolbar.tsx
    - Frontend/src/components/EditorCanvas.tsx
    - Frontend/src/components/EditorPage.tsx
    - Frontend/src/components/RegionPolygon.tsx
  modified:
    - Frontend/src/App.tsx (replaced editor placeholder with EditorPage)
key_decisions:
  - "handleEditorDelete exported as standalone function from EditorCanvas so EditorPage toolbar and keyboard shortcut share the same logic without circular refs"
  - "Canvas aspect ratio uses 4:3 (height = width * 3/4) to match 640x480 capture resolution rather than 16:9"
  - "Task 1 and Task 2 implemented in single commit since RegionPolygon is a direct compile dependency of EditorCanvas"
patterns-established:
  - "Konva Group draggable body: bake dx/dy offset into point array then reset position to avoid accumulating drift"
  - "Vertex anchors only rendered when isSelected to avoid Konva Circle overhead on all regions"
requirements-completed: [REGN-01, REGN-02, REGN-06, UI-06]
duration: 10min
completed: "2026-03-24"
---

# Phase 4 Plan 03: Konva Canvas Editor Summary

**Konva.js canvas editor with polygon/rectangle drawing, vertex editing, body drag, and live WebSocket camera preview wired to the Region CRUD API.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-24T22:34:00Z
- **Completed:** 2026-03-24T22:44:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- EditorPage renders 70/30 layout with ResizeObserver-driven canvas sizing and Light Panel placeholder
- DrawingToolbar provides Rectangle/Polygon/Select/Delete buttons reading from Zustand drawingMode
- EditorCanvas implements three-layer Konva Stage: preview (listening=false), regions, handles; polygon and rectangle drawing; keyboard shortcuts (Delete/Escape)
- RegionPolygon renders semi-transparent colored polygon with draggable body and vertex anchors when selected; position drift prevented; 400ms debounced auto-save

## Task Commits

Each task was committed atomically:

1. **Task 1 + Task 2: EditorPage, DrawingToolbar, EditorCanvas, RegionPolygon** - `78a2772` (feat)

_Note: Tasks 1 and 2 were committed together since RegionPolygon is a direct compile-time dependency of EditorCanvas — splitting would produce a non-compiling intermediate state._

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `Frontend/src/components/DrawingToolbar.tsx` - Four-button mode toolbar reading drawingMode from store
- `Frontend/src/components/EditorCanvas.tsx` - Konva Stage with preview layer, region rendering, polygon/rectangle drawing, keyboard shortcuts, and delete logic
- `Frontend/src/components/RegionPolygon.tsx` - Interactive polygon Group with vertex anchors, body drag, debounced auto-save
- `Frontend/src/components/EditorPage.tsx` - 70/30 layout with ResizeObserver for responsive canvas, Light Panel placeholder
- `Frontend/src/App.tsx` - EditorPage replaces editor placeholder div

## Decisions Made

- `handleEditorDelete` exported as standalone async function from EditorCanvas so both the DrawingToolbar `onDelete` prop and the keyboard shortcut can call it without duplicating logic or introducing circular ref complexity.
- Canvas aspect ratio set to 4:3 (matching 640x480 capture resolution) rather than 16:9. The backend captures at 480x640 so 4:3 gives accurate region-to-screen mapping.
- Tasks 1 and 2 implemented and committed together: RegionPolygon is a compile-time import of EditorCanvas, so a two-commit TDD split would produce a non-compiling intermediate state.

## Deviations from Plan

None — plan executed exactly as written. All specified behaviors implemented:
- `listening={false}` on preview layer
- Rectangle stored as 4-vertex polygon (no special Rect shape in data model)
- Group position reset to (0,0) after dragEnd to prevent drift
- `e.cancelBubble = true` on Circle event handlers

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- EditorPage ready for Plan 04 to wire in the LightPanel (right 30% panel) with light assignment drag-and-drop
- `stageRef` is declared in EditorCanvas and the wrapper div exposes `onDragOver`/`onDrop` placeholders for Plan 04's HTML5 DnD integration
- All REGN-01, REGN-02, REGN-06, UI-06 requirements satisfied

---
*Phase: 04-frontend-canvas-editor*
*Completed: 2026-03-24*
