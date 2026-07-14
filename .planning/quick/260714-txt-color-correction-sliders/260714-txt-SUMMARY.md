---
phase: 260714-txt
plan: 01
subsystem: api
tags: [color-math, settings, react, hue-shift, color-correction]

requires:
  - phase: 260704-iss
    provides: color_vibrancy + saturation_boost sliders, shared SettingSlider component, per-frame live-settings read pattern
  - phase: 260714-png
    provides: _put_setting per-setting (min_value, max_value) range parameter, SettingSlider optional min/max props
provides:
  - correct_channels_rgb(rgb, gain_r, gain_g, gain_b) relational per-channel color correction, generalizing boost_saturation_rgb
  - color_correction_r/g/b settings (default 1.0, range [0.5, 1.5]) persisted, exposed via API, hydrated on startup
  - per-frame color correction applied after saturation boost on the shared gradient for both Hue and WLED sinks
  - three color-correction sliders in both Settings surfaces
affects: [color_math, settings-router, streaming-coordinator, settings-ui]

tech-stack:
  added: []
  patterns:
    - "Relational per-channel correction: out = mx - (mx - arr) * gains, where gains is a (3,) vector broadcasting per-channel instead of a single scalar ratio -- generalizes boost_saturation_rgb's dominant-channel-invariant structure from one scalar knob to three independent ones"
    - "_get_setting takes an optional per-call default (0.0 unchanged for existing callers) mirroring the existing per-call (min_value, max_value) pattern on _put_setting, so a feature whose neutral value is NOT 0.0 can reuse the same shared helper"
    - "_read_live_setting(key, default) called with an explicit non-zero default (1.0) for gain-style settings, so a missing/None app_state (tests, startup race) is always identity rather than destructively zeroing the output"

key-files:
  created: []
  modified:
    - Backend/services/color_math.py
    - Backend/tests/test_color_math.py
    - Backend/database.py
    - Backend/routers/settings.py
    - Backend/main.py
    - Backend/tests/test_settings_router.py
    - Backend/services/streaming_coordinator.py
    - Backend/tests/test_streaming_coordinator.py
    - Frontend/src/components/Settings/SettingsPanel.tsx
    - Frontend/src/components/Settings/SettingsPage.tsx

key-decisions:
  - "correct_channels_rgb uses a (3,) gains vector broadcast against the last axis (out = mx - (mx - arr) * gains) rather than per-channel branching, keeping the function fully vectorized and structurally identical to boost_saturation_rgb's ratio-based formula"
  - "color_correction_{r,g,b} seed at '1.0' (identity) and default to 1.0 everywhere (DB seed, _get_setting fallback, app.state hydration, coordinator live-read default) -- deliberately breaking from every other setting in this file, which defaults to 0.0"
  - "Correction is applied AFTER boost_saturation_rgb, once per shared gradient, reaching both the Hue path (hue_gradients comprehension) and the WLED path (_wled_pipeline._compute) identically -- never duplicated, never touching /ws/preview"

patterns-established:
  - "A setting whose neutral/identity value is not the file's historical default (0.0) can ride the same shared _get_setting/_put_setting/_read_live_setting helpers by passing an explicit default at each call site, without changing any existing caller's behavior"

requirements-completed: [COLORCORRECT-RGB]

duration: ~15min
completed: 2026-07-14
---

# Phase 260714-txt Plan 01: Color Correction Sliders Summary

**Added three relational color-correction gains (`color_correction_r/g/b`, default 1.0, range 0.5–1.5) that let the user compensate for a residual hardware tint in their Hue/WLED lights, using the same dominant-channel-invariant math trick as `boost_saturation_rgb` so pure colors of other hues are never discolored.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-14 (plan read + codebase exploration)
- **Completed:** 2026-07-14T21:46:04+02:00 (final task commit)
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments
- `correct_channels_rgb(rgb, gain_r, gain_g, gain_b)` added to `color_math.py`, directly after `boost_saturation_rgb`: identity fast path (same-object return) at all-1.0 gains; `out = mx - (mx - arr) * gains` leaves each pixel's dominant (max) channel exactly unchanged for any gain values, while correcting that same channel wherever it is non-dominant — proven by a dual test (pure green [10,250,15] stays at green=250 under gain_g=1.5; orange [250,120,40] under the SAME gain_g=1.5 has green reduced to 55)
- `color_correction_r/g/b` settings seeded at `"1.0"` in `database.py`, exposed via `GET`/`PUT /api/settings/color_correction_{r,g,b}` validating `[0.5, 1.5]` with a 1.0 missing-row/default fallback (new optional `default` param on `_get_setting`, existing callers unaffected), hydrated in `main.py` startup
- `StreamingCoordinator._frame_loop` reads the three gains once per frame (default 1.0 via `_read_live_setting`) and applies `correct_channels_rgb` immediately after `boost_saturation_rgb` on the shared gradient, identically for the Hue path (`hue_gradients` comprehension) and the WLED path (`_wled_pipeline._compute`) — `/ws/preview` is untouched
- Three `SettingSlider` instances (R/G/B, `min={0.5}` `max={1.5}`) added to both `SettingsPanel.tsx` and `SettingsPage.tsx`, no changes to the shared `SettingSlider` component itself (it already supported custom `min`/`max` from quick-task 260714-png)

## Task Commits

Each task was committed atomically:

1. **Task 1: correct_channels_rgb relational correction + unit tests** - `7774032` (feat)
2. **Task 2: Persist + expose color_correction_r/g/b settings** - `febadc0` (feat)
3. **Task 3: Apply correction per-frame in the coordinator + frontend sliders** - `2616e7a` (feat)

**Plan metadata:** (recorded separately by orchestrator per no-docs-commit convention for quick tasks)

_Note: tdd="true" was set on all three tasks in the plan, but per the plan's explicit TDD-mode-off instruction (mirroring quick-task 260714-png), implementation and tests were written and verified together per task rather than as separate RED/GREEN commits. All three tasks passed full verification (backend + relevant frontend suites) before commit._

## Files Created/Modified
- `Backend/services/color_math.py` - added `correct_channels_rgb(rgb, gain_r, gain_g, gain_b)` after `boost_saturation_rgb`
- `Backend/tests/test_color_math.py` - added `TestCorrectChannels` (identity, vibrant-green, corrected-orange, dominant-invariance, gray-invariance, single-pixel-shape)
- `Backend/database.py` - seeded `color_correction_r/g/b` at `"1.0"` via the existing `INSERT OR IGNORE` pattern
- `Backend/routers/settings.py` - `_get_setting` gained an optional `default` param; added three GET/PUT route pairs for `color_correction_{r,g,b}` validating `[0.5, 1.5]`
- `Backend/main.py` - hydration block extended: `app.state.color_correction_{r,g,b} = 1.0` defaults, then overwritten from the DB via the extended `SELECT ... WHERE key IN (...)` list
- `Backend/tests/test_settings_router.py` - added a dedicated parametrized block (`color_correction_r/g/b`): default-1.0 GET, round-trip PUT, boundary accept/reject at 0.5/1.5, NaN rejection, live app.state update
- `Backend/services/streaming_coordinator.py` - imported `correct_channels_rgb`; read `gain_r/gain_g/gain_b` once per frame (default 1.0); wrapped the Hue path's `boost_saturation_rgb(...)` call and the WLED path's `_compute()` result in `correct_channels_rgb(..., gain_r, gain_g, gain_b)`
- `Backend/tests/test_streaming_coordinator.py` - added `_solid_orange_frame()` helper and `test_frame_loop_applies_color_correction_gain_to_hue_gradient`, comparing a baseline run (`app_state=None`) against a `color_correction_g=1.5` run and asserting green is reduced while red (dominant) is unchanged
- `Frontend/src/components/Settings/SettingsPanel.tsx` - added three `SettingSlider` instances (`color_correction_r/g/b`, `min={0.5}` `max={1.5}`) after the `hdr_input` toggle
- `Frontend/src/components/Settings/SettingsPage.tsx` - identical addition, mirrored per RESEARCH.md Pitfall 6 (both surfaces stay in sync)

## Decisions Made
- Kept `correct_channels_rgb`'s structure a direct generalization of `boost_saturation_rgb`: same `mx = arr.max(axis=-1, keepdims=True)` per-pixel dominant-channel extraction, same `out = mx - (mx - arr) * <multiplier>` tail, just swapping the single scalar `ratio` for a `(3,)` `gains` vector that broadcasts across R/G/B independently.
- `_get_setting`'s new `default` parameter defaults to `0.0`, matching every existing call site's historical behavior — only the three new `color_correction_*` GET handlers pass `1.0` explicitly. No other setting's default changed.
- The coordinator's `_read_live_setting(key, default)` calls for the three gains pass `1.0` explicitly (not the method's own `0.0` default), so a `None` `app_state` (unit tests, or a race at startup before hydration) can never zero out a light's channel — it always falls back to true identity.

## Deviations from Plan

None - plan executed exactly as written. All three tasks' `<action>` and `<verify>` steps were followed as specified; no Rule 1-4 auto-fixes were needed.

## Issues Encountered
- The plan's CLAUDE.md test command (`source /tmp/hpc-venv/bin/activate`) assumes a Linux-style venv layout; this Windows checkout's venv at `/tmp/hpc-venv` uses `Scripts/activate` instead of `bin/activate` (Windows venv layout). Used `source /tmp/hpc-venv/Scripts/activate` instead — no code or plan changes needed, environment activation path only.
- Full backend suite run showed the same 12 pre-existing failures in `tests/test_cameras_router.py` already logged as out-of-scope (Linux/V4L2-specific, unrelated to this task's files) in the 260714-png SUMMARY — confirmed unchanged in both count and identity, left untouched.

## User Setup Required

None - no external service configuration required. The three new sliders will appear in both Settings surfaces immediately after deployment, defaulting to 1.00 (no change to current light output) until the user adjusts them.

## Next Phase Readiness
- `color_correction_r/g/b` are fully wired end-to-end (math, DB, API, live coordinator read, both sinks, both UI surfaces) with full backend + frontend regression coverage.
- No blockers for future work. The user can now use the sliders to compensate for the residual hardware tint identified in `.planning/debug/hdr10-color-hue-shift.md` without discoloring already-correct colors.

---
*Phase: 260714-txt*
*Completed: 2026-07-14*

## Self-Check: PASSED

All 10 modified files confirmed present on disk; all three task commits (7774032, febadc0, 2616e7a) confirmed present in git history. Backend suite: 447 passed, 12 pre-existing unrelated failures (test_cameras_router.py), 21 skipped. Frontend suite: 131 passed, 20 todo, 2 skipped test files.
