# Phase 8: Capture Registry - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the global CaptureBackend singleton (`app.state.capture`) with a CaptureRegistry that manages a pool of independent CaptureBackend instances keyed by device path. Multiple entertainment zones can capture from different cameras concurrently. Stopping streaming fully releases device handles. Mid-stream camera reassignment (stop → reassign → start) opens the new device and closes the old one.

This phase does NOT change the preview WebSocket routing (Phase 9), the frontend camera selector (Phase 10), or Docker device passthrough (Phase 11).

</domain>

<decisions>
## Implementation Decisions

### Registry Lifecycle
- **D-01:** CaptureRegistry uses lazy instantiation — CaptureBackend instances are created on first `get(device_path)` call, not at startup. This avoids opening devices that aren't actively streaming.
- **D-02:** CaptureRegistry is stored on `app.state.capture_registry` (new attribute). The existing `app.state.capture` singleton is replaced — all consumers migrate to the registry.
- **D-03:** `create_capture(device_path)` factory (already exists in `capture_service.py`) is reused by the registry to create backends. No change to the factory itself.

### Reference Counting & Cleanup
- **D-04:** Reference counting tracks how many active StreamingService sessions use each backend. When ref count drops to zero, the backend is released (`release()` called, handle freed). This prevents premature release during mid-stream camera switches.
- **D-05:** `acquire(device_path)` increments ref count (creates backend if first ref), `release(device_path)` decrements and destroys at zero. These are the two primary public methods alongside `get(device_path)`.
- **D-06:** If a backend is released while ref count > 0 (e.g., forced cleanup during shutdown), all refs are cleared and the backend is released. Lifespan shutdown calls `registry.shutdown()` which releases all backends.

### StreamingService Wiring
- **D-07:** StreamingService constructor changes from `__init__(self, db, capture, broadcaster)` to `__init__(self, db, capture_registry, broadcaster)`. The `start(config_id)` method looks up the camera assignment for `config_id` from the DB, then calls `registry.acquire(device_path)` to get the capture backend.
- **D-08:** `stop()` calls `registry.release(device_path)` for the device it acquired. This ensures clean ref count management.
- **D-09:** If no camera assignment exists for a config, fall back to `CAPTURE_DEVICE` env var (existing default behavior per CAMA-03).

### Error Isolation
- **D-10:** Each CaptureBackend instance has independent error/reconnect state (already true in current architecture). One camera failing does not affect other zones' streaming.
- **D-11:** The registry does NOT auto-reconnect failed backends — that's handled by StreamingService's existing `_capture_reconnect_loop` per-session. Registry only manages creation/destruction.

### Claude's Discretion
- Thread safety strategy for the registry (threading.Lock vs asyncio.Lock) — Claude decides based on whether callers are sync or async
- Whether `CaptureRegistry` is a standalone class or integrated into `capture_service.py` — either is fine

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Codebase
- `Backend/services/capture_service.py` — CaptureBackend ABC, `create_capture()` factory, `CAPTURE_DEVICE` env var default
- `Backend/services/capture_v4l2.py` — V4L2Capture implementation, `enumerate_capture_devices()`, `V4L2DeviceInfo`
- `Backend/services/streaming_service.py` — StreamingService with `__init__(db, capture, broadcaster)`, `start(config_id)`, `stop()`, `_capture_reconnect_loop`
- `Backend/main.py` — Lifespan: creates singleton capture + StreamingService, stores on `app.state`
- `Backend/routers/capture.py` — `PUT /api/capture/device` (switch device), reads `app.state.capture`
- `Backend/routers/preview_ws.py` — WebSocket reads `app.state.capture` for frames
- `Backend/routers/cameras.py` — Camera list/reconnect/assignment endpoints (Phase 7)
- `Backend/database.py` — `camera_assignments` table (entertainment_config_id → camera_stable_id)
- `Backend/services/device_identity.py` — `get_stable_id()` for resolving stable_id → device_path

### Project Docs
- `.planning/REQUIREMENTS.md` — MCAP-01, MCAP-03
- `.planning/ROADMAP.md` — Phase 8 success criteria
- `.planning/phases/07-device-enumeration-and-camera-assignment-schema/07-CONTEXT.md` — Phase 7 decisions (D-06 through D-09 on DB schema)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CaptureBackend` ABC with `open()`, `release()`, `get_frame()`, `get_jpeg()` — clean interface for pooling
- `create_capture(device_path)` factory — registry wraps this, no changes needed
- `StreamingService._capture_reconnect_loop` — already handles per-session capture reconnection
- `camera_assignments` DB table — maps entertainment_config_id → camera_stable_id

### Established Patterns
- `app.state.{service}` for service instances — registry goes here
- Background reader threads per CaptureBackend (daemon threads, stop_event pattern)
- `run_in_executor` for blocking V4L2 operations in async context
- Lifespan context manager in `main.py` for startup/shutdown

### Integration Points
- `main.py` lifespan: replace `capture = create_capture()` with `registry = CaptureRegistry()`
- `StreamingService.__init__`: change `capture` param to `capture_registry`
- `StreamingService.start()`: lookup camera assignment, acquire from registry
- `StreamingService.stop()`: release to registry
- `routers/capture.py`: migrate `app.state.capture` reads to registry (or deprecate)
- `routers/preview_ws.py`: will need registry access (but routing logic is Phase 9)

</code_context>

<specifics>
## Specific Ideas

- The STATE.md blocker "[Phase 8]: Reference counting edge cases during mid-stream camera switches need explicit test scenarios" must be addressed with dedicated tests
- `acquire()` / `release()` naming mirrors resource pool patterns (like connection pools)
- Preview WebSocket still reads from `app.state.capture` — Phase 8 keeps backward compatibility by having registry expose a default backend, or preview migration happens in Phase 9

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-capture-registry*
*Context gathered: 2026-04-03*
