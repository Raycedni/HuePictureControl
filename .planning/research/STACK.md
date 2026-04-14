# Technology Stack — v1.2 Wireless Input

**Project:** HuePictureControl
**Milestone:** v1.2 — Wireless Screen Mirroring Input
**Researched:** 2026-04-14
**Overall confidence:** MEDIUM (Miracast tooling has known instability; other components HIGH)

---

## Context: What Is NOT Being Re-Researched

The following are validated and shipped. Listed here so new additions can be evaluated against them.

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend framework | FastAPI | >=0.115 |
| Async DB | aiosqlite | >=0.20 |
| HTTP client | httpx | >=0.27 |
| Frame capture | Custom V4L2 ctypes/ioctl + mmap | `capture_v4l2.py` |
| Frame decode | opencv-python-headless | >=4.10 |
| Hue streaming | hue-entertainment-pykit | 0.9.4 |
| Python | 3.12 (pinned) | 3.12 |
| Frontend | React 19 + TypeScript + Konva.js + Zustand | — |
| Device pool | CaptureRegistry ref-counted | `capture_service.py` |

---

## New Stack Additions

### Backend — Process / Subprocess Management

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `asyncio.create_subprocess_exec` | stdlib (3.12) | Launch and supervise FFmpeg and scrcpy processes | No library needed. `asyncio` 3.12 stdlib provides `create_subprocess_exec`, async stdout/stderr streaming via `StreamReader`, and `Process.wait()` / `Process.terminate()`. The codebase already uses `asyncio.to_thread` for blocking calls in `capture_v4l2.py`. Using stdlib keeps the dependency surface flat and consistent with existing codebase patterns. |
| `asyncio.create_subprocess_exec` | stdlib (3.12) | Launch `v4l2loopback-ctl add/delete` with `sudo` | Same subprocess primitive — one-shot calls, not long-running. Capture stdout to read back the assigned `/dev/videoN` path after device creation. |

Do NOT add python-ffmpeg, asyncffmpeg, or ffmpy3. They wrap `asyncio.subprocess` with extra
abstraction that adds nothing for this use case: you only need to start a process, stream its
stderr for health detection, and kill it cleanly. That is 30 lines of stdlib Python.

### Backend — v4l2loopback Virtual Device Management

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `v4l2loopback-ctl` (system binary) | >=0.12 | Create/destroy virtual `/dev/videoN` devices at runtime | `v4l2loopback-ctl add -n "label" /dev/videoN` creates a named device at a deterministic path. `v4l2loopback-ctl delete /dev/videoN` removes it. Invoked via `asyncio.create_subprocess_exec` with `sudo`. Requires a sudoers NOPASSWD rule for these two specific commands (see System Prerequisites). |
| `v4l2loopback` kernel module (system package) | >=0.12 | Kernel-level virtual V4L2 devices — the actual driver | Must be pre-installed on the host (`apt install v4l2loopback-dkms`). The module must be loaded (`modprobe v4l2loopback`) before any device is created. The FastAPI service does NOT load the module at runtime — that is a host prerequisite. Loading at startup is acceptable if not already loaded. |

Device creation at runtime uses explicit device number assignments for determinism:
```
v4l2loopback-ctl add -n "hpc-miracast" /dev/video10
v4l2loopback-ctl add -n "hpc-scrcpy"   /dev/video11
```

Use `exclusive_caps=1` when creating if the device will be opened by any WebRTC consumer.

### Backend — Miracast (WiFi Direct) Receiver

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `miraclecast` / `miracle-sinkctl` (system binary) | git HEAD / albfan fork | Act as a Miracast sink — appear as a Cast target in Windows Win+K | The only functional open-source Miracast sink for Linux. `gnome-network-displays` is source/sender only — no sink mode exists or is roadmapped (confirmed from README and issue tracker). `miraclecast` provides `miracle-sinkctl` which manages the WFD RTSP session. GStreamer is used internally to decode the H.264 stream from the Windows source. |
| `wpa_supplicant` (system service) | >=2.9 | WiFi P2P / WiFi Direct group owner negotiation | `miraclecast` spawns its own `wpa_supplicant` instance on the P2P-capable NIC. Requires the NIC to be temporarily unmanaged by NetworkManager for the duration of the session. This is the primary integration complexity (see PITFALLS.md). |
| GStreamer (system packages) | >=1.20 | `miraclecast` runtime dependency for H.264 decode | Needed by `miracle-sinkctl` internally. HuePictureControl does NOT call GStreamer directly. Required: `gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav` |

Miracast control flow from Python's perspective:
1. Call `iw list` via subprocess to confirm NIC P2P capability before exposing the feature
2. Temporarily mark NIC as unmanaged by NetworkManager (via `nmcli device set <iface> managed no`)
3. Launch `miracle-sinkctl` via `asyncio.create_subprocess_exec`; parse stdout for session start events
4. `miracle-sinkctl` exposes the incoming H.264 stream at an RTSP endpoint (port parsed from stdout)
5. Launch FFmpeg subprocess: `ffmpeg -rtsp_transport tcp -i rtsp://127.0.0.1:<PORT>/... -pix_fmt yuv420p -f v4l2 /dev/videoN`
6. `/dev/videoN` then appears in `CaptureRegistry` — existing capture pipeline requires zero changes

CONFIDENCE: MEDIUM. `miraclecast` has documented issues with modern `wpa_supplicant` and
NetworkManager. Hardware P2P support varies across NIC models. The RTSP output port is not
officially documented and must be parsed from stdout. Requires hardware integration testing
on the actual NIC before committing to this path.

### Backend — scrcpy (Android WiFi Mirroring)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `scrcpy` (system binary) | 3.3.4 (latest as of Dec 2024) | Mirror Android screen over WiFi (ADB TCP/IP) directly to a v4l2loopback virtual device | scrcpy v3+ has native `--v4l2-sink=/dev/videoN` output — it writes decoded frames directly to the loopback device without FFmpeg as an intermediary. Officially documented, community-verified. Install via `apt install scrcpy` or download the static Linux binary from GitHub releases. |
| `adb` (system binary) | any recent | ADB device enumeration and TCP/IP connection management | scrcpy uses ADB as its transport layer. HuePictureControl backend calls `adb devices -l` and `adb connect <IP>:<PORT>` via subprocess to manage connections. ADB TCP/IP pairing requires one initial USB connection or the Android 11+ wireless debugging PIN flow. |

scrcpy command for headless v4l2 output (no display window):
```bash
scrcpy --tcpip=<ANDROID_IP> --v4l2-sink=/dev/videoN --no-display --video-codec=h264
```

The `--no-display` flag is mandatory for headless server use. scrcpy manages its own H.264
decode pipeline — no separate FFmpeg subprocess is needed for this path.

CONFIDENCE: HIGH. scrcpy v3 `--v4l2-sink` is well-documented and community-verified. v3.3.4
released December 2024.

### Backend — NIC Capability Detection

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `iw` (system binary) | any (nl80211) | Detect whether the host NIC supports WiFi Direct (P2P-GO, P2P-client modes) | `iw list` output contains a `Supported interface modes:` section listing `P2P-GO` and `P2P-client` if the driver supports WiFi Direct. `iwconfig` is deprecated (Wireless Extensions interface) — `iw` uses nl80211, the current kernel wireless API. Called once per API request, not continuously. |

Detection implementation (stdlib only, ~10 lines):
```python
proc = await asyncio.create_subprocess_exec(
    "iw", "list",
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.DEVNULL,
)
stdout, _ = await proc.communicate()
text = stdout.decode()
p2p_supported = "P2P-GO" in text and "P2P-client" in text
```

Do NOT use `iw-parse` (PyPI). It wraps `iwlist` (deprecated tool, not `iw list`), adds a
PyPI dependency, and the two-line detection above is the complete implementation.

### Backend — FFmpeg Pipeline (Miracast bridge only)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `ffmpeg` (system binary) | >=4.4 | Transcode RTSP stream from `miracle-sinkctl` to raw YUV420P frames written to v4l2loopback | `miracle-sinkctl` outputs H.264 over RTSP. v4l2loopback requires raw uncompressed frames (YUV420P is universally accepted). FFmpeg bridges these. scrcpy does NOT need FFmpeg — it writes decoded frames natively to the loopback device. |

FFmpeg command for Miracast bridge:
```bash
ffmpeg -rtsp_transport tcp \
  -i rtsp://127.0.0.1:<PORT>/miraclecast \
  -vf scale=1920:1080 \
  -pix_fmt yuv420p \
  -f v4l2 /dev/videoN
```

Process lifecycle: launched after `miracle-sinkctl` signals session start; killed when the
Miracast session ends or when the user stops the source. Managed entirely by
`asyncio.create_subprocess_exec`. Health detection: monitor stderr for `Broken pipe` or
non-zero exit code, then trigger session cleanup.

---

## No New Python Dependencies Required

All wireless input orchestration uses only:
- `asyncio.create_subprocess_exec` — process launch and supervision (stdlib)
- stdout/stderr `StreamReader` — health monitoring and path read-back (stdlib)

No new entries in `Backend/requirements.txt` are needed for v1.2.

### Frontend — No New npm Packages Required

The wireless source selection UI reuses the existing camera selector dropdown pattern
(already built in v1.1 with Konva + Zustand). No new npm packages needed. New UI surfaces:
- Wireless source panel with start/stop controls (shadcn/ui Button, already present)
- Status badges for session state (shadcn/ui Badge, already present)
- NIC capability indicator (text only — no new component)

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Miracast sink | `miraclecast` (`miracle-sinkctl`) | `gnome-network-displays` | gnome-network-displays is a **source/sender only** — no sink mode exists or is planned. Confirmed from README and issue tracker. Disqualified. |
| Miracast sink | `miraclecast` | Custom WFD/RTSP sink from scratch | WFD RTSP session negotiation (M1-M7 messages, capability exchange, HDCP optional, UIBC) is ~3000 lines of C-level protocol work. Not justified when `miraclecast` exists. |
| Android mirror | `scrcpy` binary | `pyscrcpy` / `scrcpy-client` PyPI | PyPI wrappers are community ports at version 0.0.4 — stale and unsupported. Official scrcpy binary has `--v4l2-sink` natively in v3. Use the binary. |
| FFmpeg process management | `asyncio.create_subprocess_exec` stdlib | `python-ffmpeg` v2.0.12 | python-ffmpeg adds a fluent API and progress events that are irrelevant here. You only need: start process, watch stderr, kill on stop. That is 30 stdlib lines. Zero benefit; adds a new PyPI dependency. |
| NIC capability | `iw list` + regex | `iw-parse` PyPI | `iw-parse` wraps `iwlist` (deprecated), not `iw list`. Wrong tool. The two-line regex is the full implementation. |
| v4l2 device creation | `v4l2loopback-ctl` subprocess | Direct ioctl to `/dev/v4l2loopback` control device | `v4l2loopback-ctl` is the documented, stable interface. Direct ioctl requires matching internal kernel struct definitions against the installed module version — fragile and undocumented. |
| NetworkManager conflict | `nmcli device set <iface> managed no` | Stop NetworkManager entirely | Stopping NM disrupts all other network connections on the host. `nmcli device set unmanaged` releases only the specified interface, leaving everything else intact. |

---

## System Prerequisites (Host Setup)

These must be present on the Linux host before v1.2 features function. This is a deployment
concern, not a code concern, but must be documented for setup automation or a setup check
endpoint.

```bash
# Kernel module for virtual cameras
apt install v4l2loopback-dkms v4l2loopback-utils
modprobe v4l2loopback

# Miracast sink (no stable distro package on most distros)
# git clone https://github.com/albfan/miraclecast && cd miraclecast
# mkdir build && cd build && cmake .. && make && sudo make install
# Runtime deps:
apt install gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav

# Android mirroring
apt install scrcpy android-tools-adb

# FFmpeg (likely already present)
apt install ffmpeg

# WiFi info (likely already present on any Linux desktop)
apt install iw
```

Privilege escalation for v4l2loopback-ctl (narrow NOPASSWD rules):
```
# /etc/sudoers.d/hpc-v4l2
<username> ALL=(ALL) NOPASSWD: /usr/bin/v4l2loopback-ctl add *
<username> ALL=(ALL) NOPASSWD: /usr/bin/v4l2loopback-ctl delete *
```

---

## Integration With Existing Capture Pipeline

`CaptureRegistry` in `capture_service.py` is transparent to the video source. It takes a
`/dev/videoN` path and opens it with the V4L2 backend. A v4l2loopback device at
`/dev/video10` is indistinguishable from a physical capture card at `/dev/video0` from
`CaptureRegistry`'s perspective — both are V4L2 character devices.

Integration points:
1. New `WirelessInputService` class manages wireless session lifecycle (start/stop subprocesses, create/destroy v4l2loopback device)
2. After the wireless session is active, `WirelessInputService` registers the virtual device path via `registry.acquire()` — the same call pattern `StreamingService` uses
3. The virtual device appears in the existing `GET /api/cameras` enumeration automatically (it is a real V4L2 node visible to `linuxpy` enumeration)
4. On session stop, `WirelessInputService` calls `registry.release()` then deletes the v4l2loopback device
5. No changes required to `capture_v4l2.py`, `CaptureRegistry`, or `StreamingService`

New files:
- `routers/wireless.py` — start/stop wireless sessions, NIC capability check, session list
- `services/wireless_service.py` — subprocess lifecycle, v4l2loopback device creation, health monitoring

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| scrcpy v4l2-sink | HIGH | Official docs, v3.3.4 release confirmed Dec 2024, community verified |
| v4l2loopback-ctl API | HIGH | Official README and DeepWiki documentation verified |
| FFmpeg `-f v4l2` output | HIGH | Well-documented, widely used pattern |
| asyncio subprocess management | HIGH | Python 3.12 stdlib documentation |
| iw P2P detection | HIGH | Linux kernel wireless docs, nl80211 |
| miraclecast sink architecture | MEDIUM | Project active; GStreamer/RTSP output confirmed; RTSP port undocumented |
| miraclecast hardware compat | LOW | Heavily NIC-driver dependent; P2P support varies; requires testing on actual hardware |
| miraclecast + NM coexistence | LOW | Known wpa_supplicant/NM conflict; `nmcli unmanaged` is the mitigation but behavior is driver-specific |

---

## Sources

- [scrcpy v4l2 docs](https://github.com/Genymobile/scrcpy/blob/master/doc/v4l2.md) — `--v4l2-sink`, `--no-display` options, HIGH confidence
- [scrcpy v3.3.4 releases](https://github.com/Genymobile/scrcpy/releases) — Latest version Dec 2024, HIGH confidence
- [v4l2loopback README](https://github.com/v4l2loopback/v4l2loopback/blob/main/README.md) — `v4l2loopback-ctl add/delete`, modprobe params, HIGH confidence
- [v4l2loopback-ctl DeepWiki](https://deepwiki.com/v4l2loopback/v4l2loopback/4.1-v4l2loopback-ctl-utility) — Control device, privilege requirements, HIGH confidence
- [miraclecast README](https://github.com/albfan/miraclecast/blob/master/README.md) — Build deps (systemd, glib, gstreamer, wpa_supplicant), MEDIUM confidence
- [miraclecast DeepWiki](https://deepwiki.com/albfan/miraclecast) — RTSP + GStreamer output path, MEDIUM confidence
- [gnome-network-displays README](https://github.com/GNOME/gnome-network-displays/blob/master/README.md) — Source/sender only; no sink mode (disqualifier), HIGH confidence
- [iw wireless.kernel.org](https://wireless.wiki.kernel.org/en/users/documentation/iw) — nl80211 P2P detection via `iw list`, HIGH confidence
- [Python asyncio subprocesses 3.12](https://docs.python.org/3.12/library/asyncio-subprocess.html) — `create_subprocess_exec`, StreamReader stdout, HIGH confidence
- [python-ffmpeg PyPI](https://pypi.org/project/python-ffmpeg/) — v2.0.12, Apr 2024 (not recommended; listed as alternative considered), MEDIUM confidence
