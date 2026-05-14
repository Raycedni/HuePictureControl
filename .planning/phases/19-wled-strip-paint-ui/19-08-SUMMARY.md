---
phase: 19
plan: "08"
subsystem: backend
tags: [phase-19, wled, fastapi-router, wave-3, channel-crud, orientation]
dependency_graph:
  requires: [19-03, 19-06]
  provides: [channel-crud-endpoints, assignment-endpoints, orientation-patch-endpoint]
  affects: [Frontend/src/api/wled.ts, Backend/routers/wled.py]
tech_stack:
  added: []
  patterns:
    - FastAPI route ordering (literal path segment before path param to avoid greedy match)
    - Per-region orientation narrowing via single UPDATE on (region_id, entertainment_config_id)
    - Service delegation pattern (router -> services.wled_channels for geometry logic)
    - Orientation inheritance on upsert (reads region's current orientation, falls back to 'auto')
key_files:
  created: []
  modified:
    - Backend/routers/wled.py
    - Backend/tests/test_wled_router.py
decisions:
  - "boundary PUT endpoint declared before {channel_id} PUT to prevent FastAPI greedy path match"
  - "orientation inheritance on upsert: body wins, then existing region row, then 'auto'"
  - "PATCH /regions/{rid}/orientation uses single UPDATE on (region_id, config_id) per D-16/D-22"
  - "_make_db() updated with next_channel_n + orientation columns to match Phase 19 schema"
metrics:
  duration: "~15 minutes"
  completed: "2026-05-14"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 19 Plan 08: Channel CRUD + Assignment + Orientation Endpoints Summary

**One-liner:** 8 FastAPI endpoints wired to Phase 19-06 service helpers, enforcing per-region orientation narrowing and atomic boundary resize; all 7 Wave-1 router stubs flipped GREEN (18/18 tests pass).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Pydantic models + service imports | 6a36286 | Backend/routers/wled.py |
| 2 | 8 endpoint handlers + flip 7 stubs | 848a401 | Backend/routers/wled.py, Backend/tests/test_wled_router.py |

## Endpoint Registrations

| Method | Path | Handler | Service |
|--------|------|---------|---------|
| GET | /api/wled/devices/{device_id}/channels | `list_channels` | raw SQL |
| POST | /api/wled/devices/{device_id}/channels | `create_channel` | `create_channel_with_split` |
| PUT | /api/wled/devices/{device_id}/channels/boundary | `resize_channel_boundary` | `resize_boundary` |
| PUT | /api/wled/devices/{device_id}/channels/{channel_id} | `update_channel` | raw SQL |
| DELETE | /api/wled/devices/{device_id}/channels/{channel_id} | `delete_channel` | `delete_channel_with_cascade` |
| GET | /api/wled/assignments | `list_assignments` | raw SQL |
| PUT | /api/wled/assignments | `upsert_assignment` | raw SQL + orientation inheritance |
| DELETE | /api/wled/assignments | `delete_assignment` | raw SQL |
| PATCH | /api/wled/regions/{region_id}/orientation | `patch_region_orientation` | single UPDATE |

## Critical Routing Note

The `PUT /devices/{device_id}/channels/boundary` handler is declared **before** `PUT /devices/{device_id}/channels/{channel_id}` in the file. FastAPI matches routes in declaration order; if `{channel_id}` appeared first, the literal string `"boundary"` would be consumed as a channel ID, making the boundary endpoint unreachable.

## Test Results

```
tests/test_wled_router.py — 18 passed in 0.27s
  (11 pre-existing Phase 17 tests + 7 new Phase 19 tests, 0 skipped)

Full backend suite — 316 passed, 12 failed (pre-existing test_cameras_router.py failures), 23 skipped
```

**7 stubs flipped GREEN:**
- `test_create_channel_basic` — POST 201 + body shape validation
- `test_list_channels_for_device` — seed 2 channels, GET ordered list
- `test_update_channel_rename` — PUT with name, assert renamed
- `test_boundary_resize_atomic` — two adjacent channels, PUT boundary, assert both rows updated
- `test_delete_channel_cascades` — seed channel + assignment, DELETE, assert assignment count == 0
- `test_patch_region_orientation_writes_all_rows` — seed 2 rows same region+config, PATCH, assert both == new value
- `test_upsert_assignment_inherits_region_orientation` — existing row orientation='vertical-TTB', upsert without orientation, new row inherits 'vertical-TTB'

## Pydantic Models Added

- `WledOrientation` — `Literal["auto", "horizontal-LTR", "horizontal-RTL", "vertical-TTB", "vertical-BTT"]`
- `WledChannelOut`, `WledChannelsResponse`, `WledChannelCreate`, `WledChannelUpdate`
- `WledChannelBoundaryUpdate`
- `WledAssignmentIn`, `WledAssignmentOut`, `WledAssignmentsResponse`, `WledAssignmentDelete`
- `WledOrientationPatch`, `WledOrientationPatchResponse`

## Test Fixture Update

`_make_db()` in `test_wled_router.py` updated to include Phase 19 schema columns:
- `wled_devices.next_channel_n INTEGER NOT NULL DEFAULT 1`
- `wled_light_assignments.orientation TEXT NOT NULL DEFAULT 'auto'`

## Deviations from Plan

None — plan executed exactly as written. The test file already used `async def` for the stub tests but the new implementations use `def` (synchronous TestClient pattern), matching the existing Phase 17 test style in the same file.

## Threat Surface Scan

No new network endpoints beyond those specified in the plan's threat model (T-19-11 through T-19-16). All SQL uses parameterised queries (`?` placeholders). `WledOrientation = Literal[...]` enforces enum membership at Pydantic validation time before handlers execute.

## Self-Check: PASSED

- `Backend/routers/wled.py` exists and contains all 9 new route decorators
- `Backend/tests/test_wled_router.py` contains 0 `pytest.skip` markers on Phase 19 tests
- Commits 6a36286 and 848a401 exist in git log
- 18/18 tests pass in `tests/test_wled_router.py`
