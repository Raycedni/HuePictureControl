---
phase: 07-device-enumeration-and-camera-assignment-schema
plan: "02"
subsystem: backend-cameras-router
tags: [cameras, v4l2, device-identity, api, frontend-alert]
dependency_graph:
  requires:
    - enumerate_capture_devices() from capture_v4l2.py (plan 01)
    - get_stable_id() from device_identity.py (plan 01)
    - known_cameras + camera_assignments tables from database.py (plan 01)
  provides:
    - GET /api/cameras
    - POST /api/cameras/reconnect
    - PUT /api/cameras/assignments/{config_id}
    - GET /api/cameras/assignments/{config_id}
    - EditorPage sysfs degraded-identity alert banner
  affects:
    - Backend/routers/cameras.py
    - Backend/main.py
    - Frontend/src/components/EditorPage.tsx
tech_stack:
  added: []
  patterns:
    - run_in_executor for blocking ioctl/sysfs calls in async FastAPI context
    - ON CONFLICT(stable_id) DO UPDATE for idempotent camera upsert
    - 404 fallback contract for camera_assignments (caller uses default device)
key_files:
  created:
    - Backend/routers/cameras.py
    - Backend/tests/test_cameras_router.py
  modified:
    - Backend/main.py
    - Frontend/src/components/EditorPage.tsx
decisions:
  - "enumerate_capture_devices + get_stable_id wrapped in run_in_executor — both do blocking file I/O (ioctl, sysfs reads)"
  - "GET /api/cameras always returns known_cameras rows (not just current scan) to preserve disconnected device history per D-06"
  - "identity_mode set to 'degraded' when any device in scan returns sysfs_available=False, or when no devices found and sysfs dir absent"
  - "PUT /api/cameras/assignments validates camera_stable_id exists in known_cameras before upsert to prevent orphaned assignments"
metrics:
  duration: "13 minutes"
  completed_date: "2026-04-03"
  tasks_completed: 2
  files_created: 2
  files_modified: 2
---

# Phase 7 Plan 02: Cameras Router and Frontend Alert Summary

**One-liner:** Four-endpoint cameras REST router with per-config assignment persistence plus frontend amber alert for sysfs-degraded device identity.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Cameras router with all endpoints (TDD) | ba4239a | cameras.py (new), main.py (modified), test_cameras_router.py (new) |
| 2 | Frontend sysfs degraded-identity alert banner | 83795e8 | EditorPage.tsx (modified) |

## What Was Built

### GET /api/cameras (cameras.py)

Fresh V4L2 scan on every call (DEVC-03 — no caching). Calls `enumerate_capture_devices()` and `get_stable_id()` in `run_in_executor` to keep the async event loop unblocked. Upserts each scanned device into `known_cameras` with current timestamp and device path (D-09). Returns all rows from `known_cameras` — including previously-seen-but-disconnected devices with `connected=False` (D-06). Sets `identity_mode` to `"degraded"` if any device lacked sysfs identity, else `"stable"`.

### POST /api/cameras/reconnect (cameras.py)

Re-runs the full scan logic and matches by `stable_id`. Returns `connected=True` with current `device_path` if found, or `connected=False` with preserved `display_name` if not found. Returns 404 if the `stable_id` was never seen. Updates `known_cameras` with fresh `last_device_path` when reconnected successfully.

### PUT/GET /api/cameras/assignments/{config_id} (cameras.py)

PUT validates `camera_stable_id` against `known_cameras` (404 if unknown), then upserts into `camera_assignments` using `ON CONFLICT DO UPDATE`. GET returns the assignment row or 404 with the CAMA-03 fallback message: "No camera assignment for this config. Default capture device will be used."

### main.py Registration

`cameras_router` imported and registered with `app.include_router()` alongside existing routers.

### EditorPage Alert Banner (EditorPage.tsx)

`useEffect` on mount fetches `GET /api/cameras` and stores `identity_mode`. When `identity_mode === 'degraded'`, renders an amber alert banner above the 20-channel warning. Non-dismissable per UI-SPEC. Exact copy: "Device identity is limited to capture card name. Devices may be misidentified if multiple identical cards are connected."

## Test Results

- 14 new tests in `test_cameras_router.py` — all pass
- Full backend suite: **187 passed, 34 skipped** — no regressions (14 net new vs plan 01)
- Frontend suite: **30 passed** — no regressions

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all endpoints are fully implemented, tested, and wired to real DB tables.

## Self-Check: PASSED

Files verified:
- `Backend/routers/cameras.py` — FOUND
- `Backend/main.py` (contains `cameras_router`) — FOUND
- `Backend/tests/test_cameras_router.py` — FOUND
- `Frontend/src/components/EditorPage.tsx` (contains `identityMode`) — FOUND

Commits verified:
- ba4239a (Task 1) — FOUND
- 83795e8 (Task 2) — FOUND
