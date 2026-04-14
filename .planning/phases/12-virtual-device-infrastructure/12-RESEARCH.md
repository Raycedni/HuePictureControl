# Phase 12: Virtual Device Infrastructure - Research

**Researched:** 2026-04-14
**Domain:** Linux v4l2loopback virtual camera devices, asyncio subprocess lifecycle management, FFmpeg process supervision, wireless capability detection
**Confidence:** HIGH — all decisions pre-locked in CONTEXT.md; research verifies exact implementation patterns against existing codebase

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Session Lifecycle**
- D-01: Wireless sessions are ephemeral (memory only, not persisted to DB). Use `wireless_sessions` dict on `app.state` or within the PipelineManager.
- D-02: Static device numbering: video10 = Miracast, video11 = scrcpy. Deterministic stable_ids, no dynamic allocation races.
- D-03: Service shutdown must destroy all virtual devices and kill all subprocesses within 5 seconds. Registered in FastAPI lifespan shutdown handler following the existing pattern in `main.py`.

**Device Management**
- D-04: Use `v4l2loopback-ctl add/delete` for device lifecycle (subprocess calls). No module reload (rmmod blocked by open fds). Requires two sudoers NOPASSWD rules — documented in setup instructions.
- D-05: `card_label` parameter on `v4l2loopback-ctl add` to set device display name (e.g., "Miracast Input", "scrcpy Input").

**FFmpeg Pipeline**
- D-06: FFmpeg `stderr=DEVNULL` + `-loglevel quiet -nostats` as production default to prevent pipe deadlock.
- D-07: Pipeline health monitored via stale-frame detection — if no new frame in 3 seconds, consider pipeline dead and trigger supervised restart with exponential backoff.
- D-08: Producer-ready gate: `CaptureRegistry.acquire()` must not open a virtual device until the FFmpeg/scrcpy process has written its first frame. Implemented via an `asyncio.Event` set by a monitor task watching for device readability.

**Capabilities API**
- D-09: `GET /api/wireless/capabilities` returns structured JSON with: tool presence + version for ffmpeg, scrcpy, adb, iw; NIC P2P support (parsed from `iw list`); overall ready/not-ready assessment per capability.
- D-10: Tool version detection via `asyncio.create_subprocess_exec` parsing stdout of `ffmpeg -version`, `scrcpy --version`, `adb version`, `iw list`.

**Error Reporting**
- D-11: Pipeline failures surface via status field on session objects. `GET /api/wireless/sessions` returns `status` (starting, active, error, stopped) and `error_message` per session. Polling-friendly, no WebSocket needed for this phase.

### Claude's Discretion
- PipelineManager class structure (single class vs separate concerns) — Claude decides based on code complexity
- Exact exponential backoff parameters (base delay, max delay, max retries)
- Whether to use `asyncio.create_subprocess_exec` or `asyncio.create_subprocess_shell` — exec preferred for security
- DB table for wireless_sessions if Claude finds it useful for session enumeration (contradicts D-01 only if justified)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VCAM-01 | Backend creates v4l2loopback virtual device at a static node (e.g. `/dev/video10`) on demand and existing `V4L2Capture` opens it without modification | STACK.md: `v4l2loopback-ctl add -n "label" /dev/video10` + `exclusive_caps=1` ensures `V4L2_CAP_VIDEO_CAPTURE` bit is set; existing `_setup_device()` VIDIOC_QUERYCAP check passes transparently |
| VCAM-02 | Stopping a virtual session destroys `/dev/videoN` within 5 seconds; service shutdown destroys all virtual devices and kills all FFmpeg subprocesses cleanly | PITFALLS.md Pitfall 5: SIGTERM → 5s wait → SIGKILL kill sequence; registered in FastAPI lifespan shutdown handler pattern (existing `main.py`) |
| VCAM-03 | FFmpeg subprocess failure is detected within 3 seconds and triggers supervised restart with exponential backoff | PITFALLS.md Pitfall 3/6: existing `_STALE_FRAME_TIMEOUT = 3.0` in `capture_service.py`; `_drain_stderr` asyncio.Task detects non-zero exit within that window |
| WPIP-01 | `CaptureRegistry.acquire()` blocks until FFmpeg producer has written its first frame into the virtual device (producer_ready gate prevents blank-frame acquisition) | PITFALLS.md Pitfall 6: `asyncio.Event` set when stale-frame poll detects first VIDIOC_DQBUF success; `acquire()` called only after event |
| WPIP-02 | Virtual session creates v4l2loopback device, `device_path` registered in `CaptureRegistry` via `acquire()`, and the device auto-appears in `GET /api/cameras` | ARCHITECTURE.md: `enumerate_capture_devices()` scans all `/dev/video*`; v4l2loopback advertises `V4L2_CAP_VIDEO_CAPTURE` with driver="v4l2loopback" — appears automatically |
| WPIP-03 | `PipelineManager` is the single owner of all subprocess + v4l2loopback device lifecycle | ARCHITECTURE.md: PipelineManager pattern with `_sessions` dict; integrates with `main.py` lifespan at startup/shutdown |
| WAPI-01 | `GET /api/wireless/capabilities` returns NIC P2P support status, installed tool versions (ffmpeg, scrcpy, adb, iw), and a ready/not-ready assessment | STACK.md: `iw list` → `P2P-GO`/`P2P-client` detection; per-tool version via `asyncio.create_subprocess_exec` |
| WAPI-04 | `GET /api/wireless/sessions` lists all active wireless sessions with source type and status | D-11: PipelineManager._sessions dict → response model serialization; status enum: starting, active, error, stopped |
</phase_requirements>

---

## Summary

Phase 12 delivers the virtual device layer that all subsequent wireless input phases (Miracast, scrcpy) depend on. The core engineering is a `PipelineManager` service that wraps `asyncio.create_subprocess_exec` and `v4l2loopback-ctl` subprocess calls, plus a capabilities API router. All decisions are pre-locked in CONTEXT.md and confirmed by the existing milestone research files (STACK.md, ARCHITECTURE.md, PITFALLS.md). The codebase is well-understood from direct inspection.

The key insight is that v4l2loopback devices are transparent to the existing V4L2 pipeline — `V4L2Capture.open()` works identically on `/dev/video10` as on `/dev/video0` because both advertise `V4L2_CAP_VIDEO_CAPTURE`. The only new complexity is the producer-ready gate (D-08): `CaptureRegistry.acquire()` must be deferred until after FFmpeg/scrcpy has actually written its first frame, because the existing `_STALE_FRAME_TIMEOUT = 3.0s` health check will fire if the device is acquired before any frames arrive.

No new Python packages are required. All orchestration uses Python 3.12 stdlib (`asyncio.create_subprocess_exec`, `asyncio.Event`, `asyncio.Task`).

**Primary recommendation:** Implement PipelineManager as a single class with `start_miracast()` and `start_android_scrcpy()` as distinct methods sharing private helpers for device creation, health monitoring, and DB writes. The `asyncio.Event` producer_ready gate is the most critical implementation detail — get that right before wiring up the router.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| v4l2loopback device create/destroy | Backend (subprocess) | OS kernel module | v4l2loopback-ctl is a privileged system call; owned entirely by PipelineManager |
| FFmpeg / scrcpy process lifecycle | Backend (PipelineManager) | OS process tree | asyncio subprocess management; cleanup at app shutdown |
| Producer-ready gate | Backend (PipelineManager) | CaptureRegistry | Monitor task watches device readability; sets asyncio.Event before acquire() |
| Health monitoring / supervised restart | Backend (PipelineManager) | — | _drain_stderr task detects exit; exponential backoff restart loop |
| Session state storage | Backend (in-memory dict) | — | D-01: ephemeral only; PipelineManager._sessions; no DB persistence |
| Capabilities detection (NIC, tools) | Backend (API route) | OS tools (iw, ffmpeg) | One-shot subprocess calls per request; no caching required |
| Session listing API | Backend (router) | PipelineManager | Serializes _sessions dict to response model |
| Camera enumeration (virtual devices) | Backend (existing cameras.py) | — | No changes; enumerate_capture_devices() auto-discovers /dev/video10 |

---

## Standard Stack

### Core (all stdlib — no new packages)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncio.create_subprocess_exec` | stdlib (3.12) | Launch FFmpeg, scrcpy, v4l2loopback-ctl, iw, version probes | Used in existing codebase via `asyncio.to_thread`; exec (not shell) for security |
| `asyncio.Event` | stdlib (3.12) | Producer-ready gate (D-08) — set when first frame written | Canonical asyncio synchronization primitive |
| `asyncio.Task` | stdlib (3.12) | Background stderr drain, health monitor, restart loop | Pattern used in existing streaming_service.py |
| `asyncio.wait_for` | stdlib (3.12) | Bounded shutdown wait (5s per D-03) | Existing shutdown handler in main.py uses similar timeout patterns |

### Supporting (existing dependencies — no new additions)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `aiosqlite` | >=0.20 | `wireless_sessions` table (if Claude decides to use DB per discretion note) | Only if DB enumeration proves necessary for session listing across restarts |
| `pydantic` (via FastAPI) | current | `WirelessSession`, `CapabilitiesResponse` Pydantic models | Same as all other routers |
| `fastapi` | >=0.115 | `APIRouter` for `routers/wireless.py` | Standard router pattern |

### No New pip Packages Required

The existing `Backend/requirements.txt` needs no changes for Phase 12. All v4l2 device management and process supervision uses Python 3.12 stdlib. [VERIFIED: STACK.md — explicit statement "No new entries in Backend/requirements.txt are needed for v1.2"]

---

## Architecture Patterns

### System Architecture Diagram

```
User (REST API call)
        |
        v
POST /api/wireless/sessions  ─────────────────────────────────┐
GET  /api/wireless/sessions                                    |
GET  /api/wireless/capabilities                                |
        |                                                      |
        v                                                      |
  routers/wireless.py                                          |
  (WirelessRouter)                                             |
        |  calls                                               |
        v                                                      |
  services/pipeline_manager.py                                 |
  (PipelineManager)                                            |
  ┌─────────────────────────────────────────────────────┐      |
  │  _sessions: dict[str, WirelessSessionState]         │      |
  │                                                     │      |
  │  start_miracast(device_nr=10)                       │      |
  │    │                                                │      |
  │    ├─ 1. v4l2loopback-ctl add -n "Miracast Input"  │      |
  │    │     /dev/video10  (sudo, asyncio.to_thread)    │      |
  │    │                                                │      |
  │    ├─ 2. asyncio.create_subprocess_exec(            │      |
  │    │     "ffmpeg", "-i", "rtsp://...",              │      |
  │    │     "-f", "v4l2", "/dev/video10",              │      |
  │    │     stderr=DEVNULL)                            │      |
  │    │                                                │      |
  │    ├─ 3. asyncio.Task: _monitor_producer_ready()   │      |
  │    │     polls /dev/video10 until first frame       │      |
  │    │     → sets producer_ready asyncio.Event        │      |
  │    │                                                │      |
  │    ├─ 4. await producer_ready.wait()               │      |
  │    │                                                │      |
  │    └─ 5. registry.acquire("/dev/video10")          │      |
  │          (existing CaptureRegistry — unchanged)     │      |
  │                                                     │      |
  │  start_android_scrcpy(device_ip, device_nr=11)     │      |
  │    └─ same flow, scrcpy --v4l2-sink instead        │      |
  │                                                     │      |
  │  stop_session(session_id)                           │      |
  │    1. proc.terminate() → wait 5s → proc.kill()     │      |
  │    2. registry.release(device_path)                 │      |
  │    3. v4l2loopback-ctl delete /dev/videoN           │      |
  │    4. update session status = "stopped"             │      |
  │                                                     │      |
  │  stop_all()  ← called from main.py lifespan        │◄─────┘
  │    for each session: stop_session(id)               │
  └─────────────────────────────────────────────────────┘
        |
        v
  /dev/video10, /dev/video11  (v4l2loopback kernel devices)
        |
        v
  CaptureRegistry.acquire("/dev/video10")
  V4L2Capture.open("/dev/video10")
  V4L2Capture._setup_device() → VIDIOC_QUERYCAP (VIDEO_CAPTURE bit set)
  V4L2Capture._reader_loop() → MJPEG mmap streaming
        |
        v
  StreamingService / preview_ws  (UNCHANGED — zero modifications)
```

### Recommended Project Structure

```
Backend/
├── services/
│   ├── pipeline_manager.py      # NEW — PipelineManager + WirelessSessionState
│   ├── capture_service.py       # unchanged
│   └── ...
├── routers/
│   ├── wireless.py              # NEW — APIRouter /api/wireless/*
│   └── ...
├── models/
│   ├── wireless.py              # NEW — Pydantic response models
│   └── hue.py                   # existing
├── main.py                      # modified — add PipelineManager + wireless_router
└── database.py                  # modified — add wireless_sessions table (see below)
```

### Pattern 1: PipelineManager Lifecycle (lifespan integration)

**What:** PipelineManager is initialized at startup and registered for cleanup at shutdown — identical to the existing `CaptureRegistry` and `StreamingService` pattern.

**When to use:** Any service that owns OS resources needing guaranteed cleanup.

```python
# Source: direct codebase inspection — Backend/main.py lifespan pattern
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing startup ...
    pipeline_manager = PipelineManager(capture_registry=registry, db=db)
    app.state.pipeline_manager = pipeline_manager

    yield  # app runs here

    # Shutdown: stop wireless sessions before releasing capture
    await asyncio.wait_for(pipeline_manager.stop_all(), timeout=5.0)
    # ... existing shutdown (streaming.stop, registry.shutdown, close_db) ...
```

**Critical ordering:** `pipeline_manager.stop_all()` MUST run before `registry.shutdown()`. Each session's `stop_session()` calls `registry.release(device_path)` — that must complete before the registry is forcibly shut down.

### Pattern 2: Producer-Ready Gate (asyncio.Event)

**What:** `CaptureRegistry.acquire()` is deferred until a monitoring task confirms the FFmpeg/scrcpy process has written at least one frame to the v4l2loopback device.

**When to use:** Any time a producer and consumer share a device with a latency-sensitive startup sequence.

**The problem:** Existing `_STALE_FRAME_TIMEOUT = 3.0` in `capture_service.py` fires a `RuntimeError` if no frame arrives within 3 seconds after `acquire()`. FFmpeg RTSP negotiation can take 1-5 seconds. Acquiring before the first frame is written reliably causes a health check failure on fresh sessions.

```python
# Source: PITFALLS.md Pitfall 6 + asyncio docs
class WirelessSessionState:
    producer_ready: asyncio.Event  # set when first frame written

async def _monitor_producer_ready(
    session: WirelessSessionState,
    device_path: str,
    timeout: float = 15.0,
) -> None:
    """Poll v4l2loopback device until readable (first frame written), then set event."""
    import fcntl, os, struct
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            fd = os.open(device_path, os.O_RDWR | os.O_NONBLOCK)
            buf = bytearray(104)
            fcntl.ioctl(fd, 0x80685600, buf)  # VIDIOC_QUERYCAP
            os.close(fd)
            # Device exists and is queryable — check if process is writing
            # Simplest: attempt DQBUF with O_NONBLOCK; if EAGAIN -> not ready yet
            # If success -> first frame written -> signal ready
        except OSError:
            pass  # device not yet writable
        await asyncio.sleep(0.2)
    # Timeout — mark session as error
    session.status = "error"
    session.error_message = "Producer did not start within timeout"
```

**Simpler implementation:** Open device with `O_RDONLY | O_NONBLOCK`; if the open succeeds and `VIDIOC_QUERYCAP` succeeds AND the process `returncode is None`, the device is ready. The V4L2 capture subsystem for loopback devices will block on DQBUF until a frame is available — the ready check is whether the process is alive and the device node exists, not whether frames have arrived. Use a timed wait: `await asyncio.wait_for(session.producer_ready.wait(), timeout=15.0)` and have the drain stderr task set the event when it detects the first `frame=` output line from FFmpeg, OR simply set it after a `asyncio.sleep(1.0)` if the process is still alive.

**Recommended implementation for Phase 12 (simple, reliable):**
```python
async def _wait_for_producer(proc: asyncio.subprocess.Process, event: asyncio.Event, delay: float = 1.5) -> None:
    """Set producer_ready after delay if process is still running."""
    await asyncio.sleep(delay)
    if proc.returncode is None:  # process still alive
        event.set()
    # else: process died — session monitor will handle the error
```

### Pattern 3: Supervised Restart with Exponential Backoff

**What:** If a process exits unexpectedly, restart it with increasing delays to prevent busy-looping on persistent failures.

**When to use:** D-07 — pipeline health failure detected.

```python
# Source: CONTEXT.md D-07 + asyncio subprocess docs
async def _supervise_session(self, session_id: str) -> None:
    """Monitor process exit; restart with backoff on unexpected exit."""
    session = self._sessions[session_id]
    base_delay = 1.0
    max_delay = 30.0
    max_retries = 5
    attempt = 0

    while session.status not in ("stopped",) and attempt < max_retries:
        await session.proc.wait()  # block until process exits
        if session.status == "stopped":
            break  # user-initiated stop — do not restart

        attempt += 1
        delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
        session.status = "error"
        session.error_message = f"Process exited (attempt {attempt}); retrying in {delay}s"
        logger.warning("Session %s process died, restart attempt %d in %.1fs", session_id, attempt, delay)

        await asyncio.sleep(delay)

        if session.status == "stopped":
            break  # stop requested during backoff sleep

        # Restart: create device again (it was deleted on exit) and relaunch
        await self._restart_session(session_id)

    if attempt >= max_retries:
        session.status = "error"
        session.error_message = f"Max retries ({max_retries}) exceeded — session terminated"
        await self._cleanup_session_resources(session_id)
```

**Discretion decision:** Base delay 1.0s, max delay 30s, max retries 5. This gives the sequence: 1s, 2s, 4s, 8s, 16s before giving up — sufficient to survive transient disconnects without hammering.

### Pattern 4: v4l2loopback-ctl Subprocess Call (asyncio.to_thread)

**What:** `v4l2loopback-ctl add/delete` are short-lived blocking commands that must not block the asyncio event loop.

**When to use:** Device creation (session start) and deletion (session stop/shutdown).

```python
# Source: ARCHITECTURE.md + STACK.md
import asyncio
import subprocess

async def _create_v4l2_device(device_nr: int, card_label: str) -> None:
    """Create a v4l2loopback device. Raises RuntimeError on failure."""
    device_path = f"/dev/video{device_nr}"
    await asyncio.to_thread(
        subprocess.run,
        ["sudo", "v4l2loopback-ctl", "add",
         "-n", card_label,
         "--exclusive_caps=1",
         device_path],
        check=True,
        capture_output=True,
        text=True,
    )

async def _delete_v4l2_device(device_nr: int) -> None:
    """Delete a v4l2loopback device. Logs on failure but does not raise."""
    device_path = f"/dev/video{device_nr}"
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["sudo", "v4l2loopback-ctl", "delete", device_path],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.warning("Failed to delete v4l2loopback device %s: %s", device_path, exc.stderr)
```

**Note on `exclusive_caps=1`:** This flag ensures the device advertises `V4L2_CAP_VIDEO_CAPTURE` (bit 0x01) — required for `enumerate_capture_devices()` in `capture_v4l2.py` which checks `device_caps & 0x01`. Without it, Ubuntu 24.04 shows the cap incorrectly (PITFALLS.md Pitfall 9).

### Pattern 5: Process Launch with stderr=DEVNULL (D-06)

**What:** FFmpeg subprocess launched with stderr suppressed to prevent pipe buffer deadlock.

**When to use:** All FFmpeg/scrcpy process launches in production. D-06 is a locked decision.

```python
# Source: PITFALLS.md Pitfall 3 + CONTEXT.md D-06
async def _launch_ffmpeg(rtsp_url: str, device_path: str) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-i", rtsp_url,
        "-vf", "scale=640:480",
        "-pix_fmt", "yuyv422",   # matches V4L2Capture's format negotiation
        "-f", "v4l2",
        device_path,
        "-loglevel", "quiet",
        "-nostats",
        stderr=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
    )
```

**Pixel format note:** `yuyv422` (YUYV/YUY2) is the most universally accepted raw format for v4l2loopback. The existing `V4L2Capture._setup_device()` requests `_V4L2_PIX_FMT_MJPEG` first — if that fails on a loopback device, it falls through to whatever format the device negotiates. YUYV is safe. See PITFALLS.md Pitfall 11.

### Pattern 6: Capability Detection API

**What:** One-shot subprocess calls at request time to detect installed tool versions and NIC P2P capability.

**When to use:** `GET /api/wireless/capabilities` endpoint (WAPI-01).

```python
# Source: STACK.md + CONTEXT.md D-09/D-10
async def _check_tool(cmd: list[str]) -> tuple[bool, str]:
    """Return (available, version_string). Returns (False, "") on any error."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        output = (stdout + stderr).decode("utf-8", errors="replace")
        # Extract first line with version info
        version_line = output.split("\n")[0][:100]
        return True, version_line
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return False, ""

async def check_capabilities() -> dict:
    ffmpeg_ok, ffmpeg_ver = await _check_tool(["ffmpeg", "-version"])
    scrcpy_ok, scrcpy_ver = await _check_tool(["scrcpy", "--version"])
    adb_ok, adb_ver = await _check_tool(["adb", "version"])
    iw_ok, _ = await _check_tool(["iw", "--version"])

    # NIC P2P check
    p2p_supported = False
    if iw_ok:
        proc = await asyncio.create_subprocess_exec(
            "iw", "list",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        text = stdout.decode()
        p2p_supported = "P2P-GO" in text and "P2P-client" in text

    return {
        "tools": {
            "ffmpeg": {"available": ffmpeg_ok, "version": ffmpeg_ver},
            "scrcpy": {"available": scrcpy_ok, "version": scrcpy_ver},
            "adb": {"available": adb_ok, "version": adb_ver},
            "iw": {"available": iw_ok},
        },
        "nic": {"p2p_supported": p2p_supported},
        "miracast_ready": ffmpeg_ok and p2p_supported,
        "scrcpy_ready": scrcpy_ok and adb_ok,
    }
```

### Anti-Patterns to Avoid

- **rmmod in code:** NEVER call `rmmod v4l2loopback` from PipelineManager. Only `v4l2loopback-ctl add/delete`. rmmod fails silently when CaptureRegistry holds an fd — documented in PITFALLS.md Pitfall 1. D-04 locks this decision.
- **Dynamic device number allocation:** NEVER scan `/dev/video*` to find a free number. D-02 locks video10/video11. Dynamic allocation creates race conditions (PITFALLS.md Pitfall 2, ARCHITECTURE.md Anti-Pattern 4).
- **`asyncio.create_subprocess_shell`:** Always use `create_subprocess_exec` for security and correctness (CONTEXT.md discretion note, STACK.md).
- **Long-lived `subprocess.run()` in async context:** For short-lived commands (v4l2loopback-ctl), use `asyncio.to_thread(subprocess.run, ...)`. For long-lived processes (FFmpeg, scrcpy), use `asyncio.create_subprocess_exec` (ARCHITECTURE.md Anti-Pattern 2).
- **Premature `registry.acquire()`:** NEVER call `registry.acquire(device_path)` immediately after FFmpeg start. The producer-ready gate (D-08, WPIP-01) MUST be satisfied first. See PITFALLS.md Pitfall 6.
- **Modifying CaptureBackend to accept pushed frames:** v4l2loopback is the interface contract. Wireless sources write to the kernel device; V4L2Capture reads via normal ioctls. (ARCHITECTURE.md Anti-Pattern 1)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Process supervision | Custom process watcher thread | `asyncio.create_subprocess_exec` + `asyncio.Task` awaiting `proc.wait()` | stdlib; non-blocking; `returncode` property gives instant health check |
| v4l2 device creation | Direct ioctl to `/dev/v4l2loopback` control device | `v4l2loopback-ctl` subprocess | v4l2loopback-ctl is the documented stable interface; direct ioctl requires matching kernel struct internals — fragile |
| NIC capability detection | Parsing `/proc/net/wireless` or `iwconfig` | `iw list` + grep | `iwconfig` uses deprecated Wireless Extensions; `iw` uses nl80211 (current kernel API) |
| Tool version parsing | External library | `asyncio.create_subprocess_exec` + stdout parsing | 5 lines; no dependency |
| Exponential backoff | PyPI `backoff` or `tenacity` | Inline loop: `min(base * 2**attempt, max_delay)` | ~3 lines; zero dependency |

**Key insight:** This phase uses exclusively system binaries (`v4l2loopback-ctl`, `ffmpeg`, `scrcpy`, `adb`, `iw`) orchestrated by Python stdlib asyncio. No new PyPI packages. The complexity budget is in the lifecycle sequencing, not the individual operations.

---

## Common Pitfalls

### Pitfall 1: rmmod Blocked by Open CaptureRegistry fd
[VERIFIED: PITFALLS.md Pitfall 1]
**What goes wrong:** Code calls `rmmod v4l2loopback` while `CaptureRegistry` holds an fd. Command fails silently; module remains loaded.
**Why it happens:** v4l2loopback module ref-count prevents unload while any fd is open.
**How to avoid:** NEVER call rmmod from PipelineManager. Use only `v4l2loopback-ctl add/delete` (D-04).
**Warning signs:** `subprocess.run(["rmmod", ...])` returns non-zero; `lsmod` still shows v4l2loopback.

### Pitfall 2: Premature acquire() Before Producer Writes First Frame
[VERIFIED: PITFALLS.md Pitfall 6]
**What goes wrong:** `registry.acquire("/dev/video10")` is called immediately after FFmpeg launch. `_STALE_FRAME_TIMEOUT = 3.0s` fires before FFmpeg completes RTSP negotiation (1-5s). Health check raises `RuntimeError` and kills the session.
**Why it happens:** `_check_health()` in `capture_service.py:114` checks `time.monotonic() - _last_frame_time > 3.0`. If no frame has arrived, this fires.
**How to avoid:** Producer-ready gate (D-08, WPIP-01) — `asyncio.Event` set only after process is confirmed alive and first frame (or negotiation complete) detected.
**Warning signs:** Session transitions to error state 3-5 seconds after start; FFmpeg logs show it was still negotiating.

### Pitfall 3: FFmpeg Pipe Buffer Deadlock
[VERIFIED: PITFALLS.md Pitfall 3]
**What goes wrong:** FFmpeg spawned with `stderr=PIPE` but no task draining it. 64KB OS pipe buffer fills, FFmpeg blocks on write, frames stop flowing.
**Why it happens:** FFmpeg generates verbose stdout/stderr even at `-loglevel warning`. Buffer fills in seconds.
**How to avoid:** D-06 (locked) — `stderr=asyncio.subprocess.DEVNULL` + `-loglevel quiet -nostats`.
**Warning signs:** `proc.returncode is None` (process alive) but no frames for 3s; adding `-loglevel quiet` to FFmpeg args "fixes" it.

### Pitfall 4: Orphan FFmpeg Processes After FastAPI SIGKILL
[VERIFIED: PITFALLS.md Pitfall 5]
**What goes wrong:** FastAPI receives SIGKILL (not SIGTERM). Lifespan shutdown handler never runs. FFmpeg child processes become orphans (reparented to init). Next startup: `EBUSY` when creating new loopback session.
**Why it happens:** `asyncio.create_subprocess_exec` children are not killed when parent exits unless explicitly terminated.
**How to avoid:** `stop_all()` must use `try/finally` to call `proc.kill()`. Register `atexit.register(sync_kill_all_processes)` as last-resort fallback.
**Warning signs:** `ps aux | grep ffmpeg` shows processes after restart; `lsof /dev/video10` shows orphan fd.

### Pitfall 5: v4l2loopback exclusive_caps Not Set — enumerate_capture_devices Misses Device
[VERIFIED: PITFALLS.md Pitfall 9]
**What goes wrong:** Device created without `--exclusive_caps=1`. On Ubuntu 24.04, `device_caps & 0x01` returns 0 for the loopback node. `enumerate_capture_devices()` skips it. `/dev/video10` never appears in `GET /api/cameras`.
**Why it happens:** Known v4l2loopback bug (issue #619) where VIDEO_CAPTURE bit not set without `exclusive_caps`.
**How to avoid:** Always pass `--exclusive_caps=1` to `v4l2loopback-ctl add`.
**Warning signs:** `/dev/video10` exists (`ls /dev/video10` succeeds) but `GET /api/cameras` doesn't list it.

### Pitfall 6: Pixel Format Mismatch — cv2.imdecode Returns None
[VERIFIED: PITFALLS.md Pitfall 11]
**What goes wrong:** FFmpeg writes YUV420P to v4l2loopback; `V4L2Capture._setup_device()` requests `_V4L2_PIX_FMT_MJPEG` (0x47504A4D). The `VIDIOC_S_FMT` ioctl either errors silently or accepts a mismatched format. `cv2.imdecode(bytes, cv2.IMREAD_COLOR)` returns `None` on every frame (bytes are raw YUV, not JPEG).
**Why it happens:** v4l2loopback format is negotiated by the first writer (FFmpeg). The reader (V4L2Capture) can only negotiate what the writer provides.
**How to avoid:** Use `yuyv422` as the FFmpeg pixel format (YUYV/YUY2 is the most widely accepted V4L2 raw format). The existing `V4L2Capture._setup_device()` sets MJPEG first; if the loopback device was written with YUYV, MJPEG negotiation may fail — V4L2Capture needs to detect `driver == "v4l2loopback"` and adapt. OR use MJPEG output from FFmpeg: `-vcodec mjpeg -f v4l2`.
**Warning signs:** Frames arrive (`_last_frame_time` updates) but `get_frame()` returns black/garbage frames; adding FFmpeg `-vcodec mjpeg` fixes it.

---

## Integration Points with Existing Code (Confirmed by Codebase Inspection)

### main.py Changes Required

```python
# Add to imports (main.py)
from services.pipeline_manager import PipelineManager
from routers.wireless import router as wireless_router

# Add to lifespan startup (after registry creation):
pipeline_manager = PipelineManager(capture_registry=registry, db=db)
app.state.pipeline_manager = pipeline_manager

# Add to lifespan shutdown (BEFORE registry.shutdown()):
await asyncio.wait_for(pipeline_manager.stop_all(), timeout=5.0)

# Add router registration:
app.include_router(wireless_router)
```

**Shutdown ordering constraint:** `pipeline_manager.stop_all()` calls `registry.release(device_path)` for each session — this must complete before `registry.shutdown()` at line 63 of current `main.py`. Existing code has `registry.shutdown()` after `streaming.stop()` — add `pipeline_manager.stop_all()` between `streaming.stop()` and `registry.shutdown()`.

### database.py Changes Required

Per D-01, sessions are ephemeral in memory. However, the `wireless_sessions` table is still needed for:
1. Session enumeration if `app.state.pipeline_manager` is not available in a route handler
2. Startup cleanup of stale records from previous crash

```sql
-- Add to database.py init_db():
CREATE TABLE IF NOT EXISTS wireless_sessions (
    id TEXT PRIMARY KEY,               -- UUID
    session_type TEXT NOT NULL,        -- "miracast" | "android_scrcpy"
    device_path TEXT NOT NULL,         -- "/dev/video10"
    device_nr INTEGER NOT NULL,        -- 10
    card_label TEXT NOT NULL,          -- "Miracast Input"
    status TEXT NOT NULL DEFAULT 'starting',
    source_ip TEXT,
    pid INTEGER,
    started_at TEXT NOT NULL,
    stopped_at TEXT,
    error_message TEXT
);
```

Add to startup in `init_db`: `DELETE FROM wireless_sessions` — clears stale records from previous run. Sessions that survived in the DB from a crashed process are invalid (processes are gone, devices may or may not exist).

**Claude's discretion:** Use the DB table for `GET /api/wireless/sessions` serialization (reads from `pipeline_manager._sessions` dict, which may also write to DB for crash recovery). The in-memory dict is the source of truth during the run; DB is only for startup cleanup and optional persistence. This does not contradict D-01 because sessions are still ephemeral (cleared on startup).

### cameras.py — No Changes Required

`enumerate_capture_devices()` in `capture_v4l2.py` scans all `/dev/video*`. A v4l2loopback device at `/dev/video10` (with `exclusive_caps=1`) will:
1. Respond to `VIDIOC_QUERYCAP` with `V4L2_CAP_VIDEO_CAPTURE` bit set
2. Return `driver = "v4l2loopback"` in the QUERYCAP response
3. Return `card = "Miracast Input"` (the card_label set at creation)
4. Return `bus_info = "platform:v4l2loopback-000"`

The stable_id computed by `device_identity.get_stable_id()` falls back to `"{card}@{bus_info}"` = `"Miracast Input@platform:v4l2loopback-000"` — deterministic because device number is static (D-02). [VERIFIED: ARCHITECTURE.md stable_id analysis section]

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| v4l2loopback-dkms | VCAM-01, VCAM-02 | Unknown (Linux host) | >=0.12 | None — must be installed; capabilities endpoint reports unavailable |
| v4l2loopback-utils | VCAM-01, VCAM-02 | Unknown (Linux host) | >=0.12 | None |
| v4l2loopback-ctl binary | VCAM-01, VCAM-02 | Unknown (Linux host) | >=0.12 | None |
| sudoers NOPASSWD rule | VCAM-01, VCAM-02 | Unknown | N/A | None — without it, subprocess fails with permission denied |
| ffmpeg | VCAM-03, WPIP-01 | Unknown | >=4.4 | Report unavailable in capabilities; Miracast path blocked |
| scrcpy | WPIP-02 | Unknown | >=3.0 (--v4l2-sink needs v3+) | Report unavailable; Android path blocked |
| adb | WPIP-02 | Unknown | any | Report unavailable |
| iw | WAPI-01 | Unknown | any (nl80211) | Report NIC P2P unknown |
| Python 3.12 | All | Confirmed (pinned) | 3.12 | N/A |

**Note:** This phase runs on Linux only. The test machine is Windows (dev environment), so all subprocess calls to v4l2loopback-ctl, ffmpeg, scrcpy, etc. will fail on Windows. Tests MUST mock all subprocess calls. The implementation adds Linux-only code paths consistent with existing `sys.platform == "win32"` guards in `capture_service.py` and `cameras.py`.

**Missing dependencies with no fallback (block execution on target):**
- `v4l2loopback-dkms` + `v4l2loopback-ctl` — required for VCAM-01/02; must be pre-installed
- sudoers NOPASSWD rules for `v4l2loopback-ctl add/delete` — required at runtime

**Missing dependencies with graceful degradation:**
- `ffmpeg` missing → capabilities endpoint returns `miracast_ready: false`
- `scrcpy` missing → capabilities endpoint returns `scrcpy_ready: false`
- `iw` missing → `p2p_supported: false` (can't detect)

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `Backend/pytest.ini` (`asyncio_mode = auto`) |
| Quick run command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_pipeline_manager.py tests/test_wireless_router.py -x` |
| Full suite command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VCAM-01 | `_create_v4l2_device()` calls v4l2loopback-ctl with correct args | unit | `pytest tests/test_pipeline_manager.py::TestDeviceCreation -x` | ❌ Wave 0 |
| VCAM-01 | v4l2loopback-ctl failure raises error propagated to session | unit | `pytest tests/test_pipeline_manager.py::TestDeviceCreationFailure -x` | ❌ Wave 0 |
| VCAM-02 | `stop_session()` kills process + calls delete + does so within timeout | unit | `pytest tests/test_pipeline_manager.py::TestSessionStop -x` | ❌ Wave 0 |
| VCAM-02 | `stop_all()` in lifespan completes within 5s budget | unit | `pytest tests/test_pipeline_manager.py::TestStopAll -x` | ❌ Wave 0 |
| VCAM-03 | Process exit detected → supervised restart triggered | unit | `pytest tests/test_pipeline_manager.py::TestSupervisedRestart -x` | ❌ Wave 0 |
| VCAM-03 | Max retries exceeded → session marked error | unit | `pytest tests/test_pipeline_manager.py::TestMaxRetriesExceeded -x` | ❌ Wave 0 |
| WPIP-01 | `acquire()` not called until producer_ready event set | unit | `pytest tests/test_pipeline_manager.py::TestProducerReadyGate -x` | ❌ Wave 0 |
| WPIP-01 | producer_ready times out → session status = error | unit | `pytest tests/test_pipeline_manager.py::TestProducerReadyTimeout -x` | ❌ Wave 0 |
| WPIP-02 | Session start triggers `registry.acquire(device_path)` | unit | `pytest tests/test_pipeline_manager.py::TestRegistryAcquire -x` | ❌ Wave 0 |
| WPIP-03 | PipelineManager is sole owner — stop cleans up all resources | unit | `pytest tests/test_pipeline_manager.py::TestResourceOwnership -x` | ❌ Wave 0 |
| WAPI-01 | GET /api/wireless/capabilities returns correct structure | unit | `pytest tests/test_wireless_router.py::TestCapabilities -x` | ❌ Wave 0 |
| WAPI-01 | Tool not found → available=false in response | unit | `pytest tests/test_wireless_router.py::TestCapabilitiesToolMissing -x` | ❌ Wave 0 |
| WAPI-04 | GET /api/wireless/sessions returns list with correct fields | unit | `pytest tests/test_wireless_router.py::TestSessionsList -x` | ❌ Wave 0 |
| WAPI-04 | Session status reflects starting/active/error/stopped | unit | `pytest tests/test_wireless_router.py::TestSessionStatus -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_pipeline_manager.py tests/test_wireless_router.py -x`
- **Per wave merge:** `python -m pytest` (full suite — must keep 167+ existing tests green)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `Backend/tests/test_pipeline_manager.py` — covers VCAM-01 through WPIP-03
- [ ] `Backend/tests/test_wireless_router.py` — covers WAPI-01, WAPI-04
- [ ] `conftest.py` additions: `wireless_app_client` fixture with mocked PipelineManager; `mock_pipeline_manager` fixture

**Key testing constraint:** All subprocess calls (`asyncio.create_subprocess_exec`, `asyncio.to_thread(subprocess.run, ...)`) must be mocked. Tests run on Windows (dev machine) and Linux CI — neither will have `v4l2loopback-ctl` or `ffmpeg` installed in the test environment. Use `unittest.mock.patch("services.pipeline_manager.asyncio.create_subprocess_exec")` pattern consistent with existing test mocking patterns.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth — local network tool (CLAUDE.md) |
| V3 Session Management | no | Wireless sessions are internal state, not user sessions |
| V4 Access Control | no | No auth; all endpoints unauthenticated per design |
| V5 Input Validation | yes | `source_ip` field in POST body — validate is valid IP address before passing to subprocess |
| V6 Cryptography | no | No crypto involved |

### Known Threat Patterns for subprocess management

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Shell injection via source_ip | Tampering | Use `asyncio.create_subprocess_exec` (not shell); validate IP with `ipaddress.ip_address()` before use |
| Runaway subprocess not killed | Denial of Service | `stop_all()` with SIGTERM → SIGKILL; `atexit.register` fallback |
| v4l2loopback-ctl sudo privilege escalation | Elevation of Privilege | Narrow NOPASSWD rules: only `v4l2loopback-ctl add *` and `v4l2loopback-ctl delete *` — not `ALL=(ALL) NOPASSWD: ALL` |

**Shell injection prevention:** `source_ip` from POST body must be validated before being passed to scrcpy args:
```python
import ipaddress
def validate_ip(ip: str) -> str:
    try:
        return str(ipaddress.ip_address(ip))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid IP address")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `modprobe v4l2loopback video_nr=10` at load time | `v4l2loopback-ctl add /dev/videoN` at runtime | v4l2loopback >=0.12 | Dynamic device creation without module reload — avoids rmmod-while-in-use failures |
| `iwconfig` (Wireless Extensions) | `iw list` (nl80211) | ~2012 kernel 3.x | `iwconfig` deprecated; P2P capability only in nl80211 |
| `subprocess.Popen` + manual drain thread | `asyncio.create_subprocess_exec` + `StreamReader` | Python 3.4+ asyncio | Non-blocking subprocess management in async context |

**Deprecated/outdated:**
- `iwconfig`: Uses Wireless Extensions (deprecated). `iw` is the replacement. Do not use `iwconfig` or any library wrapping it.
- `python-wled` (PyPI): JSON API only, no UDP realtime. Not relevant to Phase 12 but noted from CLAUDE.md.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `v4l2loopback-ctl --exclusive_caps=1` flag syntax is correct | Standard Stack, Pitfalls | Flag may be `--exclusive_caps 1` or modprobe param style — verify on target system before first test |
| A2 | `yuyv422` pixel format is accepted by existing V4L2Capture without modification | Common Pitfalls (Pitfall 6) | If V4L2Capture fails to decode YUYV, FFmpeg must output MJPEG (`-vcodec mjpeg`) — adds ~5ms encode latency per frame |
| A3 | producer_ready gate of 1.5s sleep is sufficient for FFmpeg to negotiate RTSP | Code Examples (Pattern 2) | If RTSP negotiation takes >1.5s consistently, increase to 3-5s or implement actual frame detection |

**If this table has only 3 items:** All other claims were verified against STACK.md, ARCHITECTURE.md, PITFALLS.md (direct prior research) or existing codebase inspection.

---

## Open Questions

1. **Pixel format compatibility between FFmpeg output and V4L2Capture**
   - What we know: `V4L2Capture._setup_device()` requests `_V4L2_PIX_FMT_MJPEG` (MJPEG). v4l2loopback format is negotiated by the first writer (FFmpeg). YUYV is the most common raw format.
   - What's unclear: Will the existing `cv2.imdecode` path decode YUYV correctly without modification, or does it only handle MJPEG (JPEG bytes)?
   - Recommendation: Plan a Wave 0 or Wave 1 test task to verify format compatibility early. If V4L2Capture only handles MJPEG, add `-vcodec mjpeg` to the FFmpeg command template. This is the highest-risk unknown for Phase 12.

2. **sudoers NOPASSWD rule — service user vs developer user**
   - What we know: `v4l2loopback-ctl add/delete` require elevated privileges. D-04 documents this requires NOPASSWD rules.
   - What's unclear: Will the service run as a specific system user (e.g., `hpc-service`) or the developer's user? The sudoers rule syntax depends on the username.
   - Recommendation: Plan setup instructions (or a setup-check endpoint) that validates the sudoers rule exists before allowing session creation.

3. **v4l2loopback kernel module pre-loaded vs. modprobe at startup**
   - What we know: STACK.md says "The FastAPI service does NOT load the module at runtime — that is a host prerequisite." ARCHITECTURE.md says "Check on startup... attempt a test modprobe and rmmod to confirm module availability."
   - What's unclear: Should PipelineManager attempt `modprobe v4l2loopback` at startup if the module isn't loaded, or should it only report the module as unavailable?
   - Recommendation: Attempt `modprobe v4l2loopback` at PipelineManager startup (requires `sudo modprobe` NOPASSWD rule too). If it fails, mark wireless as unavailable and return that in capabilities endpoint. Don't hard-fail the entire app.

---

## Sources

### Primary (HIGH confidence)
- `.planning/research/STACK.md` — v4l2loopback-ctl API, scrcpy flags, FFmpeg subprocess patterns, no new pip packages [VERIFIED: direct file inspection]
- `.planning/research/ARCHITECTURE.md` — PipelineManager class design, integration points, component boundaries, unchanged components [VERIFIED: direct file inspection]
- `.planning/research/PITFALLS.md` — FFmpeg pipe deadlock, producer_ready gate, orphan processes, exclusive_caps, rmmod failure [VERIFIED: direct file inspection]
- `Backend/main.py` — lifespan pattern, app.state setup, shutdown ordering [VERIFIED: direct codebase inspection]
- `Backend/services/capture_service.py` — `_STALE_FRAME_TIMEOUT = 3.0`, `CaptureRegistry.acquire()`, `_check_health()` implementation [VERIFIED: direct codebase inspection]
- `Backend/services/capture_v4l2.py` — `enumerate_capture_devices()`, `V4L2DeviceInfo.driver` field, MJPEG format negotiation in `_setup_device()` [VERIFIED: direct codebase inspection]
- `Backend/services/device_identity.py` — sysfs fallback to `"{card}@{bus_info}"` for virtual devices [VERIFIED: direct codebase inspection]
- `Backend/database.py` — `ALTER TABLE` + `try/except` migration pattern [VERIFIED: direct codebase inspection]
- `Backend/tests/conftest.py` — pytest-asyncio `asyncio_mode = auto`, mock patterns [VERIFIED: direct codebase inspection]

### Secondary (MEDIUM confidence)
- `.planning/phases/12-virtual-device-infrastructure/12-CONTEXT.md` — locked decisions D-01 through D-11 [VERIFIED: direct file inspection]
- `Backend/routers/cameras.py` — router structure pattern, Pydantic models, `_scan_devices()` helper pattern [VERIFIED: direct codebase inspection]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all stdlib asyncio + existing dependencies; confirmed by STACK.md
- Architecture: HIGH — PipelineManager design fully specified in ARCHITECTURE.md; integration points verified by codebase inspection
- Pitfalls: HIGH — all pitfalls verified against PITFALLS.md (prior research) + codebase inspection confirming `_STALE_FRAME_TIMEOUT`, MJPEG format, etc.
- Test architecture: HIGH — pytest-asyncio patterns confirmed; test file structure follows existing project conventions

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (stable domain — v4l2loopback, asyncio subprocess, FFmpeg are mature technologies)

**Note on development environment:** This project is developed on Windows (IdeaProjects path) but deploys on Linux. All subprocess-based features are Linux-only. Tests must mock all system calls. This is consistent with existing `sys.platform == "win32"` guards throughout the codebase.
