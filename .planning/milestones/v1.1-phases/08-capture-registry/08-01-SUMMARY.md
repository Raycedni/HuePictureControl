---
phase: 08-capture-registry
plan: "01"
subsystem: backend/capture
tags: [capture, registry, ref-counting, thread-safety, multi-camera]
dependency_graph:
  requires: []
  provides: [CaptureRegistry]
  affects: [streaming_service, preview_ws, capture_router]
tech_stack:
  added: []
  patterns: [threading.Lock for sync-in-async, ref-counted pool pattern]
key_files:
  created:
    - Backend/tests/test_capture_registry.py
  modified:
    - Backend/services/capture_service.py
decisions:
  - "Used threading.Lock (not asyncio.Lock) because callers use asyncio.to_thread — methods run from thread-pool threads"
  - "shutdown() catches and logs exceptions per backend to ensure all are released even if one fails"
  - "13 tests written (exceeded the 10 minimum) including thread safety smoke test"
metrics:
  duration: "~8 min"
  completed: "2026-04-03"
  tasks_completed: 1
  files_created: 1
  files_modified: 1
---

# Phase 08 Plan 01: CaptureRegistry Summary

**One-liner:** Thread-safe ref-counted CaptureBackend pool keyed by device path, enabling multi-camera capture sharing without premature resource release.

## What Was Built

`CaptureRegistry` class appended to `Backend/services/capture_service.py`. The class provides:

- `acquire(device_path)` — creates a backend on first call (via `create_capture()`), opens it, then returns the same backend on subsequent calls; increments ref count each time
- `release(device_path)` — decrements ref count; only calls `backend.release()` and removes from pool when count reaches zero; noop for unknown paths
- `get_default()` — returns the backend for `CAPTURE_DEVICE` or `None`
- `shutdown()` — force-releases all backends regardless of ref count; tolerates per-backend exceptions via try/except + logging

The implementation uses `threading.Lock` (not `asyncio.Lock`) because callers will use `asyncio.to_thread()` — the registry methods run in thread-pool threads, not the event loop.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | CaptureRegistry class and unit tests | 2d77589 | Backend/services/capture_service.py, Backend/tests/test_capture_registry.py |

## Test Results

- Registry tests: 13 passed
- Full suite: 200 passed, 34 skipped (0 failures, no regressions)

## Deviations from Plan

**Auto-additions (Rule 2):**

1. Added `test_two_zones_same_device_release_twice_destroys` — the plan specified 10 behaviors; this additional test validates the symmetric case to `test_two_zones_same_device_no_premature_release`, making the ref-count story complete.

2. Added `test_shutdown_tolerates_release_exception` — plan didn't explicitly call for this test but the implementation includes try/except in shutdown(); added a test verifying the exception tolerance works as intended.

3. Added `TestThreadSafety.test_concurrent_acquire_same_device_returns_same_backend` — thread safety is a stated requirement ("thread-safe pool"); added a smoke test with 5 concurrent threads to verify the lock works correctly.

Total: 13 tests (plan minimum was 10).

## Known Stubs

None — `CaptureRegistry` is fully implemented with no placeholder behavior. Plan 02 will wire it into `StreamingService` and routers.

## Self-Check: PASSED

- `Backend/services/capture_service.py` contains `class CaptureRegistry:` — confirmed
- `Backend/tests/test_capture_registry.py` exists with 13 test functions — confirmed
- Commit `2d77589` exists — confirmed
- All 13 registry tests pass — confirmed
- Full suite (200 passed) — confirmed
