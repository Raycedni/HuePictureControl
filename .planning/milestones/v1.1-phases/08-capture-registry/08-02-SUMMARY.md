---
phase: 08-capture-registry
plan: "02"
subsystem: backend/streaming, backend/routers, backend/lifespan
tags: [capture-registry, streaming-service, camera-assignment, router-migration]
dependency_graph:
  requires: [CaptureRegistry]
  provides: [registry-aware StreamingService, registry-aware routers]
  affects: [main.py, capture.py, preview_ws.py, conftest.py]
tech_stack:
  added: []
  patterns: [per-config camera assignment via DB lookup, registry acquire/release lifecycle]
key_files:
  created: []
  modified:
    - Backend/services/streaming_service.py
    - Backend/tests/test_streaming_service.py
    - Backend/main.py
    - Backend/routers/capture.py
    - Backend/routers/preview_ws.py
    - Backend/tests/conftest.py
    - Backend/tests/test_capture_router.py
decisions:
  - "_resolve_device_path uses two-step DB query: camera_assignments → known_cameras → last_device_path"
  - "_capture_reconnect_loop calls capture.release()/open() directly, NOT registry acquire/release (per D-11)"
  - "PUT /api/capture/device returns 410 Gone — deprecated in favor of camera assignments API"
  - "preview_ws polls registry.get_default() inside the loop to pick up newly acquired backends"
  - "Lifespan no longer opens device eagerly — CaptureRegistry is lazy"
metrics:
  duration: "~15 min"
  completed: "2026-04-04"
  tasks_completed: 2
  files_created: 0
  files_modified: 7
---

# Phase 08 Plan 02: StreamingService Registry Integration Summary

**One-liner:** StreamingService resolves per-config camera assignments from the DB, acquires/releases devices through CaptureRegistry; all routers and fixtures migrated from singleton to registry pattern.

## What Was Built

### Task 1: StreamingService registry integration

- Changed `__init__` signature from `(db, capture, broadcaster)` to `(db, capture_registry, broadcaster)`
- Added `_resolve_device_path(config_id)` — two-step DB lookup: `camera_assignments` (config_id → stable_id) then `known_cameras` (stable_id → last_device_path), falls back to `CAPTURE_DEVICE`
- `start()` resolves device path, calls `registry.acquire(device_path)` via `asyncio.to_thread`
- `_run_loop` finally block calls `registry.release(device_path)` (best-effort) instead of `capture.release()`
- `_capture_reconnect_loop` still calls `capture.release()/open()` directly (per D-11 — reconnect doesn't touch registry)
- 7 new tests added, 29 existing test call sites migrated to `capture_registry` parameter

### Task 2: Lifespan wiring, router migration, fixture updates

- `main.py`: Replaced `create_capture(CAPTURE_DEVICE)` singleton with lazy `CaptureRegistry()`, removed eager `capture.open()`, shutdown calls `registry.shutdown()`
- `capture.py`: Snapshot and debug_color use `registry.get_default()`, PUT /device returns 410 Gone
- `preview_ws.py`: Polls `registry.get_default()` inside the loop for dynamic backend pickup
- `conftest.py`: Both `_make_capture_app_client` and `_make_capture_app_client_with_streaming` now create `mock_registry` with `get_default()` returning `mock_capture`
- `test_capture_router.py`: `TestSetDeviceEndpoint` replaced with single 410 assertion test

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | StreamingService registry integration + _resolve_device_path | 8fa7da9 | streaming_service.py, test_streaming_service.py |
| 2 | Lifespan wiring, router migration, fixture updates | 0077501 | main.py, capture.py, preview_ws.py, conftest.py, test_capture_router.py |

## Test Results

- Streaming service tests: 36 passed
- Capture router tests: 10 passed (was 11, lost 1 from deprecated endpoint consolidation)
- Full suite: 206 passed, 34 skipped (0 failures, no regressions)

## Deviations from Plan

1. Fixed 4 pre-existing test bugs where `_capture_reconnect_loop` tests didn't set `service._capture = mocks["capture"]`, causing infinite loops when `self._capture` was `None`
2. Fixed `test_stop_sequence_order` — `track_release` needed to accept `device_path` argument since `registry.release(device_path)` passes it through

## Known Stubs

None — Phase 08 is fully implemented. CaptureRegistry is wired end-to-end.

## Self-Check: PASSED

- `Backend/services/streaming_service.py` contains `def __init__(self, db, capture_registry, broadcaster)` — confirmed
- `Backend/services/streaming_service.py` contains `async def _resolve_device_path` — confirmed
- `Backend/services/streaming_service.py` contains `camera_assignments WHERE entertainment_config_id` — confirmed
- `Backend/services/streaming_service.py` contains `self._capture_registry.acquire` — confirmed
- `Backend/services/streaming_service.py` contains `self._capture_registry.release` — confirmed
- `Backend/main.py` contains `CaptureRegistry()` and `capture_registry=registry` — confirmed
- `Backend/main.py` contains `registry.shutdown()` — confirmed
- `Backend/main.py` does NOT contain `capture = create_capture(` — confirmed
- `Backend/routers/capture.py` contains `registry.get_default()` — confirmed
- `Backend/routers/capture.py` set_device contains `status_code=410` — confirmed
- `Backend/routers/preview_ws.py` contains `capture_registry` — confirmed
- `Backend/tests/conftest.py` uses `capture_registry` (not `app.state.capture`) — confirmed
- `Backend/tests/test_capture_router.py` TestSetDeviceEndpoint asserts 410 — confirmed
- Full suite green (206 passed) — confirmed
