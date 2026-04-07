# HuePictureControl

## What This Is

A real-time ambient lighting system that captures HDMI video via a USB capture card, analyzes configurable freeform regions of the frame, and drives Philips Hue lights (including gradient-capable devices like Festavia and Flux) to match the on-screen colors. Controlled entirely through a web UI with no authentication required.

## Core Value

Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Capture frames from a USB HDMI capture card (UVC device) inside Docker
- [ ] Analyze freeform user-drawn regions of the camera frame for dominant colors
- [ ] Drive Hue lights in real-time (<100ms) via the Hue Entertainment API (streaming mode)
- [ ] Specialized support for gradient-capable devices: Hue Festavia (string light, per-segment), Hue Flux (lightstrip, per-segment)
- [ ] Support all other Hue light products as single-color targets
- [ ] Web frontend for configuration: draw freeform regions on a camera snapshot, assign each to a light/segment
- [ ] Live camera preview in the web UI for verifying region-to-light mappings
- [ ] Global on/off toggle in the UI — capture and color processing only runs when explicitly enabled
- [ ] Separate backend and frontend services in Docker
- [ ] Direct Hue API usage (no wrapper libraries), targeting API v2 (CLIP) and Entertainment API
- [ ] Scale to 16+ simultaneous light segments
- [ ] No authentication on the web UI

### Active (v1.2)

- [ ] Wireless screen mirroring from Windows via Miracast (WiFi Direct) as a virtual camera input
- [ ] Wireless screen mirroring from Android via scrcpy over WiFi as a fallback input
- [ ] v4l2loopback virtual camera management — create/destroy on demand, transparent to capture pipeline
- [ ] FFmpeg pipeline management — pipe wireless streams to virtual V4L2 devices with health monitoring
- [ ] Wireless input API — start/stop receivers, list sessions, check NIC capabilities
- [ ] Docker configuration for wireless dependencies and Linux capabilities

### Out of Scope

- User authentication / multi-user support — single-user local tool
- Mobile app — web UI is the only interface
- Non-Hue smart lights — Hue ecosystem only
- Audio reactivity — video/color only
- Cloud connectivity — fully local, Bridge on LAN
- Apple AirPlay support — user explicitly scoped to Windows and Android only

## Context

- **Hardware setup:** HDMI source → 4K USB capture card (presents as UVC webcam) → Docker container. Hue Bridge on local network with all lights paired and operational.
- **Specific devices:** Philips Hue Festavia (20m, 250 mini LEDs, gradient), Philips Hue Flux 3m lightstrip (RGBWWIC, gradient)
- **Prior experience:** User has tried Hyperion and similar ambilight solutions — primary frustration was lack of support for gradient-capable Hue devices with per-segment control
- **Key technical challenge:** Hue REST API is rate-limited (~10 req/s). The Entertainment API (UDP streaming, ~25Hz) is required to hit the <100ms latency target with 16+ segments
- **Environment:** Docker Compose with separate backend/frontend containers. USB device passthrough to backend container.

## Constraints

- **Latency**: <100ms from frame capture to light update — requires Entertainment API streaming, not REST polling
- **Docker**: All services containerized; USB capture device passed through to backend container
- **Hue API**: Direct API usage (v2 CLIP for config, Entertainment API for streaming) — no third-party Hue wrapper libraries
- **Network**: Hue Bridge must be reachable from Docker network (host network or bridge with LAN access)
- **No auth**: Web UI is unauthenticated — local network tool only

## Current Milestone: v1.1 Multi-Camera Support

**Goal:** Replace the single static camera with a per-entertainment-zone camera selector, showing all available video devices.

**Target features:**
- Enumerate all video capture devices available to the container/host
- Camera dropdown selector per entertainment zone in the UI
- Each entertainment zone can independently use a different camera source
- Live preview updates when camera selection changes

## Next Milestone: v1.2 Wireless Input

**Goal:** Enable any Windows or Android device to wirelessly mirror its screen to the system as an input source, supplementing or replacing the physical HDMI capture card.

**Target features:**
- Miracast (WiFi Direct) receiver for Windows and older Android — appears as Cast target in Win+K
- scrcpy over WiFi fallback for newer Android devices that dropped Miracast
- v4l2loopback virtual cameras fed by FFmpeg pipelines — transparent to existing capture pipeline
- Wireless sources appear in camera selector alongside physical devices
- API for starting/stopping wireless receivers and checking NIC capabilities

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Entertainment API for streaming | REST API rate limits make <100ms with 16+ segments impossible | — Pending |
| Freeform region mapping | User needs flexible region shapes, not just grid/edge sampling | — Pending |
| Docker Compose deployment | User's preferred deployment model, capture card passthrough via device mapping | — Pending |
| No auth | Single-user local tool, complexity not justified | — Pending |

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

---
*Last updated: 2026-04-07 — Phase 10 complete: per-zone camera dropdown in editor UI with live preview switching*
