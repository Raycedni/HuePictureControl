---
phase: 02-capture-pipeline-color-extraction
plan: 02
subsystem: api
tags: [fastapi, opencv, v4l2, cie-xy, capture, rest-api]

# Dependency graph
requires:
  - phase: 02-01
    provides: LatestFrameCapture service, color_math (rgb_to_xy, build_polygon_mask, extract_region_color)
provides:
  - "GET /api/capture/snapshot — JPEG image from capture device, 503 if unavailable"
  - "PUT /api/capture/device — hot-swap capture device path without restart"
  - "GET /api/capture/debug/color — CIE xy color for hard-coded center region"
  - "FastAPI lifespan wires LatestFrameCapture; non-fatal if device absent at startup"
affects:
  - phase-04-frontend
  - phase-03-hue-streaming

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Capture service accessed via request.app.state.capture (set in lifespan)"
    - "RuntimeError from capture service maps to HTTP 503"
    - "Lifespan startup: device absence is non-fatal (log warning, continue)"
    - "TDD: conftest fixtures use AsyncMock for async get_frame, MagicMock for sync open"

key-files:
  created:
    - Backend/routers/capture.py
    - Backend/tests/test_capture_router.py
  modified:
    - Backend/main.py
    - Backend/tests/conftest.py

key-decisions:
  - "Lifespan catches RuntimeError from capture.open() and logs a warning instead of crashing — backend must be testable and runnable without hardware"
  - "Debug color endpoint uses hard-coded center polygon [[0.25,0.25],[0.75,0.25],[0.75,0.75],[0.25,0.75]] to satisfy Phase 2 Success Criterion 3"
  - "capture_app_client fixtures in conftest.py use _make_capture_mock() helper to share mock construction across three fixture variants"

patterns-established:
  - "Router test pattern: create dedicated test_app with lifespan that sets mock on app.state; include only the router under test"
  - "Endpoint pattern: catch RuntimeError from service layer -> HTTPException(status_code=503)"

requirements-completed: [CAPT-02, CAPT-05]

# Metrics
duration: 15min
completed: 2026-03-23
---

# Phase 2 Plan 02: Capture Router and Lifespan Wiring Summary

**FastAPI capture pipeline with JPEG snapshot, device hot-swap, and CIE xy debug endpoints — backed by 7 router tests and non-fatal lifespan wiring**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-23T22:00:00Z
- **Completed:** 2026-03-23T22:15:00Z
- **Tasks:** 2 of 2 (Task 2 human-verify checkpoint approved)
- **Files modified:** 4

## Accomplishments
- Created `Backend/routers/capture.py` with three endpoints: snapshot (JPEG), device switch, debug color
- Updated `Backend/main.py` lifespan to create and release `LatestFrameCapture`; non-fatal when device absent
- 7 new router tests with mocked capture service; full suite: 66/66 passing, zero regressions
- TDD executed: RED commit (tests failing on missing module), GREEN commit (implementation passing all tests)

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Add failing capture router tests** - `09d0cd7` (test)
2. **Task 1 (GREEN): Implement capture router and lifespan wiring** - `b12363f` (feat)

3. **Task 2: Human-verify checkpoint** - approved by user

_TDD task has two commits: test (RED) then implementation (GREEN)_

**Plan metadata:** (committed via final docs commit after human verification)

## Files Created/Modified
- `Backend/routers/capture.py` - GET /api/capture/snapshot, PUT /api/capture/device, GET /api/capture/debug/color
- `Backend/main.py` - Lifespan wires LatestFrameCapture; includes capture_router
- `Backend/tests/test_capture_router.py` - 7 tests for all three endpoints
- `Backend/tests/conftest.py` - Three capture fixture variants (working, broken get_frame, broken open)

## Decisions Made
- Lifespan startup wraps `capture.open()` in try/except: device absence logs a warning and does not crash the server. Snapshot endpoint returns 503 when device unavailable. This makes the backend testable/runnable without hardware.
- Debug endpoint returns CIE xy for center 50% region (normalized polygon `[[0.25,0.25],[0.75,0.25],[0.75,0.75],[0.25,0.75]]`) — satisfies Phase 2 success criterion 3.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 2 fully complete — all tasks done and human-verify checkpoint approved
- Phase 3 (Hue streaming) can begin immediately
- Backend starts cleanly without hardware; all tests green

---
*Phase: 02-capture-pipeline-color-extraction*
*Completed: 2026-03-23*
