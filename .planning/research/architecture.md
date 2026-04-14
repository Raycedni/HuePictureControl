# Architecture Patterns: Wireless Input Integration (v1.2)

**Domain:** Real-time ambient lighting — wireless screen mirroring input via Miracast, scrcpy, v4l2loopback, FFmpeg
**Researched:** 2026-04-14
**Confidence:** HIGH — based on direct codebase inspection, verified upstream documentation, and confirmed protocol behaviour

> This document covers v1.2 wireless input additions only.
> The existing v1.1 architecture (CaptureRegistry, preview WebSocket, camera_assignments, known_cameras) is already shipped and is not re-documented here.
> The v1.3 architecture (WledService, StreamingCoordinator, HA router) is in the archived v1.3 ARCHITECTURE.md.

---

## System Overview (v1.2)

The core insight: v4l2loopback lets any wireless input appear as a `/dev/video*` device. Once that device exists, the **existing CaptureRegistry, V4L2Capture, StreamingService, and preview WebSocket require zero changes.** The entire integration lives in a new PipelineManager service and a new wireless router.

```
+-------------------------------------------------------+
|  Wireless Source                                      |
|                                                       |
|  Windows machine     Android device                   |
|  (Win+K Miracast)    (scrcpy over WiFi)               |
+----------+------------------+--------------------------+
           |  WiFi Direct     |  TCP/IP (adb 5555)
           |                  |
+----------v------------------v-----------+
|  Linux Host — Wireless Input Layer     |
|                                        |
|  MiracleCast sink     scrcpy process   |
|  (miracled daemon)    --v4l2-sink      |
|         |              (direct, no     |
|         |               FFmpeg needed) |
|         | RTSP stream                  |
|  +------v------+                       |
|  | FFmpeg proc |                       |
|  | -i rtsp://  |                       |
|  | -vf scale   |                       |
|  | -f v4l2     |                       |
|  +------+------+                       |
|         |                              |
|  /dev/video10 (v4l2loopback)           |
|  /dev/video11 (v4l2loopback)           |
|         |                              |
|  PipelineManager (new service)         |
|  v4l2loopback-ctl / modprobe           |
+----+---------+--------------------------+
     |         |
+----v---------v------------------------------------------+
|  Existing V4L2 Pipeline (UNCHANGED)                     |
|                                                         |
|  CaptureRegistry.acquire("/dev/video10")                |
|    -> V4L2Capture.open("/dev/video10")                  |
|    -> VIDIOC_QUERYCAP -> VIDEO_CAPTURE capability found |
|    -> MJPEG mmap streaming starts                       |
|                                                         |
|  StreamingService._resolve_device_path() -> /dev/video10|
|  preview_ws.py -> registry.get("/dev/video10")         |
|                                                         |
|  cameras.py: enumerate_capture_devices()               |
|   -> scans /dev/video* including /dev/video10          |
|   -> video10 appears in camera selector dropdown       |
+----------------------------------------------------------+
```

---

## Key Constraint: scrcpy Does Not Need FFmpeg

scrcpy has a native `--v4l2-sink=/dev/videoN` flag (Linux only). It creates the loopback device directly — no FFmpeg intermediary needed for Android. This is the preferred path for Android.

For Miracast (Windows), the sink is a RTSP stream from the MiracleCast receiver daemon. FFmpeg is needed to transcode that RTSP output into rawvideo and pipe it into a v4l2loopback device.

```
Android path:   scrcpy --tcpip=IP --v4l2-sink=/dev/video10 --no-display
Windows path:   miracled (RTSP on port 7236) -> ffmpeg -i rtsp://localhost:7236/wfd1.0 -f v4l2 /dev/video10
```

---

## New vs Modified Components

### New Components

| Component | File | Purpose |
|-----------|------|---------|
| PipelineManager | `services/pipeline_manager.py` | Lifecycle manager for FFmpeg and scrcpy subprocesses + v4l2loopback device creation/deletion |
| WirelessRouter | `routers/wireless.py` | REST API: start/stop wireless sessions, list sessions, NIC capability check |
| WirelessSession (model) | `models/wireless.py` | Pydantic: session type, device path, status, PID, source IP |

### Modified Components

| Component | File | Change |
|-----------|------|--------|
| `main.py` | existing | Add `app.state.pipeline_manager = PipelineManager()` in lifespan. Add `wireless_router` include. Shutdown: call `pipeline_manager.stop_all()`. |
| `cameras.py` router | existing | `enumerate_capture_devices()` already scans all `/dev/video*`. Virtual devices created by v4l2loopback appear automatically. No code change required — only `display_name` from `VIDIOC_QUERYCAP` will read the card_label set at device creation time. |
| `database.py` | existing | Add `wireless_sessions` table (one row per active session, cleared on startup). |

### Unchanged Components (explicitly verified)

| Component | Why Unchanged |
|-----------|--------------|
| `V4L2Capture` | v4l2loopback devices advertise `V4L2_CAP_VIDEO_CAPTURE` — `V4L2Capture.open()` works identically |
| `CaptureRegistry` | Acquires by device path. `/dev/video10` is identical to `/dev/video0` from its perspective |
| `StreamingService` | Resolves device path from DB, acquires from registry. Transparent to how the device was created |
| `preview_ws.py` | `registry.get(device_path)` — works for any device path |
| `streaming_ws.py` | No changes |
| All existing routers | `capture.py`, `hue.py`, `regions.py`, `streaming_ws.py` — unmodified |

---

## Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| `PipelineManager` | Create/destroy v4l2loopback devices via `v4l2loopback-ctl`. Spawn/monitor/restart FFmpeg and scrcpy subprocesses. Map session_id -> process + device_path. Emit health events. | `asyncio.create_subprocess_exec`, `subprocess.run` (for v4l2loopback-ctl), OS signals |
| `WirelessRouter` | Start/stop wireless sessions via REST. List active sessions. Check NIC P2P capability. | `PipelineManager`, `database.py` |
| Frontend WirelessPage | Tab with start/stop controls, session list, NIC status indicator | `api/wireless.ts` HTTP client |

---

## Data Flow: Wireless Source to Hue Lights

```
1. User clicks "Start Miracast" in UI
   -> POST /api/wireless/sessions {type: "miracast"}
   -> WirelessRouter -> PipelineManager.start_miracast()

2. PipelineManager creates virtual device
   -> subprocess.run(["v4l2loopback-ctl", "add", "-n", "Miracast Input", "/dev/video10"])
   -> writes session to wireless_sessions table

3. PipelineManager spawns FFmpeg (for Miracast) or scrcpy (for Android)
   Miracast:
     -> asyncio.create_subprocess_exec(
          "ffmpeg", "-i", "rtsp://localhost:7236/wfd1.0",
          "-vf", "scale=640:480",
          "-pix_fmt", "yuyv422",   # matches V4L2Capture's _V4L2_PIX_FMT_MJPEG expectation
          "-f", "v4l2", "/dev/video10"
        )
   Android (scrcpy):
     -> asyncio.create_subprocess_exec(
          "scrcpy", "--tcpip=192.168.x.x",
          "--v4l2-sink=/dev/video10",
          "--no-display"
        )

4. /dev/video10 now appears as a V4L2 capture device
   -> GET /api/cameras lists it with display_name "Miracast Input"

5. User assigns /dev/video10 to entertainment config in UI
   -> PUT /api/cameras/assignments/{config_id} {camera_stable_id: ..., camera_name: "Miracast Input"}

6. User starts streaming
   -> POST /api/capture/start {config_id: "..."}
   -> StreamingService._resolve_device_path() -> "/dev/video10"
   -> CaptureRegistry.acquire("/dev/video10") -> V4L2Capture.open("/dev/video10")
   -> V4L2Capture._setup_device() -> VIDIOC_QUERYCAP OK, MJPEG streaming starts
   -> Frame loop runs at target Hz, extracts colors, drives Hue lights
```

---

## PipelineManager Internal Architecture

```python
class PipelineManager:
    """Lifecycle owner for FFmpeg/scrcpy subprocesses and v4l2loopback devices.

    Each wireless session owns:
      - One v4l2loopback device (/dev/videoN)
      - One subprocess (FFmpeg or scrcpy)
      - One health monitor asyncio.Task
    """

    # session_id -> WirelessSessionState
    _sessions: dict[str, WirelessSessionState]

    async def start_miracast(self, device_nr: int) -> WirelessSessionState:
        """Create v4l2loopback device + spawn FFmpeg -> RTSP pipeline."""

    async def start_android(self, device_ip: str, device_nr: int) -> WirelessSessionState:
        """Create v4l2loopback device + spawn scrcpy --v4l2-sink."""

    async def stop_session(self, session_id: str) -> None:
        """Kill subprocess -> destroy v4l2loopback device -> update DB."""

    async def stop_all(self) -> None:
        """Called at app shutdown. Kills all processes and destroys all devices."""

    async def _monitor_process(self, session_id: str) -> None:
        """asyncio.Task: watches process.returncode.
           On unexpected exit: update DB status to 'crashed', log stderr."""
```

### Process Spawning Pattern

Use `asyncio.create_subprocess_exec` with `stderr=asyncio.subprocess.PIPE` to capture FFmpeg/scrcpy output for health monitoring and logging. Do not use stdout pipe for FFmpeg — it outputs to the v4l2 device, not stdout.

```python
proc = await asyncio.create_subprocess_exec(
    "ffmpeg", *args,
    stderr=asyncio.subprocess.PIPE,
    # stdout NOT piped — FFmpeg writes to /dev/videoN directly
)
# Spawn background task to drain stderr and detect crash
asyncio.create_task(_drain_stderr(session_id, proc))
```

`proc.returncode is None` means the process is still running. When it exits non-zero, update session status to `"crashed"` and optionally auto-restart (not required for MVP).

### v4l2loopback Device Management

```python
# Create device (requires sudo or CAP_SYS_ADMIN):
subprocess.run(
    ["v4l2loopback-ctl", "add", "-n", card_label, f"/dev/video{device_nr}"],
    check=True
)

# Delete device on session stop:
subprocess.run(
    ["v4l2loopback-ctl", "delete", f"/dev/video{device_nr}"],
    check=True
)
```

Use fixed `video_nr` in range 10-19 to avoid colliding with physical capture cards (typically video0, video1). Reserve one device slot per session type (e.g., video10 = Miracast, video11 = Android scrcpy). Do not dynamically allocate — static assignment prevents race conditions during startup.

**Kernel module requirement:** The v4l2loopback kernel module must be loaded before any device can be created. Check on startup:

```python
def ensure_module_loaded() -> bool:
    result = subprocess.run(["lsmod"], capture_output=True, text=True)
    if "v4l2loopback" not in result.stdout:
        try:
            subprocess.run(["modprobe", "v4l2loopback"], check=True)
            return True
        except subprocess.CalledProcessError:
            return False  # Module not installed — wireless unavailable
    return True
```

---

## Database Schema Addition

```sql
-- Active wireless streaming sessions
-- Cleared on app startup (sessions don't survive restarts)
CREATE TABLE IF NOT EXISTS wireless_sessions (
    id TEXT PRIMARY KEY,               -- UUID
    session_type TEXT NOT NULL,        -- "miracast" | "android_scrcpy"
    device_path TEXT NOT NULL,         -- "/dev/video10"
    device_nr INTEGER NOT NULL,        -- 10
    card_label TEXT NOT NULL,          -- "Miracast Input"
    status TEXT NOT NULL DEFAULT 'starting',  -- starting | running | crashed | stopped
    source_ip TEXT,                    -- Android IP for scrcpy, NULL for Miracast
    pid INTEGER,                       -- OS process ID of FFmpeg or scrcpy
    started_at TEXT NOT NULL,          -- ISO8601
    stopped_at TEXT                    -- NULL while running
);
```

Cleared on startup because subprocesses don't survive app restarts. On `lifespan` startup, run `DELETE FROM wireless_sessions` then call `pipeline_manager.stop_all()` (defensive cleanup of any zombie processes from previous run).

---

## New API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/wireless/sessions` | List all sessions with status and device_path |
| POST | `/api/wireless/sessions` | Start a new session — body: `{type: "miracast" \| "android_scrcpy", source_ip?: "..."}` |
| DELETE | `/api/wireless/sessions/{id}` | Stop session, kill process, destroy v4l2 device |
| GET | `/api/wireless/nic/status` | Check if WiFi NIC supports P2P (required for Miracast) |

### NIC Capability Check

For Miracast (WiFi Direct), the NIC must support P2P mode. Check via `iw list` output:

```python
async def check_p2p_support() -> dict:
    proc = await asyncio.create_subprocess_exec(
        "iw", "list",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode()
    p2p_supported = "P2P-client" in output and "P2P-GO" in output
    return {"p2p_supported": p2p_supported, "raw": output[:2000]}
```

---

## Frontend Changes

### New WirelessPage Component

New tab: "Wireless Input". Contains:

1. **NIC Status Banner** — shows `GET /api/wireless/nic/status` result. "P2P supported" or "Miracast unavailable — NIC does not support WiFi Direct".
2. **Session List** — cards for each active session with type, status badge, device_path, stop button.
3. **Start Miracast** button — enabled only when `p2p_supported: true`. One click starts the session.
4. **Start Android (scrcpy)** form — IP address input field + connect button. No P2P NIC required.

### Camera Selector (No Changes Required)

The camera selector dropdown in `EditorPage` already calls `GET /api/cameras` which scans all `/dev/video*`. Virtual devices created by v4l2loopback appear automatically with their `card_label` as the `display_name`. No frontend code changes to the camera selector.

**One edge case:** The stable_id for a v4l2loopback device comes from `get_stable_id()` which reads `/sys/class/video4linux/video10/device/idVendor`. v4l2loopback devices are virtual and have no USB sysfs path, so `get_stable_id()` falls back to the degraded `"{card}@{bus_info}"` format (e.g., `"Miracast Input@platform:v4l2loopback-000"`). This stable_id is deterministic across restarts as long as the `card_label` and device number stay constant — the static device number assignment (video10 = Miracast) ensures this.

---

## Architectural Patterns

### Pattern 1: Virtual Device as Integration Boundary

The v4l2loopback device is the interface contract between wireless input and the existing V4L2 pipeline. Everything downstream (CaptureRegistry, V4L2Capture, StreamingService, preview WebSocket) is unchanged because `/dev/video10` is indistinguishable from `/dev/video0` at the V4L2 ioctl level.

This is the correct abstraction. Do not attempt to pipe wireless frames directly into CaptureBackend memory — that would require modifying CaptureBackend to accept frames from sources other than V4L2 ioctls, which would add a new code path, new tests, and new failure modes.

### Pattern 2: PipelineManager as Pure Subprocess Owner

PipelineManager does not understand colors, regions, or Hue lights. It only knows about OS processes, device paths, and session lifecycle. It is a thin wrapper around `asyncio.create_subprocess_exec` and `subprocess.run`.

This keeps the wireless logic isolated from streaming logic. If FFmpeg crashes, PipelineManager handles the restart. If the V4L2 device disappears, the existing `_capture_reconnect_loop` in `StreamingService` handles recovery — same as a disconnected USB capture card.

### Pattern 3: Static Device Number Allocation

Allocate `/dev/video10` = Miracast, `/dev/video11` = Android scrcpy. Do not scan for available device numbers dynamically. Static allocation:
- Produces deterministic stable_ids (the `card@bus_info` fallback is consistent)
- Prevents races when two sessions start simultaneously
- Simplifies camera_assignments: the user assigns once and the device path doesn't change between sessions

### Pattern 4: scrcpy --no-display for Headless Operation

scrcpy normally opens an SDL2 window to display the mirrored screen. In server mode (FastAPI running headlessly), pass `--no-display` to suppress the window. The `--v4l2-sink` output continues unaffected.

```
scrcpy --tcpip=192.168.x.x --v4l2-sink=/dev/video11 --no-display --turn-screen-off
```

`--turn-screen-off` is optional but recommended for the Android device power budget.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Modifying CaptureBackend to Accept Pushed Frames

**What:** Add a method like `CaptureBackend.push_frame(numpy_array)` so wireless sources can inject frames directly.

**Why bad:** Destroys the clean abstraction. `V4L2Capture._reader_loop` uses mmap and ioctls to pull frames from the kernel. Adding a push path creates two competing frame sources, requires locking changes, and breaks the `_last_frame_time` health check.

**Do this instead:** Let v4l2loopback create a real kernel buffer. FFmpeg or scrcpy writes into it. `V4L2Capture` reads from it via normal ioctls. No code changes anywhere downstream.

### Anti-Pattern 2: Long-lived subprocess.run() Calls in Async Code

**What:** Blocking subprocess calls (e.g., `subprocess.run(["ffmpeg", ...])`) inside a FastAPI async route handler.

**Why bad:** Blocks the event loop until the process exits. For a long-lived FFmpeg pipeline, this never returns.

**Do this instead:** `asyncio.create_subprocess_exec()` for long-lived processes (returns immediately, process runs in background). `asyncio.to_thread(subprocess.run, ...)` only for short-lived one-shot commands like `v4l2loopback-ctl add`.

### Anti-Pattern 3: Running v4l2loopback-ctl as a Blocking Call Inside Route Handler

**What:** Directly calling `subprocess.run(["v4l2loopback-ctl", ...])` in a FastAPI route.

**Why bad:** `subprocess.run` is synchronous and blocks the event loop, even for a fast command. The startup time of `v4l2loopback-ctl` is unpredictable (~50-200ms).

**Do this instead:** `await asyncio.to_thread(subprocess.run, ["v4l2loopback-ctl", ...])`.

### Anti-Pattern 4: Dynamically Scanning for Available Device Numbers

**What:** Scan `/dev/video*` to find the first unoccupied number before creating a v4l2loopback device.

**Why bad:** Race condition — another process could claim the same number between the scan and the `v4l2loopback-ctl add` call. Produces non-deterministic device paths, breaking stable_id consistency.

**Do this instead:** Static device numbers in config (video10, video11). Fixed allocation means the stable_id `"Miracast Input@platform:v4l2loopback-000"` is always the same.

### Anti-Pattern 5: Treating Miracast and scrcpy as Equivalent Pipelines

**What:** Abstracting both into a single generic `start_pipeline(source_type, ...)` that builds different ffmpeg/scrcpy args.

**Why bad:** The two have fundamentally different runtime concerns. Miracast requires: (a) NIC P2P capability check, (b) miracled daemon running, (c) WiFi Direct peer discovery, (d) RTSP endpoint appearing at a known port. scrcpy requires: (a) adb connectivity check, (b) TCP connection to device IP. The failure modes and reconnect logic are completely different.

**Do this instead:** `start_miracast()` and `start_android_scrcpy()` as separate PipelineManager methods. Common infrastructure (v4l2 device creation, process monitoring, DB writes) is extracted into private helpers they both call.

---

## Build Order (Phase Dependencies)

```
Phase 1: Infrastructure (no dependencies)
  Step 1a: Install v4l2loopback-dkms on host. Verify with: sudo modprobe v4l2loopback
  Step 1b: Install miraclecast (or lazycast) on host. Verify RTSP endpoint appears.
  Step 1c: Add wireless_sessions table to database.py
  Step 1d: Add PipelineManager scaffold (empty start/stop methods) + wire into main.py

Phase 2: Android scrcpy path (lower risk — no NIC requirement)
  Step 2a: PipelineManager.start_android_scrcpy(device_ip, device_nr=11)
            creates /dev/video11 via v4l2loopback-ctl
            spawns scrcpy --tcpip=IP --v4l2-sink=/dev/video11 --no-display
  Step 2b: WirelessRouter /api/wireless/sessions POST (android_scrcpy type)
  Step 2c: Test: GET /api/cameras shows "Android Mirror" device
  Step 2d: Test: assign /dev/video11 to entertainment config, start streaming

Phase 3: Miracast path (requires WiFi Direct NIC, higher risk)
  Step 3a: GET /api/wireless/nic/status — iw list P2P check
  Step 3b: PipelineManager.start_miracast(device_nr=10)
            spawns miracled / sets up WiFi Direct
            FFmpeg RTSP -> v4l2loopback pipeline
  Step 3c: Integration test with Windows source

Phase 4: Frontend
  Step 4a: WirelessPage (session list, start forms, NIC status)
  Step 4b: Wire into App.tsx tab structure
```

**Why Android first:** scrcpy requires only `adb connect IP` — testable with any Android device over LAN without P2P NIC. Miracast requires WiFi Direct hardware support and a Windows sender. Android path validates the entire v4l2loopback + V4L2Capture integration before the higher-risk Miracast path.

**Why frontend last:** The backend API (`/api/wireless/sessions`, `/api/cameras`) must be stable and tested before building the UI against it.

---

## Integration Points Summary

| New Component | Existing Module | Integration Method |
|--------------|----------------|-------------------|
| `PipelineManager` | `main.py` lifespan | Created at startup; `stop_all()` called at shutdown |
| `PipelineManager` | `database.py` | Writes `wireless_sessions` table rows on start/stop |
| `WirelessRouter` | `PipelineManager` | Calls `start_*/stop_session` via `app.state.pipeline_manager` |
| v4l2loopback `/dev/video10` | `capture_v4l2.enumerate_capture_devices()` | No integration needed — enumerate scans all `/dev/video*` automatically |
| v4l2loopback `/dev/video10` | `CaptureRegistry.acquire("/dev/video10")` | No integration needed — registry works by path |
| v4l2loopback `/dev/video10` | `V4L2Capture.open("/dev/video10")` | No integration needed — VIDIOC_QUERYCAP works on virtual devices |
| v4l2loopback `/dev/video10` | `StreamingService._resolve_device_path()` | No integration needed — returns path from DB, hands to registry |
| v4l2loopback `/dev/video10` | `preview_ws.py /ws/preview?device=` | No integration needed — already routes by path |
| `WirelessPage.tsx` | `App.tsx` | Add `'wireless'` to `Page` type union; add nav tab |
| `WirelessPage.tsx` | Camera selector dropdown | No change — virtual device appears automatically in `GET /api/cameras` |

---

## Confidence Assessment

| Area | Confidence | Source |
|------|------------|--------|
| v4l2loopback virtual devices pass VIDIOC_QUERYCAP | HIGH | v4l2loopback README, ArchWiki — module specifically designed to appear as V4L2_CAP_VIDEO_CAPTURE |
| scrcpy --v4l2-sink flag exists and is Linux-only | HIGH | Genymobile/scrcpy GitHub, official docs |
| scrcpy WiFi via --tcpip=IP adb TCP connection | HIGH | Genymobile/scrcpy connection.md, verified multiple sources |
| scrcpy --no-display suppresses SDL window | HIGH | scrcpy docs — confirmed flag exists |
| v4l2loopback-ctl add/delete for runtime device management | HIGH | v4l2loopback README (confirmed dynamic management tool exists) |
| FFmpeg -f v4l2 output to loopback device | HIGH | Standard FFmpeg v4l2 output, multiple tutorials confirmed |
| Miracast receiver via MiracleCast RTSP on port 7236 | MEDIUM | MiracleCast GitHub — mentions mplayer rtsp://localhost:7236/wfd1.0 |
| v4l2loopback stable_id degrades to card@bus_info | HIGH | Direct code inspection of device_identity.py — sysfs absent for virtual devices |
| miracled daemon reliability on non-RPi hardware | LOW | MiracleCast last active commit 2021; community reports mixed results on non-RPi hosts |

**LOW confidence flag for Miracast:** MiracleCast (the primary Linux Miracast sink) has limited recent maintenance and community reports indicate reliability issues on non-Raspberry Pi hardware. lazycast is also RPi-targeted. Phase 3 (Miracast) should begin with a feasibility spike on the specific host hardware before building the PipelineManager integration. The scrcpy/Android path (Phase 2) is well-supported and should be built first regardless.

---

## Sources

- Direct code inspection: `Backend/services/capture_service.py` — CaptureRegistry, V4L2Capture, CaptureBackend interface
- Direct code inspection: `Backend/services/capture_v4l2.py` — V4L2 ioctl implementation, VIDIOC_QUERYCAP, mmap setup
- Direct code inspection: `Backend/services/device_identity.py` — stable_id sysfs fallback for virtual devices
- Direct code inspection: `Backend/services/streaming_service.py` — `_resolve_device_path`, `_capture_reconnect_loop`
- Direct code inspection: `Backend/routers/cameras.py` — `enumerate_capture_devices` scan pattern
- Direct code inspection: `Backend/routers/preview_ws.py` — `?device=` routing, `registry.get()` pattern
- Direct code inspection: `Backend/main.py` — `app.state` layout, lifespan pattern
- Direct code inspection: `Backend/database.py` — schema, ALTER TABLE migration pattern
- [v4l2loopback GitHub](https://github.com/v4l2loopback/v4l2loopback) — dynamic device creation via v4l2loopback-ctl, modprobe parameters — HIGH confidence
- [scrcpy GitHub](https://github.com/Genymobile/scrcpy) — `--v4l2-sink`, `--no-display`, `--tcpip` flags — HIGH confidence
- [scrcpy connection docs](https://github.com/Genymobile/scrcpy/blob/master/doc/connection.md) — WiFi TCP/IP connection procedure — HIGH confidence
- [MiracleCast GitHub](https://github.com/albfan/miraclecast) — miracled daemon, RTSP output, wpa_supplicant P2P — MEDIUM confidence
- [lazycast GitHub](https://github.com/homeworkc/lazycast) — Miracast RPi receiver, RTSP + H.264 decode, system deps — MEDIUM confidence (RPi-specific)
- [Python asyncio subprocess docs](https://docs.python.org/3.12/library/asyncio-subprocess.html) — `create_subprocess_exec`, process lifecycle, returncode — HIGH confidence

---

*Architecture research for: HuePictureControl v1.2 Wireless Input*
*Researched: 2026-04-14*
