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
