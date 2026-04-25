---
phase: 17-wled-backend-and-streaming
plan: 02
subsystem: database

requires:
  - phase: 17-wled-backend-and-streaming
    provides: 17-01 mock_capture._default_frame fixture (consumed by sub_sample_gradient tests)
provides:
  - wled_devices, wled_channels, wled_light_assignments tables (created by init_db)
  - sub_sample_gradient(frame, region, n) — per-LED RGB sampler
affects: ["17-04", "17-05", "17-06", "17-07"]

tech-stack:
  added: []
  patterns:
    - "Three-table WLED schema (devices / channels / region-assignments) with composite PK on assignments"
    - "FK clauses as documentation-only (no PRAGMA foreign_keys = ON); cascade deletes implemented in router code"

key-files:
  created: []
  modified:
    - "Backend/database.py"
    - "Backend/services/color_math.py"
    - "Backend/tests/test_database.py"
    - "Backend/tests/test_color_math.py"

key-decisions:
  - "FK ON DELETE CASCADE clauses in DDL are documentation-only — SQLite ignores without PRAGMA. Cascade implemented in Plan 17-07 DELETE handler (per A5 in RESEARCH)."
  - "sub_sample_gradient clamps N to longest_axis_length (Pitfall 8 route) instead of producing duplicate identical samples beyond the pixel resolution"
  - "Slab around each sample center is 3 px wide (col_center ± 1) — absorbs single-pixel noise without smearing across the gradient"
  - "Output ordering is RGB (cv2.mean returns BGR; we swap on assignment) so downstream code can index [0]=R, [1]=G, [2]=B without confusion"

patterns-established:
  - "sub_sample_gradient: bounding-box longest-axis selection + per-position 3-px slab + cv2.mean(slab, mask=slab_mask) + BGR-to-RGB swap"
  - "WLED schema reads cleanly from Plan 07 router code: SELECT id, ip, name, led_count, enabled FROM wled_devices ORDER BY created_at"

requirements-completed:
  - WLED-01
  - WLED-02
  - WLED-05
  - WSTR-03

duration: ~7min
completed: 2026-04-25
---

# Phase 17 Plan 02: WLED Schema + Sub-Sample Gradient Summary

**Three WLED tables landed in init_db (devices, channels, light_assignments) and sub_sample_gradient gives per-LED RGB sampling along the longest bbox axis.**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-04-25 inline
- **Completed:** 2026-04-25
- **Tasks:** 2 (TDD discipline)
- **Files modified:** 4

## Accomplishments

- **WLED schema (Task 1)**: three new `CREATE TABLE IF NOT EXISTS` blocks in `init_db` per D-07. `wled_devices` enforces `UNIQUE(ip)` and defaults `enabled` to 1; `wled_channels` references `wled_devices(id)` with documentary FK; `wled_light_assignments` has a composite PK `(region_id, wled_channel_id, entertainment_config_id)` mirroring the existing Hue `light_assignments` shape and per-config scope (D-08).
- **sub_sample_gradient (Task 2)**: pure function in `color_math.py` returning an `(n, 3)` uint8 RGB array sampled along the region's longest bounding-box axis (per D-10). Each LED `i` samples position `i/(n-1)` of the longer dimension; a 3-px slab around the center is averaged via `cv2.mean(slab, mask=slab_mask)`. N=1 collapses to `extract_region_color`. N greater than the longest axis is clamped (Pitfall 8 route).

## Task Commits

1. **Task 1: WLED schema (3 tables)** — `f8236b5` (feat)
2. **Task 2: sub_sample_gradient** — `11103de` (feat)

## Files Created/Modified

- `Backend/database.py` — added three `CREATE TABLE IF NOT EXISTS` blocks before `await db.commit()`. FK clauses included as documentation; no `PRAGMA foreign_keys = ON` (per A5).
- `Backend/services/color_math.py` — added `sub_sample_gradient` (~50 LOC) and exported it in module docstring. Reuses `extract_region_color` for N=1 path.
- `Backend/tests/test_database.py` — appended 7 new tests for WLED schema (table presence × 3, UNIQUE(ip), enabled DEFAULT 1, composite PK rejection, IF NOT EXISTS idempotency). Also deduplicated three stale identical copies of these tests left over from a failed prior worker run (lines 348-577 deleted).
- `Backend/tests/test_color_math.py` — appended `TestSubSampleGradient` class with 5 tests; imports `_default_frame` from the Plan 01 mock_capture fixture.

## Decisions Made

- **FK clauses are documentary, not enforced**: SQLite without `PRAGMA foreign_keys = ON` ignores FK constraints. The project intentionally omits the PRAGMA (per RESEARCH A5); cascade deletes are implemented in the Plan 17-07 router DELETE handler. The FK lines in DDL serve as code-level documentation of the intended relationships.
- **Clamping over uniform-output for tiny regions**: Pitfall 8 offered two routes — clamp N to longest_axis_length, or produce N duplicate samples regardless. Chose clamping because (a) returning a smaller array correctly signals to WledStreamer that fewer LEDs got distinct colors, (b) avoids implying spatial resolution that doesn't exist.
- **3-pixel slab width**: balances noise absorption against gradient smearing. Single-pixel sampling would be flickery; full bounding-box averaging would erase the gradient. Half-width 1 (3 px total: center ± 1) is a clean middle.
- **Test-side import via `tests.fixtures.mock_capture`**: matches the existing pytest rootdir convention (Backend/) — same as how `test_database.py` imports `from database import init_db`.

## Deviations from Plan

**1. [Stale test duplication] Removed 2 duplicate copies of WLED schema tests from test_database.py**
- **Found during:** Task 1 (preparing to add tests)
- **Issue:** test_database.py was modified before this session and contained three identical copies of all 7 WLED schema tests (lines 232-345, 348-461, 464-577). Likely a residue of a failed prior worker run that retried the append three times.
- **Fix:** Removed the second and third copies; kept the first canonical block. Tests now run once each.
- **Files modified:** Backend/tests/test_database.py
- **Verification:** `pytest tests/test_database.py -q` -> 20 passed (was failing with "duplicate function definition" warnings before)
- **Committed in:** f8236b5 (Task 1 commit, since it shipped with the schema)

---

**Total deviations:** 1 (cleanup of pre-existing stale append). No scope creep.

## Issues Encountered

None during execution. The pre-existing dedup issue was found and resolved inline.

## User Setup Required

None — schema migrations apply automatically on `init_db` via `CREATE TABLE IF NOT EXISTS`. Existing user databases will gain the three new empty tables on next backend start.

## Next Phase Readiness

- **Plan 17-03** can now build packet builders against confirmed schema constraints (e.g. tests will INSERT devices with valid `id`/`ip` columns).
- **Plan 17-05** coordinator can SELECT from `wled_light_assignments` JOIN `wled_channels` to compute `N_region` for the region_plan query.
- **Plan 17-06** integration tests can monkey-patch `_build_region_plan` to return realistic gradient arrays and assert WledStreamer slices them correctly.
- **Plan 17-07** router CRUD can rely on UNIQUE(ip) for 409 duplicate detection.

---
*Phase: 17-wled-backend-and-streaming*
*Plan: 02*
*Completed: 2026-04-25*
