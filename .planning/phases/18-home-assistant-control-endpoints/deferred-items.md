# Phase 18 — Deferred Items

Out-of-scope issues discovered during Phase 18 execution. Do NOT fix in this phase.

## Pre-existing test failures (discovered during Plan 01)

Backend test suite has 12 pre-existing failures in `Backend/tests/test_cameras_router.py`,
all confirmed present BEFORE Plan 18-01 edits (verified via `git stash` baseline run).
These are unrelated to the `ha_state` schema add or `device_path_override` parameter.

Failing tests (all in `tests/test_cameras_router.py`):
- `test_stable_identity_mode` — asserts `identity_mode == "stable"` but gets `"degraded"`
- `test_known_cameras_updated_on_scan`
- `test_reconnect_found` (404 vs 200)
- `test_reconnect_not_found` (404)
- `test_put_assignment` (404)
- `test_put_assignment_upsert` (KeyError)
- `test_zone_health_connected`
- `test_put_last_zone_persists` (404)
- `test_put_last_zone_updates_last_seen_at`
- `test_put_last_zone_upsert` (404)
- `test_get_cameras_exposes_last_entertainment_config_id`
- `test_put_assignment_updates_last_seen_at`

**Total:** 12 failed, 286 passed, 21 skipped (pre-existing state).

Scope: out of Phase 18. Likely related to native-Linux migration (no Docker since v1.2)
affecting `/dev/video*` device detection in the cameras router on Windows.
