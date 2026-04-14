# Research Summary: HuePictureControl v1.2 Wireless Input

**Synthesized:** 2026-04-14
**Sources:** STACK.md, FEATURES.md, ARCHITECTURE.md, PITFALLS.md
**Confidence:** MEDIUM overall (HIGH for scrcpy/infrastructure, LOW for Miracast)

## Executive Summary

HuePictureControl v1.2 adds wireless screen mirroring (Miracast from Windows, scrcpy from Android) as additional camera inputs. The recommended approach is a virtual device abstraction layer: wireless sources feed into v4l2loopback kernel virtual devices, which appear to the existing CaptureRegistry, V4L2Capture, and StreamingService as ordinary `/dev/videoN` nodes — requiring zero changes to any downstream pipeline code.

The two wireless input paths have asymmetric risk. The **scrcpy/Android path is HIGH confidence**: scrcpy v3 has a native `--v4l2-sink` flag (officially documented), requires only ADB over WiFi, and the integration is ~100 lines of Python asyncio subprocess management. The **Miracast/Windows path is LOW confidence**: miraclecast (the only functional open-source Linux Miracast sink) has known wpa_supplicant/NetworkManager conflicts, limited maintenance since 2021, and hardware P2P support that varies by NIC driver — it requires a hardware feasibility spike before any implementation.

The dominant risks are process lifecycle failures: FFmpeg stderr pipe deadlocks, orphaned FFmpeg processes surviving FastAPI restarts, premature v4l2loopback device acquisition before FFmpeg writes its first frame, and WiFi Direct P2P mode dropping the LAN connection on single-radio hardware. All have well-defined prevention strategies but must be built into the session lifecycle from day one.

---

## Key Findings

### Stack Additions

| Component | What | Why |
|-----------|------|-----|
| v4l2loopback-dkms | Kernel module for virtual V4L2 devices | Creates `/dev/videoN` nodes that wireless sources write to |
| v4l2loopback-ctl | Runtime device add/delete (no rmmod) | Dynamic lifecycle without module reload |
| scrcpy + adb | Android screen mirroring | `--v4l2-sink=/dev/videoN` writes directly to loopback — no FFmpeg needed |
| miraclecast (miracle-sinkctl) | WiFi Direct Miracast sink | Only Linux Miracast receiver implementation |
| FFmpeg | RTSP → v4l2loopback transcode | Miracast path only (scrcpy writes directly) |
| iw | NIC P2P capability detection | Parse `iw list` for P2P-GO/P2P-client support |
| **No new Python packages** | All subprocess via asyncio stdlib | Consistent with existing architecture |

### Feature Table Stakes

- Virtual cameras appear in camera selector alongside physical devices
- Wireless sources drive Hue lights through existing pipeline — same latency
- Start/stop wireless sessions via REST API
- Session cleanup on disconnect (automatic pipeline + device teardown)
- NIC capability reporting before Miracast attempt
- scrcpy `--lock-video-orientation=0` mandatory — prevents mid-stream dimension change crash

### Architecture

- **Zero changes downstream:** CaptureRegistry, V4L2Capture, StreamingService, preview WebSocket — all untouched
- **New components:** PipelineManager (subprocess lifecycle + v4l2loopback-ctl), WirelessRouter (/api/wireless/*), WirelessPage.tsx, wireless_sessions DB table
- **Static device numbering:** video10 = Miracast, video11 = scrcpy — deterministic stable_ids, no race conditions
- **Data flow:** Wireless source → (scrcpy direct | FFmpeg transcode) → v4l2loopback → existing V4L2 pipeline

### Critical Pitfalls

1. **FFmpeg stderr pipe deadlock** — Must use `stderr=DEVNULL` + `-loglevel quiet -nostats` as production default
2. **Premature device acquisition** — CaptureRegistry.acquire() must wait for producer_ready event (first frame written, 500ms-2000ms)
3. **Orphan FFmpeg processes** — Every subprocess must be wrapped in context manager with try/finally kill in FastAPI lifespan shutdown
4. **WiFi Direct drops LAN** — Single-radio NICs lose Hue Bridge connection when Miracast activates; must gate behind NIC check
5. **v4l2loopback rmmod blocked by open fds** — Use v4l2loopback-ctl add/delete instead of module reload
6. **scrcpy screen-lock disconnect** — Android 12/14 drops connection on screen lock; watchdog with supervised restart needed

---

## Implications for Roadmap

### Suggested Build Order (4 phases)

**Phase 1: Infrastructure and Virtual Device Foundation**
- v4l2loopback module management via v4l2loopback-ctl
- PipelineManager scaffold with subprocess lifecycle + cleanup context manager
- wireless_sessions DB table
- `GET /api/wireless/capabilities` endpoint (NIC check, dependency versions)
- Static device number allocation (video10, video11)

**Phase 2: Android scrcpy Integration**
- PipelineManager.start_scrcpy: ADB WiFi connect → scrcpy --v4l2-sink → virtual device
- producer_ready event sequencing (wait for first frame before CaptureRegistry.acquire)
- Supervised restart watchdog with exponential backoff
- REST API: POST /api/wireless/scrcpy/start, DELETE /api/wireless/scrcpy/stop
- End-to-end test: Android screen → lights

**Phase 3: Miracast Integration (hardware-gated)**
- NIC P2P capability check via `iw list` parsing
- Hardware feasibility spike before implementation
- miraclecast daemon lifecycle management
- FFmpeg RTSP → v4l2loopback pipeline with stderr=DEVNULL
- REST API: POST /api/wireless/miracast/start, DELETE /api/wireless/miracast/stop
- May scope down to "unsupported" if hardware lacks P2P

**Phase 4: Frontend Wireless Tab**
- WirelessPage.tsx: NIC status banner, session list, start/stop controls
- scrcpy IP entry form
- Miracast status (P2P-gated or unavailable)
- Wireless sources in camera selector dropdown

### Research Flags

- **Needs hardware spike:** Phase 3 (Miracast) — host NIC P2P support unknown until tested
- **Skip research-phase:** Phase 1 (v4l2loopback HIGH confidence), Phase 2 (scrcpy officially documented), Phase 4 (reuses existing shadcn/ui + Zustand patterns)

---

## Confidence Assessment

| Path | Level | Key Risk |
|------|-------|----------|
| scrcpy/Android | HIGH | ADB WiFi connection fragility (mitigated by watchdog) |
| v4l2loopback | HIGH | Requires sudoers NOPASSWD for v4l2loopback-ctl |
| Miracast/Windows | LOW | miraclecast maintenance, NIC P2P support, wpa_supplicant conflicts |
| FFmpeg pipelines | HIGH | Well-understood patterns, needs proper lifecycle management |

### Open Questions

- Does the host NIC support WiFi Direct P2P? (`iw list` check gates entire Miracast path)
- Is miraclecast available as distro package or must be compiled from source?
- Should Miracast require a dedicated USB WiFi adapter to avoid LAN dropout?
- What is the exact RTSP URL format from miracle-sinkctl stdout? Needs hardware spike.

---
*Research completed: 2026-04-14*
*Ready for requirements: yes*
