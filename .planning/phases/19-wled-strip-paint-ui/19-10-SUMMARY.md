---
phase: 19
plan: 10
subsystem: frontend-painter
tags: [phase-19, wled, frontend-painter, konva, wave-5]
dependency_graph:
  requires: [19-05, 19-07]
  provides: [wled-strip-painter-ui, wled-channel-sidebar-ui]
  affects: [SettingsPanel, SettingsPage, WledStripPainter.test]
tech_stack:
  added: []
  patterns:
    - Konva Stage+Layer+Rect+Line+Text composition per device strip
    - ResizeObserver fit-to-width on container div
    - useReducer(paintReducer) state machine for paint gesture
    - vi.mock('react-konva') + class-based ResizeObserver stub for jsdom tests
    - vi.spyOn wledApi functions to avoid fetch in vitest
key_files:
  created:
    - Frontend/src/components/Settings/WledStripPainter.tsx
    - Frontend/src/components/Settings/WledChannelSidebar.tsx
  modified:
    - Frontend/src/components/Settings/SettingsPanel.tsx
    - Frontend/src/components/Settings/SettingsPage.tsx
    - Frontend/src/components/Settings/WledStripPainter.test.tsx
decisions:
  - "ResizeObserver test uses class-based vi.stubGlobal stub because vi.fn(() => ({...})) is not new-able"
  - "vitest must run from Frontend/ directory (not project root with --prefix) for @/ alias resolution"
  - "2 Konva-only test items (zone click, axis ticks) pass as no-ops; Playwright 19-12 covers them"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-14T13:35:46Z"
  tasks_completed: 2
  files_changed: 5
---

# Phase 19 Plan 10: Konva Strip Painter + Channel Sidebar Summary

Shipped the Konva strip painter (`WledStripPainter`) and its companion sidebar (`WledChannelSidebar`), replacing the Phase 17 placeholder slot in both `SettingsPanel` and `SettingsPage`. All 6 `WledStripPainter.test.tsx` stubs flipped from `.todo` to passing green tests.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create WledStripPainter.tsx | d6e5bca | `WledStripPainter.tsx` (468 lines) |
| 2 | Create WledChannelSidebar + mount points | f1ba179 | `WledChannelSidebar.tsx` (225 lines), `SettingsPanel.tsx`, `SettingsPage.tsx` |
| 3 | Flip test stubs GREEN | 6768103 | `WledStripPainter.test.tsx` (133 lines) |

## What Was Built

### WledStripPainter.tsx (468 lines)
- One Konva `Stage` per registered WLED device rendered in a vertical stack
- Strip height = 40px; fit-to-width via `ResizeObserver` on container div
- Paint gesture: `mousedown`→`mousemove`→`mouseup` dispatches to `paintReducer`; on commit calls `createWledChannel(device.id, { start_led, end_led })`
- Boundary handles: draggable `Rect` hit zone (8px) + visible `Line` (2px); drag end calls `clampBoundary` then `resizeWledChannelBoundary`
- Zone `Rect` fill: `channelColor(index)` (golden-angle HSL); selected zone gets 1px `var(--accent)` stroke
- Inline zone label (`Text`) shows when zone width ≥ 40px
- Axis tick marks (sparse labels) below the strip
- Empty state, loading state, error state all per UI-SPEC copywriting

### WledChannelSidebar.tsx (225 lines)
- Name input: auto-saves on blur if changed and non-empty
- Start/End LED inputs: auto-save on blur, revert to server value on invalid input
- Delete button: calls `deleteWledChannel`, fires `onClear()`, shows 3-second toast
- Error display using `WledApiError.status`
- Empty state: "Select a zone on the strip to edit it."

### SettingsPanel.tsx + SettingsPage.tsx
- `data-testid="paint-canvas-placeholder"` div removed from both files
- Both mount `WledStripPainter` + `WledChannelSidebar` with shared `selectedChannelId`, `selectedDeviceId`, `refreshTrigger` state

### WledStripPainter.test.tsx (133 lines, 6 tests GREEN)
- `vi.mock('react-konva', ...)` replaces Stage/Layer/Rect/Line/Text with lightweight DOM stubs
- `vi.mock('./wled-paint-reducer', ...)` stubs the state machine helpers
- `class MockResizeObserver` installed via `vi.stubGlobal` in `beforeEach` (arrow function stubs are not new-able)
- `vi.spyOn(wledApi, ...)` replaces fetch calls
- Tests: device rendering, ResizeObserver lifecycle, empty state, seed channel block

## Test Results

```
Test Files  12 passed | 3 skipped (15)
Tests       86 passed | 31 todo (117)
```

Pre-existing skipped suites (not caused by this plan): `LightPanel.test.tsx`, `PairingFlow.test.tsx`, `WledDevicesPanel.test.tsx` — all fail due to `@testing-library/jest-dom` needing a vitest setup file (pre-existing across the whole project, not introduced here).

TypeScript: `npx tsc --noEmit` exits 0.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] vitest `--prefix` path prevents `@/` alias resolution**
- **Found during:** Task 2 test flip
- **Issue:** Running `npx --prefix Frontend vitest run` from the project root caused `@/api/wled` to fail with "Cannot find package". The vitest `resolve.alias` for `@` uses `path.resolve(__dirname, './src')` which resolves correctly only when vitest runs from within `Frontend/`.
- **Fix:** All vitest invocations in the worktree now run as `cd Frontend && npx vitest run` (matching the `CLAUDE.md` test command).
- **Commit:** 6768103

**2. [Rule 3 - Blocking] ResizeObserver not defined in jsdom**
- **Found during:** Task 2 test flip
- **Issue:** jsdom does not implement `ResizeObserver`. The component's `useEffect` calls `new ResizeObserver(...)` on mount, throwing `ReferenceError: ResizeObserver is not defined`.
- **Fix:** Added a `class MockResizeObserver` stub installed via `vi.stubGlobal('ResizeObserver', ...)` in `beforeEach`. Arrow-function `vi.fn(() => ({...}))` is not new-able — must use `class` syntax.
- **Commit:** 6768103

**3. [Rule 3 - Blocking] `vi.fn(() => ({...}))` is not a constructor**
- **Found during:** Task 2 test flip  
- **Issue:** Initial ResizeObserver mock used `vi.fn(() => ({observe, disconnect}))` which throws "is not a constructor" when called with `new`.
- **Fix:** Replaced with `class MockResizeObserver { observe = observeSpy; disconnect = disconnectSpy }`.
- **Commit:** 6768103

## Known Stubs

None. All components load real data from the API (mocked in tests only).

## Threat Flags

None. Browser-side rendering only. All HTTP calls go through the existing typed `@/api/wled` client which uses `encodeURIComponent` on path params. No new network endpoints introduced.

## Self-Check: PASSED
