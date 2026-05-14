---
phase: 19
plan: 12
subsystem: frontend
tags: [phase-19, wled, popover, drop-branch, wave-6, canvas, orientation]
dependency_graph:
  requires: [19-07, 19-11]
  provides: [wled-drop-branch, region-orientation-popover, orientation-segmented-control, wled-assignments-store]
  affects: [EditorCanvas, useRegionStore, LightPanel-drag-target]
tech_stack:
  added: []
  patterns:
    - Base UI virtual-anchor popover pattern (Popover.Positioner anchor={{ getBoundingClientRect }})
    - Per-device channel_index for chip color parity (UI-SPEC §Color line 95)
    - Optimistic orientation update with rollback on PATCH error
    - Zustand store wledAssignments slice with updateWledAssignmentOrientation
key_files:
  created:
    - Frontend/src/components/Editor/OrientationSegmentedControl.tsx
    - Frontend/src/components/Editor/RegionOrientationPopover.tsx
  modified:
    - Frontend/src/store/useRegionStore.ts
    - Frontend/src/components/EditorCanvas.tsx
    - Frontend/src/components/EditorCanvas.test.tsx
decisions:
  - "selectedConfigId added as optional prop to EditorCanvasProps (default null) — avoids breaking existing callers while enabling WLED popover"
  - "Chip color uses deviceChannelIndexById lookup built from channelsByDevice to match UI-SPEC §Color line 95 contract"
  - "4 EditorCanvas tests flipped to passing via full RTL render with mocked react-konva Stage (useImperativeHandle exposes mockStage)"
metrics:
  duration: ~5min
  completed: "2026-05-14"
  tasks_completed: 3
  files_changed: 5
  lines_added: 661
  lines_removed: 13
---

# Phase 19 Plan 12: Region Orientation Popover + WLED Drop Branch Summary

**One-liner:** Canvas-side region properties surface with Base UI virtual-anchor popover, per-device chip color parity, and WLED handleDrop branch with explicit return preserving the Hue path byte-identical.

## Objective

Ship the final UI layer of the WLED vertical slice: drag a channel from LightPanel onto a canvas region → assignment created → popover opens showing assigned channels + per-region orientation segmented control.

## What Was Built

### Task 1: useRegionStore extension + OrientationSegmentedControl (commit fb32055)

**`Frontend/src/store/useRegionStore.ts`** — two new slice members added:
- `wledAssignments: Record<string, WledAssignment[]>` — keyed by region ID
- `setWledAssignments(a)` — full replace (used on mount + drop refresh)
- `updateWledAssignmentOrientation(regionId, orientation)` — updates all assignments for the region (per-region invariant from D-16/D-22), used for optimistic orientation updates in the popover

**`Frontend/src/components/Editor/OrientationSegmentedControl.tsx`** (new, 57 lines):
- 5-option controlled segmented control: `auto / → / ← / ↓ / ↑`
- `data-testid="orientation-segmented-control"` + per-button `orientation-btn-{value}`
- Active button: `var(--accent)` text, `var(--accent-bg)` fill, `var(--accent-border)` inset shadow
- Purely controlled — parent owns value + fires onChange; no internal state

### Task 2: RegionOrientationPopover (commit b73814c)

**`Frontend/src/components/Editor/RegionOrientationPopover.tsx`** (new, 260 lines):

Key design decisions:
- **Virtual anchor:** `Popover.Positioner anchor={{ getBoundingClientRect }}` computes the selected region's screen bbox from its normalised polygon × canvas pixel size + `canvasContainerEl.getBoundingClientRect()`
- **Chip color contract (UI-SPEC §Color line 95):** `deviceChannelIndexById` memo builds `Record<wled_channel_id, channel_index>` where `channel_index` is each channel's position in its own device's `start_led`-sorted list — identical to the LightPanel formula. `channelColor(deviceChannelIndex)` produces the same color as the LightPanel chip and strip painter zone for the same channel.
- **Orientation save:** `handleOrientationChange` does an optimistic `updateWledAssignmentOrientation` store update, then awaits `patchRegionOrientation`. On error: rolls back to `prev` and sets `saveError = "Couldn't save. Retry?"` (T-19-18 mitigation).
- **Empty state:** "Drag a channel from the LightPanel to add an assignment." (no segmented control shown)
- **Per-region single control:** one `OrientationSegmentedControl` regardless of how many channels are assigned (D-19/D-22 invariant)
- **Close:** `Popover.Close` with `aria-label="Close orientation panel"` calls `setSelectedId(null)`

Props: `canvasWidth`, `canvasHeight`, `canvasContainerEl`, `selectedConfigId`, `channelsByDevice`

### Task 3: EditorCanvas WLED branch + popover mount (commit 42d176c)

**`Frontend/src/components/EditorCanvas.tsx`** — additive changes only:

**handleDrop diff (key excerpt):**
```
  async function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()

    // Phase 19: WLED branch first — wledChannelId is unambiguous discriminator
    const wledChannelId = e.dataTransfer.getData('wledChannelId')
    if (wledChannelId) {
      // ... upsertWledAssignment + refresh + setSelectedId(hit.id) ...
      return  // CRITICAL: prevent fall-through to the Hue branch.
    }

    // EXISTING HUE BRANCH BELOW - byte-identical to the pre-Phase-19 code.
    const channelId = e.dataTransfer.getData('channelId')
    // ...
```

Additional changes:
- `selectedConfigId?: string | null` added to `EditorCanvasProps` (default null)
- `canvasContainerRef = useRef<HTMLDivElement>(null)` + attached to outer wrapper div
- `channelsByDevice` state + WLED assignments/channels load effect (runs on mount + config change)
- `<RegionOrientationPopover>` mounted as sibling of `<Stage>` inside the container div (Base UI Portal renders to `document.body` regardless)

**`Frontend/src/components/EditorCanvas.test.tsx`** — 4 stubs flipped to passing:
1. `WLED drop: when wledChannelId is present, calls upsertWledAssignment and returns`
2. `Hue drop preserved: payload without wledChannelId still calls updateRegionAPI`
3. `WLED branch returns: payload with BOTH wledChannelId and lightId only calls WLED handler`
4. `No payload: handler exits without API calls when neither key is present`

Test approach: full RTL render with mocked `react-konva` Stage (`React.forwardRef` + `useImperativeHandle` exposing `mockStage` with `setPointersPositions` + `getPointerPosition`). Mocked `@/api/wled` and `@/api/regions`. Store seeded with a full-canvas region so pointer hit always succeeds.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written.

### Minor adjustments

**1. [Rule 2 - Missing] Added `Group` and `Text` to react-konva mock**
- **Found during:** Task 3 test run
- **Issue:** `RegionPolygon` imports `Group` from `react-konva`; the initial mock was missing it, causing all 4 tests to fail
- **Fix:** Added `Group` and `Text` to the `vi.mock('react-konva', ...)` factory
- **Files modified:** `Frontend/src/components/EditorCanvas.test.tsx`
- **Commit:** 42d176c (same task commit)

## Verification

| Check | Result |
|-------|--------|
| `npx tsc --noEmit` | Clean (no output) |
| `npx vitest run` | 13 passed, 2 skipped — 95 tests pass, 20 todos |
| WLED branch has explicit return | Line 295: `return  // CRITICAL: prevent fall-through to the Hue branch.` |
| Hue branch byte-identical | Confirmed — only outer wrapper changed, Hue body untouched |
| Chip color via per-device channel_index | `deviceChannelIndexById[a.wled_channel_id]` used, not in-region position |
| 4 EditorCanvas tests green | `4 passed \| 1 todo` |

## Known Stubs

The `EditorCanvas — popover mount` describe block has one remaining `it.todo`:
- `renders RegionOrientationPopover as a sibling of Konva Stage` — deferred to Plan 19-13 Playwright verification (requires full DOM portal rendering to assert sibling relationship)

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced by this plan. The drag payload trust boundary (T-19-17/T-19-18) and optimistic UI rollback were addressed in the implementation as planned.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `Frontend/src/store/useRegionStore.ts` | FOUND |
| `Frontend/src/components/Editor/OrientationSegmentedControl.tsx` | FOUND |
| `Frontend/src/components/Editor/RegionOrientationPopover.tsx` | FOUND |
| `Frontend/src/components/EditorCanvas.tsx` | FOUND |
| `.planning/phases/19-wled-strip-paint-ui/19-12-SUMMARY.md` | FOUND |
| commit fb32055 | FOUND |
| commit b73814c | FOUND |
| commit 42d176c | FOUND |
