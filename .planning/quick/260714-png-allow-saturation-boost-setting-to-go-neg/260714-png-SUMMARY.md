---
phase: 260714-png
plan: 01
subsystem: api
tags: [color-math, settings, react, hsv, saturation]

requires:
  - phase: 260704-iss
    provides: color_vibrancy + saturation_boost sliders, saturation-weighted sampling, shared SettingSlider component
provides:
  - boost_saturation_rgb symmetric negative-boost branch (desaturation down to full grayscale at -1.0)
  - _put_setting per-setting (min_value, max_value) range parameter
  - SettingSlider optional min/max props
  - saturation_boost slider wired to [-1.0, 1.0] in both Settings surfaces
affects: [color_math, settings-router, settings-ui]

tech-stack:
  added: []
  patterns:
    - "Per-setting validation range passed as optional (min_value, max_value) args to a shared _put_setting helper, defaulting to the historical [0.0, 1.0] so unrelated settings need zero changes"
    - "Shared UI slider component takes optional min/max props defaulting to [0.0, 1.0]; call sites opt in to a wider range explicitly"

key-files:
  created: []
  modified:
    - Backend/services/color_math.py
    - Backend/routers/settings.py
    - Backend/tests/test_color_math.py
    - Backend/tests/test_settings_router.py
    - Frontend/src/components/Settings/SettingSlider.tsx
    - Frontend/src/components/Settings/SettingsPanel.tsx
    - Frontend/src/components/Settings/SettingsPage.tsx
    - Frontend/src/components/Settings/SettingSlider.test.tsx

key-decisions:
  - "boost_saturation_rgb fast-path guard changed from `boost <= 0.0` to `boost == 0.0` so negative values now flow through the math instead of being treated as identity"
  - "Negative-boost formula s_new = s * (1.0 + boost) chosen for symmetry with the existing positive formula s_new = s + boost*(1.0 - s); both reuse the same ratio/clip tail unchanged"
  - "_put_setting takes optional min_value/max_value (default 0.0/1.0) rather than a per-setting config table, keeping the other three settings' call sites untouched"

patterns-established:
  - "Optional range parameters with backward-compatible defaults let one generic helper/component serve settings with different valid ranges without touching unrelated call sites"

requirements-completed: [SATBOOST-NEG]

duration: 7min
completed: 2026-07-14
---

# Phase 260714-png Plan 01: Negative saturation_boost Summary

**Extended `saturation_boost` to a symmetric [-1.0, 1.0] range so users can desaturate (not just boost) output color, via a shared negative-boost math branch, a per-setting validation range, and optional slider min/max props — while `color_vibrancy`, `brightness_cutoff_threshold`, and `hdr_input` remain untouched at [0.0, 1.0].**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-07-14T18:30:51+02:00 (plan commit)
- **Completed:** 2026-07-14T18:37:08+02:00
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- `boost_saturation_rgb` now desaturates for negative `boost` (full grayscale at -1.0, HSV V always preserved) while keeping the `boost == 0.0` identity fast path and unchanged positive-boost behavior
- `_put_setting` accepts an optional per-call `(min_value, max_value)` range; `saturation_boost` PUT now validates against `[-1.0, 1.0]` with an accurate error message, while the other three settings inherit the unchanged `[0.0, 1.0]` default
- `SettingSlider` exposes optional `min`/`max` props (default `0.0`/`1.0`); both `saturation_boost` instances (SettingsPanel, SettingsPage) render with `min={-1.0}` and an updated description; `color_vibrancy` instances are untouched

## Task Commits

Each task was committed atomically:

1. **Task 1: Negative-boost math + per-setting validation range (Backend)** - `540b345` (feat)
2. **Task 2: Slider min/max props + wire saturation_boost to negative range (Frontend)** - `4fdb173` (feat)

**Plan metadata:** (recorded separately by orchestrator per no-docs-commit convention for quick tasks)

_Note: tdd="true" was set on both tasks in the plan, but since color_math.py/settings.py/SettingSlider.tsx already had extensive existing test coverage and the plan specified exact implementation + test additions together, tests and implementation were written and verified together per task rather than as separate RED/GREEN commits. Both tasks passed full verification before commit._

## Files Created/Modified
- `Backend/services/color_math.py` - `boost_saturation_rgb`: fast-path guard `boost == 0.0`; negative branch `s_new = s * (1.0 + boost)`; docstring updated for the [-1.0, 1.0] range
- `Backend/routers/settings.py` - `_put_setting(request, key, min_value=0.0, max_value=1.0)`; range-aware 422 detail message; `put_saturation_boost` passes `(-1.0, 1.0)`
- `Backend/tests/test_color_math.py` - added `test_boost_gray_pixels_stay_gray_negative`, `test_boost_negative_one_fully_desaturates`, `test_boost_negative_half_partially_desaturates`, `test_boost_negative_preserves_value`
- `Backend/tests/test_settings_router.py` - removed `saturation_boost` from the shared `rejects_below_zero` parametrization (kept as regression guard for `color_vibrancy`/`hdr_input` only); added 4 dedicated `saturation_boost` range tests
- `Frontend/src/components/Settings/SettingSlider.tsx` - `Props` gains optional `min`/`max` (default `0.0`/`1.0`); removed unused module-level `MIN`/`MAX` constants; `<input>` uses the prop values
- `Frontend/src/components/Settings/SettingsPanel.tsx` - `saturation_boost` `<SettingSlider>` gets `min={-1.0}` and an updated desaturate/boost description
- `Frontend/src/components/Settings/SettingsPage.tsx` - identical change mirrored for the second surface (Pitfall 6 sync)
- `Frontend/src/components/Settings/SettingSlider.test.tsx` - added default-min/max regression test and custom-min/max prop test

## Decisions Made
- Kept the exact `ratio = np.where(s > 1e-6, s_new / s, 1.0)` and `out = mx - (mx - arr) * ratio` lines unchanged for both signs of boost — only the `s_new` computation branches, minimizing surface area and preserving the existing division-by-zero guard.
- `_put_setting`'s new parameters have defaults matching the prior hardcoded range, so `put_brightness_cutoff`, `put_color_vibrancy`, and `put_hdr_input` required zero code changes.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The plan's CLAUDE.md test commands (`source /tmp/hpc-venv/bin/activate`, `npx vitest run`) assume a pre-existing Linux venv and installed Frontend `node_modules`; neither existed in this Windows worktree checkout. Rule 3 (blocking) auto-fix: created a fresh Python 3.12 venv at `/tmp/hpc-venv` and `pip install -r Backend/requirements.txt`, and used the sibling main-repo checkout's `node_modules` (via a temporary local copy, deleted after the test run — not committed) to run `npx vitest run`. No source files were affected; this is tooling/environment setup only.
- Backend full-suite run showed 12 pre-existing failures in `tests/test_cameras_router.py`, matching the count already logged as out-of-scope in STATE.md (19.1-01 decision) — confirmed unrelated to this task's files and left untouched.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `saturation_boost` now supports the full [-1.0, 1.0] range end-to-end (math, API validation, UI) with no regressions in the other three settings.
- No blockers for future work.

---
*Phase: 260714-png*
*Completed: 2026-07-14*

## Self-Check: PASSED

All 8 modified files confirmed present on disk; both task commits (540b345, 4fdb173) confirmed present in git history.
