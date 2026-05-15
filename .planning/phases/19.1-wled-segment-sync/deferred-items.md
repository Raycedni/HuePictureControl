# Phase 19.1 — Deferred Items

Out-of-scope issues discovered during execution. Tracked here for future cleanup.

## Pre-existing Failures (Out of Scope)

### Plan 01 (2026-05-14)

**12 failing tests in `Backend/tests/test_cameras_router.py`** — confirmed pre-existing by
stashing Plan 01 changes and re-running the file (still 12 failures, 14 passes). All return
404 where 200 expected, suggesting the cameras router URL prefix or routing changed without
test updates. Unrelated to Phase 19.1 (WLED segment sync). Should be picked up by a separate
bug-fix plan or `/gsd-debug` session.

Failing tests:
- `test_stable_identity_mode`
- `test_known_cameras_updated_on_scan`
- `test_reconnect_found`
- `test_reconnect_not_found`
- `test_put_assignment`
- `test_put_assignment_upsert`
- `test_zone_health_connected`
- `test_put_last_zone_persists`
- `test_put_last_zone_updates_last_seen_at`
- `test_put_last_zone_upsert`
- `test_get_cameras_exposes_last_entertainment_config_id`
- `test_put_assignment_updates_last_seen_at`

### Plan 03 (2026-05-14)

**`test_phase19_1_e2e.py::test_cache_survives_db_reopen`** auto-activated when Plan 03 shipped
`services.wled_segments`, then failed with `sqlite3.IntegrityError: NOT NULL constraint failed:
wled_devices.created_at`. The Wave 0 stub (created in Plan 01) seeds `wled_devices` without the
`created_at` column, which is `NOT NULL` in the real production schema produced by `init_db`
(database.py line 105). Bug is in the test fixture, not in `reconcile_segments`.

Owner: **Plan 04** — per the file's own docstring ("Wired in Plan 04 (router)... Replaces
test_phase19_e2e.py once Plan 05 deletes it"). Plan 04 will either fix the seeding statement
or rewrite the test against the new refresh endpoint. Out of scope for Plan 03 per scope
boundary rule (only auto-fix issues DIRECTLY caused by current task's changes; this is a
pre-existing test fixture bug).

**Resolved in Plan 04 (2026-05-15):** Task 2 rewired `test_phase19_1_e2e.py` to (a) include
`created_at` in the `INSERT INTO wled_devices` seed and (b) replace the invented
`'left-to-right'` orientation with a valid `WledOrientation` literal (`'horizontal-LTR'`). The
refresh-smoke variant now boots a real FastAPI lifespan + `init_db` round-trip + httpx mock and
asserts the cache is written end-to-end. Both e2e tests pass.

### Plan 04 (2026-05-15)

**2 pre-existing `test_phase19_e2e.py` failures + 1 `test_phase17_e2e.py` failure** remain
RED on master. Root cause is the Phase 19.1 schema drop of `wled_channels` (Plan 02 D-20);
these legacy e2e files still reference the dropped table. Per Plan 02 summary's "Downstream
Tests Remaining RED" map and `19.1-PATTERNS.md` D-23 mapping, the entire `test_phase19_e2e.py`
file is **replaced by** `test_phase19_1_e2e.py` (which now passes after Plan 04). The Phase 17
e2e failure is the same root cause for the same Phase 17 file.

Owner: **Plan 05** (streaming coordinator rewrite — re-grounds the Phase 17/19 streaming path
on `wled_seg_cache` instead of `wled_channels`) or **Plan 08** (whichever lands the deletion
of these legacy e2e files first). Out of scope for Plan 04 because (a) Plan 04 owns the
router surface and its own tests, not the streaming-coordinator path, and (b) the failure is
caused by the Plan 02 schema drop, not by anything Plan 04 changed.

Failing tests:
- `tests/test_phase19_e2e.py::test_persistence`
- `tests/test_phase19_e2e.py::test_paint_assign_stream_smoke`
- `tests/test_phase17_e2e.py::test_register_stream_observe_packets_delete`

**Resolved in Plan 05 (2026-05-15):**
`tests/test_phase17_e2e.py::test_register_stream_observe_packets_delete` is now GREEN.
Plan 05 Task 2 rewrote both the file's inline schema and the per-test seeds to use
Phase 19.1 tables (`wled_seg_cache` D-12 + composite-key `wled_light_assignments`
D-13). The cascade-delete assertion was retargeted from `wled_channels` to
`wled_seg_cache`. The second test (`test_enabled_false_device_receives_zero_packets`)
got the same fixture migration and remains GREEN.

The 2 `test_phase19_e2e.py` failures stay deferred — Plan 08 owns the file deletion
per D-23 mapping; `test_phase19_1_e2e.py` (already green from Plan 04) is its
designated replacement.
