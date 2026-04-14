# Feature Landscape: Wireless Input (v1.2)

**Domain:** Wireless screen mirroring as virtual camera input for ambient lighting
**Researched:** 2026-04-14
**Confidence:** HIGH (scrcpy --v4l2-sink from official docs), MEDIUM (Miracast receiver on Linux from community), HIGH (v4l2loopback/FFmpeg from Arch Wiki + official repo), MEDIUM (FFmpeg watchdog patterns from real-world implementations)

## Context: What This Milestone Adds

HuePictureControl v1.1 has a working multi-camera pipeline: physical UVC devices, `CaptureRegistry` ref-counted pool, per-zone camera selector, live preview WebSocket. v1.2 makes wireless sources (Miracast from Windows, scrcpy from Android) appear in the existing camera selector as if they were physical UVC devices. The mechanism is: wireless receiver → FFmpeg → v4l2loopback device node → existing V4L2 capture path. No changes to the capture pipeline itself; only a new layer above it that creates and feeds virtual devices.

---

## Table Stakes

Features users expect. Missing = the wireless input feels broken or alien compared to the physical capture card experience.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Wireless source appears in camera dropdown automatically | Users expect zero extra steps after connecting — the same dropdown they use for physical devices should show it | LOW | v4l2loopback device node creation must happen before or at service startup; `linuxpy` device enumeration already finds `/dev/videoN` nodes |
| Miracast: discoverable via Win+K without any app on the Windows side | Standard Windows 11 UX — Win+K is the only flow users know | HIGH | Requires Linux Miracast receiver (miraclecast or compatible) listening as WiFi Direct sink; this is the hard part |
| scrcpy: connect by typing Android device IP | Users expect "type an IP, click Connect" — ADB pairing is a one-time step they accept | MEDIUM | First-time Android 11+ requires QR/code pairing; Android <=10 requires USB-first `adb tcpip 5555`; subsequent connections are IP-only |
| Connected wireless source streams immediately | After pairing/connection, color processing starts without a separate UI action | MEDIUM | FFmpeg must start piping to v4l2loopback as soon as the receiver accepts the connection |
| Disconnecting a wireless source stops its stream gracefully | Abrupt WiFi drop or the user closing the cast session must clean up the virtual device and stop FFmpeg | MEDIUM | Process watchdog detects exit; v4l2loopback device can remain registered but will produce no frames |
| Status visible in UI (connected / disconnected / idle) | Users need to know whether their wireless source is active before starting color sync | LOW | WebSocket or poll endpoint with per-source state machine: `idle → connecting → streaming → disconnected` |
| Resolution and framerate controls | Users coming from 4K capture cards expect to tune the wireless input down for latency | LOW | scrcpy: `--max-size=1920` and `--max-fps=30/60`; Miracast: negotiated but can be capped via FFmpeg decode side |
| NIC capability check before attempting Miracast | Users must know whether their WiFi adapter supports WiFi Direct before setup fails silently | LOW | `netsh wlan show drivers` (done from backend via subprocess) surfaces `Wireless Display Supported: Yes` or `No` |
| FFmpeg auto-restart on crash | WiFi drops, device sleeps, encoder hiccups — FFmpeg will die; users expect the stream to recover | MEDIUM | Watchdog task monitors process returncode; exponential backoff restart loop, max attempts configurable |
| Virtual device node stays stable across sessions | Users expect `/dev/video10` to always be the Miracast input, not a random number that changes on restart | LOW | `v4l2loopback-ctl add` with fixed device number; or `modprobe v4l2loopback video_nr=10,11` on module load |

---

## Differentiators

Features that would set this wireless input above comparable solutions (Hyperion wireless grabbers, Scrcpy standalone, etc.)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Wireless and wired sources in the same per-zone selector | No other ambilight tool mixes a capture card zone and a wireless mirror zone in the same session — e.g., left half of screen from HDMI, right half from Android mirror | LOW | Consequence of transparent v4l2loopback design; no special work if virtual device appears in `linuxpy` enumeration |
| scrcpy orientation lock preserved in pipeline | Other solutions output rotated frames when phone switches orientation; ambient lighting breaks on portrait content | LOW | `--lock-video-orientation=0` (landscape lock) is a single scrcpy flag; prevents aspect ratio chaos in region mapping |
| Per-source latency target display | Showing measured capture-to-light latency per wireless source lets users tune settings with feedback | MEDIUM | Extend existing streaming metrics WebSocket with per-device frame-arrival timestamps |
| One-click re-pair for scrcpy sessions | After Android reboots, reconnect without going through pairing again if device already trusted | LOW | Store `device_ip` + `adb_port` in DB; attempt `adb connect IP:PORT`; surface "re-pair needed" only if it fails |
| Miracast over Infrastructure (MS-MICE) support | Most Linux Miracast implementations require WiFi Direct P2P; MS-MICE works over the existing LAN without P2P hardware support | HIGH | MS-MICE requires TCP port 7250 and DNS resolution; supported since Win 10 1703; opens the feature to Ethernet-only NICs — investigate feasibility in phase research |

---

## Anti-Features

Features commonly requested in wireless mirroring setups that should be explicitly excluded.

| Anti-Feature | Why Problematic | What to Do Instead |
|--------------|-----------------|-------------------|
| AirPlay receiver | User explicitly scoped to Windows and Android only; AirPlay on Linux (RPiPlay, UxPlay) is poorly maintained and adds significant system dependencies | Out of scope per PROJECT.md; document this in UI |
| Google Cast / Chromecast receiver | Google Cast is proprietary and requires a licensed receiver SDK; no open-source Linux implementation exists | Not feasible without licensing; scrcpy covers the Android use case |
| Simultaneous multi-device Miracast sources | The WiFi Direct P2P group topology only supports one concurrent session per NIC | Physical limit; document max one Miracast source |
| H.264 stdout pipe from scrcpy | scrcpy >=3.3 removed raw H.264 stdout output; using `--v4l2-sink` directly is the supported path | Use `--v4l2-sink=/dev/videoN` — native support, no pipe needed |
| WARLS/DNRGB streaming protocol for wireless sources | Unrelated — those are WLED protocols, not wireless input protocols | WLED is v1.3 scope |
| Storing Android device credentials / screen content | Logs or screenshots of mirrored screens create privacy risk | Never persist frame data; only persist device IP + ADB port for reconnect |
| Always-on Miracast receiver daemon at system startup | Consumes WiFi resources and wpa_supplicant state even when no cast is happening | Start receiver only on user-initiated "Enable Miracast" toggle; auto-stop on timeout |

---

## Feature Dependencies

```
[v4l2loopback module loaded with fixed device numbers]
    └──enables──> [Virtual device nodes at /dev/video10, /dev/video11, ...]
                       └──required by──> [linuxpy enumeration finds virtual devices]
                                             └──enables──> [Wireless sources in camera dropdown]

[Miracast receiver process (miraclecast / wifid daemon)]
    └──requires──> [WiFi Direct capable NIC (NDIS >= 6.3)]
    └──requires──> [wpa_supplicant P2P mode or systemd-networkd support]
    └──on connect──> [FFmpeg -i rtsp://... -vf format=yuv420p -f v4l2 /dev/video10]
                         └──fills──> [v4l2loopback device node]

[scrcpy --v4l2-sink=/dev/videoN]
    └──requires──> [ADB connection to Android device (USB first-time OR Android 11 wireless pair)]
    └──directly fills──> [v4l2loopback device node — no FFmpeg step needed]
    └──requires lock──> [--lock-video-orientation=0 (landscape)]

[FFmpeg pipeline (Miracast path only)]
    └──watched by──> [Python asyncio watchdog task]
                         └──on death──> [exponential backoff restart]
                         └──reports to──> [status WebSocket]

[NIC capability check]
    └──gates──> [Miracast receiver start]
    └──informs──> [UI: "WiFi Direct not supported" warning]

[Per-source status state machine]
    └──feeds──> [Existing /ws/status WebSocket (extend with wireless_sources field)]
```

### Dependency Notes

- **scrcpy is the simpler path.** It outputs directly to v4l2loopback via `--v4l2-sink`; no separate FFmpeg process required for Android. The watchdog only needs to restart `scrcpy`, not a two-stage pipeline.
- **Miracast needs FFmpeg as a second stage.** miraclecast's `miracle-gst` or `miracle-sinkctl` outputs RTSP or GStreamer pipeline; FFmpeg decodes this and writes raw YUV to v4l2loopback.
- **v4l2loopback module must be loaded with a fixed device number** before enumeration. Otherwise the virtual node gets a random index and disappears from the UI. The API must provision specific numbers at startup.
- **Orientation lock is mandatory for scrcpy + v4l2loopback.** Without `--lock-video-orientation`, rotating the phone produces different frame dimensions mid-stream, which crashes the V4L2 write (v4l2loopback cannot change frame size while a reader is attached). This is confirmed in scrcpy issue #3795.
- **FFmpeg watchdog is a new service.** No equivalent exists in the current codebase. It is a long-running asyncio task launched alongside a streaming session, not a top-level daemon.
- **Virtual devices are transparent to CaptureRegistry.** The existing ref-counted pool calls `linuxpy` for enumeration. If v4l2loopback nodes exist at that path, they appear alongside physical devices with no code changes needed in `capture_registry.py` or `capture_v4l2.py`.

---

## Miracast-Specific Expectations

| User Action | Expected System Behavior | Technical Reality |
|-------------|--------------------------|-------------------|
| Press Win+K on Windows 11 | See "HuePictureControl" or hostname in the cast target list within 5 seconds | miraclecast must be broadcasting P2P service via wpa_supplicant; discovery is mDNS/P2P probe — can be slow |
| Select the receiver in Win+K | Connection handshake and video stream starts within 3-5 seconds | RTSP negotiation + MPEG2-TS/H.264 decode + FFmpeg startup chain; realistic time is 3-8 seconds |
| Windows changes display resolution | Stream continues at new resolution | FFmpeg re-negotiate needed; v4l2loopback device size is fixed at creation — mismatch causes pipe failure |
| Windows user closes cast session | Virtual device stays registered but produces no frames; HPC shows "disconnected" status | miraclecast session teardown triggers FFmpeg stdin EOF or process death |
| Miracast over existing LAN (no P2P) | Same Win+K flow, but NIC does not need WiFi Direct | Requires MS-MICE implementation; miraclecast does not currently support this; HIGH RISK area |

---

## scrcpy-Specific Expectations

| User Action | Expected System Behavior | Technical Reality |
|-------------|--------------------------|-------------------|
| First-time setup, Android 11+ | Scan QR code in Developer Options → Wireless Debugging → Pair with QR Code | `adb pair IP:PORT CODE` then `adb connect IP:PORT`; one-time per device |
| First-time setup, Android <=10 | Connect USB once, run `adb tcpip 5555`, then WiFi-only forever | USB required once; after that `adb connect IP:5555` works wirelessly |
| Type IP in HPC UI, click Connect | scrcpy starts, Android screen appears in camera dropdown within 2 seconds | `subprocess.run(['scrcpy', '--v4l2-sink=/dev/videoN', '--lock-video-orientation=0', '--no-video-playback', '--tcpip=IP'])` |
| Phone rotates to portrait | No impact on video in pipeline | `--lock-video-orientation=0` prevents dimension change |
| Phone goes to sleep / screen off | scrcpy exits; watchdog restarts connection attempt | `--stay-awake` flag prevents screen-off during active scrcpy session |
| High-latency WiFi | Expect 50-150ms additional pipeline latency vs wired capture | scrcpy WiFi latency is 50-100ms baseline; adds to existing capture→light pipeline; total budget <200ms is achievable |
| User stops wireless input | scrcpy process killed; device node becomes idle | `SIGTERM` to scrcpy subprocess; v4l2loopback continues to exist but produces no new frames |

---

## v4l2loopback-Specific Expectations

| Scenario | User Expectation | Implementation Approach |
|----------|-----------------|------------------------|
| Service starts | Virtual devices already exist at predictable paths | `modprobe v4l2loopback video_nr=10,11 card_label="Miracast,Android-Mirror"` at service startup; or `v4l2loopback-ctl add` per device on demand |
| Module not installed | Friendly error in UI, not a crash | Check `modinfo v4l2loopback` on startup; surface "v4l2loopback not installed" warning if absent |
| Physical device also at /dev/video10 | Conflict: v4l2loopback creation fails | Use high device numbers (10+); enumerate existing nodes first; detect collision and pick next available |
| Application reading device while module reloads | Reader (CaptureRegistry) sees device disappear | Never unload the module while streaming; only `rmmod` on explicit teardown when no readers present |
| Exclusive caps for WebRTC apps | Not required for HuePictureControl's V4L2 reader | `exclusive_caps=0` is fine; only needed for browser-based WebRTC consumers |

---

## FFmpeg Pipeline Health — Expectations

| Failure Scenario | Expected Recovery | Implementation |
|-----------------|------------------|----------------|
| FFmpeg crashes (SIGSEGV, OOM) | Restart within 2 seconds | `asyncio.create_subprocess_exec`; `await proc.wait()` detects death; restart loop with 2s initial backoff |
| WiFi connection drops mid-stream | FFmpeg stalls, then times out and exits | `reconnect` and `reconnect_streamed` flags on FFmpeg RTSP input; also set `-timeout 5000000` (microseconds) |
| RTSP source not available at startup | FFmpeg fails immediately; watchdog backs off | Exponential backoff: 2s, 4s, 8s, max 30s; log each attempt |
| v4l2loopback device not present | FFmpeg exits with device open error | Pre-check device node existence before starting FFmpeg; surface error to UI |
| FFmpeg restart loop (repeated failures) | Give up after N attempts; surface "Wireless input unavailable" | Max 5 consecutive failures before marking source as `error` state; require user to manually retry |
| scrcpy ADB connection refused | scrcpy exits; watchdog retries | Same backoff as FFmpeg; ADB connection refused = device not reachable, not a hard error |

---

## MVP for v1.2

### Must Ship (v1.2.0)

- [ ] `v4l2loopback` module load at service startup with fixed device numbers — without this, nothing else works
- [ ] scrcpy `--v4l2-sink` integration: connect by Android IP, lock orientation, suppress display window
- [ ] scrcpy watchdog: asyncio subprocess monitor, restart on crash, exponential backoff
- [ ] Wireless source appears in existing camera dropdown (no new UI element needed beyond source management panel)
- [ ] Per-source status: `idle / connecting / streaming / error` surfaced via `/ws/status` extension
- [ ] NIC capability check endpoint: `GET /api/wireless/capabilities` returns WiFi Direct supported: true/false
- [ ] Basic Miracast receiver wiring (miraclecast `miracle-wifid` + `miracle-sinkctl` + FFmpeg decode to v4l2loopback) — even if reliability is experimental
- [ ] FFmpeg watchdog for Miracast path (same pattern as scrcpy watchdog, different process graph)
- [ ] API: `POST /api/wireless/miracast/start`, `POST /api/wireless/miracast/stop`, `POST /api/wireless/scrcpy/connect`, `POST /api/wireless/scrcpy/disconnect`

### Add After Validation (v1.2.x)

- [ ] Miracast over Infrastructure (MS-MICE) — high value for users without WiFi Direct NIC, but high complexity; defer until Miracast P2P is stable
- [ ] Per-source latency display in metrics WebSocket
- [ ] Stored Android device history (IP + port) for one-click reconnect
- [ ] Resolution/framerate controls exposed in UI (scrcpy `--max-size`, `--max-fps`)

### Future Consideration (v2+)

- [ ] Multi-device simultaneous scrcpy (two phones simultaneously as two camera inputs)
- [ ] Miracast audio passthrough (out of scope for ambient lighting)
- [ ] Android 10 first-time USB pairing wizard in the UI

---

## Complexity Assessment vs Existing Pipeline

| Component | Existing Pattern to Reuse | New Work |
|-----------|--------------------------|----------|
| Virtual device enumeration | `linuxpy` scan already runs; virtual nodes appear automatically | Only need device nodes to exist at startup |
| V4L2 frame capture from virtual device | Zero changes — `capture_v4l2.py` reads any V4L2 node | None |
| CaptureRegistry ref-counting | Zero changes — pool works by device path | None |
| Per-zone camera selection UI | Zero changes — dropdown already handles N cameras | Only need virtual device names to be descriptive |
| scrcpy subprocess | New asyncio subprocess wrapper + watchdog | ~100 lines Python |
| FFmpeg subprocess (Miracast) | Same subprocess pattern as scrcpy watchdog | ~80 lines Python |
| miraclecast daemon management | No existing pattern | Highest complexity; requires wpa_supplicant P2P config, systemd or manual daemon lifecycle |
| v4l2loopback module management | No existing pattern | `modprobe` at startup, `v4l2loopback-ctl add` on demand; ~40 lines |
| NIC capability check | No existing pattern | `subprocess(['netsh', 'wlan', 'show', 'drivers'])` ... wait: this is a **Linux** backend, not Windows. On Linux: `iw list` + `iw phy phyN info \| grep -i "P2P"` or check `wpa_cli p2p_find`; ~30 lines |
| Status WebSocket extension | Existing `/ws/status` broadcasts `StreamingStatus` object | Add `wireless_sources: list[WirelessSourceStatus]` field |

---

## Sources

- [scrcpy v4l2.md official docs](https://github.com/Genymobile/scrcpy/blob/master/doc/v4l2.md) — `--v4l2-sink`, `--lock-video-orientation` requirement, v4l2loopback-dkms install, HIGH confidence
- [scrcpy connection.md](https://github.com/Genymobile/scrcpy/blob/master/doc/connection.md) — wireless ADB pairing flows for Android 11+ and <=10, `--tcpip` flag, HIGH confidence
- [scrcpy issue #3795](https://github.com/Genymobile/scrcpy/issues/3795) — v4l2 sink empty on Android 13, confirms `--lock-video-orientation` requirement, HIGH confidence
- [v4l2loopback ArchWiki](https://wiki.archlinux.org/title/V4l2loopback) — modprobe options, `video_nr`, `card_label`, dynamic `v4l2loopback-ctl add`, MEDIUM confidence
- [v4l2loopback GitHub](https://github.com/v4l2loopback/v4l2loopback) — official repo, device lifecycle, exclusive_caps, HIGH confidence
- [miraclecast GitHub (albfan)](https://github.com/albfan/miraclecast) — wifid + sinkctl + gst-sink architecture; video streaming described as "highly experimental", MEDIUM confidence
- [miraclecast issue #471 — Windows as WFD_Sink](https://github.com/albfan/miraclecast/issues/471) — confirms Windows→Linux Miracast connection attempts have known failures, MEDIUM confidence
- [MS-MICE: Miracast over Infrastructure](https://learn.microsoft.com/en-us/surface-hub/miracast-over-infrastructure) — TCP port 7250, requires same LAN, supported Win 10 1703+, MEDIUM confidence
- [netsh wlan show drivers — Miracast check](https://cyberraiden.wordpress.com/2025/04/16/check-the-hardware-and-driver-capabilities-of-the-wi-fi-network-adapter-using-netsh-tool/) — `Wireless Display Supported` field, NDIS >= 6.3, MEDIUM confidence (note: this is Windows-side check for sender, not Linux receiver)
- [ffmpeg-watchdog](https://github.com/rrymm/ffmpeg-watchdog) — monitor FFmpeg process, respawn on exit, retry/wait/reset options, MEDIUM confidence
- [Frigate FFmpeg watchdog implementation](https://deepwiki.com/blakeblackshear/frigate/4.1-camera-capture-and-ffmpeg-integration) — production watchdog with "no frames in 20s" detection, MEDIUM confidence
- [FFmpeg reconnect flags](https://ffmpeg.org/ffmpeg-protocols.html) — `-reconnect 1 -reconnect_streamed 1 -timeout 5000000` for RTSP resilience, HIGH confidence
- [scrcpy wireless latency](https://howisolve.com/fix-lag-scrcpy/) — WiFi baseline 50-100ms, HIGH confidence
- [Wireless display latency for ambient lighting context](https://us.lemorele.com/blogs/blog/is-wireless-screen-mirroring-latency-noticeable-in-everyday-use) — consumer expectation <100ms for video, MEDIUM confidence

---
*Feature research for: HuePictureControl v1.2 — Wireless Input (Miracast + scrcpy + v4l2loopback + FFmpeg)*
*Researched: 2026-04-14*
