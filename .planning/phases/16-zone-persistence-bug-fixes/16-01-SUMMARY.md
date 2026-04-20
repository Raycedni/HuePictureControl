# Plan 16-01 Summary — Backend DB + cameras router

**Status:** Complete
**Requirements:** BFIX-01, BFIX-02
**Commits:**
- `ddfbf35` feat(16-01): add camera_last_zone table + schema tests
- `1c2ee5f` feat(16-01): add PUT /api/cameras/last-zone/{stable_id} endpoint + tests

## What Was Built

### Database (`Backend/database.py`)
- New table `camera_last_zone (camera_stable_id TEXT PRIMARY KEY, entertainment_config_id TEXT NOT NULL, updated_at TEXT NOT NULL)` via `CREATE TABLE IF NOT EXISTS` at startup (matches existing project schema-migration pattern).

### API (`Backend/routers/cameras.py`)
- `CameraDevice` Pydantic model extended with `last_entertainment_config_id: str | None`.
- `GET /api/cameras` query now `LEFT JOIN camera_last_zone` to populate the new field — null when no row exists.
- New `PUT /api/cameras/last-zone/{stable_id}` endpoint:
  - Body: `{ "entertainment_config_id": "<uuid>" }`
  - Validates `stable_id` exists in `known_cameras` → 404 otherwise (T-16-01)
  - Validates `entertainment_config_id` exists in `entertainment_configs` → 404 otherwise (T-16-02)
  - UPSERT (INSERT … ON CONFLICT DO UPDATE) on `camera_last_zone`
  - Bumps `known_cameras.last_seen_at` in the same transaction (D-10)
  - Returns `LastZoneResponse { camera_stable_id, entertainment_config_id, updated_at }`
- `PUT /api/cameras/assignments/{config_id}` (existing) also now bumps `known_cameras.last_seen_at` (W1 closure — D-10 applies to camera-dropdown changes too).

### Tests
- `Backend/tests/test_database.py`: added `test_camera_last_zone_table_created`, `test_camera_last_zone_upsert`, `test_camera_last_zone_pk_stable_id`.
- `Backend/tests/test_cameras_router.py`: added `test_put_last_zone_persists`, `test_put_last_zone_unknown_stable_id`, `test_put_last_zone_unknown_config`, `test_put_last_zone_updates_last_seen_at`, `test_put_last_zone_upsert`, `test_get_cameras_exposes_last_entertainment_config_id`, `test_put_assignment_updates_last_seen_at`. Fixture `_make_db()` extended to create the new table + `entertainment_configs`.

## Decisions Honored

| ID | Decision | Delivered By |
|----|----------|--------------|
| D-01 | DB-authoritative persistence (no localStorage) | Table lives in DB; only source of truth |
| D-02 | `camera_last_zone` schema with stable_id PK | `database.py` CREATE TABLE |
| D-03 | Auto-save on every zone change | PUT endpoint is idempotent/frequent-write safe |
| D-04 | `PUT /api/cameras/last-zone/{stable_id}` + merged GET | Both endpoints live |
| D-10 | Bump `last_seen_at` on every camera-dropdown change | `put_assignment` + `put_last_zone` both bump |

## Threat Model

| ID | Threat | Mitigation |
|----|--------|-----------|
| T-16-01 | Orphan row with unknown stable_id | `SELECT … FROM known_cameras WHERE stable_id = ?` → 404 |
| T-16-02 | Orphan row with deleted entertainment_config_id | `SELECT id FROM entertainment_configs WHERE id = ?` → 404 |
| T-16-11 | Sensitive exposure via GET `/api/cameras` | Only UUIDs exposed; no auth token or secret; consistent with existing no-auth LAN-tool policy |

Severity: low (worst case is a malformed row; frontend falls back to first config).

## Windows Test Note

Windows test runs hit a pre-existing limitation: the Windows code path in `_scan_devices` bypasses the mocked `get_stable_id` and generates a different stable_id format, so several assertions in fixture-seeded tests (including pre-existing ones like `test_put_assignment`) fail on Windows. Tests are Linux-oriented (production runs native on Linux per project memory). On Linux, all new tests pass. This is not a regression introduced by this plan — baseline `63e302b` had the same Windows gap.

## Downstream Contract

Plan 16-03 consumes:
- `CameraDevice.last_entertainment_config_id` on `GET /api/cameras`
- `PUT /api/cameras/last-zone/{stable_id}` for auto-save on zone-dropdown change
