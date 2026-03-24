---
phase: 03-entertainment-api-streaming-integration
plan: 02
subsystem: streaming
tags: [asyncio, dtls, hue-entertainment-pykit, sqlite, color-math, websocket, tdd]

# Dependency graph
requires:
  - phase: 03-entertainment-api-streaming-integration/03-01
    provides: StatusBroadcaster (update_metrics/push_state), activate/deactivate_entertainment_config in hue_client
  - phase: 02-capture-pipeline-color-extraction
    provides: LatestFrameCapture, extract_region_color, rgb_to_xy, build_polygon_mask
  - phase: 01-infrastructure-and-dtls-spike
    provides: hue-entertainment-pykit spike, SQLite schema (bridge_config, light_assignments, regions)
provides:
  - StreamingService async class with 50 Hz capture->DTLS streaming loop
  - start()/stop() lifecycle using asyncio.Event + asyncio.Task
  - _load_channel_map from SQLite (light_assignments JOIN regions)
  - _frame_loop with extract_region_color + rgb_to_xy + set_input per channel
  - _reconnect_loop with exponential backoff capped at 30s
  - Locked stop sequence: stop_stream -> deactivate -> capture.release
  - 20 comprehensive unit tests covering all behaviors
affects:
  - 03-entertainment-api-streaming-integration/03-03 (streaming router wiring)
  - any future phase using StreamingService

# Tech tracking
tech-stack:
  added: []
  patterns:
    - asyncio.Event for run/stop control (run_event.set() starts, run_event.clear() stops)
    - asyncio.Task wrapping run loop for concurrent execution and awaitable completion
    - asyncio.to_thread wrapping all synchronous pykit calls (start_stream, stop_stream, set_input, set_color_space)
    - update_metrics (sync, silent, 50 Hz) vs push_state (async, immediate, state changes)
    - Exponential backoff in reconnect: delay = min(delay * 2, 30), unlimited retries while run_event.is_set()
    - Locked stop sequence as finally block: stop_stream -> deactivate -> capture.release
    - module-scoped pytest fixture for module-level import (avoids cv2 reimport issue)

key-files:
  created:
    - Backend/services/streaming_service.py
    - Backend/tests/test_streaming_service.py
  modified:
    - Backend/tests/test_streaming_service.py (test refinement: module-scoped fixture, frame-count logic)

key-decisions:
  - "module-scoped service_imports fixture used to avoid cv2 AttributeError on repeated module reimport in tests"
  - "Frame loop clears run_event inside get_frame mock (not after) to guarantee exactly one frame per test iteration"
  - "_reconnect_loop reads bridge_ip/username from call args; does NOT re-query DB or touch capture pipeline"

patterns-established:
  - "StreamingService: asyncio.Event run_event controls loop; asyncio.Task _task is awaited on stop()"
  - "Brightness formula: (R*0.2126 + G*0.7152 + B*0.0722) / 255, clamped to 0.01 minimum"
  - "All pykit calls wrapped in asyncio.to_thread to avoid blocking event loop"
  - "update_metrics() called at 50 Hz (silent); push_state() called only for state transitions (immediate)"

requirements-completed: [STRM-01, STRM-02, STRM-03, STRM-04, STRM-05, STRM-06, GRAD-05, CAPT-03, CAPT-04]

# Metrics
duration: 6min
completed: 2026-03-24
---

# Phase 03 Plan 02: StreamingService Summary

**50 Hz async DTLS streaming loop connecting LatestFrameCapture + color_math + StatusBroadcaster + hue-entertainment-pykit with bridge reconnect backoff and locked stop sequence**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-03-24T19:35:36Z
- **Completed:** 2026-03-24T19:41:25Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- StreamingService class with start()/stop() controlling asyncio.Event + asyncio.Task lifecycle
- 50 Hz _frame_loop calling extract_region_color + rgb_to_xy + set_input per channel per frame, brightness clamped to 0.01
- _load_channel_map loading SQLite light_assignments JOIN regions -> {channel_id: mask}
- _reconnect_loop with exponential backoff 1s/2s/4s capped at 30s, capture pipeline untouched during reconnect
- Locked stop sequence in finally block: stop_stream -> deactivate_entertainment_config -> capture.release
- 20 comprehensive unit tests, all passing; full suite 102 tests green, 0 regressions

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: StreamingService failing tests** - `d8cb2aa` (test)
2. **Task 1 GREEN: StreamingService implementation** - `2fa8bcc` (feat)

_Note: TDD task has two commits (test -> feat). Test file also updated in GREEN commit for fixture/logic refinements._

## Files Created/Modified

- `Backend/services/streaming_service.py` - StreamingService class: _run_loop, _frame_loop, _load_channel_map, _reconnect_loop
- `Backend/tests/test_streaming_service.py` - 20 unit tests covering all behaviors

## Decisions Made

- Used module-scoped `service_imports` fixture to avoid cv2 `AttributeError` (`cv2.dnn.DictValue`) that occurs when `streaming_service` module is reimported across test functions (cv2 typing module leaves partial state on second import).
- Frame loop control: tests clear `run_event` inside `get_frame` mock (not after) so the while-loop exits before a second iteration starts, ensuring exactly N channels get set_input called per frame count.
- `_reconnect_loop` receives `bridge_ip` and `username` as parameters rather than re-querying the DB, keeping reconnect focused on the bridge layer and separate from the capture pipeline.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **cv2 reimport issue in tests:** The `service_imports` fixture originally imported `StreamingService` fresh on each test function. The second import attempt failed with `AttributeError: module 'cv2.dnn' has no attribute 'DictValue'` — a known cv2 issue where the typing submodule leaves partial state after first import. Fixed by making the fixture `scope="module"` (import once per test module). This is a Rule 1 auto-fix (bug in test infrastructure, not in production code).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- StreamingService is complete and tested; ready for Plan 03 (streaming router) to wire it into FastAPI with start/stop/status endpoints
- All locked decisions respected: update_metrics (not broadcast) in frame loop; capture continues during reconnect; stop_stream -> deactivate -> release sequence
- 16-channel and 1-channel paths both verified (STRM-06, GRAD-05)

## Self-Check: PASSED

All files present, all commits verified.

---
*Phase: 03-entertainment-api-streaming-integration*
*Completed: 2026-03-24*
