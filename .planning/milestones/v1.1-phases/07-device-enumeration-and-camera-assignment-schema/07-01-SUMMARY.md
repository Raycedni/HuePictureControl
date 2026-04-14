---
phase: 07-device-enumeration-and-camera-assignment-schema
plan: "01"
subsystem: backend-device-enumeration
tags: [v4l2, device-enumeration, database, camera-identity, schema]
dependency_graph:
  requires: []
  provides:
    - enumerate_capture_devices() in capture_v4l2.py
    - get_stable_id() in device_identity.py
    - known_cameras table in database
    - camera_assignments table in database
  affects:
    - Backend/services/capture_v4l2.py
    - Backend/database.py
    - Backend/tests/conftest.py
tech_stack:
  added: []
  patterns:
    - V4L2 ioctl VIDIOC_QUERYCAP for device capability filtering
    - sysfs VID/PID/serial for stable USB device identity with fallback to card@bus_info
    - O_RDWR | O_NONBLOCK to avoid blocking on active capture devices
key_files:
  created:
    - Backend/services/device_identity.py
    - Backend/tests/test_device_enum.py
    - Backend/tests/test_device_identity.py
  modified:
    - Backend/services/capture_v4l2.py
    - Backend/database.py
    - Backend/tests/conftest.py
    - Backend/tests/test_database.py
decisions:
  - "Used bytearray(104) + struct.unpack_from at offset 88 for device_caps — consistent with existing _setup_device() pattern in the same file"
  - "get_stable_id() returns tuple[str, bool] to signal caller whether identity is stable (sysfs) or degraded (card@bus_info)"
  - "No linuxpy dependency added — existing ctypes/ioctl infrastructure in capture_v4l2.py is sufficient for enumeration without a new package"
metrics:
  duration: "2 minutes"
  completed_date: "2026-04-03"
  tasks_completed: 2
  files_created: 3
  files_modified: 4
---

# Phase 7 Plan 01: Device Enumeration and Camera Assignment Schema Summary

**One-liner:** V4L2 device enumeration with capability filtering plus two new DB tables for multi-camera camera assignment persistence.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Device enumeration function and stable identity module | 42eb2cc | device_identity.py (new), capture_v4l2.py (extended), test_device_enum.py (new), test_device_identity.py (new) |
| 2 | Database schema and conftest extension | 8233ba1 | database.py, conftest.py, test_database.py |

## What Was Built

### enumerate_capture_devices() (capture_v4l2.py)

New function that scans `/dev/video*`, opens each with `O_RDWR | O_NONBLOCK`, issues `VIDIOC_QUERYCAP`, reads `device_caps` at offset 88, and returns only nodes where `device_caps & 0x01` (V4L2_CAP_VIDEO_CAPTURE). Returns `list[V4L2DeviceInfo]` sorted by device path. Metadata-only nodes (bit 0x01 not set) are silently excluded.

### get_stable_id() (device_identity.py)

New module with a single exported function. Reads USB identity from `/sys/class/video4linux/{device}/device/idVendor` and `idProduct` (plus optional `serial`). Returns `("{vid}:{pid}:{serial}", True)` or `("{vid}:{pid}", True)` when sysfs is accessible. Falls back to `("{card}@{bus_info}", False)` when sysfs raises `FileNotFoundError` or `OSError` (e.g., in some Docker/WSL2 configurations).

### Database Tables (database.py)

Two new tables added after `light_assignments`:

- **known_cameras** — stable_id TEXT PK, display_name TEXT NOT NULL, last_seen_at TEXT, last_device_path TEXT. Supports upsert via INSERT OR REPLACE.
- **camera_assignments** — entertainment_config_id TEXT PK, camera_stable_id TEXT NOT NULL, camera_name TEXT NOT NULL. One row per entertainment zone, persists across DB close/reopen.

### conftest.py and test_database.py

Both updated to include the new tables. Five new database tests covering table creation, persistence across reopen, upsert behavior, and the fallback contract (no row = API-layer fallback to CAPTURE_DEVICE env var).

## Test Results

- 13 new tests in test_device_enum.py + test_device_identity.py — all pass
- 5 new tests in test_database.py — all pass
- Full backend suite: **173 passed, 34 skipped** — no regressions

## Deviations from Plan

None — plan executed exactly as written.

No `linuxpy` dependency was added per the deviation note in the action section: the existing `_VIDIOC_QUERYCAP` constant and bytearray/struct approach already present in the file was used directly. This is consistent with the CLAUDE.md recommendation that the stdlib fallback is viable when the existing ctypes infrastructure is already in place.

## Known Stubs

None — all functions are fully implemented and tested.

## Self-Check: PASSED

Files verified:
- `Backend/services/device_identity.py` — FOUND
- `Backend/services/capture_v4l2.py` (contains `enumerate_capture_devices`) — FOUND
- `Backend/database.py` (contains `known_cameras`) — FOUND
- `Backend/tests/test_device_enum.py` — FOUND
- `Backend/tests/test_device_identity.py` — FOUND
- `Backend/tests/test_database.py` (contains `test_camera_assignments_table_created`) — FOUND

Commits verified:
- 42eb2cc (Task 1) — FOUND
- 8233ba1 (Task 2) — FOUND
