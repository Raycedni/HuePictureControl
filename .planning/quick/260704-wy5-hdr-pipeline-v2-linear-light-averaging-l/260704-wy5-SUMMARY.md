---
phase: quick-260704-wy5
plan: 01
subsystem: color-math
tags: [numpy, hdr10, pq, bt2020, color-science, streaming]

# Dependency graph
requires:
  - phase: quick-260704-w88
    provides: hdr_input toggle + settings KV wiring + v1 hdr10_to_srgb (post-hoc byte-space conversion)
provides:
  - Module-level 256-entry linear-light LUT (limited-range PQ byte -> linear light)
  - _finish_linear_bt2020_to_srgb (roll-off -> BT.2020->BT.709 -> sRGB, composable second half)
  - hdr=True averaging path on extract_region_color/sub_sample_gradient (region means computed in linear light before tone-mapping)
  - streaming_coordinator threading hdr directly into sampling calls (post-hoc conversion removed)
affects: [any future HDR/color-pipeline work, streaming_coordinator frame loop]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Decompose a byte->uint8 conversion pipeline into a LUT half (per-pixel, applied via numpy fancy indexing) + a finishing half (batch tone-map), so the LUT can be applied BEFORE an averaging step instead of only after it"

key-files:
  created: []
  modified:
    - Backend/services/color_math.py
    - Backend/tests/test_color_math.py
    - Backend/services/streaming_coordinator.py

key-decisions:
  - "hdr10_to_srgb is now the LUT + finish composition rather than its own independent pipeline, so there is a single source of truth for the PQ decode + tone-map math"
  - "hdr10_to_srgb shifted from full-range PQ decode (v1) to limited-range PQ decode (v2) intentionally, matching the capture card's actual limited-range signal (blacks ~16, whites ~235); verified all v1 invariant tests (neutral->neutral, orange R>G>B, black->black, bright->valid uint8) still pass unmodified because byte 255 saturates to the same LUT value as byte 235 under the new clipping"
  - "_weighted_region_mean_linear drops the byte-space version's 255/max_channel overflow cap because there is no uint8 ceiling to protect in linear light -- the downstream tone-map handles range compression"

patterns-established:
  - "LUT-then-finish decomposition for HDR color pipelines: build once at import, index with numpy fancy indexing on a uint8 ROI, then average in linear space before the finishing tone-map runs once on the batch"

requirements-completed: [QUICK-260704-wy5]

# Metrics
duration: ~20min
completed: 2026-07-04
---

# Quick Task 260704-wy5: HDR Pipeline v2 (Linear-Light Averaging) Summary

**Region color sampling now averages in linear light (via a 256-entry limited-range PQ->linear LUT) before tone-mapping, instead of averaging PQ-encoded bytes and converting after — fixes murky warm-gray output on high-dynamic-range scenes.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-04
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added a module-level 256-entry `_LINEAR_LUT` (limited-range expansion -> PQ EOTF -> linear light), built once at import, with a black floor at byte 16 and saturation at byte 235
- Added `_finish_linear_bt2020_to_srgb` as the composable "second half" (roll-off -> BT.2020->BT.709 matrix -> sRGB encode)
- Reimplemented `hdr10_to_srgb` as the composition of the LUT and finishing halves — all v1 invariant tests pass unmodified
- Added `hdr: bool = False` to `extract_region_color` and `sub_sample_gradient`: when `True`, the ROI is expanded to linear light BEFORE averaging (per-pixel for `extract_region_color`, per-slab for `sub_sample_gradient`, finished once per call), so a bright area dominates the region mean the way it dominates perceptually
- `streaming_coordinator._frame_loop` now passes `hdr=hdr`/`hdr=hdr_on` directly into `sub_sample_gradient` for both the Hue and WLED pipelines, removing the post-hoc `hdr10_to_srgb(...)` wrapping that was the v1 defect (convert-after-average)
- Removed the now-unused `hdr10_to_srgb` import from `streaming_coordinator.py`

## Task Commits

Each task was committed atomically:

1. **Task 1: Linear LUT + finishing function + linear-light hdr averaging paths in color_math.py** - `61653c2` (feat)
2. **Task 2: Thread hdr into sampling calls in streaming_coordinator and remove post-hoc conversion** - `4fde109` (feat)

**Plan metadata:** pending (docs: complete plan — committed by orchestrator)

## Files Created/Modified
- `Backend/services/color_math.py` - Added `_LINEAR_LUT`, `_finish_linear_bt2020_to_srgb`, `_weighted_region_mean_linear`; reimplemented `hdr10_to_srgb`; added `hdr=` param to `extract_region_color`/`sub_sample_gradient`
- `Backend/tests/test_color_math.py` - Added `TestLinearLut` (endpoint/monotonic assertions), `TestHdrLinearAveraging` (orange-dominant motivating scenario, linear-vs-byte-space spread comparison, empty-mask guard, hdr=False parity, n<=1 delegation, multi-sample dtype/range)
- `Backend/services/streaming_coordinator.py` - Threaded `hdr`/`hdr_on` into both the Hue (`hue_gradients`) and WLED (`_wled_pipeline._compute`) sampling calls; removed the post-hoc `hdr10_to_srgb(...)` wrapping and its now-unused import

## Decisions Made
- Kept `hdr10_to_srgb` as a public composition entry point (LUT + finish) rather than deleting it, since it still has value as a standalone conversion utility and its test suite (`TestHdr10ToSrgb`) is a useful v1-invariant regression guard even though it is no longer called from `streaming_coordinator`
- Verified via direct script run that the motivating scenario (half bright PQ orange + half dull gray) produces R-B spread 245 under linear-before-average vs. 208 under convert-after-average (byte mean then `hdr10_to_srgb`) — confirms the fix in a measurable way, not just directionally

## Deviations from Plan

None - plan executed exactly as written. The plan explicitly granted discretion on whether `hdr10_to_srgb`'s shift to limited-range decode would break v1 invariants (task action step 3); it did not — all `TestHdr10ToSrgb` tests pass unmodified, so no fallback path was needed.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. No new settings, dependencies, or frontend changes.

## Next Phase Readiness
- HDR v2 linear-light averaging is live in the frame loop for both Hue and WLED sinks whenever `hdr_input` is toggled on
- No blockers. The 12 pre-existing `test_cameras_router.py` failures remain out of scope (unrelated to this task, verified via full-suite run showing zero new failures)

---
*Phase: quick-260704-wy5*
*Completed: 2026-07-04*

## Self-Check: PASSED

- FOUND: Backend/services/color_math.py
- FOUND: Backend/tests/test_color_math.py
- FOUND: Backend/services/streaming_coordinator.py
- FOUND: commit 61653c2
- FOUND: commit 4fde109
