# Phase 12: Virtual Device Infrastructure - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

The backend can create and destroy v4l2loopback virtual camera devices on demand, manage FFmpeg subprocesses with safe lifecycle controls, report system wireless readiness, and list active sessions. Virtual devices appear in the existing camera API alongside physical devices — zero changes to downstream pipeline code (CaptureRegistry, V4L2Capture, StreamingService, preview WebSocket).

</domain>

<decisions>
## Implementation Decisions

### Session Lifecycle
- **D-01:** Wireless sessions are ephemeral (memory only, not persisted to DB). Virtual devices and FFmpeg subprocesses don't survive process death — DB persistence would create stale records requiring cleanup. Use a `wireless_sessions` dict on `app.state` or within the PipelineManager.
- **D-02:** Static device numbering: video10 = Miracast, video11 = scrcpy. Deterministic stable_ids, no dynamic allocation races.
- **D-03:** Service shutdown must destroy all virtual devices and kill all subprocesses within 5 seconds. Registered in FastAPI lifespan shutdown handler following the existing pattern in `main.py`.

### Device Management
- **D-04:** Use `v4l2loopback-ctl add/delete` for device lifecycle (subprocess calls). No module reload (rmmod blocked by open fds). Requires two sudoers NOPASSWD rules — documented in setup instructions.
- **D-05:** `card_label` parameter on v4l2loopback-ctl add to set device display name (e.g., "Miracast Input", "scrcpy Input") so devices are identifiable in camera selector.

### FFmpeg Pipeline
- **D-06:** FFmpeg stderr=DEVNULL + `-loglevel quiet -nostats` as production default to prevent pipe deadlock.
- **D-07:** Pipeline health monitored via stale-frame detection — if no new frame in 3 seconds, consider pipeline dead and trigger supervised restart with exponential backoff.
- **D-08:** Producer-ready gate: CaptureRegistry.acquire() must not open a virtual device until the FFmpeg/scrcpy process has written its first frame. Implemented via an asyncio.Event set by a monitor task watching for device readability.

### Capabilities API
- **D-09:** `GET /api/wireless/capabilities` returns structured JSON with: tool presence + version for ffmpeg, scrcpy, adb, iw; NIC P2P support (parsed from `iw list`); overall ready/not-ready assessment per capability.
- **D-10:** Tool version detection via `asyncio.create_subprocess_exec` parsing stdout of `ffmpeg -version`, `scrcpy --version`, `adb version`, `iw list`.

### Error Reporting
- **D-11:** Pipeline failures surface via status field on session objects. `GET /api/wireless/sessions` returns `status` (starting, active, error, stopped) and `error_message` per session. Polling-friendly, no WebSocket needed for this phase.

### Claude's Discretion
- PipelineManager class structure (single class vs separate concerns) — Claude decides based on code complexity
- Exact exponential backoff parameters (base delay, max delay, max retries)
- Whether to use `asyncio.create_subprocess_exec` or `asyncio.create_subprocess_shell` — exec preferred for security
- DB table for wireless_sessions if Claude finds it useful for session enumeration (contradicts D-01 only if justified)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Backend Architecture
- `Backend/main.py` — Lifespan pattern (startup/shutdown), app.state setup, router registration
- `Backend/services/capture_service.py` — CaptureBackend ABC, CaptureRegistry ref-counted pool, _STALE_FRAME_TIMEOUT pattern
- `Backend/database.py` — Migration pattern (ALTER TABLE + try/except), table creation
- `Backend/routers/cameras.py` — Camera enumeration API pattern (for wireless.py to follow)

### Research
- `.planning/research/STACK.md` — v4l2loopback-ctl usage, scrcpy --v4l2-sink, no new Python packages
- `.planning/research/ARCHITECTURE.md` — New component design, data flow, integration points
- `.planning/research/PITFALLS.md` — FFmpeg stderr deadlock, producer_ready gate, orphan process prevention

### Requirements
- `.planning/REQUIREMENTS.md` — VCAM-01 through VCAM-03, WPIP-01 through WPIP-03, WAPI-01, WAPI-04

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CaptureRegistry` (`services/capture_service.py`): Ref-counted pool keyed by device path. Virtual devices will be acquired/released through this same interface.
- `CaptureBackend` ABC: Defines `open()`, `release()`, `get_frame()`, `get_jpeg()`, `is_open`. V4L2 loopback devices implement the V4L2Capture subclass — no new backend needed.
- `StatusBroadcaster` (`services/status_broadcaster.py`): WebSocket broadcast pattern — could be extended for wireless status in future phases.

### Established Patterns
- **Lifespan management:** `main.py` uses `@asynccontextmanager` for startup/shutdown. New PipelineManager should follow the same pattern (create in startup, cleanup in shutdown yield).
- **Router structure:** Each domain gets its own router file (`routers/hue.py`, `routers/cameras.py`). New `routers/wireless.py` follows this.
- **DB migrations:** `ALTER TABLE` with try/except for idempotent column adds.
- **Async subprocess:** `asyncio.to_thread()` used in capture_v4l2.py for blocking calls. Same pattern for v4l2loopback-ctl calls.

### Integration Points
- `main.py` lifespan: Add PipelineManager initialization + shutdown
- `main.py` router registration: Add wireless_router
- `app.state`: Add `pipeline_manager` attribute
- Camera enumeration (`routers/cameras.py`): Virtual devices auto-appear via V4L2 device scan — no changes needed

</code_context>

<specifics>
## Specific Ideas

No specific requirements — research-informed defaults apply. Key constraint: zero changes to existing capture pipeline code.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 12-virtual-device-infrastructure*
*Context gathered: 2026-04-14*
