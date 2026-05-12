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

### Validated (v1.2 — completed 2026-05-12)

- ✓ WLED device discovery and management in a dedicated UI tab — Phase 17
- ✓ UDP realtime protocol (DRGB/DNRGB) streaming to WLED ESP32 devices — Phase 17
- ✓ Shared channel-per-area mapping abstraction for Hue and WLED — Phase 17 (StreamingCoordinator + region_plan with COALESCE(MAX(...), 1))
- ✓ Home Assistant REST endpoints: start/stop streaming, select camera/zone, query status — Phase 18

### Active (v1.3)

- [ ] MQTT auto-discovery — publish HA discovery messages so entities appear without YAML edits
- [ ] HA YAML snippet documentation — rest_command:, sensor:, input_select: examples for the non-MQTT path
- [ ] WebSocket push for HA status changes — lower-latency alternative to REST polling
- [ ] Per-device WLED health in HA status payload — expose broadcaster._metrics["wled_devices"]

### Deferred

- [ ] Wireless screen mirroring (Miracast / scrcpy / v4l2loopback) — deferred from original v1.2 scope, not yet rescheduled
- [ ] Paint-on-strip UI for assigning LED pixel ranges to canvas zones — deferred (Phase 19 placeholder)
- [ ] Persist selected entertainment config per camera across page reloads — bug fix, defer to v1.4
- [ ] Dropdown reflects actual streaming state on reload — bug fix, defer to v1.4

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

## Current Milestone: v1.3 Home Assistant Integration Polish

**Goal:** Make HuePictureControl a first-class Home Assistant citizen — zero-YAML setup for new users and feature-complete telemetry/control for power users — without violating the existing no-auth, no-outbound-secrets design.

**Target features:**
- MQTT auto-discovery — backend publishes `homeassistant/<component>/<id>/config` messages so HA creates switch/sensor/select entities automatically when a Mosquitto broker is reachable
- HA YAML snippet documentation — ship `rest_command:`, `sensor:`, `input_select:` examples for the non-MQTT path (deferred from Phase 18)
- WebSocket push for HA status changes — lower-latency alternative to HA's REST polling of `/api/ha/status`
- Per-device WLED health in HA status payload — expose `broadcaster._metrics["wled_devices"]` through `/api/ha/status`

**Out of scope for v1.3 (defer to v1.4+):**
- `PUT /api/ha/target_hz` runtime frame-rate tuning — revisit only if users report friction
- `POST /api/ha/restart` combined verb — HA can chain stop+start trivially
- Persist entertainment config per camera across reloads (bug fix) — defer to v1.4 bug-fix cycle
- Dropdown reflects actual streaming state on reload (bug fix) — defer to v1.4 bug-fix cycle

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
*Last updated: 2026-05-12 — v1.2 complete, v1.3 (HA Integration Polish) opened*
