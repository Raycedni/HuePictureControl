---
phase: 04-frontend-canvas-editor
plan: "02"
subsystem: frontend
tags: [react, zustand, tailwind, shadcn, websocket, typescript, vitest]
dependency_graph:
  requires: []
  provides:
    - useRegionStore (Zustand region state for canvas editor)
    - useStatusStore (Zustand status state for streaming metrics)
    - usePreviewWS (WebSocket hook for binary preview stream)
    - useStatusWS (WebSocket hook for 1Hz status heartbeat)
    - StatusBar (global status component rendered on all tabs)
    - geometry utils (normalize/denormalize/pointInPolygon)
    - Region API CRUD (createRegion/updateRegion/deleteRegion)
  affects:
    - Frontend/src/App.tsx (extended to 3 tabs + StatusBar)
    - Frontend/src/api/regions.ts (light_id field added)
tech_stack:
  added:
    - react-konva@latest (canvas rendering, used in Plan 03)
    - konva@latest (canvas engine)
    - zustand@latest (state management)
    - use-image@latest (image loading hook)
    - tailwindcss v4 + @tailwindcss/vite (utility CSS)
    - shadcn/ui (button, badge, separator, scroll-area)
  patterns:
    - Zustand stores with getState() for test access outside hooks
    - WebSocket hooks with useEffect + cleanup for connection lifecycle
    - TDD: RED tests committed before GREEN implementations
key_files:
  created:
    - Frontend/src/utils/geometry.ts
    - Frontend/src/utils/geometry.test.ts
    - Frontend/src/store/useRegionStore.ts
    - Frontend/src/store/useRegionStore.test.ts
    - Frontend/src/store/useStatusStore.ts
    - Frontend/src/store/useStatusStore.test.ts
    - Frontend/src/hooks/usePreviewWS.ts
    - Frontend/src/hooks/usePreviewWS.test.ts
    - Frontend/src/hooks/useStatusWS.ts
    - Frontend/src/components/StatusBar.tsx
    - Frontend/components.json
    - Frontend/src/lib/utils.ts
    - Frontend/src/components/ui/button.tsx
    - Frontend/src/components/ui/badge.tsx
    - Frontend/src/components/ui/separator.tsx
    - Frontend/src/components/ui/scroll-area.tsx
  modified:
    - Frontend/src/api/regions.ts (added light_id, createRegion, updateRegion, deleteRegion)
    - Frontend/src/App.tsx (3-tab layout, StatusBar, Tailwind tab styling)
    - Frontend/src/index.css (Tailwind v4 import + shadcn theme vars)
    - Frontend/vite.config.ts (Tailwind plugin + path alias)
    - Frontend/tsconfig.json (baseUrl + paths for @/* alias)
    - Frontend/tsconfig.app.json (baseUrl + paths for @/* alias)
    - Frontend/package.json (new dependencies)
decisions:
  - shadcn scroll-area generated unused React import causing strict TS error — removed import (Rule 1 auto-fix)
  - Tailwind v4 requires @tailwindcss/vite plugin (not postcss); shadcn init auto-detected v4
  - useStatusWS uses reconnect-on-close pattern with 2s delay; destroyed flag prevents reconnect after unmount
  - usePreviewWS stores previous ObjectURL in ref and revokes on each new frame to prevent memory leaks
metrics:
  duration: "7 minutes"
  completed_date: "2026-03-24"
  tasks_completed: 2
  files_created: 16
  files_modified: 6
  tests_added: 30
---

# Phase 4 Plan 02: Frontend Foundation — Stores, Hooks, StatusBar, and Tailwind v4 Summary

**One-liner:** Zustand stores, WebSocket hooks, Tailwind v4 + shadcn/ui, and global StatusBar establishing the complete frontend foundation for the canvas editor.

## What Was Built

The frontend foundation required by Plans 03 and 04 of this phase. Every piece is infrastructure consumed downstream.

**Task 1 — Install dependencies and configure Tailwind v4 + shadcn/ui**

- Installed `react-konva`, `konva`, `zustand`, `use-image` runtime dependencies
- Installed `tailwindcss` v4 + `@tailwindcss/vite` plugin; configured in `vite.config.ts`
- Added `@import "tailwindcss"` to `index.css`; shadcn init auto-appended its theme variables
- Added `@/*` path alias to both `tsconfig.json` and `tsconfig.app.json`; matching `resolve.alias` in vite
- Ran `npx shadcn@latest init -d` which created `button.tsx`, `lib/utils.ts`, and `components.json`
- Added `badge`, `separator`, `scroll-area` components via `npx shadcn@latest add`
- TypeScript compiled cleanly after removing an unused `React` import from the generated `scroll-area.tsx`

**Task 2 — Stores, hooks, StatusBar, geometry utils, API client, App.tsx (TDD)**

- `geometry.ts`: `normalize` (pixel→[0..1]), `denormalize` ([0..1]→pixel), `pointInPolygon` (ray-casting)
- `useRegionStore.ts`: Zustand store holding `regions[]`, `selectedId`, `drawingMode`, `drawingPoints[]` with full mutation actions
- `useStatusStore.ts`: Zustand store holding `fps`, `latency`, `bridgeState`, `error`, `isStreaming` with `setMetrics` partial-update
- `usePreviewWS.ts`: WebSocket hook connecting to `/ws/preview`; manages `ObjectURL` lifecycle (revokes previous on each frame)
- `useStatusWS.ts`: WebSocket hook connecting to `/ws/status`; parses JSON, calls `setMetrics`, reconnects after 2s on close
- `StatusBar.tsx`: Renders streaming badge (green/gray), FPS, latency ms, bridge state, and error text using shadcn Badge and Tailwind
- `regions.ts`: Added `light_id: string | null` to `Region`; added `createRegion`, `updateRegion`, `deleteRegion` functions
- `App.tsx`: Extended `Page` type to include `'editor'`; added Editor tab button and placeholder; rendered `<StatusBar />` below all tab content; replaced inline styles with Tailwind classes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused React import from shadcn-generated scroll-area.tsx**
- **Found during:** Task 1 TypeScript verification
- **Issue:** shadcn generated `import * as React from "react"` in scroll-area.tsx but the component doesn't use the React namespace — strict `noUnusedLocals` TS flag caused a compile error
- **Fix:** Removed the unused import line
- **Files modified:** `Frontend/src/components/ui/scroll-area.tsx`
- **Commit:** 3579fbf (included in Task 1 commit)

## Test Results

All 30 tests pass across 5 test files:
- `geometry.test.ts`: 11 tests (normalize, denormalize, roundtrip, pointInPolygon)
- `useRegionStore.test.ts`: 8 tests (setRegions, addRegion, updateRegion, deleteRegion, setSelectedId, setDrawingMode, appendPoint, clearDrawing)
- `useStatusStore.test.ts`: 4 tests (initial state, partial/full setMetrics, null error)
- `usePreviewWS.test.ts`: 4 tests (WS construction, enabled=false, unmount cleanup, initial null)
- `PairingFlow.test.tsx`: 3 tests (pre-existing, still passing)

## Commits

| Hash | Type | Description |
|------|------|-------------|
| 3579fbf | chore | Install deps and configure Tailwind v4 + shadcn/ui (Task 1) |
| 3adc5be | feat | Implement stores, WS hooks, StatusBar, geometry utils, extend API (Task 2) |

Note: TDD intermediate commits (RED/GREEN) were made to the Frontend sub-repo (.git); the root-level commits above contain the complete implementation including test files.

## Self-Check: PASSED

All key files confirmed present:
- Frontend/src/utils/geometry.ts - FOUND
- Frontend/src/store/useRegionStore.ts - FOUND
- Frontend/src/store/useStatusStore.ts - FOUND
- Frontend/src/hooks/usePreviewWS.ts - FOUND
- Frontend/src/hooks/useStatusWS.ts - FOUND
- Frontend/src/components/StatusBar.tsx - FOUND
- Frontend/src/api/regions.ts - FOUND
- Frontend/src/App.tsx - FOUND

Commits confirmed: 3579fbf, 3adc5be in master branch.
30 tests pass, TypeScript compiles without errors.
