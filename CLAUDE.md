# HuePictureControl — Development Guide

## Test Commands

### Backend (Python 3.12)
```bash
source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest
```
If venv doesn't exist:
```bash
python3 -m venv /tmp/hpc-venv && source /tmp/hpc-venv/bin/activate && pip install -r Backend/requirements.txt
```

### Frontend (Node 20+)
```bash
cd Frontend && npx vitest run
```

### Full Stack (Docker)
```bash
docker compose up -d
```

## Dev Servers
- Backend: http://localhost:8000 (runs via Docker or `uvicorn main:app --reload --port 8000`)
- Frontend: http://localhost:8091 (`npm run dev` in Frontend/)
- Backend health: `curl http://localhost:8000/api/health`

## Key API Endpoints
- `GET /api/health` — service health
- `GET /api/hue/status` — bridge pairing status
- `GET /api/hue/lights` — discover lights on bridge
- `GET /api/hue/configs` — entertainment configurations
- `GET /api/regions` — configured screen regions
- `POST /api/capture/start` — start streaming to lights
- `POST /api/capture/stop` — stop streaming
- `GET /ws/status` — WebSocket for streaming metrics
- `GET /ws/preview` — WebSocket for live JPEG frames

## Architecture
- Backend: FastAPI + aiosqlite + hue-entertainment-pykit (DTLS streaming)
- Frontend: React 19 + TypeScript + Konva.js canvas + Zustand + shadcn/ui
- Python 3.12 pinned (hue-entertainment-pykit incompatible with 3.13+)
- Backend needs host network for DTLS/UDP port 2100 access to Hue Bridge

## Hardware
- Hue Bridge v2 at 192.168.178.23 (paired)
- USB capture card at /dev/video0 (or virtual via v4l2loopback at /dev/video10)
- Entertainment config "TV-Bereich" (6 channels)

## Autonomous Testing Checklist
Before making changes, verify:
1. `python -m pytest` — all backend tests pass (167+)
2. `npx vitest run` — all frontend tests pass (30+)
3. `curl localhost:8000/api/health` — backend is reachable
4. Use Playwright MCP to visually verify frontend changes at http://localhost:8091

<!-- GSD:project-start source:PROJECT.md -->
## Project

**HuePictureControl**

A real-time ambient lighting system that captures HDMI video via a USB capture card, analyzes configurable freeform regions of the frame, and drives Philips Hue lights (including gradient-capable devices like Festavia and Flux) to match the on-screen colors. Controlled entirely through a web UI with no authentication required.

**Core Value:** Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.

### Constraints

- **Latency**: <100ms from frame capture to light update — requires Entertainment API streaming, not REST polling
- **Docker**: All services containerized; USB capture device passed through to backend container
- **Hue API**: Direct API usage (v2 CLIP for config, Entertainment API for streaming) — no third-party Hue wrapper libraries
- **Network**: Hue Bridge must be reachable from Docker network (host network or bridge with LAN access)
- **No auth**: Web UI is unauthenticated — local network tool only
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Context: What Already Exists (Do Not Re-Research)
| Layer | Technology | Version |
|-------|-----------|---------|
| Backend framework | FastAPI | >=0.115 |
| Async DB | aiosqlite | >=0.20 |
| HTTP client | httpx | >=0.27 |
| Frame capture (Linux) | Custom V4L2 ctypes/ioctl + mmap | in `capture_v4l2.py` |
| Frame decode | opencv-python-headless | >=4.10 |
| Hue streaming | hue-entertainment-pykit | 0.9.4 |
| Python | 3.12 (pinned) | 3.12 |
| Frontend | React 19 + TypeScript + Konva.js + Zustand | — |
| Device enumeration | linuxpy | >=0.24 (added in v1.1) |
## Recommended Stack Additions
### Core Technologies (Backend — New)
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python `socket` stdlib (UDP) | stdlib (3.12) | WLED DRGB/DNRGB realtime packet sending | No library needed. WLED UDP realtime is a 2-byte header + raw RGB bytes over `SOCK_DGRAM`. This codebase already builds protocols from scratch (see `capture_v4l2.py`, `hue_client.py`). One `WledStreamer` class with `socket.socket(AF_INET, SOCK_DGRAM)` is the complete implementation — ~30 lines of Python. |
| `zeroconf` | `>=0.148,<2` | WLED device discovery via mDNS (`_wled._tcp.local.`) | Pure Python, no system Bonjour/Avahi/D-Bus dependency. WLED devices advertise as `_wled._tcp.local.`; `AsyncServiceBrowser` integrates with the existing asyncio event loop. Version 0.148.0 released Oct 2025. Python 3.9+ compatible, no conflict with existing requirements. See Docker caveat below — only useful if backend uses `network_mode: host`. |
| `httpx` (already present) | `>=0.27` | WLED JSON API queries + Home Assistant REST API | Already a dependency. WLED's `GET /json/info` returns `leds.count` (needed at device registration for strip UI). HA REST API uses the same bearer-token HTTP pattern. Zero new libraries needed for either integration. |
### Core Technologies (Frontend — New)
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `react-konva` (already in use) | current | Paint-on-strip LED range selector UI | Already the established canvas primitive. The strip UI is a horizontal canvas showing one cell per LED (or one rect per zone range). Click-drag paints a zone color assignment. Same pointer event model as the existing freeform region editor — no new library needed. |
## Protocol Specifications (Build-Not-Buy)
### WLED UDP Realtime — Packet Formats
### WLED JSON API (Device Registration)
### Home Assistant REST API (Inbound — HA Calls HuePictureControl)
- No HA token stored in HuePictureControl config
- No outbound firewall rules needed
- HA user configures `rest_command:` in their `configuration.yaml` pointing at `http://[HPC_HOST]:8001/api/ha/...`
- HuePictureControl exposes new unauthenticated REST endpoints (consistent with existing no-auth design)
## Integration Points with Existing Code
### New `WledStreamingService` (sibling to `StreamingService`)
| Aspect | Hue (existing) | WLED (new) |
|--------|---------------|------------|
| Transport | DTLS/UDP via `hue-entertainment-pykit` | Raw UDP `socket.SOCK_DGRAM` |
| Color space | xyb (CIE 1931) | Raw RGB bytes |
| Activation | REST call to Bridge required | None — UDP is stateless |
| Reconnect | Bridge socket re-activate | Reconnect UDP socket (trivial) |
| Config | Entertainment config UUID | WLED device IP + LED count |
### `database.py` — Three New Tables
### `main.py` — App State Addition
### New Router Files
- `routers/wled.py` — CRUD for WLED devices, start/stop WLED streaming, paint assignments (`/api/wled/...`)
- `routers/ha.py` — HA control endpoints (`/api/ha/start`, `/api/ha/stop`, `/api/ha/camera`, `/api/ha/zone`)
- No changes to `routers/capture.py`, `routers/hue.py`, or `routers/regions.py`
## Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `zeroconf` | `>=0.148,<2` | WLED auto-discovery on LAN via `_wled._tcp.local.` | Only during user-initiated device scan in the WLED tab. `AsyncServiceBrowser` with 3-second timeout. Not continuous background browsing. Only useful with `network_mode: host` in Docker — see caveat. |
| Python `socket` stdlib | stdlib | WLED UDP DRGB/DNRGB packet send | Per-frame during streaming. One `SOCK_DGRAM` socket per WLED device created at stream start, reused for the session, closed on stop. |
| `httpx` (existing) | `>=0.27` | WLED `/json/info` fetch, HA REST calls | At device registration and on-demand refresh. Not per-frame. |
## Alternatives Considered
| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| Raw `socket` stdlib for WLED UDP | `python-wled` (PyPI v0.21.0) | `python-wled` wraps the JSON API only — no UDP realtime protocol support. Confirmed from source. Adding a 3+ dependency library for HTTP calls already covered by `httpx` is unjustified. |
| DNRGB for strips > 490 LEDs | DDP protocol (port 4048) | DDP has a 10-byte header with push IDs, flags, and offset fields. WLED explicitly states it ignores optional timecodes in DDP headers. DNRGB achieves the same segmented addressing with a 4-byte header. Lower complexity, same result for this use case. |
| DRGB for strips <= 490 LEDs | WARLS (protocol byte = 1) | WARLS has a 255 LED limit and requires per-LED index bytes. DRGB covers 490 LEDs, has a simpler packet format (no indices), and is the recommended WLED realtime protocol for full-strip updates. |
| HA calls HuePictureControl (`rest_command`) | HuePictureControl calls HA REST API | Storing an HA long-lived access token in HuePictureControl adds a configuration burden and an outbound dependency. `rest_command` is purpose-built for HA→external service control. Simpler, no secrets stored in HPC. |
| Sibling `WledStreamingService` class | Extend `StreamingService` with WLED support | Extending entangles DTLS and UDP codepaths, making each harder to test. `StreamingService` has Hue-specific activation/deactivation; WLED has none. Same lifecycle interface, separate classes. |
| `react-konva` (existing) for strip paint UI | Dedicated LED strip React component | No suitable package exists for this specific interaction pattern. The Konva canvas already handles pointer drag events and zone coloring in this project. A custom component using `Rect` nodes per LED range is ~150 lines of TSX. |
| Manual IP entry as primary discovery | mDNS-only discovery | mDNS multicast does not propagate through Docker bridge networks. Manual IP entry works reliably regardless of Docker network mode. |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `python-wled` (PyPI) | JSON API only, no UDP realtime streaming. Adds indirect dependencies for functionality `httpx` already covers. | `httpx` for JSON API; raw `socket` for UDP |
| DDP over DNRGB | More complex header, no benefit for this use case. WLED ignores optional DDP timecodes anyway. | DNRGB chunked packets for > 490 LEDs |
| WARLS protocol (byte 0 = 1) | 255 LED limit. Superseded by DRGB/DNRGB. Most WS2812B strips are 300–1200 LEDs. | DRGB or DNRGB |
| Polling `/json/state` per frame | HTTP polling destroys latency. WLED does not confirm UDP receipt. | Fire-and-forget UDP only during streaming |
| `zeroconf` with Docker bridge network mode | Multicast does not propagate through Docker bridge. `AsyncServiceBrowser` will find zero devices. | Manual IP entry; mDNS only if backend switches to `network_mode: host` |
| Storing HA long-lived access token in HuePictureControl | Adds secret management burden; violates no-auth local tool design. | HA calls HPC via `rest_command`; HPC exposes unauthenticated control endpoints |
| New camera manager service / process for WLED camera | The existing `CaptureRegistry` pattern is sufficient. WLED streaming uses the same frame as Hue streaming — no second capture needed for the same device. | Extend `app.state` with `wled_streaming` that calls `registry.acquire()` on the same device path |
## Docker / Network Considerations
## Version Compatibility
| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `zeroconf>=0.148,<2` | Python 3.9–3.14, asyncio | Pure Python, no C extension required. Optional Cython for performance (not needed). No conflict with any existing requirement. |
| `zeroconf>=0.148,<2` | `fastapi>=0.115`, `uvicorn[standard]` | No interaction. Used only in a FastAPI route handler via `asyncio.to_thread` or `AsyncServiceBrowser`. |
| Python `socket` stdlib | Python 3.12, asyncio | Use `asyncio.to_thread(sock.sendto, data, addr)` for non-blocking sends — same pattern as `capture_v4l2.py` uses `asyncio.to_thread` for blocking ioctl calls. Consistent with existing codebase. |
## Installation
# Add to Backend/requirements.txt:
# Install in venv:
## Sources
- [WLED UDP Realtime docs](https://kno.wled.ge/interfaces/udp-realtime/) — WARLS/DRGB/DNRGB/DRGBW packet formats, port 21324, LED count limits, HIGH confidence
- [WLED Wiki UDP Realtime Control](https://github.com/Aircoookie/WLED/wiki/UDP-Realtime-Control) — Protocol byte values (1=WARLS, 2=DRGB, 3=DRGBW, 4=DNRGB), timeout semantics, exact byte offsets, HIGH confidence
- [WLED DDP docs](https://kno.wled.ge/interfaces/ddp/) — DDP port 4048, WLED does not read optional timecodes, HIGH confidence
- [WLED JSON API docs](https://kno.wled.ge/interfaces/json-api/) — `/json/info` endpoint, `leds.count` field structure, HIGH confidence
- [python-wled GitHub](https://github.com/frenck/python-wled) — v0.21.0, JSON API only, no UDP realtime, confirmed via README, HIGH confidence
- [zeroconf PyPI](https://pypi.org/project/zeroconf/) — v0.148.0 (Oct 2025), Python 3.9+, pure Python with optional Cython, HIGH confidence
- [WLED mDNS service type issue #103](https://github.com/Aircoookie/WLED/issues/103) — `_wled._tcp.local.` service type confirmed, HIGH confidence
- [Home Assistant REST API developer docs](https://developers.home-assistant.io/docs/api/rest/) — Bearer token auth, `/api/services/` endpoint format, HIGH confidence
- [wledcast reference implementation](https://github.com/ppamment/wledcast) — DDP streaming from Python, MEDIUM confidence (reference only, uses wxPython GUI not relevant here)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

| Skill | Description | Path |
|-------|-------------|------|
| health | Check full stack health — backend API, frontend, Hue Bridge connectivity, and WebSocket endpoints | `.claude/skills/health/SKILL.md` |
| preflight | Full pre-commit verification — runs tests, health checks, and visual UI verification before committing | `.claude/skills/preflight/SKILL.md` |
| test | Run all backend and frontend tests in parallel and report results | `.claude/skills/test/SKILL.md` |
| verify-ui | Visually verify the frontend UI by screenshotting all tabs using Playwright MCP | `.claude/skills/verify-ui/SKILL.md` |
<!-- GSD:skills-end -->
