---
phase: 19-wled-strip-paint-ui
plan: 05
subsystem: ui
tags: [phase-19, wled, frontend-helpers, pure-functions, vitest, typescript]

requires:
  - phase: 19-02
    provides: Vitest test stubs for wled-palette and wled-paint-reducer (created inline as part of this plan since 19-02 ran in parallel)

provides:
  - "Frontend/src/utils/wled-palette.ts — channelColor(index) pure function"
  - "Frontend/src/components/Settings/wled-paint-reducer.ts — paintReducer, pixelToLed, ledToPixel, clampBoundary pure helpers + PaintState/PaintAction types"

affects:
  - WledStripPainter.tsx (Plan 19-07) — imports paintReducer via useReducer
  - LightPanel.tsx (Plan 19-08) — imports channelColor for channel chip colors
  - RegionOrientationPopover.tsx (Plan 19-08) — imports channelColor

tech-stack:
  added: []
  patterns:
    - "Pure TypeScript helper modules with no React/DOM/Konva dependencies — matches geometry.ts shape"
    - "Reducer pattern for Konva pointer gesture state machines"
    - "Golden-angle HSL palette: hue = (index * 137.508) % 360, sat 60%, light 60%"

key-files:
  created:
    - Frontend/src/utils/wled-palette.ts
    - Frontend/src/utils/wled-palette.test.ts
    - Frontend/src/components/Settings/wled-paint-reducer.ts
    - Frontend/src/components/Settings/wled-paint-reducer.test.ts
  modified: []

key-decisions:
  - "Test files use direct ESM import (not require() try/catch) because vitest runs in ESM mode where require is not defined at module scope — the 19-02 stub design used require() as a conditional load guard but that fails silently in ESM, permanently skipping tests"
  - "wled-palette.ts: hue computed as (index * 137.508) % 360 with no rounding — JavaScript floating point yields exact expected values (index 3 → 52.524)"
  - "pixelToLed uses Math.floor so x=stripWidth maps to ledCount-1, not ledCount (off-by-one guard)"
  - "clampBoundary: min = leftMin + 1, max = rightMax — keeps both adjacent zones at ≥1 LED"
  - "_exhaustive: never guard retained in paintReducer default branch for TypeScript exhaustiveness checking"

patterns-established:
  - "Pure helper pattern: no imports from React, Konva, or browser APIs — enables full Vitest coverage without JSDOM overhead"
  - "Reducer split: Konva pointer events handled in component; state transitions handled in pure reducer — same split as geometry.ts vs EditorCanvas.tsx"

requirements-completed: [WMAP-01, WMAP-03, WMAP-04]

duration: 8min
completed: 2026-05-14
---

# Phase 19 Plan 05: WLED Frontend Pure Helpers Summary

**Golden-angle HSL palette helper and paint gesture reducer shipped as zero-dependency TypeScript modules with 15 Vitest assertions passing**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-14T14:51:00Z
- **Completed:** 2026-05-14T14:56:00Z
- **Tasks:** 2
- **Files created:** 4

## Accomplishments

- `channelColor(index)` — deterministic golden-angle HSL, hue = (index × 137.508) % 360, sat 60%, light 60%. Adjacent indices are always visually distinct.
- `paintReducer` — idle/painting state machine for drag-to-paint gesture. Calls `commit(min, max)` exactly once on mouseup; cancel returns to idle without committing.
- `pixelToLed` / `ledToPixel` — bidirectional strip-canvas pixel ↔ LED index conversion with clamping.
- `clampBoundary` — prevents either adjacent zone from collapsing below 1 LED during boundary drag.
- Full frontend suite green: 11 files / 80 tests passing + 1 todo.

## Task Commits

1. **Task 1: wled-palette.ts + test** — `4d38e79` (feat)
2. **Task 2: wled-paint-reducer.ts + test** — `b478ec0` (feat)

## Files Created

- `Frontend/src/utils/wled-palette.ts` — 24 lines, `channelColor` export
- `Frontend/src/utils/wled-palette.test.ts` — 4 passing assertions + 1 todo
- `Frontend/src/components/Settings/wled-paint-reducer.ts` — 107 lines, 4 exports + 2 type exports
- `Frontend/src/components/Settings/wled-paint-reducer.test.ts` — 11 passing assertions

## Decisions Made

- Used direct ESM `import` in test files instead of `require()` try/catch. The 19-02 stub design used `require()` as a conditional load guard, but vitest runs in ESM mode where `require` is not defined — the try/catch catches a ReferenceError and sets the import to null, permanently skipping all tests even after the implementation ships. Direct import is the correct pattern for this project (matches `geometry.test.ts`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Replaced require() try/catch with direct ESM import in test stubs**
- **Found during:** Task 1 (verifying RED → GREEN flip)
- **Issue:** The 19-02 stub design wraps imports in `require()` inside try/catch. In vitest's ESM environment, `require` is not defined — the catch silently sets `channelColor = null`, so all `it.skipIf(channelColor === null)` tests remain permanently skipped even after the implementation file exists.
- **Fix:** Rewrote both test files to use direct ESM `import { ... } from './module'` — the correct pattern for this vitest project (matches `geometry.test.ts`).
- **Files modified:** `wled-palette.test.ts`, `wled-paint-reducer.test.ts`
- **Verification:** Vitest output shows 4 + 11 = 15 passing assertions (not skipped)
- **Committed in:** `4d38e79`, `b478ec0`

---

**Total deviations:** 1 auto-fixed (Rule 1 — test stub ESM compatibility bug)
**Impact on plan:** Fix was necessary for the "flip from skipped → green" goal. No scope change.

## Issues Encountered

- Worktree had no `node_modules` — ran `npm install` before executing tests (Rule 3 auto-fix, not tracked as deviation since it's environment setup).
- Plan 19-02 test stubs not yet committed to this worktree (parallel wave execution). Created them inline as part of the TDD RED phase.

## User Setup Required

None — pure frontend helpers, no configuration required.

## Next Phase Readiness

- `channelColor` ready for import in `WledStripPainter.tsx` (Plan 19-07), `LightPanel.tsx` (Plan 19-08), `RegionOrientationPopover.tsx` (Plan 19-08)
- `paintReducer` + pixel helpers ready for `useReducer(paintReducer, ...)` in `WledStripPainter.tsx` (Plan 19-07)
- No blockers for Wave 5+ plans

---
*Phase: 19-wled-strip-paint-ui*
*Completed: 2026-05-14*
