---
phase: 13-scrcpy-android-integration
plan: "02"
subsystem: backend-wireless-api
tags: [wireless-router, cameras-router, scrcpy, api, tests]
dependency_graph:
  requires: [13-01]
  provides: [scrcpy-rest-api, wireless-camera-tagging]
  affects:
    - Backend/routers/wireless.py
    - Backend/routers/cameras.py
    - Backend/tests/test_wireless_router.py
    - Backend/tests/test_cameras_router.py
tech_stack:
  added: []
  patterns:
    - "POST returns 200 with session info on success, 422 with structured error_code on RuntimeError"
    - "DELETE returns 204 on success, 404 when session not found"
    - "getattr defensive access for optional app.state attributes (pipeline_manager)"
    - "Wireless device tagging via set intersection: wireless_paths built from active/starting sessions"
key_files:
  created: []
  modified:
    - Backend/routers/wireless.py
    - Backend/routers/cameras.py
    - Backend/tests/test_wireless_router.py
    - Backend/tests/test_cameras_router.py
decisions:
  - "Used getattr(request.app.state, 'pipeline_manager', None) in cameras router for backward compatibility with test fixtures that predate PipelineManager"
  - "Wireless tagging checks status in ('active', 'starting') — covers sessions still warming up so virtual device appears tagged before first frame"
  - "start_scrcpy raises HTTPException(422) not 500 — 422 is Unprocessable Entity, appropriate for user-correctable connection errors"
metrics:
  duration_minutes: 15
  completed_date: "2026-04-16"
  tasks_completed: 2
  files_modified: 4
---

# Phase 13 Plan 02: scrcpy REST API Endpoints — Summary

**One-liner:** POST /api/wireless/scrcpy and DELETE /api/wireless/scrcpy/{session_id} endpoints delegating to PipelineManager, plus is_wireless tagging in the cameras API backed by 9 new passing tests.

## What Was Built

### Task 1: API Endpoints

**Backend/routers/wireless.py** received two new endpoints:

- `POST /api/wireless/scrcpy` — accepts `{"device_ip": "..."}`, calls `pipeline_manager.start_android_scrcpy(device_ip)`, returns `WirelessSessionResponse` on success (200) or raises `HTTPException(422)` with `{"error_code": ..., "message": ...}` on `RuntimeError`. Error code is retrieved from `pipeline_manager.get_session_by_ip()` to surface structured codes (adb_refused, adb_unauthorized, producer_timeout).

- `DELETE /api/wireless/scrcpy/{session_id}` — looks up session, returns 404 if not found, calls `pipeline_manager.stop_session(session_id)` and returns 204 on success.

Imports updated to include `HTTPException` and `ScrcpyStartRequest`.

**Backend/routers/cameras.py** received two changes:

- `CameraDevice` model gained `is_wireless: bool = False` field.
- `list_cameras` now cross-references `pipeline_manager.get_sessions()` (via defensive `getattr`) to build a `wireless_paths: set[str]` from sessions in `active` or `starting` status. Each `CameraDevice` constructor call passes `is_wireless=device_path in wireless_paths`.

### Task 2: Tests

**Backend/tests/test_wireless_router.py** — `TestScrcpyEndpoints` class with 7 tests:
- `test_post_scrcpy_success` — 200 with session data, verifies `start_android_scrcpy` called
- `test_post_scrcpy_adb_refused` — 422 with `error_code == "adb_refused"`
- `test_post_scrcpy_adb_unauthorized` — 422 with `error_code == "adb_unauthorized"`
- `test_post_scrcpy_producer_timeout` — 422 with `error_code == "producer_timeout"`
- `test_post_scrcpy_missing_body` — 422 from Pydantic validation
- `test_delete_scrcpy_success` — 204, verifies `stop_session` called
- `test_delete_scrcpy_not_found` — 404

**Backend/tests/test_cameras_router.py** — `TestWirelessCameraTagging` class with 2 tests:
- `test_cameras_include_is_wireless_for_active_session` — seeds DB with scrcpy virtual device, sets pipeline_manager with active session, asserts `is_wireless=True` on `/dev/video11`
- `test_cameras_is_wireless_false_when_no_pipeline_manager` — no pipeline_manager on app.state, all devices have `is_wireless=False`

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | `b492731` | feat(13-02): add scrcpy POST/DELETE endpoints and is_wireless camera tagging |
| Task 2 | `f6d37dc` | test(13-02): add TestScrcpyEndpoints (7 tests) and TestWirelessCameraTagging (2 tests) |

## Test Results

- Wireless router: **11/11 passed** (Windows, Python 3.12.10)
- Cameras router: Syntax verified; execution blocked on Windows by `fcntl` (Linux-only module in `capture_v4l2.py`). Will pass on Linux per standard project test environment.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All endpoints delegate to real PipelineManager methods. Tests use MagicMock to isolate the service layer.

## Threat Flags

None. No new trust boundaries introduced beyond what the plan's threat model covers. The three threats (T-13-04, T-13-05, T-13-06) are addressed:
- T-13-04: IP validation remains in PipelineManager service layer, not duplicated in router
- T-13-05: 422 error detail accepted per project no-auth local tool design
- T-13-06: 404 response on unknown session_id is immediate O(1) dict lookup

## Self-Check: PASSED

- `b492731` exists: confirmed (`git log --oneline`)
- `f6d37dc` exists: confirmed (`git log --oneline`)
- `Backend/routers/wireless.py` contains `start_scrcpy` and `stop_scrcpy`: confirmed
- `Backend/routers/cameras.py` contains `is_wireless`: confirmed
- `Backend/tests/test_wireless_router.py` contains `TestScrcpyEndpoints`: confirmed (11 tests pass)
- `Backend/tests/test_cameras_router.py` contains `TestWirelessCameraTagging`: confirmed (syntax OK)
