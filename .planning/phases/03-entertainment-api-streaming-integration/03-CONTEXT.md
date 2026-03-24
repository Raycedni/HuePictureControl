# Phase 3: Entertainment API Streaming Integration - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Connect the capture pipeline output (Phase 2) to the DTLS streaming session (Phase 1 spike) and deliver measurable end-to-end color synchronization under 100ms. This phase builds the streaming loop, start/stop lifecycle, error recovery, and real-time status WebSocket. No UI changes — Phase 4 builds the frontend that consumes these endpoints.

</domain>

<decisions>
## Implementation Decisions

### Stop behavior
- Graceful drain: finish sending the current frame's colors, then deactivate entertainment mode via REST API
- Bridge handles light restoration — deactivating entertainment mode returns lights to their previous scene/state automatically
- Capture device released immediately on Stop (frees USB for other processes; ~200ms warmup cost on next Start is acceptable)
- Sequence: finish current packet → deactivate entertainment config → close DTLS → release capture device

### Error recovery — bridge disconnect
- Auto-reconnect with exponential backoff: 1s, 2s, 4s... capped at 30s
- Unlimited retries (bridge reboots can take 2-3 minutes; user can press Stop to cancel)
- Full re-activation on reconnect: PUT /entertainment_configuration/{id} to re-activate, then open new DTLS session (bridge silently rejects DTLS without active entertainment mode)
- Push state transitions to /ws/status: 'bridge disconnected' → 'reconnecting (attempt N)' → 'reconnected'
- Continue capturing frames during bridge reconnect (capture pipeline runs independently)

### Error recovery — capture card disconnect
- Stop streaming entirely: stop capture, close DTLS, deactivate entertainment mode
- Push error to /ws/status with human-readable message
- User must replug the capture card and press Start manually (auto-retry for USB disconnect is unreliable)

### Status WebSocket (/ws/status)
- 1 Hz heartbeat with: FPS, latency, bridge connection state, packets sent, packets dropped, sequence number
- Immediate push on state transitions (start, stop, error, reconnect) in addition to heartbeat
- Streaming state enum: 'idle' | 'starting' | 'streaming' | 'reconnecting' | 'error' | 'stopping'
- Human-readable error messages: 'Bridge disconnected', 'Capture device lost', 'Reconnecting (attempt 3)'
- Broadcast to all connected WebSocket clients (multiple browser tabs supported)
- No per-channel color data in status feed (not selected — can add in v2 if needed)

### Claude's Discretion
- Asyncio loop architecture (how capture → color extraction → packet building → DTLS send is structured)
- HueStream v2 binary packet format implementation
- Thread pool management for blocking cap.read()
- Keep-alive implementation (resend if silent >9.5s)
- Entertainment configuration activation/deactivation REST call patterns
- Region-to-channel mapping data flow from SQLite to send loop

</decisions>

<specifics>
## Specific Ideas

- Graceful drain on Stop was preferred over hard cutoff — the last color update should be fully transmitted before closing
- Bridge reconnect should feel automatic to the user (unlimited retries, always re-activate entertainment config)
- Capture card loss is treated as a physical event requiring user intervention, unlike bridge network blips which are recoverable

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `spike/dtls_test.py`: Working `create_bridge()` → `Entertainment()` → `Streaming()` → `set_color_space("xyb")` → `set_input((x, y, bri, channel))` pattern — port this into an async service
- `services/capture_service.py`: `LatestFrameCapture` with `get_frame()` async method — the capture side of the loop
- `services/color_math.py`: `rgb_to_xy()`, `build_polygon_mask()`, `extract_region_color()` — the color extraction pipeline
- `services/hue_client.py`: `list_entertainment_configs()` — async entertainment config discovery
- `database.py`: Schema already has `entertainment_configs`, `regions`, `light_assignments` tables

### Established Patterns
- FastAPI lifespan for service initialization/teardown (`main.py`)
- `request.app.state.X` for accessing shared services from route handlers
- `asyncio.to_thread()` for wrapping blocking calls (capture_service pattern)
- Non-fatal initialization with 503 fallback (capture device pattern)
- `logging.getLogger(__name__)` throughout

### Integration Points
- `main.py` lifespan: add streaming service initialization alongside existing capture + DB
- `routers/capture.py`: add `POST /api/capture/start` and `POST /api/capture/stop` endpoints
- `app.state`: will need streaming_service, status_broadcaster references
- `hue-entertainment-pykit`: `Streaming.start_stream()`, `set_input()`, `stop_stream()` are synchronous — need `asyncio.to_thread` wrappers

</code_context>

<deferred>
## Deferred Ideas

- Per-channel color data in /ws/status — could enable live color preview widgets (v2 requirement AUI-04)

</deferred>

---

*Phase: 03-entertainment-api-streaming-integration*
*Context gathered: 2026-03-24*
