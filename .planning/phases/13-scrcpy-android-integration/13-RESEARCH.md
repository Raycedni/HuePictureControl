# Phase 13: scrcpy Android Integration — Research

**Researched:** 2026-04-16
**Domain:** ADB WiFi, scrcpy --v4l2-sink, stale-frame watchdog, FastAPI async subprocess, Python asyncio process management
**Confidence:** HIGH (core tech verified via official scrcpy docs and codebase inspection)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 (Reconnect strategy):** Stale-frame monitoring — no new frame within ~3 seconds triggers reconnect. Reuses `_STALE_FRAME_TIMEOUT` pattern from capture_service.py.

**D-02 (ADB cycle on reconnect):** Full ADB cycle: `adb disconnect <ip>` then `adb connect <ip>:5555` before relaunching scrcpy. Clean ADB state required.

**D-03 (WirelessSessionState fix):** `device_ip` must be stored in `WirelessSessionState` so `_restart_session()` can re-launch scrcpy. Phase 12 stub logs a warning and returns — Phase 13 fixes this.

**D-04 (error_code field):** Session objects gain `error_code` alongside `error_message`. Structured codes: `adb_refused`, `adb_unauthorized`, `scrcpy_crash`, `wifi_timeout`, `producer_timeout`. Backward-compatible (optional/nullable).

**D-05 (Synchronous POST):** `POST /api/wireless/scrcpy` blocks until scrcpy is producing frames (up to ~15s via producer-ready gate). Returns 200 + session_id on success, error response with error_code on failure.

**D-06 (POST endpoint):** `POST /api/wireless/scrcpy` body: `{ "device_ip": "..." }`. Validates IP, runs ADB connect, launches scrcpy, waits for producer-ready.

**D-07 (DELETE endpoint):** `DELETE /api/wireless/scrcpy/{session_id}` kills scrcpy, runs `adb disconnect`, destroys v4l2 device. Per SCPY-03.

**D-08 (ephemeral sessions):** Sessions are in-memory only, not DB-persisted.

**D-09 (static device numbering):** video11 = scrcpy. One Android device at a time.

**D-10 (producer-ready gate):** CaptureRegistry.acquire() must not open virtual device until first frame written.

### Claude's Discretion

- Exact stale-frame monitoring implementation (polling asyncio task vs device readability watch)
- ADB connection timeout values
- Whether `adb connect` runs inside `start_android_scrcpy()` or as a separate `_run_adb_connect()` helper
- Error code string values (must be consistent and documented)
- Whether to add `device_ip` to `WirelessSessionResponse` model or keep it internal

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SCPY-01 | User can provide an Android device IP; backend connects via ADB WiFi and starts scrcpy with --v4l2-sink | ADB connect flow + scrcpy subprocess launch pattern documented below |
| SCPY-02 | Mirrored Android screen appears as virtual camera in camera selector alongside physical devices | cameras.py scan picks up v4l2loopback devices by card_label; no changes needed |
| SCPY-03 | Stopping a scrcpy session disconnects ADB and destroys the virtual device | stop_session() extended to run `adb disconnect`; existing SIGTERM→SIGKILL pattern reused |
| SCPY-04 | scrcpy sessions survive brief WiFi interruptions via supervised watchdog with auto-reconnect | Stale-frame asyncio task + _restart_session() fix using stored device_ip |
| WAPI-03 | POST and DELETE endpoints start/stop scrcpy sessions by Android device IP | wireless.py router extended with two new endpoints |
</phase_requirements>

---

## Summary

Phase 13 extends the Phase 12 PipelineManager skeleton to make the scrcpy-specific path fully functional. Three gaps exist in the Phase 12 code that Phase 13 must close: (1) `_restart_session()` logs a warning and returns without relaunching scrcpy — fixing this requires storing `device_ip` in `WirelessSessionState`; (2) no stale-frame watchdog exists yet — the supervisor only watches `proc.wait()` (process exit), not frame production; (3) the API endpoints for starting/stopping a scrcpy session (`POST /DELETE /api/wireless/scrcpy`) are not implemented.

**Primary recommendation:** Add `device_ip: str` to `WirelessSessionState`, implement `_run_adb_connect()` helper, fix `_restart_session()` for the `android_scrcpy` branch, add a `_stale_frame_monitor()` asyncio task that polls `capture_service._last_frame_time`, add `POST` and `DELETE` endpoints to `wireless.py`, and add `error_code` to models. No new Python packages required — all existing tools (`adb`, `scrcpy`, `asyncio`, `subprocess`) are already wired.

The scrcpy virtual device is transparent to the rest of the capture pipeline. `GET /api/cameras` will include `/dev/video11` automatically when it exists, because `enumerate_capture_devices()` finds all `/dev/videoN` nodes and the `card_label` "scrcpy Input" set at device creation makes it identifiable as a wireless source.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ADB WiFi connect / disconnect | Backend (service layer) | — | Shell subprocess; no user-facing state needed |
| scrcpy process lifecycle | Backend (PipelineManager) | — | Long-running subprocess; needs supervised restart |
| Stale-frame watchdog | Backend (PipelineManager async task) | — | Monitors frame timestamps in CaptureRegistry; asyncio task |
| Producer-ready gate | Backend (PipelineManager) | — | Existing pattern; blocks CaptureRegistry.acquire() |
| v4l2loopback device create/delete | Backend (PipelineManager) | — | Kernel module via sudo subprocess |
| Camera enumeration (SCPY-02) | Backend (cameras.py) | — | V4L2 scan already finds virtual devices |
| Wireless source tagging | Backend (cameras.py) | — | Tag devices whose card_label == "scrcpy Input" |
| POST/DELETE scrcpy endpoints (WAPI-03) | Backend (wireless.py router) | — | Thin HTTP wrapper over PipelineManager |
| Error code surface (D-04) | Backend (models/wireless.py) | — | Optional field on WirelessSessionResponse |

---

## Standard Stack

### Core (No New Packages)

| Tool | Version | Purpose | Source |
|------|---------|---------|--------|
| `scrcpy` | system-installed (v2.x+) | Mirror Android screen to v4l2loopback device | [CITED: github.com/Genymobile/scrcpy/doc/v4l2.md] |
| `adb` | system-installed (platform-tools) | WiFi TCP/IP ADB connection management | [CITED: github.com/Genymobile/scrcpy/blob/master/doc/connection.md] |
| `asyncio.create_subprocess_exec` | Python 3.12 stdlib | Non-blocking process launch (already used in pipeline_manager.py) | [VERIFIED: codebase — pipeline_manager.py line 333] |
| `asyncio.to_thread` | Python 3.12 stdlib | Non-blocking subprocess.run for adb connect/disconnect | [VERIFIED: codebase — existing pattern in pipeline_manager.py, capture_v4l2.py] |
| `ipaddress.ip_address()` | Python 3.12 stdlib | IP injection prevention — already used in start_android_scrcpy() | [VERIFIED: codebase — pipeline_manager.py line 315] |
| `v4l2loopback-ctl` | system-installed | Create/delete /dev/video11 — already used in Phase 12 | [VERIFIED: codebase — pipeline_manager.py _create_v4l2_device] |

**No new pip packages required for Phase 13.**

---

## Architecture Patterns

### System Architecture Diagram

```
POST /api/wireless/scrcpy
        |
        v
  wireless.py router
        |
        v
  PipelineManager.start_android_scrcpy(device_ip)
        |
        +--[1]--> adb disconnect <ip>  (clean state)
        |
        +--[2]--> adb connect <ip>:5555
        |              |
        |         [authorized?] --(no)--> error_code=adb_unauthorized
        |              |
        |         [refused?]   --(yes)--> error_code=adb_refused
        |
        +--[3]--> _create_v4l2_device(11, "scrcpy Input")
        |
        +--[4]--> asyncio.create_subprocess_exec("scrcpy",
        |              "--v4l2-sink=/dev/video11",
        |              "--no-video-playback",
        |              f"--tcpip={device_ip}")
        |
        +--[5]--> _wait_for_producer(session, delay=1.5)
        |              |
        |         [timeout?] --> error_code=producer_timeout
        |
        +--[6]--> CaptureRegistry.acquire("/dev/video11")
        |
        +--[7]--> status = "active"
        |
        +--[8]--> _supervise_session(session_id)  [asyncio Task]
        |              |
        |         watches proc.wait() for crash
        |
        +--[9]--> _stale_frame_monitor(session_id)  [asyncio Task]
                       |
                  polls _last_frame_time every 1s
                  if stale > 3s --> _restart_session()
                       |
                  _restart_session():
                       adb disconnect <ip>
                       adb connect <ip>:5555
                       kill old proc
                       relaunch scrcpy
                       reset producer_ready
```

### Scrcpy Command (Headless Server)

The correct scrcpy command for a headless Linux server (no display attached):

```bash
scrcpy \
  --v4l2-sink=/dev/video11 \
  --no-video-playback \
  --tcpip=<device_ip>
```

Key facts verified from official docs:
- `--no-video-playback` disables the SDL window — **no DISPLAY env var needed** [CITED: scrcpy/doc/v4l2.md]
- `--tcpip=<ip>` connects to a device already listening on port 5555 [CITED: scrcpy/doc/connection.md]
- The v4l2loopback device **must already exist** before scrcpy starts [VERIFIED: scrcpy issue #5449]
- scrcpy exits immediately when ADB disconnects (no built-in reconnect as of 2026) [CITED: scrcpy issue #6607]

### ADB Connection Flow

```python
# _run_adb_connect(device_ip) — runs in asyncio via asyncio.to_thread
# Returns: (success: bool, error_code: str | None)

# Step 1: disconnect to clean stale state
subprocess.run(["adb", "disconnect", f"{device_ip}:5555"], ...)

# Step 2: connect
result = subprocess.run(
    ["adb", "connect", f"{device_ip}:5555"],
    capture_output=True, text=True, timeout=10
)
output = result.stdout + result.stderr

if "connected to" in output or "already connected to" in output:
    return True, None
elif "unauthorized" in output:
    return False, "adb_unauthorized"
elif "refused" in output or "cannot connect" in output:
    return False, "adb_refused"
else:
    return False, "adb_refused"
```

`adb connect` is idempotent: outputs "already connected to" and exits 0 if already connected. [VERIFIED: Mobly test framework source — success regex: `^connected to .*|^already connected to .*`]

### ADB Disconnect on Stop

```python
# In stop_session() extension for android_scrcpy:
if session.source_type == "android_scrcpy" and session.device_ip:
    await asyncio.to_thread(
        subprocess.run,
        ["adb", "disconnect", f"{session.device_ip}:5555"],
        capture_output=True,
        timeout=5,
    )
```

### WirelessSessionState — Required Changes

```python
@dataclass
class WirelessSessionState:
    session_id: str
    source_type: str
    device_path: str
    device_nr: int
    card_label: str
    status: str = "starting"
    error_message: Optional[str] = None
    error_code: Optional[str] = None      # NEW — D-04
    device_ip: Optional[str] = None       # NEW — D-03 (for restart)
    proc: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    producer_ready: asyncio.Event = field(default_factory=asyncio.Event)
    supervisor_task: Optional[asyncio.Task] = field(default=None, repr=False)
    stale_monitor_task: Optional[asyncio.Task] = field(default=None, repr=False)  # NEW
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

### Stale-Frame Monitor Pattern

The existing `_STALE_FRAME_TIMEOUT = 3.0` in `capture_service.py` uses `CaptureBackend._last_frame_time`. The stale-frame watchdog in PipelineManager needs to observe the same signal. Two viable approaches:

**Option A — Poll CaptureRegistry backend's `_last_frame_time`:**
```python
async def _stale_frame_monitor(self, session_id: str) -> None:
    """Watch for stale frames; trigger restart if none arrive in 3s."""
    POLL_INTERVAL = 1.0
    STALE_THRESHOLD = 3.0
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        session = self._sessions.get(session_id)
        if session is None or session.status == "stopped":
            return
        backend = self._capture_registry.get(session.device_path)
        if backend is None:
            continue  # Not yet acquired — skip
        elapsed = time.monotonic() - backend._last_frame_time
        if backend._last_frame_time > 0 and elapsed > STALE_THRESHOLD:
            logger.warning(
                "Session %s: stale frame (%.1fs) — triggering reconnect",
                session_id, elapsed,
            )
            await self._restart_session(session_id)
```

**Option B — Watch `proc.returncode` with a separate supervisor task (current implementation) + rely on scrcpy exiting on ADB disconnect.**

Since scrcpy exits when ADB disconnects (confirmed: issue #6607), the existing `_supervise_session()` already catches crashes. The stale-frame monitor (Option A) adds sub-second detection for cases where scrcpy is alive but writing no frames (rare but possible during brief WiFi flaps that don't fully disconnect ADB).

**Recommendation (Claude's discretion):** Implement Option A as a lightweight asyncio polling task. Polling every 1s is negligible overhead. It catches the case where scrcpy hangs without crashing. For simplicity, both `_supervise_session` and `_stale_frame_monitor` can call `_restart_session` — add a guard so only one restart runs at a time (e.g., check `session.status == "error"` before restarting).

### Wireless Source Tagging (SCPY-02)

`GET /api/cameras` currently scans V4L2 devices and returns them as `CameraDevice` objects. The `card_label` for the scrcpy virtual device is set to `"scrcpy Input"` at creation time via `v4l2loopback-ctl add -n "scrcpy Input"`. The camera response currently only includes `display_name` (which comes from the `card` field of V4L2 device info).

To tag wireless sources, two approaches:
1. **Read card_label from PipelineManager sessions at camera list time** — cross-reference device_path against active sessions.
2. **Add `is_wireless: bool` field to `CameraDevice`** — set true when `display_name in ("scrcpy Input", "Miracast Input")`.

The simplest approach that requires minimal model changes: add `is_wireless: bool = False` to `CameraDevice` and populate it by checking if the device_path appears in `pipeline_manager.get_sessions()` device paths. This requires the cameras router to receive `pipeline_manager` via `request.app.state.pipeline_manager`.

### POST Endpoint Pattern

```python
@router.post("/scrcpy", status_code=200)
async def start_scrcpy(
    body: ScrcpyStartRequest, request: Request
) -> WirelessSessionResponse:
    """Start an Android scrcpy session. Blocks until producer-ready (~15s max)."""
    pipeline_manager = request.app.state.pipeline_manager
    try:
        session_id = await pipeline_manager.start_android_scrcpy(body.device_ip)
    except RuntimeError as exc:
        session = pipeline_manager.get_session_by_ip(body.device_ip)
        error_code = session.error_code if session else "unknown"
        raise HTTPException(status_code=422, detail={
            "error_code": error_code,
            "message": str(exc),
        })
    session = pipeline_manager.get_session(session_id)
    return WirelessSessionResponse(
        session_id=session.session_id,
        source_type=session.source_type,
        device_path=session.device_path,
        status=session.status,
        error_message=session.error_message,
        error_code=session.error_code,
        started_at=session.started_at,
    )
```

### DELETE Endpoint Pattern

```python
@router.delete("/scrcpy/{session_id}", status_code=204)
async def stop_scrcpy(session_id: str, request: Request) -> None:
    """Stop a scrcpy session: kill scrcpy, disconnect ADB, destroy device."""
    pipeline_manager = request.app.state.pipeline_manager
    if pipeline_manager.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await pipeline_manager.stop_session(session_id)
```

The existing `stop_session()` needs extension to run `adb disconnect <ip>:5555` after terminating the process when `source_type == "android_scrcpy"`.

### Model Changes (models/wireless.py)

```python
class ScrcpyStartRequest(BaseModel):
    device_ip: str   # Validated by ipaddress.ip_address() in PipelineManager

class WirelessSessionResponse(BaseModel):
    session_id: str
    source_type: str
    device_path: str
    status: str
    error_message: str | None = None
    error_code: str | None = None   # NEW — D-04
    started_at: str
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| IP address validation | Custom regex | `ipaddress.ip_address()` stdlib | Already in codebase (line 315) |
| ADB WiFi connection | Custom TCP socket | `adb connect <ip>:5555` subprocess | ADB handles auth, handshake, device protocol |
| Screen mirror transport | Custom screen capture protocol | scrcpy --tcpip | scrcpy handles H.264 decode, frame rate, device handshake |
| v4l2loopback lifecycle | Direct ioctl calls | `v4l2loopback-ctl add/delete` subprocess | Already wired in Phase 12 |
| Reconnect timing | Custom timer | asyncio.sleep in polling task | Straightforward; backoff already exists in supervisor |

---

## Common Pitfalls

### Pitfall 1: Launching scrcpy Without `--no-video-playback` on a Headless Server
**What goes wrong:** scrcpy tries to open an SDL window and crashes with "Could not initialize SDL: No available video device" when no DISPLAY is set.
**Why it happens:** scrcpy opens a mirroring window by default; the v4l2-sink doesn't suppress it.
**How to avoid:** Always pass `--no-video-playback` in the subprocess command.
**Warning signs:** scrcpy exits immediately (proc.returncode = 1) during producer-ready gate.
**Source:** [CITED: scrcpy issue #2757, scrcpy/doc/v4l2.md note "No SDL/display requirements when using --no-video-playback"]

### Pitfall 2: scrcpy Started Before v4l2loopback Device Exists
**What goes wrong:** scrcpy logs "ERROR: Failed to open output device: /dev/video11" and exits immediately (returncode != 0).
**Why it happens:** scrcpy tries to open the v4l2loopback sink at startup; if `/dev/video11` doesn't exist, it fails.
**How to avoid:** Always call `_create_v4l2_device()` before launching scrcpy. Phase 12 code already does this in the correct order.
**Warning signs:** producer-ready timeout immediately after device creation; proc.returncode != None right after launch.
**Source:** [CITED: scrcpy GitHub issue #5449]

### Pitfall 3: ADB Unauthorized — Device Needs User Prompt
**What goes wrong:** `adb connect` outputs "unauthorized" — the Android device shows a popup asking to trust the computer. The user must physically tap "Accept" on the device.
**Why it happens:** ADB requires explicit authorization on first connection from a new host. This is a security feature, not a bug.
**How to avoid:** Surface `error_code=adb_unauthorized` in the API response so the frontend can show the message "Accept the USB debugging prompt on your Android device." (Per D-04)
**Warning signs:** `adb connect` output contains "unauthorized"; scrcpy never starts.
**Source:** [CITED: scrcpy FAQ.md — "Device is unauthorized"]

### Pitfall 4: Stale ADB State After WiFi Interruption
**What goes wrong:** ADB believes the device is connected even after WiFi drops. Running `adb connect <ip>:5555` after a reconnect attempt gets "already connected" but scrcpy still can't talk to it.
**Why it happens:** ADB TCP connection state is stale in the adb server daemon.
**How to avoid:** Per D-02, always run `adb disconnect <ip>:5555` before `adb connect <ip>:5555` in the reconnect cycle. This clears the stale connection and forces a fresh handshake.
**Warning signs:** `adb connect` reports "already connected" but scrcpy exits within 2 seconds.
**Source:** [ASSUMED — based on ADB WiFi behavior patterns observed across community reports]

### Pitfall 5: Concurrent Restart Calls (Race Condition)
**What goes wrong:** Both `_supervise_session` (process exit) and `_stale_frame_monitor` (stale frames) detect a failure simultaneously and both call `_restart_session()`, resulting in two scrcpy processes competing for `/dev/video11`.
**Why it happens:** Two independent asyncio tasks, both watching for failure conditions.
**How to avoid:** In `_restart_session()`, check `session.status == "error"` first and use a lock or status transition guard. Only one task should trigger restart. After the first task sets `status = "error"`, the second should find the status already in error and skip.
**Warning signs:** Two scrcpy processes appear in process list; V4L2 device write conflict logs.
**Source:** [ASSUMED — standard concurrent restart pitfall in supervised process managers]

### Pitfall 6: `_capture_registry.get()` Returns None During Reconnect
**What goes wrong:** In `_stale_frame_monitor`, calling `self._capture_registry.get(session.device_path)` returns None during the reconnect window when the device has been released but not yet re-acquired. Monitor loop may panic or mis-trigger.
**Why it happens:** `_restart_session()` may clear and reacquire the registry. `get()` (non-incrementing) is safe to call but returns None when not acquired.
**How to avoid:** In the monitor, check `if backend is None: continue` — already shown in the code example above. Backend absence is a valid transient state.
**Source:** [VERIFIED: capture_service.py line 217 — get() returns None if device not acquired]

### Pitfall 7: scrcpy Exit Code Is Not Reliable for Distinguishing Failure Types
**What goes wrong:** Using `proc.returncode != 0` to distinguish "crash" from "user stopped" is insufficient. scrcpy exits 0 on clean quit and non-zero on crash, but the specific non-zero code varies across versions and is not documented.
**Why it happens:** scrcpy doesn't document exit codes formally.
**How to avoid:** Use `session.status == "stopped"` (set by user-initiated stop) as the primary discriminator, not exit code. The supervisor already does this correctly in Phase 12.
**Source:** [CITED: scrcpy issue discussion — non-zero exit codes mentioned but not specified]

### Pitfall 8: ADB Port 5555 Not Open on Android Device
**What goes wrong:** `adb connect <ip>:5555` gets "Connection refused" if the Android device has not had ADB TCP/IP mode enabled. This requires the device to be connected via USB first and `adb tcpip 5555` run — a one-time setup step.
**Why it happens:** ADB WiFi mode must be enabled manually before the first wireless connection.
**How to avoid:** Surface `error_code=adb_refused` in the API response. Document the setup prerequisite: "Enable ADB over WiFi on your Android device (requires USB connection first)." Phase 15 (frontend) should show this guidance.
**Source:** [CITED: scrcpy connection.md — manual WiFi setup flow]

---

## Code Examples

### scrcpy subprocess launch (headless, correct flags)
```python
# Source: scrcpy/doc/v4l2.md + connection.md
session.proc = await asyncio.create_subprocess_exec(
    "scrcpy",
    "--v4l2-sink=/dev/video11",
    "--no-video-playback",      # No SDL window — works without DISPLAY
    f"--tcpip={device_ip}",     # Connect to device already listening on :5555
    stderr=asyncio.subprocess.DEVNULL,
    stdout=asyncio.subprocess.DEVNULL,
)
```

### ADB connect helper (with output parsing)
```python
# Source: Mobly adb.py success regex pattern + community ADB docs
async def _run_adb_connect(self, device_ip: str) -> tuple[bool, str | None]:
    """Returns (success, error_code | None)."""
    # Step 1: clear stale state (D-02)
    await asyncio.to_thread(
        subprocess.run,
        ["adb", "disconnect", f"{device_ip}:5555"],
        capture_output=True, text=True, timeout=5,
    )
    # Step 2: fresh connect
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["adb", "connect", f"{device_ip}:5555"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False, "adb_refused"

    output = (result.stdout + result.stderr).lower()
    if "connected to" in output or "already connected to" in output:
        return True, None
    if "unauthorized" in output:
        return False, "adb_unauthorized"
    return False, "adb_refused"
```

### ADB disconnect on session stop
```python
# In stop_session() or _cleanup_session_resources(), per SCPY-03
if session.source_type == "android_scrcpy" and session.device_ip:
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["adb", "disconnect", f"{session.device_ip}:5555"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as exc:
        logger.warning("Session %s: adb disconnect failed (best-effort): %s", session_id, exc)
```

### Stale-frame monitor asyncio task
```python
# Claude's discretion on exact impl; recommended approach:
import time

async def _stale_frame_monitor(self, session_id: str) -> None:
    POLL_INTERVAL = 1.0
    STALE_THRESHOLD = 3.0
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        session = self._sessions.get(session_id)
        if session is None or session.status == "stopped":
            return
        if session.status == "error":
            continue  # Supervisor already handling restart
        backend = self._capture_registry.get(session.device_path)
        if backend is None or backend._last_frame_time == 0:
            continue  # Not yet acquired or no first frame
        elapsed = time.monotonic() - backend._last_frame_time
        if elapsed > STALE_THRESHOLD:
            logger.warning(
                "Session %s: stale frame (%.1fs) — triggering reconnect", session_id, elapsed
            )
            session.status = "error"
            session.error_code = "wifi_timeout"
            session.error_message = f"No frame for {elapsed:.1f}s — reconnecting"
            await self._restart_session(session_id)
```

### Updated _restart_session for android_scrcpy
```python
elif session.source_type == "android_scrcpy":
    if not session.device_ip:
        logger.error("Session %s: cannot restart — device_ip not stored", session_id)
        return
    # Full ADB cycle (D-02)
    success, error_code = await self._run_adb_connect(session.device_ip)
    if not success:
        session.status = "error"
        session.error_code = error_code
        session.error_message = f"ADB reconnect failed: {error_code}"
        return
    # Kill old proc if still alive
    if session.proc and session.proc.returncode is None:
        try:
            session.proc.kill()
            await session.proc.wait()
        except Exception:
            pass
    # Relaunch scrcpy
    session.proc = await asyncio.create_subprocess_exec(
        "scrcpy",
        "--v4l2-sink=/dev/video11",
        "--no-video-playback",
        f"--tcpip={session.device_ip}",
        stderr=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
    )
    session.producer_ready.clear()
    asyncio.create_task(self._wait_for_producer(session))
    session.status = "active"
```

### Wireless source tagging in cameras.py
```python
# In list_cameras(), after assembling devices list:
# Cross-reference PipelineManager active sessions
pipeline_manager = getattr(request.app.state, "pipeline_manager", None)
wireless_paths: set[str] = set()
if pipeline_manager:
    for s in pipeline_manager.get_sessions():
        if s["status"] in ("active", "starting"):
            wireless_paths.add(s["device_path"])

# When building CameraDevice, set is_wireless=True if path matches
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| `--no-display` flag | `--no-video-playback` flag | Older scrcpy used `--no-display`; current versions use `--no-video-playback`. Using wrong flag causes "unrecognized option" error. [CITED: scrcpy issue #2959] |
| `scrcpy --tcpip` (no IP) | `scrcpy --tcpip=<ip>` (with IP) | Auto-discovery variant requires USB first; with-IP variant works for already-paired devices over WiFi |
| Force reconnect: `scrcpy --tcpip=+<ip>` | Managed reconnect: adb cycle + relaunch | scrcpy's `+` prefix forces reconnect but doesn't give us ADB state cleanup control |

---

## Environment Availability

| Dependency | Required By | Notes |
|------------|------------|-------|
| `scrcpy` | SCPY-01, SCPY-04 | Must be installed on host; `GET /api/wireless/capabilities` already checks and reports version |
| `adb` (Android platform tools) | SCPY-01, SCPY-03, SCPY-04 | Must be installed on host; already checked by capabilities endpoint |
| `v4l2loopback-ctl` | VCAM-01 (Phase 12) | Already required and used by Phase 12 |
| Android device with ADB WiFi enabled | SCPY-01 | One-time user setup: USB + `adb tcpip 5555` then WiFi |

All system dependencies are already checked and reported by `GET /api/wireless/capabilities` (Phase 12). Phase 13 adds no new system tool requirements.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `Backend/pytest.ini` or `pyproject.toml` (existing) |
| Quick run command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_pipeline_manager.py tests/test_wireless_router.py -x -q` |
| Full suite command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | File | Command |
|--------|----------|-----------|------|---------|
| SCPY-01 | `start_android_scrcpy()` runs adb connect before scrcpy launch | unit | `test_pipeline_manager.py` | `pytest tests/test_pipeline_manager.py::TestScrcpyStart -x` |
| SCPY-01 | `start_android_scrcpy()` stores device_ip on WirelessSessionState | unit | `test_pipeline_manager.py` | above |
| SCPY-01 | POST /api/wireless/scrcpy returns 200 + session_id on success | unit | `test_wireless_router.py` | `pytest tests/test_wireless_router.py::TestScrcpyEndpoints -x` |
| SCPY-01 | POST returns 422 with error_code on adb_unauthorized | unit | `test_wireless_router.py` | above |
| SCPY-01 | POST returns 422 with error_code on adb_refused | unit | `test_wireless_router.py` | above |
| SCPY-01 | POST returns 422 with error_code on producer_timeout | unit | `test_pipeline_manager.py` | above |
| SCPY-02 | GET /api/cameras includes scrcpy virtual device as wireless source | unit | `test_cameras_router.py` | `pytest tests/test_cameras_router.py -x` |
| SCPY-03 | DELETE /api/wireless/scrcpy/{id} calls stop_session | unit | `test_wireless_router.py` | above |
| SCPY-03 | stop_session() calls adb disconnect for android_scrcpy sessions | unit | `test_pipeline_manager.py` | above |
| SCPY-04 | `_stale_frame_monitor()` triggers _restart_session on stale frames | unit | `test_pipeline_manager.py` | above |
| SCPY-04 | `_restart_session()` runs full ADB cycle (disconnect+connect) before relaunch | unit | `test_pipeline_manager.py` | above |
| WAPI-03 | POST /api/wireless/scrcpy rejects invalid IP with 422 | unit | `test_wireless_router.py` | above |
| WAPI-03 | DELETE /api/wireless/scrcpy/{id} returns 404 for unknown session_id | unit | `test_wireless_router.py` | above |

### Existing Test Baseline
- `test_pipeline_manager.py`: 19 tests (Phase 12 scope — device lifecycle, producer gate, stop, supervisor)
- `test_wireless_router.py`: 4 tests (capabilities, sessions endpoints)

Phase 13 adds to both files. Estimated new tests: ~12 in `test_pipeline_manager.py`, ~7 in `test_wireless_router.py`.

### Wave 0 Gaps
- No test file gaps — both files exist. New test classes are added within existing files.
- `ScrcpyStartRequest` and updated `WirelessSessionResponse` models must exist before endpoint tests can run.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth — local tool per design |
| V3 Session Management | no | Sessions are in-memory, not user sessions |
| V4 Access Control | no | No auth — local network tool |
| V5 Input Validation | yes | `ipaddress.ip_address()` already validates device_ip before subprocess; already in codebase |
| V6 Cryptography | no | No crypto operations |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Shell injection via device_ip | Tampering | `ipaddress.ip_address()` validation + `asyncio.create_subprocess_exec` (no shell=True) — already in Phase 12 code |
| ADB unauthorized device connecting to wrong host | Spoofing | ADB's own authorization prompt on device; no additional mitigation needed |
| Orphan scrcpy processes surviving server crash | Denial of Service | stop_all() in lifespan shutdown with 5s timeout — already in main.py |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `adb connect` outputs "already connected to" on idempotent reconnect and exits 0 | ADB Connection Flow | Restart cycle may fail silently; need to check actual adb output on target machine |
| A2 | Stale ADB state after WiFi drop requires `adb disconnect` before `adb connect` for clean reconnect | Pitfall 4, _restart_session | Reconnect might succeed without disconnect step, making D-02 redundant (not harmful, just unnecessary overhead) |
| A3 | `--no-video-playback` works without DISPLAY on all modern scrcpy versions (v2.x+) | Pitfall 1, scrcpy subprocess launch | Older system-installed scrcpy might use `--no-display`; needs version check |
| A4 | Concurrent restart guard: checking `session.status == "error"` is sufficient to prevent double-restart | Pitfall 5 | Needs asyncio.Lock if race window is tight; test under load |

---

## Open Questions

1. **scrcpy version on target machine**
   - What we know: scrcpy v2.x uses `--no-video-playback`; older versions use `--no-display`
   - What's unclear: The actual installed version on the Linux host is unknown (tools not available in the dev environment)
   - Recommendation: Capabilities endpoint already checks `scrcpy --version` — planner should add version check in Wave 0 setup or document minimum version requirement (v2.0+)

2. **Stale-frame monitor accessing `backend._last_frame_time` directly**
   - What we know: `_last_frame_time` is a private attribute on `CaptureBackend`
   - What's unclear: Whether accessing a private attribute from PipelineManager is acceptable, or if a public `last_frame_time` property should be added to `CaptureBackend`
   - Recommendation: Add a `@property last_frame_time -> float` to `CaptureBackend` base class. Minimal change, cleaner interface.

3. **is_wireless field in CameraDevice**
   - What we know: SCPY-02 requires the scrcpy device to appear as a virtual camera "tagged as a wireless source"
   - What's unclear: Whether `is_wireless: bool` is added to `CameraDevice` or if the display_name ("scrcpy Input") is sufficient for the frontend to distinguish
   - Recommendation: Add `is_wireless: bool = False` to `CameraDevice` model for explicit tagging. Frontend (Phase 15) will use this field.

---

## Sources

### Primary (HIGH confidence)
- [scrcpy/doc/v4l2.md](https://raw.githubusercontent.com/Genymobile/scrcpy/master/doc/v4l2.md) — `--v4l2-sink`, `--no-video-playback`, v4l2loopback requirements, no SDL/DISPLAY needed with `--no-video-playback`
- [scrcpy/doc/connection.md](https://github.com/Genymobile/scrcpy/blob/master/doc/connection.md) — `--tcpip=<ip>` flag, `adb connect`/`disconnect`, port 5555, manual WiFi setup flow
- [scrcpy FAQ.md](https://github.com/Genymobile/scrcpy/blob/master/FAQ.md) — ADB unauthorized error, authorization popup behavior
- [scrcpy issue #5449](https://github.com/Genymobile/scrcpy/issues/5449) — v4l2loopback device must exist before scrcpy starts
- [scrcpy issue #6607](https://github.com/genymobile/scrcpy/issues/6607) — scrcpy exits immediately when ADB disconnects; no built-in reconnect
- [scrcpy issue #2959](https://github.com/Genymobile/scrcpy/issues/2959) — `--no-display` deprecated; use `--no-video-playback`
- [Mobly adb.py](https://github.com/google/mobly/blob/master/mobly/controllers/android_device_lib/adb.py) — `adb connect` success regex `^connected to .*|^already connected to .*`; idempotent behavior
- Backend codebase — `pipeline_manager.py`, `capture_service.py`, `wireless.py`, `cameras.py`, `models/wireless.py` (VERIFIED via Read tool)

### Secondary (MEDIUM confidence)
- [scrcpy DeepWiki troubleshooting](https://deepwiki.com/Genymobile/scrcpy/5.4-troubleshooting-guide) — SDL error codes, ADB error messages
- [ADB Android Studio docs](https://developer.android.com/tools/adb) — ADB TCP/IP workflow

### Tertiary (LOW confidence — flagged as ASSUMED)
- Community reports — stale ADB state behavior after WiFi drop requiring disconnect-first cycle (A2)
- Concurrent restart race condition pattern (A4) — standard supervised-process pitfall, not scrcpy-specific

---

## Metadata

**Confidence breakdown:**
- ADB connect/disconnect flow: HIGH — verified via official scrcpy docs and Mobly source
- scrcpy `--no-video-playback` + `--tcpip` flags: HIGH — verified via official docs
- Stale-frame monitor design: MEDIUM — design derived from existing codebase patterns; specific behavior under WiFi flap assumed
- Concurrent restart race: MEDIUM — standard pattern; exact asyncio timing not verified under test

**Research date:** 2026-04-16
**Valid until:** 2026-07-16 (scrcpy stable; ADB protocol stable)
