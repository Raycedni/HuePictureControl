---
phase: quick-260714-nnk
plan: 01
subsystem: ui
tags: [react, typescript, camera-identity, regression-test]

# Dependency graph
requires:
  - phase: 19.1-08
    provides: CameraDevice/ZoneHealth interfaces with stable_id as unique identity key (Frontend/src/api/cameras.ts)
provides:
  - Camera selection re-keyed from device_path to stable_id end-to-end in LightPanel.tsx and EditorPage.tsx
  - device_path resolved from selected stable_id only at the EditorPage -> EditorCanvas -> usePreviewWS call site
  - Regression test reproducing the device_path-collision bug (two records sharing one device_path)
affects: [lightpanel, editor-page, camera-selection]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Identity keys that must be globally unique (stable_id) are threaded through component state/props verbatim; a derived, potentially non-unique value (device_path) is resolved only at the single downstream call site that requires it (usePreviewWS)."

key-files:
  created: []
  modified:
    - Frontend/src/components/LightPanel.tsx
    - Frontend/src/components/EditorPage.tsx
    - Frontend/src/components/LightPanel.test.tsx

key-decisions:
  - "selectedDevice (state owned by EditorPage, threaded through LightPanel) now holds a stable_id, not a device_path; the visible dropdown label still shows device_path per CMUI-02 (label text unchanged, only the option value changed)"
  - "device_path is resolved from the selected stable_id in EditorPage immediately before passing to EditorCanvas, so EditorCanvas/usePreviewWS require zero changes"

patterns-established:
  - "Camera identity key = stable_id everywhere except the single point of use that requires a real device path (preview WS connection)"

requirements-completed: [BFIX-CAM-STABLEID]

# Metrics
duration: ~10min
completed: 2026-07-14
---

# Phase quick-260714-nnk: Fix camera selection bug in LightPanel.tsx Summary

**Camera selection re-keyed from `device_path` to `stable_id` across LightPanel.tsx/EditorPage.tsx, closing a collision bug where two camera records sharing a device_path could resolve to the wrong (stale/disconnected) device.**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-07-14
- **Tasks:** 2 completed
- **Files modified:** 3

## Accomplishments
- All `.find()` lookups in `LightPanel.tsx` (camera-change handler, zone-change handler, disconnected-badge computation, tier 2/3 zone pre-selection effect, D-06 zone-health init effect) now match on `stable_id` instead of `device_path`.
- Camera `<select>` dropdown option `value` changed from `d.device_path` to `d.stable_id`; the visible label text (`{display_name} ({device_path})`) is unchanged.
- `EditorPage.tsx` resolves a real `device_path` from the selected `stable_id` at the single point of use (passed to `EditorCanvas`/`usePreviewWS`) — no changes needed to `EditorCanvas` or `usePreviewWS`.
- Regression test added reproducing the exact collision scenario: two `CameraDevice` records sharing `device_path: '/dev/video0'` (one disconnected with an old stable_id, one connected with a new stable_id). Selecting the connected device from the dropdown now persists and reports the connected device's own stable_id — never the stale first-match.
- Additional regression assertions: the dropdown lists only the connected record from the collision pair, and the "Disconnected" badge correctly tracks whichever camera is actually selected.

## Task Commits

Each task was committed atomically:

1. **Task 1: Re-key camera selection from device_path to stable_id (LightPanel.tsx + EditorPage.tsx)** - `f9a4fa3` (fix)
2. **Task 2: Update existing tests + add device_path-collision regression test** - `4806de2` (test)

**Plan metadata:** (docs commit handled by orchestrator)

## Files Created/Modified
- `Frontend/src/components/LightPanel.tsx` - All camera identity lookups, dropdown option value, and the D-06 zone-health init effect now key on `stable_id`.
- `Frontend/src/components/EditorPage.tsx` - Resolves `device_path` from the selected `stable_id` immediately before passing `device` to `EditorCanvas`.
- `Frontend/src/components/LightPanel.test.tsx` - Existing D-08 camera-switch tests updated to use stable_ids; new `describe('device_path collision (BFIX-CAM-STABLEID)')` block added with 3 tests.

## Decisions Made
- Kept the visible dropdown label showing `device_path` (per CMUI-02, unchanged) while only the underlying `<option value>` switched to `stable_id` — preserves the existing UX contract while fixing the identity bug.
- `EditorPage.tsx` is the sole place where `device_path` is derived from the selected `stable_id`, keeping `EditorCanvas`/`usePreviewWS` untouched and avoiding any change to the preview WebSocket contract.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The worktree's `Frontend/node_modules` was missing (gitignored, not present in the fresh worktree checkout). Created a Windows NTFS junction (`mklink /J`) pointing at the main repo's `Frontend/node_modules` to run `vitest` without a slow reinstall. This is a local filesystem convenience only — no repo files were affected (node_modules remains gitignored and untracked).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `cd Frontend && npx vitest run` passes in full (129 passed, 20 todo, 17 test files passed / 2 skipped).
- No known follow-up work; this closes requirement BFIX-CAM-STABLEID.

---
*Phase: quick-260714-nnk*
*Completed: 2026-07-14*

## Self-Check: PASSED

- FOUND: Frontend/src/components/LightPanel.tsx
- FOUND: Frontend/src/components/EditorPage.tsx
- FOUND: Frontend/src/components/LightPanel.test.tsx
- FOUND: commit f9a4fa3
- FOUND: commit 4806de2
