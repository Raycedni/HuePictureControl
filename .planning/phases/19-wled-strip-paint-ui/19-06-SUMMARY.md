---
phase: 19
plan: "06"
subsystem: backend-service
tags: [phase-19, wled, backend-service, overlap-split, wave-2]
dependency_graph:
  requires: [19-01, 19-03]
  provides: [wled_channels_service]
  affects: [routers/wled.py, 19-07, 19-10]
tech_stack:
  added: []
  patterns: [aiosqlite-transaction, try-commit-except-rollback, parameterised-sql]
key_files:
  created:
    - Backend/services/wled_channels.py
  modified: []
decisions:
  - "Classify overlaps before calling _next_channel_name so a classification error does not waste a counter value"
  - "Use single underscore for _next_channel_name (module-private by convention, still importable for tests)"
  - "Row access uses try/except fallback for both aiosqlite.Row (key access) and plain tuple (index access)"
  - "4 rollback sites: one per multi-statement helper (create_channel_with_split, resize_boundary, delete_channel_with_cascade) plus _next_channel_name counter increment is inside create's transaction"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-14T13:09:29Z"
  tasks_completed: 1
  files_changed: 1
---

# Phase 19 Plan 06: WLED Channels Service Summary

Pure aiosqlite service module shipping overlap auto-split cases A-G (D-02), monotonic Channel-N naming (D-10), atomic boundary resize (D-03), and cascade delete (D-04) in 335 lines of transaction-wrapped Python.

## What Was Built

### Backend/services/wled_channels.py (335 lines, created)

Four exported coroutines with no FastAPI dependency:

| Function | Decision | Transaction model |
|----------|----------|-------------------|
| `create_channel_with_split` | D-02 (cases A-G) + D-10 | try/commit/except rollback |
| `_next_channel_name` | D-10 (monotonic, no-recycle) | called inside create's transaction |
| `resize_boundary` | D-03 (atomic boundary drag) | try/commit/except rollback |
| `delete_channel_with_cascade` | D-04 (cascade to assignments) | try/commit/except rollback |

### Overlap Auto-Split Case Coverage

| Case | Description | Trigger condition | Action |
|------|-------------|-------------------|--------|
| A | No overlap | `e < start_new` or `s > end_new` | Leave alone — no writes |
| B | Strict interior split | `s < start_new and end_new < e` | Update left half (keeps id+name), insert right half (new id+Channel N), insert painted |
| C | Exact match | `start_new <= s and e <= end_new` (where s==start_new, e==end_new) | Delete + cascade, insert new with Channel N |
| D | Crosses left boundary | `start_new <= s <= end_new < e` | Update existing start_led = end_new+1 (keeps id+name), insert painted |
| E | Crosses right boundary | `s < start_new <= e <= end_new` | Update existing end_led = start_new-1 (keeps id+name), insert painted |
| F | Multiple channels crossed | Multiple rows match D+G+E in order | Update edge channels, delete swallowed ones (cascade), insert painted |
| G | Encloses one channel | `start_new <= s and e <= end_new` | Delete + cascade, insert painted |

Cases C and G share the same condition (`start_new <= s and e <= end_new`). C is the single-channel variant, G is the same condition applied when the channel is fully enclosed; both are handled by the `to_delete` path.

### Channel-N Monotonic Naming

- `_next_channel_name` reads `wled_devices.next_channel_n`, returns `f"Channel {n}"`, increments column by 1
- Counter never decrements on delete — fulfilled by the column-only increment pattern (D-10)
- Phase 17 seed `'Strip'` channel is inserted with a raw INSERT that does not call `_next_channel_name`, so the first paint always yields `Channel 1`

### Transactional Safety

- Classification of overlaps happens BEFORE `_next_channel_name` is called — a classification failure cannot waste a counter value
- `_next_channel_name` counter increment (the UPDATE to `next_channel_n`) is executed inside `create_channel_with_split`'s transaction scope; if the subsequent INSERT fails, the rollback undoes both the INSERT and the counter increment
- 4 `await db.rollback()` calls (acceptance criteria required >= 3)
- 2 `DELETE FROM wled_light_assignments` sites (one in swallow path inside create, one in delete_channel_with_cascade)

## Test Results

```
14 passed in 0.06s
```

All 14 Wave 0 stubs in `Backend/tests/test_wled_channels.py` flipped from SKIPPED to PASSED:

- test_overlap_split_case_a_no_overlap PASSED
- test_overlap_split_case_b_strict_interior PASSED
- test_overlap_split_case_c_exact_match PASSED
- test_overlap_split_case_d_crosses_left_boundary PASSED
- test_overlap_split_case_e_crosses_right_boundary PASSED
- test_overlap_split_case_f_multiple_swallowed PASSED
- test_overlap_split_case_g_encloses_existing PASSED
- test_next_channel_name_monotonic PASSED
- test_next_channel_name_survives_rename PASSED
- test_seed_strip_does_not_consume_n PASSED
- test_resize_boundary_atomic_two_row_update PASSED
- test_resize_boundary_min_1_led_clamp PASSED
- test_delete_channel_cascades_to_assignments PASSED
- test_create_channel_rejects_invalid_range PASSED

Phase 17 e2e regression: `test_phase17_e2e.py` — 2 passed.

Full suite: 309 passed, 30 skipped, 12 failed. The 12 failures are all in `test_cameras_router.py` and are pre-existing (verified by running the same suite on the git HEAD before our commit — identical failure set).

## Commits

| Hash | Message |
|------|---------|
| 9367f3b | feat(19-06): ship wled_channels service with overlap auto-split cases A-G |

## Deviations from Plan

None — plan executed exactly as written. The action block in Task 1 provided the full implementation; minor refinements made:
- Used `try/except (TypeError, KeyError)` in `_next_channel_name` and `create_channel_with_split` row access (plan used `hasattr(row, "keys")` which does not work reliably with aiosqlite.Row objects whose dict-like access raises KeyError rather than TypeError on missing keys). The tests pass with either approach; KeyError is the more precise catch.
- `to_insert_right_half` stores `(start, end)` tuples instead of the plan's `(start, end, original_name)` — the original_name was unused in the insert (right half always gets a fresh Channel N name), so it was dropped to reduce noise.

## Known Stubs

None. The service module has no hardcoded placeholder values; all logic is live.

## Threat Flags

None. No new network endpoints or auth paths introduced. All SQL uses parameterised queries (`?` placeholders). Threat register items T-19-04 through T-19-08 are all mitigated as designed.

## Self-Check: PASSED

- `Backend/services/wled_channels.py` exists: FOUND
- Commit `9367f3b` exists: FOUND
- 14/14 tests passed: CONFIRMED
