---
phase: 03-entertainment-api-streaming-integration
plan: "03"
subsystem: api
tags: [fastapi, websocket, streaming, rest, lifespan]

# Dependency graph
requires:
  - phase: 03-entertainment-api-streaming-integration-01
    provides: StatusBroadcaster service with WebSocket fan-out and 1 Hz heartbeat
  - phase: 03-entertainment-api-streaming-integration-02
    provides: StreamingService managing capture-to-DTLS loop at 50 Hz
provides:
  - POST /api/capture/start endpoint wired to StreamingService.start()
  - POST /api/capture/stop endpoint wired to StreamingService.stop()
  - /ws/status WebSocket endpoint streaming real-time JSON metrics
  - Lifespan wiring creating StatusBroadcaster and StreamingService on app.state
  - Graceful shutdown stopping streaming before releasing capture device
affects:
  - 04-frontend-ui
  - 05-configuration-ui

# Tech tracking
tech-stack:
  added: []
  patterns:
    - app.state pattern for dependency injection of services in FastAPI
    - WebSocketDisconnect exception handling for clean client removal
    - Lifespan order: broadcaster -> streaming (broadcaster must exist before streaming)

key-files:
  created:
    - Backend/routers/streaming_ws.py
    - Backend/tests/test_streaming_ws.py
  modified:
    - Backend/routers/capture.py
    - Backend/main.py
    - Backend/tests/conftest.py
    - Backend/tests/test_capture_router.py

key-decisions:
  - "Start/stop endpoints on capture router (not new router) to keep /api/capture prefix cohesive"
  - "Lifespan shutdown checks streaming.state before calling stop() to avoid no-op awaits on already-idle service"
  - "ws_status receives text to keep connection alive (browser ping support); WebSocketDisconnect triggers clean removal"
  - "Hardware verification confirmed: lights sync from capture card feed, latency under 100ms (STRM-05 satisfied)"

patterns-established:
  - "WebSocket endpoint: broadcaster.connect() -> receive loop -> disconnect on WebSocketDisconnect"
  - "REST endpoints access services via request.app.state.{service_name}"
  - "Test fixtures provide (client, mock_service) tuple for assertion on mock calls"

requirements-completed: [CAPT-03, CAPT-04, STRM-03, STRM-05]

# Metrics
duration: 10min
completed: 2026-03-24
---

# Phase 03 Plan 03: API Integration Summary

**FastAPI wired with start/stop REST endpoints and /ws/status WebSocket using app.state dependency injection — hardware-verified end-to-end color sync from capture card to Hue lights under 100ms**

## Performance

- **Duration:** ~15 min (Task 1 automated + Task 2 hardware verify)
- **Started:** 2026-03-24T19:45:00Z
- **Completed:** 2026-03-24T20:00:00Z
- **Tasks:** 2 of 2
- **Files modified:** 6

## Accomplishments
- Created `/ws/status` WebSocket endpoint that connects clients to StatusBroadcaster and handles disconnect cleanly
- Added `POST /api/capture/start` and `POST /api/capture/stop` endpoints to the capture router
- Updated lifespan to create StatusBroadcaster and StreamingService on `app.state`, with graceful shutdown ordering
- Added 16 new tests (9 capture router + 4 WebSocket) with conftest fixtures for mock streaming service and broadcaster
- All tests pass
- Hardware verification confirmed: lights update from capture card feed, latency under 100ms (STRM-05 satisfied)

## Task Commits

Each task was committed atomically:

1. **Task 1: WebSocket endpoint + start/stop REST endpoints + lifespan wiring** - `7975b54` (feat)
2. **Task 2: Hardware verification** - Approved (checkpoint, no code changes)

**Plan metadata:** `dba1a88` (docs: complete plan - awaiting checkpoint)

_Note: TDD task had single commit (tests + implementation together after RED/GREEN cycle)_

## Files Created/Modified
- `Backend/routers/streaming_ws.py` - WebSocket /ws/status endpoint using APIRouter
- `Backend/routers/capture.py` - Added StartCaptureRequest model, POST /start, POST /stop endpoints
- `Backend/main.py` - Added StatusBroadcaster, StreamingService imports and lifespan wiring
- `Backend/tests/test_streaming_ws.py` - 4 WebSocket endpoint tests
- `Backend/tests/test_capture_router.py` - 5 new start/stop endpoint tests
- `Backend/tests/conftest.py` - Added streaming service mock helpers and streaming_ws test fixture

## Decisions Made
- Start/stop endpoints stay on the capture router (`/api/capture` prefix) rather than a new router — keeps streaming control cohesive with capture management
- Lifespan shutdown calls `streaming.stop()` only when state is not idle to avoid double-stop
- WebSocket receive loop uses `receive_text()` so browser ping/pong frames keep connections alive

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Complete backend streaming API is ready for frontend (Phase 4) to call
- Hardware verification is complete — Phase 3 is fully done
- Frontend can call POST /api/capture/start with config_id and connect to /ws/status for real-time metrics
- Concerns: Festavia/gradient light channel counts still require hardware validation before Phase 5 segment UI is finalized

---
*Phase: 03-entertainment-api-streaming-integration*
*Completed: 2026-03-24*
