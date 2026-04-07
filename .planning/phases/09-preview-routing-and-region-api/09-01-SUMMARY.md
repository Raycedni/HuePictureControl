---
phase: 09-preview-routing-and-region-api
plan: 01
subsystem: api
tags: [websocket, capture, preview, fastapi, python]

# Dependency graph
requires:
  - phase: 08-capture-registry
    provides: CaptureRegistry ref-counted pool with acquire/release/get_default
provides:
  - CaptureRegistry.get() non-ref-counted peek method for passive observers
  - Device-routed preview WebSocket /ws/preview?device= with stable ID resolution
  - conftest.py regions table schema with light_id and entertainment_config_id columns
affects:
  - 09-02-region-api
  - 10-frontend-camera-selector

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Preview WebSocket as passive observer: uses registry.get() (no ref count) instead of acquire()"
    - "Device identity dual-mode: /dev/ prefix = direct path, otherwise = stable_id resolved via known_cameras"
    - "WebSocket required param enforcement: close(1008) before accept when ?device= missing (per D-04)"
    - "Retry loop for device unavailable: WebSocket stays open, sleeps 1s, retries (per D-02)"

key-files:
  created:
    - Backend/tests/test_capture_registry.py (TestGet class — 5 new tests for get() method)
  modified:
    - Backend/services/capture_service.py (added get() non-ref-counted peek method)
    - Backend/routers/preview_ws.py (complete rewrite — device routing, stable ID resolution)
    - Backend/tests/test_preview_ws.py (complete rewrite — unit tests for routing logic)
    - Backend/tests/conftest.py (added light_id and entertainment_config_id to regions table)

key-decisions:
  - "Preview WebSocket is a passive observer — uses registry.get() not acquire() to avoid holding ref count"
  - "Stable ID resolution happens once at connection time, not per-frame (per D-03)"
  - "Close 1008 (Policy Violation) before accept when ?device= missing — not 4000/custom code"

patterns-established:
  - "Peek vs acquire: get() for read-only consumers, acquire() for owners that must call release()"
  - "Stable ID dispatch: startswith('/dev/') short-circuit before DB query"

requirements-completed: [MCAP-02]

# Metrics
duration: 15min
completed: 2026-04-07
---

# Phase 9 Plan 01: Preview Routing and CaptureRegistry.get() Summary

**Device-routed preview WebSocket using non-ref-counted registry.get() with stable ID resolution via known_cameras lookup**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-07T00:00:00Z
- **Completed:** 2026-04-07T00:15:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added `CaptureRegistry.get(device_path)` as a non-ref-counted peek method — preview is a passive observer that doesn't own the backend lifecycle
- Rewrote `/ws/preview` to require `?device=` query param (close 1008 before accept if missing), routing to a specific device via `registry.get(device_path)` instead of `get_default()`
- Added `_resolve_device_path()` helper that short-circuits for `/dev/` paths and queries `known_cameras` for stable IDs
- Fixed `conftest.py` regions table to include `light_id TEXT` and `entertainment_config_id TEXT` columns, matching production schema

## Task Commits

Each task was committed atomically:

1. **Task 1: CaptureRegistry.get() method + conftest schema fix** - `b9f707c` (feat)
2. **Task 2: Preview WebSocket ?device= routing with stable ID resolution** - `4da563b` (feat)

**Plan metadata:** (pending final docs commit)

## Files Created/Modified

- `Backend/services/capture_service.py` - Added `get(device_path)` non-ref-counted peek method after `release()`, before `get_default()`
- `Backend/tests/test_capture_registry.py` - Added `TestGet` class with 5 test cases covering all `get()` behaviors
- `Backend/tests/conftest.py` - Added `light_id TEXT` and `entertainment_config_id TEXT` to regions table schema
- `Backend/routers/preview_ws.py` - Complete rewrite: required `?device=` param, `_resolve_device_path()`, `registry.get()`, retry loop
- `Backend/tests/test_preview_ws.py` - Complete rewrite: unit tests for `_resolve_device_path()` and WebSocket routing logic

## Decisions Made

- Preview uses `registry.get()` not `registry.acquire()` — preview is a passive observer and must not hold a ref count that would prevent streaming zones from releasing backends
- Stable ID resolution is done once at connection time (not per-frame) for efficiency — the resolved `device_path` is reused in the retry loop
- Close code `1008` (Policy Violation) is the correct WebSocket close code when a required parameter is missing

## Deviations from Plan

None - plan executed exactly as written. Both `capture_service.py` and `preview_ws.py` changes were already partially applied (from the b9f707c prior commit noted in git log). Task 2 was the first uncommitted task at execution start.

## Issues Encountered

None — the `b9f707c` commit already covered Task 1 fully. Task 2 changes were in the working tree but uncommitted, so they were verified against acceptance criteria and committed atomically.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 02 (Region API + entertainment_config_id migration) can proceed — conftest schema now has `entertainment_config_id` column ready
- Preview WebSocket is ready for Phase 10 frontend camera selector to wire `?device=` param based on user selection
- `registry.get()` pattern established for any future passive observers (analytics, recording, etc.)

---
*Phase: 09-preview-routing-and-region-api*
*Completed: 2026-04-07*
