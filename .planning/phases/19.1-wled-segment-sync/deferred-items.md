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
