---
phase: 19-wled-strip-paint-ui
plan: 03
subsystem: database
tags: [phase-19, wled, schema-migration, sqlite, aiosqlite, idempotent]

# Dependency graph
requires:
  - phase: 17-wled-foundation
    provides: wled_devices + wled_channels + wled_light_assignments tables

provides:
  - wled_light_assignments.orientation TEXT NOT NULL DEFAULT 'auto' column
  - wled_devices.next_channel_n INTEGER NOT NULL DEFAULT 1 column
  - Two idempotent ALTER TABLE migration blocks in init_db
  - Two Phase 19 idempotency tests in test_database.py (green)

affects:
  - 19-04 (wled_channels service queries next_channel_n)
  - 19-05 (orientation PATCH writes to wled_light_assignments.orientation)
  - 19-07 (streaming coordinator reads orientation for sub-sample axis resolution)
  - 19-08 (wled_channels fixture uses both columns)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Idempotent ALTER TABLE: try/await db.execute/await db.commit/except Exception: pass — mirrors existing regions.light_id pattern at top of init_db"

key-files:
  created: []
  modified:
    - Backend/database.py
    - Backend/tests/test_database.py

key-decisions:
  - "Placed both ALTER TABLE blocks after wled_light_assignments CREATE and before the terminal await db.commit()/return db — matches existing migration order convention"
  - "Used try/except Exception (not OperationalError) to match existing project pattern and absorb any SQLite error variant on duplicate-column attempts"
  - "Added test_init_db_idempotent_phase19 and test_init_db_idempotent_next_channel_n to test_database.py as part of this plan (Plan 19-01 which was supposed to seed them had not yet executed)"

patterns-established:
  - "Phase 19 schema migration pattern: idempotent ALTER TABLE with Phase-specific comment referencing design decision ID (D-16) and RESEARCH.md section"

requirements-completed: [WMAP-01, WMAP-04]

# Metrics
duration: 4min
completed: 2026-05-14
---

# Phase 19 Plan 03: Schema Migrations Summary

**Two idempotent ALTER TABLE migrations added to init_db: `wled_light_assignments.orientation TEXT NOT NULL DEFAULT 'auto'` and `wled_devices.next_channel_n INTEGER NOT NULL DEFAULT 1`**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-14T12:51:35Z
- **Completed:** 2026-05-14T12:55:08Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- `wled_light_assignments.orientation` column added idempotently — Wave 4 coordinator can now read/write per-region orientation for sub-sample axis resolution
- `wled_devices.next_channel_n` column added idempotently — Wave 2 service can use the monotonic counter so Channel N never recycles freed numbers
- Both migrations follow the exact `try/except Exception: pass` pattern established by the existing `regions.light_id` ALTER block at lines 49-54
- All 22 `test_database.py` tests pass; full backend suite stable at 289 passed / 12 pre-existing failures (all in `test_cameras_router.py`, unrelated) / 21 skipped

## Task Commits

Each task was committed atomically:

1. **Task 1: Append two idempotent ALTER TABLE migration blocks + Phase 19 idempotency tests** - `fbb2749` (feat)

**Plan metadata:** (SUMMARY commit — see final commit hash)

## Files Created/Modified

- `Backend/database.py` — Two ALTER TABLE blocks inserted at lines 127-151, before terminal `await db.commit(); return db`
- `Backend/tests/test_database.py` — Two new tests appended: `test_init_db_idempotent_phase19` and `test_init_db_idempotent_next_channel_n`

## Decisions Made

- Placed both ALTER TABLE blocks after the `wled_light_assignments` CREATE TABLE and before the final `await db.commit()` — consistent with the convention where migrations follow their target tables
- `except Exception` (not `except aiosqlite.OperationalError`) — matches the existing project pattern in the file exactly
- Idempotency tests added here (not in 19-01 as planned) because Plan 19-01 had not executed yet; tests use column-presence guard logic from the 19-01 plan spec so they would have skipped at Wave 0 had they been pre-seeded

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added Phase 19 idempotency tests to test_database.py**
- **Found during:** Task 1 (schema migration implementation)
- **Issue:** Plan 19-03 acceptance criteria required `test_init_db_idempotent_phase19` and `test_init_db_idempotent_next_channel_n` to exist (seeded by Plan 19-01) and flip from skipped → green. Plan 19-01 had not yet executed on this branch, so the tests were absent.
- **Fix:** Added the two tests using the exact column-presence-guard + idempotency-assertion shape specified in Plan 19-01 Task 2 action block C. Tests use `:memory:` DB and PRAGMA table_info checks.
- **Files modified:** `Backend/tests/test_database.py`
- **Verification:** Both tests pass green immediately (migration is live); `pytest tests/test_database.py` exits 0 with 22 passed
- **Committed in:** `fbb2749` (part of task commit)

---

**Total deviations:** 1 auto-fixed (Rule 2 — missing critical test coverage)
**Impact on plan:** Necessary to satisfy 19-03 acceptance criteria. Tests are exactly what 19-01 would have added; no scope creep.

## Issues Encountered

- Python venv at `/tmp/hpc-venv` was a Windows-format venv without `bin/pytest` — used `/c/Users/Lukas/AppData/Local/Programs/Python/Python312/Scripts/pytest.exe` to run tests instead
- Full suite showed 16 failures on first run; confirmed 4 extra were flaky (test isolation issue in pre-existing code) — running the affected modules in isolation showed 0 new failures from this plan

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Wave 2 (Plan 19-04): `wled_channels` service can safely query `wled_devices.next_channel_n`
- Wave 3 (Plan 19-05): orientation PATCH endpoint can write `wled_light_assignments.orientation`
- Wave 4 (Plan 19-07): streaming coordinator can read `orientation` for per-region sub-sample axis resolution
- No blockers

## Self-Check: PASSED

- `Backend/database.py` — FOUND
- `Backend/tests/test_database.py` — FOUND
- `.planning/phases/19-wled-strip-paint-ui/19-03-SUMMARY.md` — FOUND
- Commit `fbb2749` — FOUND in git log

---
*Phase: 19-wled-strip-paint-ui*
*Completed: 2026-05-14*
