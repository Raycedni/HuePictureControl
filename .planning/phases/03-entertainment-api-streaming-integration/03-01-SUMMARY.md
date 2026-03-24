---
phase: 03-entertainment-api-streaming-integration
plan: 01
subsystem: api
tags: [websocket, fastapi, httpx, streaming, hue-bridge]

# Dependency graph
requires:
  - phase: 02-capture-pipeline-color-extraction
    provides: Capture service and hue_client base with list_entertainment_configs/list_lights

provides:
  - StatusBroadcaster class with WebSocket fan-out, 1 Hz heartbeat, and immediate push_state
  - activate_entertainment_config and deactivate_entertainment_config in hue_client
  - Unit tests for both services (16 new tests, 82 total)

affects:
  - 03-02 (StreamingService depends on StatusBroadcaster and activate/deactivate)
  - 03-03 (streaming router wires StatusBroadcaster into FastAPI)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fan-out broadcaster pattern: connect/disconnect/update_metrics/push_state with dead-connection cleanup"
    - "1 Hz heartbeat with 50 Hz silent metric updates — clients never flooded"
    - "push_state bypasses rate limit for instant state transition delivery"
    - "Best-effort deactivation: no raise on failure, warning log only"

key-files:
  created:
    - Backend/services/status_broadcaster.py
    - Backend/tests/test_status_broadcaster.py
    - Backend/tests/test_hue_client.py
  modified:
    - Backend/services/hue_client.py

key-decisions:
  - "update_metrics silently updates internal state (called at 50 Hz from frame loop) — heartbeat delivers to clients at 1 Hz"
  - "push_state bypasses 1 Hz rate limit for immediate state transition delivery (streaming/error/idle)"
  - "deactivate_entertainment_config is best-effort: logs warning on failure, never raises (shutdown sequences must not be interrupted)"

patterns-established:
  - "Dead WebSocket detection: catch Exception per-connection during _send_to_all, collect dead list, remove after iteration"
  - "TDD RED → GREEN with test fix for mock setup order (set side_effect after connect to avoid breaking snapshot send)"

requirements-completed: [STRM-03, STRM-04]

# Metrics
duration: 3min
completed: 2026-03-24
---

# Phase 3 Plan 01: StatusBroadcaster and hue_client entertainment helpers

**WebSocket fan-out manager (StatusBroadcaster) with 1 Hz heartbeat and immediate push_state, plus activate/deactivate entertainment configuration helpers for the Hue CLIP v2 API**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-24T19:51:31Z
- **Completed:** 2026-03-24T19:54:22Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- StatusBroadcaster class with connect/disconnect/update_metrics/push_state, 1 Hz heartbeat loop, and dead-connection cleanup
- activate_entertainment_config raises on non-2xx; deactivate_entertainment_config is best-effort (no raise, warning log)
- 16 new unit tests; full suite grows from 66 to 82, all passing

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: StatusBroadcaster tests** - `1a3389e` (test)
2. **Task 1 GREEN: StatusBroadcaster implementation** - `508e332` (feat)
3. **Task 2 RED: hue_client activate/deactivate tests** - `44eddfa` (test)
4. **Task 2 GREEN: hue_client activate/deactivate implementation** - `d669365` (feat)

_Note: TDD tasks have two commits each (test RED then feat GREEN)_

## Files Created/Modified

- `Backend/services/status_broadcaster.py` - StatusBroadcaster with connect/disconnect/update_metrics/push_state/_send_to_all/_heartbeat_loop/start_heartbeat/stop_heartbeat
- `Backend/tests/test_status_broadcaster.py` - 12 unit tests covering all StatusBroadcaster behaviors
- `Backend/tests/test_hue_client.py` - 4 unit tests for activate/deactivate entertainment config helpers
- `Backend/services/hue_client.py` - Added logging import, module logger, activate_entertainment_config, deactivate_entertainment_config

## Decisions Made

- update_metrics does not send to clients (frame loop calls it at 50 Hz; heartbeat delivers to clients at 1 Hz to avoid flooding)
- push_state bypasses the 1 Hz rate limit so state transitions (streaming/error/idle) are delivered immediately per locked user decision
- deactivate_entertainment_config is best-effort: never raises, logs warning only, so shutdown sequences are not interrupted by bridge errors

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed dead WebSocket test mock setup order**
- **Found during:** Task 1 GREEN (StatusBroadcaster tests)
- **Issue:** Test set `send_text` side_effect to raise BEFORE calling `connect()`, but `connect()` also calls `send_text` (snapshot delivery), causing the connect to raise instead of the subsequent `_send_to_all`
- **Fix:** Updated test to call `connect()` first with normal mock, then replace `send_text` with the raising side_effect after connection is established
- **Files modified:** Backend/tests/test_status_broadcaster.py
- **Verification:** All 12 StatusBroadcaster tests pass
- **Committed in:** 508e332 (Task 1 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug in test mock ordering)
**Impact on plan:** Minor test fix only. No scope creep. All plan deliverables met exactly.

## Issues Encountered

None beyond the mock setup order bug documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- StatusBroadcaster and hue_client helpers are fully tested and ready for Plan 02 (StreamingService) to import and compose against
- Plan 02 will call `activate_entertainment_config` before opening DTLS and `deactivate_entertainment_config` on shutdown
- Plan 02 will call `update_metrics` at 50 Hz from the frame loop and `push_state` on state transitions

---
*Phase: 03-entertainment-api-streaming-integration*
*Completed: 2026-03-24*
