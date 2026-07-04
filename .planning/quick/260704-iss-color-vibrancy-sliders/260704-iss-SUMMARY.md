---
phase: quick-260704-iss
plan: 01
subsystem: api
tags: [color-math, numpy, opencv, fastapi, aiosqlite, react, settings]

# Dependency graph
requires:
  - phase: quick-260516-kra
    provides: brightness_cutoff_threshold settings KV pattern (DB seed + router + app.state hydrate + coordinator live read + frontend slider) that this task replicates end-to-end
provides:
  - "color_vibrancy setting (0.0-1.0): saturation-weighted region sampling that suppresses white pixels' chromaticity contribution while preserving region luma"
  - "saturation_boost setting (0.0-1.0): post-hoc HSV-S boost applied to final gradient RGB, HSV V untouched"
  - "boost_saturation_rgb() and _weighted_region_mean()/_saturation_weights() helpers in services/color_math.py"
  - "generic getSetting/putSetting(key) frontend API client + reusable SettingSlider component"
affects: [color_math, streaming_coordinator, settings_router, settings_ui]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Settings KV replication pattern: DB seed row -> GET/PUT router (shared _get_setting/_put_setting helpers) -> app.state hydrate at startup -> per-frame defensive getattr read in coordinator -> generic key-parameterized frontend slider"
    - "Vibrancy=0.0/boost=0.0 short-circuit to the pre-feature code path for byte-identical backward compatibility"

key-files:
  created:
    - Frontend/src/components/Settings/SettingSlider.tsx
    - Frontend/src/components/Settings/SettingSlider.test.tsx
  modified:
    - Backend/services/color_math.py
    - Backend/tests/test_color_math.py
    - Backend/routers/settings.py
    - Backend/main.py
    - Backend/database.py
    - Backend/services/streaming_coordinator.py
    - Backend/tests/test_settings_router.py
    - Frontend/src/api/settings.ts
    - Frontend/src/components/Settings/SettingsPage.tsx
    - Frontend/src/components/Settings/SettingsPanel.tsx

key-decisions:
  - "Refactored settings.py GET/PUT brightness_cutoff_threshold handlers onto shared _get_setting/_put_setting helpers instead of duplicating the validation body 3x (plan explicitly allowed a shared response model; extended that to the full handler body since the validation logic is byte-identical)"
  - "boost_saturation_rgb wraps np.where saturation/ratio math in np.errstate(invalid='ignore', divide='ignore') to suppress harmless 0/0 RuntimeWarnings on all-black/all-gray pixels (Rule 1 bug fix — the math result was already correct via np.where masking, but numpy still warns on the intermediate division)"
  - "vibrancy and boost are read once per frame via a new _read_live_setting() coordinator helper (mirrors the sinks' getattr+try/except pattern) and threaded directly into sub_sample_gradient/boost_saturation_rgb calls in _frame_loop, rather than being read inside HueStreamer/WledStreamer.render() like brightness_cutoff_threshold — required because vibrancy affects gradient computation itself (not just a post-hoc gate), so it must be applied before the sink boundary per the plan's key_links"

requirements-completed: [QUICK-260704-iss]

# Metrics
duration: ~30min
completed: 2026-07-04
---

# Phase quick-260704-iss: Color Vibrancy Sliders Summary

**Two new global settings (color_vibrancy, saturation_boost) wired end-to-end from color_math.py through settings KV storage to two new Settings-page sliders, fixing white-pollution desaturation in region color extraction without touching preview or existing tests.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-07-04T13:40:00+02:00 (approx)
- **Completed:** 2026-07-04T13:50:23+02:00
- **Tasks:** 3
- **Files modified:** 12 (10 modified, 2 created)

## Accomplishments
- `color_math.py` gained `boost_saturation_rgb`, `_saturation_weights`, `_weighted_region_mean`, plus a `vibrancy` param on `extract_region_color`/`sub_sample_gradient` — all backward-compatible (vibrancy 0.0 / boost 0.0 are byte-identical to pre-change code paths)
- Full settings KV wiring for `color_vibrancy` and `saturation_boost` replicating the existing `brightness_cutoff_threshold` pattern: DB seed rows, GET/PUT router endpoints (422 on NaN/Inf/out-of-range), `app.state` hydration at startup, and a per-frame live-read in `StreamingCoordinator._frame_loop`
- Two new reusable `SettingSlider` instances mounted on both `SettingsPage.tsx` and `SettingsPanel.tsx`, fetching on mount and PUTing on change to their own `/api/settings/{key}` endpoint
- All 3 tasks verified via automated backend (pytest) and frontend (vitest) test runs with zero regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Color math — vibrancy-weighted sampling + saturation boost helper** - `640b23a` (feat)
2. **Task 2: Settings KV wiring + coordinator live read** - `783f3fc` (feat)
3. **Task 3: Frontend — two Settings sliders (reusable component)** - `5984d66` (feat)

**Plan metadata:** commit pending (docs: complete plan, made by orchestrator)

## Files Created/Modified
- `Backend/services/color_math.py` - Added `_saturation_weights`, `_weighted_region_mean`, `boost_saturation_rgb`; extended `extract_region_color`/`sub_sample_gradient` with a `vibrancy` param (0.0 default = untouched fast path)
- `Backend/tests/test_color_math.py` - New `TestVibrancy` (6 tests) + `TestSaturationBoost` (4 tests) classes
- `Backend/routers/settings.py` - Refactored into shared `_get_setting`/`_put_setting` helpers (`SettingValueResponse` model); added `/api/settings/color_vibrancy` and `/api/settings/saturation_boost` GET/PUT
- `Backend/main.py` - Hydrates `app.state.color_vibrancy` and `app.state.saturation_boost` at startup with the same defensive try/except pattern as `brightness_cutoff_threshold`
- `Backend/database.py` - Seeds `("color_vibrancy","0.0")` and `("saturation_boost","0.0")` settings rows
- `Backend/services/streaming_coordinator.py` - New `_read_live_setting()` helper; `_frame_loop` reads vibrancy/boost once per frame, threads vibrancy into both `sub_sample_gradient` call sites, wraps both `hue_gradients` and `wled_gradients` dicts with `boost_saturation_rgb`
- `Backend/tests/test_settings_router.py` - 16 new parametrized tests covering both new keys (default, round-trip, boundaries, NaN, app.state mirror, overwrite)
- `Frontend/src/api/settings.ts` - Added generic `getSetting(key)`/`putSetting(key, value)`
- `Frontend/src/components/Settings/SettingSlider.tsx` - New settingKey-parameterized reusable slider component
- `Frontend/src/components/Settings/SettingSlider.test.tsx` - 4 tests (mount default, loaded value, PUT round-trip, error caption) using `settingKey="color_vibrancy"`
- `Frontend/src/components/Settings/SettingsPage.tsx` - Mounts two `<SettingSlider>` instances next to `<BrightnessCutoffControl>`
- `Frontend/src/components/Settings/SettingsPanel.tsx` - Same mounting, kept in sync per RESEARCH.md Pitfall 6

## Decisions Made
- Refactored the brightness_cutoff GET/PUT handlers onto shared `_get_setting`/`_put_setting` helpers rather than copy-pasting the validation body three times — the plan explicitly permitted a shared response model, and the validation logic is identical across all three keys, so this keeps the router DRY without changing any externally-observable behavior (verified: all 9 original brightness tests still pass unchanged)
- Suppressed harmless `RuntimeWarning: invalid value encountered in divide` / `divide by zero encountered in divide` from `boost_saturation_rgb`'s `np.where` saturation math on all-black pixels using `np.errstate` — the masked result was already numerically correct, but the warning was noisy in test output (Rule 1 bug fix)
- vibrancy/boost are read and applied inside `StreamingCoordinator._frame_loop` directly (not inside `HueStreamer`/`WledStreamer.render()` like `brightness_cutoff_threshold`) because vibrancy must influence the gradient sampling itself before either sink sees the data — this follows the plan's explicit `key_links` contract (`streaming_coordinator.py frame loop -> sub_sample_gradient(..., vibrancy=...)`)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Suppressed spurious RuntimeWarning in boost_saturation_rgb**
- **Found during:** Task 1 (running `pytest tests/test_color_math.py`)
- **Issue:** `boost_saturation_rgb`'s `chroma / mx` and `s_new / s` divisions triggered `invalid value encountered in divide` / `divide by zero encountered in divide` RuntimeWarnings on all-black or zero-saturation pixels, even though `np.where` already masked the result to the correct value (0.0 or 1.0 fallback)
- **Fix:** Wrapped the saturation/ratio computation in `with np.errstate(invalid="ignore", divide="ignore"):`
- **Files modified:** `Backend/services/color_math.py`
- **Verification:** `pytest tests/test_color_math.py -x -q` — 47 passed, 0 warnings (was 3 warnings before)
- **Committed in:** `640b23a` (Task 1 commit)

**2. [Rule 3 - Blocking] Recreated /tmp/hpc-venv (was present but empty/broken)**
- **Found during:** pre-execution baseline test run
- **Issue:** `/tmp/hpc-venv` existed as a directory but its `Scripts/` folder (Windows venv layout) was empty — `activate` script and `python.exe` were missing, so `pytest` could not run at all
- **Fix:** Removed the stale directory and recreated it with `python -m venv /tmp/hpc-venv`, then reinstalled `Backend/requirements.txt`
- **Files modified:** none (environment-only, no repo files touched)
- **Verification:** `pytest -q` ran successfully afterward (354 passed / 12 pre-existing failures baseline)
- **Committed in:** N/A (environment setup, not a repo change)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking/environment)
**Impact on plan:** Both fixes were necessary to complete verification; no scope creep into plan functionality.

## Issues Encountered
- Pre-existing 12 `test_cameras_router.py` failures (documented in STATE.md as out-of-scope from a prior quick task) were present in the baseline run before any changes and remained unchanged after all 3 tasks — confirmed out-of-scope per the deviation rules' scope boundary.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `color_vibrancy` and `saturation_boost` are fully live end-to-end: DB → router → app.state → coordinator → color_math → both sinks (Hue and WLED)
- Backend: 383 passed, 12 pre-existing (unrelated) failures, 21 skipped — no regressions
- Frontend: 120 passed, 20 todo (pre-existing), 2 skipped test files (pre-existing) — no regressions
- `routers/capture.py` (preview) confirmed untouched per plan's success criteria
- No blockers for future work

---
*Phase: quick-260704-iss*
*Completed: 2026-07-04*

## Self-Check: PASSED

All 12 code files + the SUMMARY.md verified present on disk; all 3 task commits (`640b23a`, `783f3fc`, `5984d66`) verified present in git log.
