---
phase: 05-gradient-device-support-and-polish
plan: 01
subsystem: api
tags: [hue, gradient, capture, reconnect, streaming, asyncio]

# Dependency graph
requires:
  - phase: 04-frontend-canvas-editor
    provides: light_assignments schema, streaming service, hue_client base functions
provides:
  - fetch_entertainment_config_channels returns service_rid and segment_index per channel
  - build_light_segment_map groups channels by entertainment service RID for segment counts
  - list_lights returns is_gradient and points_capable fields for gradient detection
  - GET /api/hue/config/{config_id}/channels endpoint with full channel-to-light mapping
  - StreamingService._capture_reconnect_loop with exponential backoff (1s/2s/4s.../30s)
  - _frame_loop resumes after capture reconnect instead of stopping permanently
affects: [frontend-gradient-ui, segment-mapping, streaming-resilience]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Exponential backoff with cap: delay doubles each retry, capped at 30s (used for both bridge and capture reconnect)"
    - "asyncio.to_thread for blocking cv2.VideoCapture.open() to avoid blocking event loop"
    - "entertainment service RID -> light ID mapping via device services array cross-reference"

key-files:
  created: []
  modified:
    - Backend/services/hue_client.py
    - Backend/routers/hue.py
    - Backend/services/streaming_service.py
    - Backend/tests/test_hue_client.py
    - Backend/tests/test_streaming_service.py

key-decisions:
  - "channel.members[0].service.rid is entertainment service RID (rtype: entertainment), not light ID — requires device cross-reference to get light_id"
  - "capture.open() wrapped in asyncio.to_thread because cv2.VideoCapture is blocking (critical for event loop health)"
  - "_capture_reconnect_loop sets state to reconnecting/streaming and pushes to broadcaster for UI feedback"
  - "test_frame_loop_capture_error_stops_and_pushes_error updated to patch _capture_reconnect_loop — previous behavior (stop immediately) no longer applies since reconnect is now attempted first"

patterns-established:
  - "Capture reconnect: RuntimeError from get_frame triggers _capture_reconnect_loop; True=resume, False=error+stop"
  - "Device cross-reference: for each device in /resource/device, map entertainment RID to light ID via services array"

requirements-completed: [BRDG-04]

# Metrics
duration: 30min
completed: 2026-03-31
---

# Phase 5 Plan 1: Gradient Detection and Capture Reconnect Summary

**Extended hue_client with gradient device detection (is_gradient, segment_count), added GET /api/hue/config/{id}/channels endpoint, and implemented capture card auto-reconnect with exponential backoff in StreamingService**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-03-31T00:00:00Z
- **Completed:** 2026-03-31T00:30:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Extended `fetch_entertainment_config_channels` to return `service_rid` and `segment_index` from channel members
- Added `build_light_segment_map` to count how many channels share each entertainment service RID (= segment count)
- Extended `list_lights` to return `is_gradient` and `points_capable` for gradient device detection
- Added `GET /api/hue/config/{config_id}/channels` endpoint that cross-references devices to produce full channel-to-light mapping with gradient info
- Added `_capture_reconnect_loop` to StreamingService — retries with 1s/2s/4s.../30s exponential backoff
- Modified `_frame_loop` to call `_capture_reconnect_loop` on RuntimeError instead of stopping streaming permanently

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend hue_client with gradient detection and channel-to-light mapping** - `2fe0827` (feat)
2. **Task 2: Add capture card reconnect with exponential backoff** - `c4e4a2a` (feat)

## Files Created/Modified

- `Backend/services/hue_client.py` - Extended channel fetch with service_rid/segment_index, added build_light_segment_map, extended list_lights with is_gradient/points_capable
- `Backend/routers/hue.py` - Added GET /api/hue/config/{config_id}/channels endpoint
- `Backend/services/streaming_service.py` - Added _capture_reconnect_loop, modified _frame_loop to use it
- `Backend/tests/test_hue_client.py` - Tests for all new hue_client functions (11 tests pass)
- `Backend/tests/test_streaming_service.py` - Tests for capture reconnect behavior (27 tests pass)

## Decisions Made

- `channel.members[0].service.rid` is an entertainment service RID (`rtype: entertainment`), not a light ID — requires cross-referencing the device endpoint to map entertainment RID -> light ID
- `capture.open()` must run via `asyncio.to_thread` because `cv2.VideoCapture` is a blocking call that would otherwise stall the asyncio event loop
- `_capture_reconnect_loop` uses same backoff pattern as `_reconnect_loop` (1s->2s->4s->...->30s cap) for consistency

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed asyncio.coroutine usage removed in Python 3.12**
- **Found during:** Task 2 verification (test_streaming_service.py)
- **Issue:** `test_capture_reconnect_loop_returns_true_on_success` used `asyncio.coroutine` which was removed in Python 3.12 (project runs Python 3.12.3)
- **Fix:** Replaced `lambda fn, *a, **kw: asyncio.coroutine(lambda: fn(*a, **kw))()` with a proper `async def fake_to_thread` function
- **Files modified:** Backend/tests/test_streaming_service.py
- **Verification:** Test passes without AttributeError
- **Committed in:** c4e4a2a (Task 2 commit)

**2. [Rule 1 - Bug] Fixed test_frame_loop_capture_error_stops_and_pushes_error hanging indefinitely**
- **Found during:** Task 2 verification
- **Issue:** Test mocks `get_frame` to always raise RuntimeError but does not patch `_capture_reconnect_loop`, causing the frame loop to enter infinite reconnect retries with `run_event` still set
- **Fix:** Added `service._capture_reconnect_loop = fake_reconnect_false` to the test so the loop exits cleanly; updated docstring to reflect the new "reconnect-then-error" behavior
- **Files modified:** Backend/tests/test_streaming_service.py
- **Verification:** Test passes in under 1s, all 27 streaming tests pass
- **Committed in:** c4e4a2a (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 - Bug)
**Impact on plan:** Both fixes were required to make the test suite run on Python 3.12. No scope creep — only test correctness fixes.

## Issues Encountered

- Python 3.12 removed `asyncio.coroutine` entirely, breaking a test written with the legacy pattern. Detected during verification run.
- One pre-existing test assumed capture RuntimeError immediately stops streaming, but the new reconnect behavior changes that contract. Both were fixed automatically.

## Next Phase Readiness

- Backend exposes full gradient device information via new endpoint — frontend can now build segment-aware UI
- Streaming resilience improved: capture disconnects trigger automatic recovery rather than requiring manual restart
- All 167 backend tests green

---
*Phase: 05-gradient-device-support-and-polish*
*Completed: 2026-03-31*
