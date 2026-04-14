# Domain Pitfalls — Wireless Screen Mirroring (v1.2)

**Domain:** Adding wireless input (Miracast/WiFi Direct, scrcpy/ADB, v4l2loopback, FFmpeg pipelines) to an existing V4L2 capture system on native Linux
**Researched:** 2026-04-14
**Confidence:** HIGH (grounded in v4l2loopback source/docs, Python asyncio subprocess docs, scrcpy issue tracker, Miracast/miraclecast community sources, and direct analysis of the existing CaptureRegistry codebase)

---

## Critical Pitfalls

### Pitfall 1: v4l2loopback `rmmod` Fails While CaptureRegistry Holds a File Descriptor

**What goes wrong:**
The operator or a restart sequence calls `rmmod v4l2loopback` to reconfigure the module (change `video_nr`, `exclusive_caps`, or `card_label`). The command fails silently or with `ERROR: Module v4l2loopback is in use` because `CaptureRegistry` has an open file descriptor to the loopback device — either from an active streaming session or from the capture reader thread still running.

The failure mode is silent from the Python side: `rmmod` exits non-zero, the module remains loaded with the old parameters, and the next `modprobe v4l2loopback video_nr=10` either silently no-ops or conflicts. The HuePictureControl process believes it restarted the virtual device, but the old module state persists.

**Why it happens:**
The v4l2loopback module maintains a reference count. `rmmod` refuses to unload while any file descriptor to a `/dev/videoN` node backed by the module is open. `CaptureRegistry.acquire()` calls `V4L2Capture.open()` which calls `os.open(path, os.O_RDWR)` — that fd stays open until `CaptureRegistry.release()` is called with the ref count dropping to zero. If streaming is active, that never happens until `streaming.stop()` and registry `shutdown()` complete.

**Consequences:**
- Module parameter changes (new `video_nr`, `exclusive_caps`) never take effect without a process restart
- If code tries to `rmmod` and then `modprobe` without waiting for the fd to close, the `modprobe` may fail or create a second conflicting module load attempt
- Operators get no visible error in the HuePictureControl UI — the failure is at the `subprocess` level

**Prevention:**
- Route all `modprobe`/`rmmod` calls through a `VirtualDeviceManager` that first calls `registry.release(device_path)` for all loopback devices, waits for the `V4L2Capture.release()` to complete (the fd to close), then proceeds with module management
- Add a check: `lsmod | grep v4l2loopback` to confirm the module loaded before returning success from any module management endpoint
- Never call `rmmod` speculatively — only call it when a full device teardown has been confirmed
- For reconfiguration (changing `video_nr`), prefer `v4l2loopback-ctl` add/remove device commands (available since v0.12) over rmmod/modprobe cycles — these work while the module is loaded, without requiring all consumers to close

**Detection:**
- `subprocess.run(["rmmod", "v4l2loopback"])` returns non-zero exit code
- `/proc/modules` still shows `v4l2loopback` after the rmmod call
- `lsof /dev/video10` (or whichever video_nr was used) shows the HuePictureControl process holding the fd

**Phase to address:**
Virtual device lifecycle phase — must be the first thing designed before any module management code is written.

---

### Pitfall 2: v4l2loopback `video_nr` Collides with Physical V4L2 Devices

**What goes wrong:**
The code loads v4l2loopback with `video_nr=10` to create `/dev/video10` for the Miracast virtual camera. On a machine with two USB capture cards, the kernel has already assigned `/dev/video0`, `/dev/video1`, `/dev/video2`, `/dev/video3` (two capture nodes + two metadata nodes per card). If the user plugs in a third device later, or if the USB capture card was absent at boot and gets assigned `/dev/video10` on attachment, the loopback device path conflicts with a real device path.

`CaptureRegistry` keyed by `/dev/video10` will open whichever device has that path — it cannot distinguish a v4l2loopback node from a physical capture node. The stream gets garbage frames (or the physical device's video, not the wireless stream) with no error.

**Why it happens:**
Linux assigns `/dev/videoN` sequentially at device-attach time. `video_nr` requests a specific number but the kernel may assign an adjacent number if that one is taken. More concretely, if another application or OS service has already reserved the node at boot (e.g., OBS installed as a system service, or another v4l2loopback instance), the requested `video_nr` silently shifts.

**Consequences:**
- Silent correctness failure: the wrong device gets opened
- `CaptureRegistry.acquire("/dev/video10")` succeeds but reads physical camera frames instead of wireless stream frames
- The existing stable-ID system (`device_identity.py`) does not distinguish v4l2loopback nodes from physical nodes — both pass `VIDIOC_QUERYCAP` with `V4L2_CAP_VIDEO_CAPTURE` set

**Prevention:**
- After `modprobe v4l2loopback video_nr=10`, verify the actual created device path by reading `/sys/devices/virtual/video4linux/video*/name` and matching the `card_label` set at load time (e.g., `card_label="HPC-Miracast"`) — do not assume `video_nr=10` means `/dev/video10`
- Store the loopback device by its `card_label`, not its `/dev/videoN` path, in the database. Resolve to current path at session start by scanning `enumerate_capture_devices()` and matching `card` field
- Use a high, unusual `video_nr` (e.g., 42, 43) that is unlikely to be claimed by physical devices on typical hardware, but still verify after load
- Add the loopback `card_label` to the `CaptureRegistry`'s resolution path so that `acquire("HPC-Miracast")` resolves to the current `/dev/videoN` rather than using the raw path directly

**Detection:**
- `v4l2-ctl -d /dev/video10 --info` shows `Card type: <real capture card name>` instead of the expected `card_label`
- `dmesg | grep video` shows a kernel message like `videoN: already in use` during modprobe
- Frames coming from `/dev/video10` contain physical camera content (desktop/webcam) rather than the wireless stream

**Phase to address:**
Virtual device creation phase — the path-verification step must be part of the `modprobe` wrapper before any CaptureRegistry integration.

---

### Pitfall 3: FFmpeg Subprocess Pipe Deadlock When stderr/stdout Are PIPE

**What goes wrong:**
The FFmpeg pipeline management code spawns FFmpeg with `asyncio.create_subprocess_exec(...)` and captures both `stdout=asyncio.subprocess.PIPE` and `stderr=asyncio.subprocess.PIPE` for log monitoring and health detection. FFmpeg writes verbose progress output to stderr. When no coroutine is actively draining the `stderr` pipe, the OS pipe buffer fills (typically 64KB on Linux). FFmpeg blocks on the next `write()` to stderr, the process freezes, frames stop flowing to the v4l2loopback device, and the CaptureRegistry reader thread on the consumer side times out after `_STALE_FRAME_TIMEOUT = 3.0` seconds, flags `_reader_error`, and kills the streaming session.

**Why it happens:**
Python's asyncio subprocess documentation explicitly warns: "Use `communicate()` rather than `process.stdin.write()`, `await process.stdout.read()` or `await process.stderr.read()` to avoid deadlocks due to streams pausing reading or writing and blocking the child process." FFmpeg writes MB/s of progress stats at the default `-stats` loglevel. Even with `-loglevel warning`, connection events, codec initializations, and reconnection messages generate hundreds of bytes per second. A 64KB buffer fills in seconds under that load.

**Consequences:**
- FFmpeg process freezes mid-stream; virtual V4L2 device stops receiving frames
- `_check_health()` in `CaptureBackend` raises `RuntimeError("No new frame for X.Xs")` after 3 seconds
- `StreamingService` receives an error and transitions to `error` state, stopping all Hue streaming
- The FFmpeg process itself is not dead — it is alive but blocked on pipe write, so health checks based on `process.returncode` incorrectly report it as running

**Prevention:**
- Launch FFmpeg with `stderr=asyncio.subprocess.DEVNULL` unless actively collecting logs for debug. For production, suppress stderr entirely with `-loglevel quiet -nostats` FFmpeg flags plus `stderr=DEVNULL`
- If stderr must be captured (for health monitoring), always start a dedicated drain coroutine: `asyncio.ensure_future(_drain_stderr(proc.stderr))` immediately after process creation. This coroutine reads and discards (or logs) stderr lines in a loop
- Never call `await proc.wait()` without also draining both stdout and stderr pipes — use `await proc.communicate()` for one-shot calls, or concurrent drain tasks for streaming processes
- For the FFmpeg-to-v4l2loopback pipeline specifically, stdout is not needed (output goes to `/dev/videoN` via `-f v4l2`). Use `stdout=asyncio.subprocess.DEVNULL` as well to eliminate any stdout pipe risk

**Detection:**
- `proc.returncode` is `None` (process alive) but no frames arrive for >3 seconds
- `lsof | grep "proc_N pipe"` shows FFmpeg holding pipe write ends with zero reads
- Adding `-loglevel quiet` to FFmpeg args immediately fixes the frame freezing

**Phase to address:**
FFmpeg pipeline phase — apply the drain-or-devnull rule before any health monitoring logic is built.

---

### Pitfall 4: Miracast WiFi Direct P2P Requires Exclusive NIC Access — Breaks LAN Connectivity

**What goes wrong:**
Enabling a Miracast receiver via WiFi Direct (P2P) mode requires the WiFi interface to enter P2P Group Owner mode. On single-radio hardware (which is the common case for desktop and embedded Linux), this is **mutually exclusive** with the interface's STA (infrastructure/AP client) mode. The moment the WiFi Direct group is created, the existing LAN connection drops. For HuePictureControl, this kills: the Hue Bridge connection (which requires LAN), the web UI access, and any WLED UDP streaming.

This is confirmed by the miraclecast project documentation: "Miracast needs P2P mode on the WiFi card which means it's not allowed to be associated with any other network." The `miracle-wifid` daemon wraps wpa_supplicant and "does not work well in parallel to NetworkManager/wicd/connman running, as you really cannot run wpa_supplicant multiple times on the same interface."

**Why it happens:**
Most consumer WiFi chipsets have one physical radio. STA mode (connected to a router) and P2P Group Owner mode both need the radio's full attention for channel management and association state. While some enterprise-class NICs and Intel Wi-Fi 6 adapters support concurrent STA+P2P via multiple virtual interfaces (MLME), this requires driver-level support that is not guaranteed and is absent on common hardware (Realtek, MediaTek, many Broadcom chips).

**Consequences:**
- Hue Bridge goes unreachable during Miracast session — all lighting stops
- Web UI becomes inaccessible from any client that connects over WiFi
- If the LAN connection is WiFi-only (no Ethernet), the entire backend becomes unreachable
- Existing streaming session transitions to error state when the Hue DTLS connection drops

**Prevention:**
- Before designing the Miracast receiver feature, verify whether the target hardware has a second NIC (Ethernet for LAN, WiFi for Miracast) — if yes, this pitfall does not apply
- If single-radio: do not attempt concurrent Miracast + LAN WiFi. The feature must be documented as requiring either a wired LAN connection or a dedicated second WiFi adapter
- Add a NIC capability check endpoint (`GET /api/wireless/capabilities`) that inspects `iw phy` output for `P2P-device` support **and** confirms a second network interface is available for LAN before allowing Miracast activation
- If the LAN is wired (Ethernet), this pitfall does not apply — WiFi can go fully P2P

**Detection:**
- LAN becomes unreachable immediately after `wpa_cli p2p_group_add` or equivalent
- `iw dev` shows only one physical radio (`phy#0`) with both the STA interface and P2P device trying to share it
- `dmesg` shows `cfg80211: failed to set channel` after P2P group creation

**Phase to address:**
NIC capability and hardware requirements validation phase — must be resolved before any Miracast implementation work begins. This pitfall may scope Miracast to specific hardware configurations.

---

### Pitfall 5: FFmpeg Subprocess Leaves Zombie/Orphan Processes on Crash or FastAPI Shutdown

**What goes wrong:**
The wireless session manager spawns FFmpeg as an `asyncio.subprocess.Process`. If: (a) the FastAPI process receives `SIGKILL` (not `SIGTERM`) during restart, (b) an unhandled exception in the session coroutine bypasses cleanup, or (c) the session is cancelled without awaiting the cleanup coroutine — the FFmpeg child process becomes an orphan. On Linux, orphaned processes are reparented to `init/systemd` and continue running. The still-running FFmpeg process holds the v4l2loopback write end open, which means: (1) `rmmod v4l2loopback` fails, (2) a new FFmpeg process cannot become the producer (the loopback device allows only one active writer), and (3) the virtual camera still appears active in `/dev/videoN` but produces no new frames.

**Why it happens:**
`asyncio.create_subprocess_exec` creates a child process that is **not** killed when the parent Python process exits normally (unlike daemon threads). FastAPI lifespan context managers are only called on clean shutdown (SIGTERM). A kill-9 bypass, an exception during lifespan teardown, or a `CancelledError` that is caught and swallowed all skip the cleanup. The standard subprocess pattern of "terminate, wait, kill if needed" must be explicitly coded — it does not happen automatically.

**Consequences:**
- `rmmod v4l2loopback` blocked indefinitely (Pitfall 1 compounded)
- `/dev/videoN` appears live but produces no frames — health checks confusingly pass
- Next session start fails because FFmpeg cannot open the loopback device as producer (`EBUSY`)
- System accumulates zombie/orphan processes across service restarts

**Prevention:**
- Use `asyncio.shield` or explicit cleanup tasks, but the most reliable pattern: wrap each FFmpeg process in a context manager class that implements `__aenter__`/`__aexit__` with `try/finally: await self._kill_proc()`
- The kill sequence must be: `proc.terminate()` (SIGTERM) → wait up to 5s with `asyncio.wait_for(proc.wait(), timeout=5)` → `proc.kill()` (SIGKILL) if still alive → `await proc.wait()` to reap
- Register the cleanup as a FastAPI lifespan shutdown step (alongside `registry.shutdown()`) — not just in the session's happy path
- For SIGKILL resilience: install a `SIGTERM` handler in the FastAPI process that calls the lifespan shutdown explicitly before Python exits. `uvicorn` with `--timeout-graceful-shutdown` gives this time to complete
- Use `atexit.register()` as a last-resort fallback that calls `proc.kill()` for any tracked FFmpeg processes

**Detection:**
- `ps aux | grep ffmpeg` shows FFmpeg processes after service restart
- `/proc/<pid>/status` shows `PPid: 1` (reparented to init) for orphaned FFmpeg
- `lsof /dev/video10` shows a dead/orphaned process holding the fd after restart

**Phase to address:**
FFmpeg lifecycle phase — the cleanup context manager must be implemented before health monitoring, so there is never a code path that spawns FFmpeg without guaranteed teardown.

---

### Pitfall 6: CaptureRegistry Acquires a v4l2loopback Device Before FFmpeg Has Written Any Frames — Reader Thread Dies Immediately

**What goes wrong:**
The wireless session manager creates the v4l2loopback device, starts the FFmpeg process, and immediately calls `registry.acquire("/dev/video10")` to make the virtual camera available to the streaming service. However, FFmpeg takes 500ms–2000ms to negotiate the Miracast/scrcpy stream, configure the codec, and write the first frame to the loopback device. During this window, the `V4L2Capture` reader thread is running `VIDIOC_DQBUF` on a device with no producer. The ioctl blocks, the reader thread returns with an error or produces zero-byte frames, `_reader_error` is set, and `CaptureRegistry`'s health check surfaces a `RuntimeError`. The streaming service receives the error and stops.

**Why it happens:**
`V4L2Capture._reader_loop()` runs immediately after `open()` (via `_start_reader()`). If the loopback device has no producer writing frames, `VIDIOC_DQBUF` will block or return `EAGAIN` depending on the device's `O_NONBLOCK` flag. The current `open()` uses `os.O_RDWR` (blocking mode), so `DQBUF` blocks until a frame arrives or the fd is closed — but `_stop_event` is never set because no one called `release()`. This is not truly a crash, but it means the first `wait_for_new_frame()` call from the streaming service hangs until FFmpeg actually delivers a frame, or times out if FFmpeg is slow.

Additionally, `_check_health()` uses `_STALE_FRAME_TIMEOUT = 3.0` — if FFmpeg takes more than 3 seconds to produce the first frame (common during initial RTSP/H.264 negotiation), the health check fires `RuntimeError("No new frame for X.Xs")`.

**Prevention:**
- Do not acquire the loopback device from `CaptureRegistry` until FFmpeg has confirmed it is writing frames. The confirmation can be: detect `/proc/$(ffmpeg_pid)/fd/` contains the v4l2loopback fd, or (simpler) open the device with `O_RDWR | O_NONBLOCK` and attempt a single `VIDIOC_DQBUF` in a polling loop with 200ms sleep until a frame arrives, before calling `registry.acquire()`
- Alternatively, increase `_STALE_FRAME_TIMEOUT` for virtual camera devices (those with `driver == "v4l2loopback"` per `VIDIOC_QUERYCAP`) to a longer value (e.g., 10.0 seconds) to accommodate codec negotiation time
- Expose a "producer ready" event from the session manager: `WirelessSession.producer_ready: asyncio.Event` that is set when FFmpeg writes its first frame. Only call `registry.acquire()` after this event is set
- The session startup sequence must be: modprobe → start FFmpeg → wait for producer ready → registry.acquire() → notify streaming service

**Detection:**
- `_reader_error` fires within 3 seconds of acquiring a fresh loopback device
- FFmpeg logs show it is still negotiating the stream when the capture health check fails
- Replacing `registry.acquire()` with a 5-second sleep before acquisition "fixes" the problem (confirming timing is the cause)

**Phase to address:**
FFmpeg-to-v4l2loopback integration phase — the "producer ready" sequencing must be designed before any session start/stop API is built.

---

## Moderate Pitfalls

### Pitfall 7: scrcpy ADB Wireless Connection Drops on Android Screen Lock

**What goes wrong:**
scrcpy runs as a child process wrapping `adb` over WiFi. On Android 12+ and some Android 14 devices, locking or unlocking the screen causes the ADB TCP connection to drop (confirmed in scrcpy issue #6607). scrcpy immediately exits when ADB disconnects, making no attempt to reconnect. The FFmpeg process reading from scrcpy's stdout receives EOF, exits, and the v4l2loopback device loses its producer — triggering `_STALE_FRAME_TIMEOUT` and killing the streaming session.

**Prevention:**
- Monitor the scrcpy child process exit code. Exit code from ADB disconnect is predictable — restart scrcpy automatically with the same arguments when exit is caused by ADB disconnect rather than user cancellation
- Implement a supervised restart loop: `while session_active: run scrcpy; if exited unexpectedly: wait 2s; restart`. Limit retries to avoid busy-looping on permanently disconnected devices
- Instruct users to disable screen lock on the Android device while using scrcpy mirroring, or configure Android's "Stay awake while charging" option in developer options
- Use `adb shell settings put global stay_on_while_plugged_in 3` via ADB before starting scrcpy to prevent screen lock programmatically

**Phase to address:**
scrcpy session management phase — the supervised restart loop must be part of the initial implementation, not a later hardening step.

---

### Pitfall 8: wpa_supplicant P2P Not Compiled or Driver Lacks P2P Support

**What goes wrong:**
The miraclecast/gnome-network-displays WiFi Direct receiver requires wpa_supplicant compiled with `CONFIG_P2P=y`. Many Linux distributions ship wpa_supplicant without P2P support (or with it disabled). The error `wpa_supplicant or driver does not support P2P` is the most commonly reported issue in the miraclecast issue tracker, with issues #92, #147, #285, and #452 all being variants of this failure. Unlike a software configuration error, this is a build/hardware constraint that cannot be fixed without recompiling or replacing wpa_supplicant.

Additionally, even with P2P-capable wpa_supplicant, the driver must expose a `P2P-device` interface in `iw dev` output. Drivers that do not support P2P at the kernel level (Realtek RTL8xxx with in-tree drivers, older Broadcom, most USB WiFi adapters) fail at this check.

**Prevention:**
- Add a preflight capability check before any Miracast receiver activation: run `iw phy phy0 info | grep -A5 "Supported interface modes"` and confirm `P2P-device` is listed; run `wpa_cli -i wlan0 p2p_find` and check for errors
- Expose `GET /api/wireless/capabilities` that returns `{"miracast_capable": bool, "reason": string}` so the UI can show "Miracast not available on this hardware" rather than failing silently mid-setup
- Document which WiFi hardware is known-working: Intel AX200/AX210 (iwlwifi), Intel 8265 (iwlwifi) are reliably P2P-capable on Linux. Realtek and most USB adapters are not

**Phase to address:**
NIC capability detection phase — implement the capability check API before building any Miracast receiver UI, so the UI gating is in place from the start.

---

### Pitfall 9: v4l2loopback `exclusive_caps` Required for WebRTC/Browser but Breaks Some V4L2 Readers

**What goes wrong:**
Without `exclusive_caps=1`, a v4l2loopback device advertises both `V4L2_CAP_VIDEO_CAPTURE` and `V4L2_CAP_VIDEO_OUTPUT` simultaneously. This confuses some applications (notably Chromium/WebRTC) into not listing the device as a camera input, but it works fine with V4L2 tools and FFmpeg consumers. With `exclusive_caps=1`, the device shows only `VIDEO_CAPTURE` to readers and only `VIDEO_OUTPUT` to writers — which Chromium requires, but which can break older V4L2 tools that probe for the combined capability.

The existing `enumerate_capture_devices()` in `capture_v4l2.py` checks `device_caps & 0x01` (VIDEO_CAPTURE bit). Without `exclusive_caps`, the loopback device has `caps = 0x05200002` (a known bug in Ubuntu 24.04 per v4l2loopback issue #619 which shows the device not getting the capture flag properly). With `exclusive_caps=1`, `caps = 0x04200001` and the VIDEO_CAPTURE bit is set correctly.

**Prevention:**
- Always load v4l2loopback with `exclusive_caps=1`. This is the correct setting for all consumer use cases and aligns with what `enumerate_capture_devices()` checks
- Do not rely on `device_caps & 0x1` alone to confirm a loopback device is working — also read the `driver` field from `VIDIOC_QUERYCAP` and confirm it equals `"v4l2loopback"` to distinguish from physical devices

**Phase to address:**
Virtual device creation phase — set this in the `modprobe` command template and do not make it configurable.

---

### Pitfall 10: scrcpy ADB Over WiFi Requires Legacy USB Pairing or Android 11+ Wireless Debug Port

**What goes wrong:**
The common mental model is: install ADB, connect Android device, run scrcpy over WiFi. In reality, there are two distinct workflows with different fragility profiles:

1. **Legacy (Android ≤ 10):** Requires initial USB connection to run `adb tcpip 5555`. The TCP port resets on device reboot — the user must replug USB on every reboot to re-enable it.

2. **Android 11+ Wireless Debugging:** Does not require USB, but uses a **randomly assigned pairing port** that changes every time "Wireless debugging" is toggled or the device reboots. The static 5555 port is only for `adb connect` after the one-time `adb pair <ip>:<random_port>` pairing step. If the user toggles wireless debugging off and on, a new random port is assigned and pairing must be repeated.

Storing `<ip>:5555` in the database and attempting `adb connect <ip>:5555` at session start silently fails if the device was rebooted or wireless debugging was re-enabled.

**Prevention:**
- The scrcpy session manager must verify `adb devices` shows the target device as `device` (not `offline` or `unauthorized`) before starting scrcpy. If not connected, surface a clear error: "Device not connected — open Wireless debugging on Android and run adb connect"
- Do not attempt to automate `adb pair` — the random pairing port requires user action to obtain. Provide UI instructions for one-time pairing setup
- For Android 11+ devices, store both IP and port, but treat the connection as requiring re-verification on every session start rather than assuming persistence

**Phase to address:**
scrcpy session management phase — connection verification must precede process launch.

---

## Minor Pitfalls

### Pitfall 11: FFmpeg Pixel Format Mismatch Causes `VIDIOC_S_FMT` Error

**What goes wrong:**
FFmpeg writes to v4l2loopback using a pixel format that doesn't match what the reader (V4L2Capture) negotiates. The existing `V4L2Capture._setup_device()` requests MJPEG (`V4L2_PIX_FMT_MJPEG`). v4l2loopback's format is negotiated by the first writer (FFmpeg). If FFmpeg outputs raw YUV (`yuv420p`) and V4L2Capture requests MJPEG, the `VIDIOC_S_FMT` ioctl returns an error (or silently accepts a mismatched format), and `cv2.imdecode` receives non-JPEG bytes, returning `None` on every frame.

**Prevention:**
- Either: always force FFmpeg to output MJPEG to the loopback device (`-vf format=yuvj420p -vcodec mjpeg -f v4l2 /dev/video10`), consistent with what `V4L2Capture` requests; or modify `V4L2Capture` to detect the actual format of loopback devices and decode accordingly
- The simplest fix: use `yuv420p` throughout and modify `V4L2Capture` to handle raw pixel formats (not just MJPEG) for devices whose driver is `v4l2loopback`

**Phase to address:**
FFmpeg pipeline configuration phase.

---

### Pitfall 12: v4l2loopback `card_label` Not Set — Device Indistinguishable from Physical Cameras

**What goes wrong:**
v4l2loopback creates a device with a generic label like `"Dummy video device (0x0000)"` by default. `enumerate_capture_devices()` lists it alongside physical cameras with no way to distinguish them in the UI or the database. Users see confusing entries like "Dummy video device" in the camera selector.

**Prevention:**
- Always set a descriptive `card_label` at modprobe time: `modprobe v4l2loopback video_nr=10 card_label="HPC-Miracast" exclusive_caps=1`
- Use the `card` field from `VIDIOC_QUERYCAP` (which reflects `card_label`) as a display name override in the camera list API
- The `driver` field from `VIDIOC_QUERYCAP` will be `"v4l2loopback"` — use this in `enumerate_capture_devices()` to tag virtual devices with `is_virtual=True` so the frontend can display them distinctly (e.g., with a wireless icon)

**Phase to address:**
Virtual device creation and camera enumeration integration phase.

---

### Pitfall 13: DKMS Module Missing After Kernel Update — v4l2loopback Fails to Load Silently

**What goes wrong:**
v4l2loopback is typically installed via DKMS (`v4l2loopback-dkms`), which rebuilds the module on each kernel update. If the DKMS build fails (missing kernel headers, build tools not installed, or ABI mismatch), `modprobe v4l2loopback` fails silently or with a cryptic error. The wireless session manager calls `modprobe`, gets a non-zero exit code, and the virtual device is never created — but if error handling is incomplete, this may not be surfaced to the user.

**Prevention:**
- After kernel update / at startup, verify v4l2loopback is loadable: `modinfo v4l2loopback` should return cleanly. If it fails, surface a clear error in `GET /api/wireless/capabilities`
- Install `linux-headers-$(uname -r)` as a prerequisite documented in the setup guide
- Add a startup health check that attempts a test `modprobe` and `rmmod` to confirm module availability before any wireless session endpoints are exposed

**Phase to address:**
System requirements and health-check phase.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| v4l2loopback module management API | rmmod blocked by open fd (Pitfall 1) | Always teardown CaptureRegistry before rmmod; use v4l2loopback-ctl for dynamic changes |
| Virtual device path assignment | video_nr collision with physical device (Pitfall 2) | Verify card_label after modprobe; resolve by label not by path |
| FFmpeg subprocess management | Pipe deadlock (Pitfall 3), orphan processes (Pitfall 5) | stderr=DEVNULL + drain task; cleanup context manager with try/finally |
| Session start sequencing | Premature registry.acquire() before FFmpeg ready (Pitfall 6) | producer_ready event; do not acquire until first frame confirmed |
| Miracast NIC requirements | WiFi kills LAN connection (Pitfall 4), no P2P driver support (Pitfall 8) | NIC capability check before any Miracast code; document hardware requirements |
| scrcpy session management | Screen lock drops ADB (Pitfall 7), connection not persistent (Pitfall 10) | Supervised restart loop; verify adb devices before each session start |
| Camera enumeration with virtual devices | exclusive_caps confusion (Pitfall 9), indistinguishable labels (Pitfall 12) | exclusive_caps=1 always; card_label set at modprobe time; tag driver=="v4l2loopback" |
| Post-kernel-update system state | DKMS rebuild failure (Pitfall 13) | modinfo check in health endpoint; document linux-headers dependency |

---

## Integration Gotchas with CaptureRegistry

| Scenario | Common Mistake | Correct Approach |
|----------|---------------|------------------|
| Module teardown while streaming | Call rmmod while StreamingService holds a registry reference | streaming.stop() → registry.release() → wait for fd close → rmmod |
| Session start sequencing | registry.acquire(loopback_path) immediately after FFmpeg start | Wait for producer_ready event (first frame written) before acquire() |
| Loopback path changes across restart | Store `/dev/video10` in camera_assignments table | Store `card_label="HPC-Miracast"` as stable_id; resolve to current path at runtime via enumerate_capture_devices() |
| Health check false positives | _STALE_FRAME_TIMEOUT fires during FFmpeg codec negotiation | Use longer timeout for v4l2loopback devices; or hold acquire() until producer ready |
| Format negotiation | V4L2Capture requests MJPEG from a loopback that was written as YUV | Force consistent format in FFmpeg output; detect driver="v4l2loopback" and adapt decode path |

---

## Sources

- [v4l2loopback README — module parameters, rmmod limitations, keep_format, exclusive_caps](https://github.com/v4l2loopback/v4l2loopback/blob/master/README.md) — HIGH confidence
- [v4l2loopback issue #619 — Ubuntu 24.04 exclusive_caps bug](https://github.com/v4l2loopback/v4l2loopback/issues/619) — HIGH confidence
- [Python asyncio subprocess docs — pipe deadlock warning, communicate() recommendation](https://docs.python.org/3/library/asyncio-subprocess.html) — HIGH confidence
- [miraclecast issue #285 — wpa_supplicant P2P not supported](https://github.com/albfan/miraclecast/issues/285) — HIGH confidence
- [miraclecast issue #415 — NetworkManager conflict with wpa_supplicant P2P](https://github.com/albfan/miraclecast/issues/415) — HIGH confidence
- [gnome-network-displays — WiFi Direct P2P Linux implementation](https://github.com/benzea/gnome-network-displays) — HIGH confidence
- [scrcpy issue #6607 — ADB disconnects on screen lock](https://github.com/Genymobile/scrcpy/issues/6607) — HIGH confidence
- [scrcpy connection docs — tcpip vs Android 11 wireless debugging](https://github.com/Genymobile/scrcpy/blob/master/doc/connection.md) — HIGH confidence
- [v4l2loopback ArchWiki — modprobe parameters, exclusive_caps, troubleshooting](https://wiki.archlinux.org/title/V4l2loopback) — HIGH confidence
- [Miracast performance overview — P2P/STA mutual exclusion on single-radio hardware](https://documentation.mersive.com/en/miracast-performance-overview.html) — MEDIUM confidence
- [FFmpeg wiki — v4l2loopback usage, yuv420p format recommendation](https://github.com/umlaeute/v4l2loopback/wiki/FFmpeg) — HIGH confidence
- [v4l2loopback issue #283 — switching producers crashes FFmpeg consumer](https://github.com/v4l2loopback/v4l2loopback/issues/283) — MEDIUM confidence
- [XDA Forums — Android 12 random ADB wireless debugging ports](https://xdaforums.com/t/adb-scrcpy-vysor-what-ports-does-android-12-randomly-set-when-wi-fi-connecting-via-wireless-debugging-adb-pair-or-connect-commands.4475621/) — MEDIUM confidence
