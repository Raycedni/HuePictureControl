---
phase: quick-260719-efy
plan: 01
subsystem: streaming
tags: [color-correction, numpy, color_math, hue, wled, hardware-tint]

# Dependency graph
requires:
  - phase: quick-260714-txt
    provides: correct_channels_rgb relational function + color_correction_r/g/b settings/UI/wiring
provides:
  - Flat per-channel multiplicative correct_channels_rgb (out = clip(arr * gains, 0, 255))
  - Updated docstring with no dominant-channel-invariance claims
  - Rewritten TestCorrectChannels asserting flat behavior
affects: [color-correction, streaming, color_math]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Flat per-channel multiplicative gain (arr * gains) replaces relational max-anchored math for direct, intuitive tint compensation"

key-files:
  created: []
  modified:
    - Backend/services/color_math.py
    - Backend/tests/test_color_math.py
    - Backend/tests/test_streaming_coordinator.py

key-decisions:
  - "Reworked correct_channels_rgb from relational (dominant-channel-invariant) to flat per-channel multiplicative gain — user's hardware test showed the relational version did not produce the desired effect"
  - "Scope kept strictly internal: function name, signature, settings keys (color_correction_r/g/b), UI range [0.5,1.5], and streaming_coordinator.py call sites unchanged"

patterns-established:
  - "correct_channels_rgb identity fast-path (1/1/1 -> same object, zero cost) preserved, mirroring boost_saturation_rgb's boost==0.0 contract"

requirements-completed: []

# Metrics
duration: 10min
completed: 2026-07-19
---

# Quick 260719-efy: Rework Color Correction to Flat Multiplicative Summary

**correct_channels_rgb reworked from relational dominant-channel-invariant math to a direct flat per-channel multiplicative gain (out = clip(arr * [gain_r, gain_g, gain_b], 0, 255)) applied to every pixel unconditionally.**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-07-19
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Replaced the relational body (`out = mx - (mx - arr) * gains`) with flat multiplicative scaling (`out = arr * gains`) so each gain is a direct per-channel multiplier hitting every pixel, independent of which channel is the per-pixel max.
- Rewrote the docstring to describe static/flat hardware-tint compensation, removing all dominant/max-channel-invariance language ("vibrant green stays vibrant green", "dominant channel numerically unchanged", "gain only affects non-dominant channels").
- Preserved the identity fast-path (`1.0/1.0/1.0` -> same object) and the `.astype(np.uint8)` truncation convention.
- Rewrote `TestCorrectChannels` to assert flat behavior (green IS scaled, uniform-across-channels, clip at 255, scale-down, identity, shape).
- Full backend suite green with zero new regressions (only 12 pre-existing, out-of-scope cameras_router failures remain).

## Task Commits

Each task was committed atomically:

1. **Task 1: Rework correct_channels_rgb to flat per-channel multiplicative gain** - `d804bcc` (feat)
2. **Task 2: Rewrite TestCorrectChannels for flat behavior + fix coordinator wiring test** - `18e2027` (test)

## Files Created/Modified
- `Backend/services/color_math.py` - `correct_channels_rgb` body now `out = clip(arr * gains, 0, 255)`; docstring rewritten to static/flat multiplicative tint compensation, no relational claims.
- `Backend/tests/test_color_math.py` - `TestCorrectChannels` rewritten: identity, green-scaled, uniform-across-channels, clip-at-255, scale-down, shape; old relational tests removed.
- `Backend/tests/test_streaming_coordinator.py` - Wiring test `test_frame_loop_applies_color_correction_gain_to_hue_gradient` updated: `gain_g=1.5` now scales green UP (was asserting green reduced under old relational behavior).

## Decisions Made
- Kept scope strictly internal per plan — no rename, no re-wire, no changes to streaming_coordinator.py source, database.py, routers/settings.py, main.py, or any frontend file.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated coordinator wiring test to match new flat semantics**
- **Found during:** Task 2 (full backend suite run)
- **Issue:** `test_streaming_coordinator.py::test_frame_loop_applies_color_correction_gain_to_hue_gradient` asserted the OLD relational behavior (`gain_g=1.5` reduces non-dominant green). The plan assumed cross-file tests only cover wiring/settings, but this one encodes the internal algorithm's directionality, so the algorithm rework broke it directly.
- **Fix:** Updated the assertion to `corrected_px[1] > baseline_px[1]` (green scaled up by the flat gain) and refreshed the docstring; red-unchanged (`gain_r=1.0`) assertion preserved. The test still verifies the same wiring (that `color_correction_g` reaches the shared gradient handed to hue.render).
- **Files modified:** Backend/tests/test_streaming_coordinator.py
- **Verification:** Test passes; full suite shows only pre-existing cameras_router failures.
- **Committed in:** `18e2027` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — test encoding stale behavior)
**Impact on plan:** Necessary to keep the suite green after the intended algorithm change. No scope creep — the test still validates the plan's wiring contract, only its directional assertion changed to match the new flat semantics.

## Issues Encountered
- 12 pre-existing `test_cameras_router.py` failures are unrelated and out-of-scope (documented in STATE.md decision [19.1-01] and phase deferred-items.md). Confirmed pre-existing via git-stash diff — not caused by this change.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Color correction sliders now act as direct, intuitive per-channel multipliers for hardware-tint compensation. Ready for user hardware re-test.

## Self-Check: PASSED

- All modified files present: color_math.py, test_color_math.py, test_streaming_coordinator.py, SUMMARY.md
- Both task commits found in git: d804bcc, 18e2027

---
*Phase: quick-260719-efy*
*Completed: 2026-07-19*
