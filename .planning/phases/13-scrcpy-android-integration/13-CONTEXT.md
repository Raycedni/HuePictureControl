# Phase 13: scrcpy Android Integration - Context

**Gathered:** 2026-04-16
**Status:** Ready for planning

<domain>
## Phase Boundary

An Android device connected to the same WiFi network can be mirrored to the system via ADB over WiFi and scrcpy, producing a virtual camera that feeds the existing capture-to-lights pipeline. This phase adds the scrcpy-specific API endpoints (POST/DELETE), ADB WiFi connection management, stale-frame-based auto-reconnect, and wireless source tagging in the camera API. The PipelineManager and v4l2loopback infrastructure from Phase 12 are extended, not replaced.

</domain>

<decisions>
## Implementation Decisions

### Reconnect Strategy
- **D-01:** WiFi interruptions are detected via stale-frame monitoring — if no new frame appears on the virtual device within ~3 seconds, the session is considered dead. This reuses the stale-frame pattern from Phase 12 (D-07) and provides sub-5-second detection, much faster than waiting for scrcpy to exit on its own (which can hang 30+ seconds).
- **D-02:** On reconnect, the system performs a full ADB cycle: `adb disconnect <ip>` then `adb connect <ip>:5555` before relaunching scrcpy. This ensures clean ADB state after WiFi interruption rather than relying on scrcpy's `--tcpip` to recover a stale ADB connection.
- **D-03:** The `WirelessSessionState` dataclass must store launch parameters (device_ip) so that `_restart_session()` can actually re-launch scrcpy. The current Phase 12 implementation logs a warning and returns — Phase 13 fixes this.

### Error Reporting
- **D-04:** Session objects gain an `error_code` field alongside `error_message`. Structured codes like `adb_refused`, `adb_unauthorized`, `scrcpy_crash`, `wifi_timeout`, `producer_timeout` enable the frontend (Phase 15) to show specific user guidance (e.g., "Accept the USB debugging prompt on your Android device"). Backward-compatible — `error_code` is optional/nullable.
- **D-05:** The POST endpoint for starting a scrcpy session is synchronous — it blocks until scrcpy is producing frames (up to ~15s timeout via the producer-ready gate). Returns 200 with session_id on success, or an error response with error_code on failure. Callers know immediately whether it worked. Matches Phase 12's producer-ready gate pattern.

### API Endpoints (WAPI-03)
- **D-06:** `POST /api/wireless/scrcpy` accepts `{ "device_ip": "..." }` and starts a scrcpy session. Validates IP, runs ADB connect, launches scrcpy, waits for producer-ready. Returns session info on success.
- **D-07:** `DELETE /api/wireless/scrcpy/{session_id}` stops a scrcpy session: kills scrcpy, runs `adb disconnect`, destroys v4l2 device. Per SCPY-03.

### Carried Forward from Phase 12
- **D-08 (was P12 D-01):** Sessions are ephemeral (in-memory, not DB persisted).
- **D-09 (was P12 D-02):** Static device numbering — video11 = scrcpy. Single Android device at a time.
- **D-10 (was P12 D-08):** Producer-ready gate — CaptureRegistry.acquire() must not open virtual device until first frame written.

### Claude's Discretion
- Exact stale-frame monitoring implementation (polling vs asyncio task watching device readability)
- ADB connection timeout values
- Whether `adb connect` step runs as part of `start_android_scrcpy()` or as a separate helper
- Error code string values (as long as they're consistent and documented)
- Whether to add device_ip to WirelessSessionResponse model or keep it internal

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Backend Architecture (Phase 12 foundation)
- `Backend/services/pipeline_manager.py` — PipelineManager with start_android_scrcpy(), _supervise_session(), _restart_session() (needs device_ip storage fix)
- `Backend/routers/wireless.py` — Existing /capabilities and /sessions endpoints; new scrcpy POST/DELETE go here
- `Backend/main.py` — Lifespan pattern, app.state.pipeline_manager already wired
- `Backend/routers/cameras.py` — Camera enumeration API (needs wireless source tagging for SCPY-02)
- `Backend/services/capture_service.py` — CaptureRegistry ref-counted pool, _STALE_FRAME_TIMEOUT pattern

### Phase 12 Context
- `.planning/phases/12-virtual-device-infrastructure/12-CONTEXT.md` — Foundational decisions D-01 through D-11

### Requirements
- `.planning/REQUIREMENTS.md` — SCPY-01 through SCPY-04, WAPI-03

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `PipelineManager.start_android_scrcpy()`: Already creates v4l2loopback device, launches scrcpy with `--v4l2-sink`, waits for producer-ready. Needs: ADB connect step before launch, stored device_ip for restarts.
- `PipelineManager._supervise_session()`: Exponential backoff restart (1s/2s/4s/8s/16s, 5 retries). Needs: stale-frame detection integration, functional _restart_session.
- `_STALE_FRAME_TIMEOUT` pattern in capture_service.py: Existing stale-frame detection can inform the monitoring approach.
- `wireless.py` router: Already has capabilities and sessions endpoints. Scrcpy endpoints extend this naturally.

### Established Patterns
- **IP validation:** `ipaddress.ip_address()` already used in `start_android_scrcpy()` for injection prevention.
- **Async subprocess:** `asyncio.create_subprocess_exec` used throughout for tool invocation.
- **Router structure:** Each domain gets its own router file. Scrcpy endpoints go in `wireless.py`.
- **Pydantic models:** `Backend/models/wireless.py` has existing response models.

### Integration Points
- `PipelineManager`: Add device_ip storage to WirelessSessionState, fix _restart_session, add stale-frame monitor task
- `wireless.py`: Add POST /api/wireless/scrcpy and DELETE /api/wireless/scrcpy/{session_id}
- `cameras.py`: Tag virtual devices as wireless sources (card_label "scrcpy Input" already set via v4l2loopback)
- `models/wireless.py`: Add error_code field to WirelessSessionResponse, add ScrcpyStartRequest model

</code_context>

<specifics>
## Specific Ideas

No specific requirements beyond the success criteria. Key constraint: scrcpy virtual device must be indistinguishable from physical cameras in the capture pipeline — zero changes to V4L2Capture, StreamingService, or preview WebSocket.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 13-scrcpy-android-integration*
*Context gathered: 2026-04-16*
