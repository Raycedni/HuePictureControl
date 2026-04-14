# HuePictureControl

## What This Is

A real-time ambient lighting system that captures HDMI video via a USB capture card, analyzes configurable freeform regions of the frame, and drives Philips Hue lights (including gradient-capable devices like Festavia and Flux) to match the on-screen colors. Supports multiple simultaneous capture devices with per-entertainment-zone camera selection. Controlled entirely through a web UI with no authentication required.

## Core Value

Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.

## Requirements

### Validated

- ✓ Capture frames from a USB HDMI capture card (UVC device) inside Docker — v1.0
- ✓ Analyze freeform user-drawn regions of the camera frame for dominant colors — v1.0
- ✓ Drive Hue lights in real-time (<100ms) via the Hue Entertainment API (streaming mode) — v1.0
- ✓ Specialized support for gradient-capable devices: Hue Festavia (per-segment), Hue Flux (per-segment) — v1.0
- ✓ Support all other Hue light products as single-color targets — v1.0
- ✓ Web frontend for configuration: draw freeform regions on a camera snapshot, assign each to a light/segment — v1.0
- ✓ Live camera preview in the web UI for verifying region-to-light mappings — v1.0
- ✓ Global on/off toggle in the UI — capture and color processing only runs when explicitly enabled — v1.0
- ✓ Separate backend and frontend services in Docker — v1.0
- ✓ Direct Hue API usage (no wrapper libraries), targeting API v2 (CLIP) and Entertainment API — v1.0
- ✓ Scale to 16+ simultaneous light segments — v1.0
- ✓ No authentication on the web UI — v1.0
- ✓ Multiple capture device enumeration and camera selector per entertainment zone — v1.1
- ✓ Per-zone camera dropdown with live preview switching — v1.1
- ✓ Docker multi-device passthrough via cgroup rules — v1.1

### Active (v1.2)

- [ ] Wireless screen mirroring from Windows via Miracast (WiFi Direct) as a virtual camera input
- [ ] Wireless screen mirroring from Android via scrcpy over WiFi as a fallback input
- [ ] v4l2loopback virtual camera management — create/destroy on demand, transparent to capture pipeline
- [ ] FFmpeg pipeline management — pipe wireless streams to virtual V4L2 devices with health monitoring
- [ ] Wireless input API — start/stop receivers, list sessions, check NIC capabilities
- [ ] Docker configuration for wireless dependencies and Linux capabilities

### Active (v1.3)

- [ ] WLED device discovery and management in a dedicated UI tab
- [ ] UDP realtime protocol (DDP/DRGB) streaming to WLED ESP32 devices
- [ ] Paint-on-strip UI for assigning LED pixel ranges to canvas zones
- [ ] Shared channel-per-area mapping abstraction for Hue and WLED
- [ ] Home Assistant REST endpoints: select camera, select zone, start/stop streaming
- [ ] Persist selected entertainment config per camera across page reloads
- [ ] Dropdown reflects actual streaming state on reload

### Out of Scope

- User authentication / multi-user support — single-user local tool
- Mobile app — web UI is the only interface
- Non-Hue, non-WLED smart lights — only Hue and WLED ecosystems supported
- Audio reactivity — video/color only
- Cloud connectivity — fully local, Bridge on LAN
- Apple AirPlay support — user explicitly scoped to Windows and Android only

## Context

- **Hardware setup:** HDMI source → 4K USB capture card (presents as UVC webcam) → Docker container. Hue Bridge on local network with all lights paired and operational.
- **Specific devices:** Philips Hue Festavia (20m, 250 mini LEDs, gradient), Philips Hue Flux 3m lightstrip (RGBWWIC, gradient)
- **Prior experience:** User has tried Hyperion and similar ambilight solutions — primary frustration was lack of support for gradient-capable Hue devices with per-segment control
- **Key technical challenge:** Hue REST API is rate-limited (~10 req/s). The Entertainment API (UDP streaming, ~25Hz) is required to hit the <100ms latency target with 16+ segments
- **Environment:** Docker Compose with separate backend/frontend containers. USB device passthrough to backend container via cgroup rules (hot-plug capable).
- **Current state:** v1.1 shipped — 19 phases planned across 4 milestones. Backend: ~4,500 LOC Python. Frontend: ~3,500 LOC TypeScript/React. 167+ backend tests, 30+ frontend tests.

## Constraints

- **Latency**: <100ms from frame capture to light update — requires Entertainment API streaming, not REST polling
- **Docker**: All services containerized; USB capture device passed through to backend container
- **Hue API**: Direct API usage (v2 CLIP for config, Entertainment API for streaming) — no third-party Hue wrapper libraries
- **Network**: Hue Bridge must be reachable from Docker network (host network or bridge with LAN access)
- **No auth**: Web UI is unauthenticated — local network tool only

## Current Milestone: v1.2 Wireless Input

**Goal:** Enable any Windows or Android device to wirelessly mirror its screen to the system as an input source, supplementing or replacing the physical HDMI capture card.

**Target features:**
- Miracast (WiFi Direct) receiver for Windows and older Android — appears as Cast target in Win+K
- scrcpy over WiFi fallback for newer Android devices that dropped Miracast
- v4l2loopback virtual cameras fed by FFmpeg pipelines — transparent to existing capture pipeline
- Wireless sources appear in camera selector alongside physical devices
- API for starting/stopping wireless receivers and checking NIC capabilities

## Next Milestone: v1.3 WLED Support, HA Control & Bug Fixes

**Goal:** Expand the system beyond Hue to support WLED (ESP32) LED strips via UDP realtime streaming, add Home Assistant control endpoints, and fix the entertainment zone persistence bug.

**Target features:**
- WLED device discovery and management in a dedicated tab
- UDP realtime protocol (DDP/DRGB) for low-latency LED streaming to WLED devices
- Paint-on-strip UI for assigning LED ranges to canvas zones (designed for 300+ LED strips)
- Shared channel-per-area mapping code between Hue and WLED
- Home Assistant REST endpoints: select camera, select zone, start/stop streaming (control-only)
- Fix: persist selected entertainment config per camera across page reloads
- Fix: dropdown reflects actual streaming state on reload

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Entertainment API for streaming | REST API rate limits make <100ms with 16+ segments impossible | ✓ Good — confirmed <100ms latency v1.0 |
| Freeform region mapping | User needs flexible region shapes, not just grid/edge sampling | ✓ Good — Konva canvas editor works well |
| Docker Compose deployment | User's preferred deployment model, capture card passthrough via device mapping | ✓ Good — cgroup rules enable hot-plug |
| No auth | Single-user local tool, complexity not justified | ✓ Good |
| hue-entertainment-pykit for DTLS | Python ssl has no DTLS support | ✓ Good — pinned Python 3.12 |
| Inlined Gamut C color math | rgbxy dependency unmaintained since 2020 | ✓ Good — 20-line algorithm |
| CaptureRegistry ref-counted pool | Thread-safe concurrent multi-camera without race conditions | ✓ Good — v1.1 |
| device_cgroup_rules for Docker passthrough | Hot-plug support without container restart | ✓ Good — v1.1 |
| Props-down state lifting in EditorPage | Zone + camera state owned at page level, passed to children | ✓ Good — v1.1 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state
5. All milestone decisions added to Key Decisions

---
*Last updated: 2026-04-14 after v1.1 milestone*
