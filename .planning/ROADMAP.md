# Roadmap: HuePictureControl

**Version:** v1.0
**Created:** 2026-03-23
**Core Value:** Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.

## Overview

Six phases take the project from zero to a fully operational ambient lighting system. Phase 1 is a spike-first gate: the DTLS transport layer must be proven working with the physical Hue Bridge before any other streaming work begins. Once that gate clears, Phase 2 (capture pipeline) and Phase 4 (frontend editor) can proceed in parallel. Phase 3 wires capture output into the DTLS stream and delivers the first end-to-end color sync. Phase 5 adds the per-segment gradient device support that is the project's core differentiator. Phase 6 hardens the deployment for reliable day-to-day use.

## Milestone: v1.0 — Full ambient lighting with gradient device support

## Phases

- [ ] **Phase 1: Infrastructure and DTLS Spike** - Prove DTLS transport works; establish Docker environment and bridge pairing
- [ ] **Phase 2: Capture Pipeline and Color Extraction** - Capture frames from USB capture card and extract per-region colors
- [ ] **Phase 3: Entertainment API Streaming Integration** - Wire capture output into DTLS stream; deliver first end-to-end color sync
- [ ] **Phase 4: Frontend Canvas Editor** - Interactive polygon region editor with live preview and light assignment
- [ ] **Phase 5: Gradient Device Support and Polish** - Per-segment control of Festavia, Flux, and Play Gradient devices
- [ ] **Phase 6: Hardening and Deployment** - Production-quality Docker deployment with nginx, health checks, and error recovery

## Phase Details

### Phase 1: Infrastructure and DTLS Spike
**Goal**: Prove the DTLS transport layer works against the physical Hue Bridge and establish the Docker environment that everything else builds on.
**Depends on**: Nothing (first phase)
**Requirements**: BRDG-01, BRDG-02, BRDG-03, BRDG-05, UI-02, INFR-01, INFR-02, INFR-03, INFR-05
**Estimated scope**: L

**Delivers:**
- Working Docker Compose with host-network backend and bridge-network frontend skeleton
- USB device passthrough verified with the actual capture card
- Bridge pairing endpoint: link button press yields application key + client key, stored in SQLite
- DTLS connection established to Hue Bridge using `hue-entertainment-pykit`
- Single Entertainment API packet sent and acknowledged — one real light changes color
- SQLite schema created via aiosqlite (credentials, regions, mappings tables)
- UI pairing flow: step-by-step instructions, status feedback, bridge selection dropdown

**Success Criteria** (what must be TRUE):
  1. User can press the bridge link button, click "Pair" in the UI, and see "Paired" status without restarting the container
  2. Bridge credentials survive a `docker compose restart` and the app reconnects without re-pairing
  3. The UI lists all entertainment configurations discovered from the paired bridge
  4. A developer can run a CLI spike script that opens a DTLS session and changes a real light's color, with no code changes required to the bridge or network
  5. Docker Compose starts both containers cleanly with `docker compose up`; backend is reachable at `/api/health`

**Risks:**
- `hue-entertainment-pykit` DTLS session may fail with specific bridge firmware versions — spike with physical hardware immediately; no simulated fallback
- nginx `proxy_pass` to host-network backend requires `127.0.0.1:8000` not `backend:8000` — verify during Phase 1 Docker setup

**Plans:** 3/4 plans executed

Plans:
- [ ] 01-01-PLAN.md — Docker Compose + FastAPI skeleton + SQLite schema + test scaffold
- [ ] 01-02-PLAN.md — Bridge pairing, credential persistence, entertainment config/light discovery
- [ ] 01-03-PLAN.md — Frontend React skeleton + PairingFlow UI + nginx reverse proxy
- [ ] 01-04-PLAN.md — DTLS spike CLI script + physical hardware verification (Phase 1 gate)

---

### Phase 2: Capture Pipeline and Color Extraction
**Goal**: Capture live frames from the USB HDMI capture card and extract average colors from configurable polygon regions, testable without the Hue Bridge.
**Depends on**: Phase 1
**Requirements**: CAPT-01, CAPT-02, CAPT-05
**Estimated scope**: M

**Delivers:**
- `LatestFrameCapture` asyncio-compatible class reading from `/dev/videoN` at 640x480 MJPEG
- Pre-computed polygon mask infrastructure using numpy; masks recomputed only when regions change
- `cv2.mean()` region color extraction with configurable polygon coordinates
- RGB to CIE xy conversion with Gamut C clamping (inline or via `rgbxy`)
- `run_in_executor` wrapper around blocking `cap.read()` to avoid asyncio starvation
- `GET /api/capture/snapshot` REST endpoint returning current frame as JPEG
- Configurable device path via environment variable or REST endpoint

**Success Criteria** (what must be TRUE):
  1. `GET /api/capture/snapshot` returns a valid JPEG from the physical capture card within 200ms
  2. Configuring a different device path (e.g. `/dev/video1`) takes effect without restarting the container
  3. A debug log or endpoint shows the extracted CIE xy color value for at least one hard-coded test region, confirming the color math is running

**Risks:**
- `cap.read()` blocking duration at 640x480 MJPEG on actual hardware may exceed 40ms — measure empirically and apply `run_in_executor` if asyncio starvation is observed

**Plans:** 2 plans

Plans:
- [ ] 02-01-PLAN.md — Capture service + color math module with TDD tests
- [ ] 02-02-PLAN.md — Capture REST endpoints + lifespan wiring + hardware verification

---

### Phase 3: Entertainment API Streaming Integration
**Goal**: Connect the capture pipeline output to the DTLS streaming session and deliver measurable end-to-end color synchronization under 100ms.
**Depends on**: Phase 1, Phase 2
**Requirements**: CAPT-03, CAPT-04, STRM-01, STRM-02, STRM-03, STRM-04, STRM-05, STRM-06, GRAD-05
**Estimated scope**: L

**Delivers:**
- HueStream v2 binary packet builder: XY color space, all channels in one UDP packet, version bytes `0x02 0x00`
- 50 Hz asyncio send loop with sequence number increment and keep-alive (resend if silent >9.5s)
- Entertainment configuration activation/deactivation lifecycle: `PUT /entertainment_configuration/{id}` before DTLS open, deactivate on shutdown
- Per-channel region-to-segment mapping read from config at loop start
- Capture loop start/stop via REST endpoints (`POST /api/capture/start`, `POST /api/capture/stop`), controlled by `asyncio.Event`
- Capture and stream stop cleanly: device released, DTLS session closed, entertainment mode deactivated
- `/ws/status` WebSocket emitting JSON: FPS, latency, bridge connection state, error messages
- Support for 16+ simultaneous channels in a single packet
- Non-gradient lights sent as single-channel targets (GRAD-05)

**Success Criteria** (what must be TRUE):
  1. Pressing "Start" in the UI causes real Hue lights to update color within 100ms of the capture card frame (measurable via `/ws/status` latency field)
  2. Pressing "Stop" causes lights to return to their pre-streaming state and the capture card device is fully released (re-openable immediately)
  3. A single UDP packet per frame drives all configured channels simultaneously at 25-50 Hz
  4. `/ws/status` shows FPS in the 25-50 range and latency under 100ms during normal operation
  5. The system supports a configuration with 16 channels without packet fragmentation or missed updates

**Risks:**
- Entertainment mode must be activated via REST before the DTLS socket opens — bridge silently rejects otherwise; add health-check logic to re-activate on reconnect
- `hue-entertainment-pykit` session recovery after bridge reboot is underdocumented — build a manual test harness for drop/reconnect during this phase

**Plans**: TBD

---

### Phase 4: Frontend Canvas Editor
**Goal**: Deliver a fully interactive web UI where users can draw polygon regions on a live camera preview and assign each region to a Hue light or gradient segment.
**Depends on**: Phase 1, Phase 3
**Requirements**: REGN-01, REGN-02, REGN-03, REGN-04, REGN-05, REGN-06, UI-01, UI-03, UI-04, UI-05, UI-06
**Estimated scope**: L

**Delivers:**
- Vite + React 19 + TypeScript scaffold with Zustand state and shadcn/ui + Tailwind CSS v4
- Konva.js canvas: layer 0 live JPEG preview (WebSocket at 10-15 fps), layer 1 semi-transparent region polygons with sampled color overlay, layer 2 selection handles
- Polygon draw tool: click to place vertices, click first vertex to close, drag anchors to edit, drag region to move, delete button to remove
- Region coordinates stored and transmitted as normalized [0..1] values
- Light discovery panel populated from `GET /api/hue/lights` showing light name, type, and segment count
- Region-to-channel assignment via click-to-assign interaction in the panel
- Global start/stop toggle wired to `POST /api/capture/start` / `POST /api/capture/stop`
- Real-time status bar consuming `/ws/status`: FPS, latency, bridge state, error messages
- Config auto-saved to backend on every region/assignment change (persists across restarts)
- Web UI accessible without authentication on the local network

**Success Criteria** (what must be TRUE):
  1. User can draw a freeform polygon on the canvas, assign it to a light, and see the light's color update in real time without any page reload
  2. The camera preview updates live at ≥10 fps in the browser while streaming is active
  3. Region shapes and light assignments survive a full `docker compose restart`
  4. The status bar shows current FPS, latency, and bridge connection state updated at least once per second
  5. The light panel lists all lights discovered from the bridge with correct names, types, and segment counts

**Risks:**
- react-konva polygon editing (vertex drag + region drag simultaneously) requires careful hit-area management — prototype the interaction model early in the phase

**Plans**: TBD

---

### Phase 5: Gradient Device Support and Polish
**Goal**: Deliver full per-segment independent control of gradient-capable devices (Festavia, Flux, Play Gradient Lightstrip) and enforce the 20-channel limit.
**Depends on**: Phase 3, Phase 4
**Requirements**: BRDG-04, GRAD-01, GRAD-02, GRAD-03, GRAD-04
**Estimated scope**: M

**Delivers:**
- Gradient device detection at discovery time: read `gradient.pixel_count` and `points_capable` from CLIP v2 to determine channel count
- Entertainment configuration channel enumeration: channel_id → segment index → light service mapping
- Per-segment region assignment in UI: a 7-segment gradient strip appears as 7 individually assignable rows in the light panel
- Festavia segment handling: empirically verify channel count with physical device; document actual count in code
- Flux lightstrip segment handling: treat as Play Gradient Lightstrip (7 channels) by analogy until empirically confirmed
- 20-channel limit validation: count total assigned channels on save; show warning banner in UI when at or above limit
- Error recovery: capture card disconnect retry with exponential backoff; bridge UDP failure detection and reconnect

**Success Criteria** (what must be TRUE):
  1. Each segment of a Festavia or Flux strip can be independently assigned to a different screen region and shows a distinct color matching that region
  2. Assigning more than 20 total channels displays a visible warning in the UI identifying which configuration exceeds the limit
  3. The gradient device's segment count shown in the light panel matches the actual channel count observed in the entertainment configuration
  4. Unplugging and replugging the capture card causes the capture loop to reconnect automatically without manual intervention

**Risks:**
- Festavia actual channel count is underdocumented (~5-7 inferred, not official) — must validate with physical device before finalizing the segment mapping UI; do not ship this phase without hardware confirmation
- Flux Lightstrip released Sept 2025 with limited developer docs — treat as Play Gradient Lightstrip until confirmed otherwise

**Plans**: TBD

---

### Phase 6: Hardening and Deployment
**Goal**: Produce a production-quality Docker deployment that a user can install with a single `docker compose up` and rely on for daily use.
**Depends on**: Phase 5
**Requirements**: INFR-04
**Estimated scope**: S

**Delivers:**
- Multi-stage Docker builds: Python 3.12-slim backend with only runtime deps; node:20-alpine build stage + nginx:alpine runtime for frontend
- `docker-compose.yaml` with: healthcheck directives, `restart: unless-stopped` policies, named volume for SQLite database
- nginx config: static asset caching, WebSocket upgrade headers, `proxy_pass http://127.0.0.1:8000` for host-network backend
- `/health` (liveness) and `/health/ready` (readiness: bridge paired + capture device present) endpoints
- Structured logging via Python `logging` module with `LOG_LEVEL` environment variable
- udev rule example for stable `/dev/videoN` assignment (documented in README or inline comment)

**Success Criteria** (what must be TRUE):
  1. `docker compose up -d` on a clean machine with the capture card plugged in results in a fully functional system reachable at `http://localhost` within 60 seconds
  2. `GET /health/ready` returns HTTP 200 only when the bridge is paired and the capture device is accessible
  3. A container restart triggered by `docker compose restart` recovers to operational state automatically without user intervention
  4. The Docker image builds successfully from scratch in under 5 minutes on a standard developer machine

**Risks:**
- Python 3.12 pin is a hard constraint from `hue-entertainment-pykit` mbedTLS bindings — do not upgrade base image; document this explicitly in the Dockerfile

**Plans**: TBD

---

## Critical Path

```
[Phase 1: DTLS spike + Docker]  <-- GATE: must pass before anything else
    |
    +---> [Phase 2: Capture pipeline]  ---> [Phase 3: End-to-end streaming]
    |                                                   |
    +---> [Phase 4: Frontend editor]  ---------------> [Phase 5: Gradient + polish]
                                                                |
                                                       [Phase 6: Hardening]
```

Phases 2 and 4 are parallel-safe after Phase 1.
Phase 3 requires Phase 1 (DTLS) and Phase 2 (capture output).
Phase 5 requires Phase 3 (streaming working) and Phase 4 (UI can display segments).
Phase 6 follows Phase 5.

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Streaming transport | Entertainment API (DTLS/UDP port 2100) | REST API (~10 req/s) cannot drive 16+ channels at <100ms; Entertainment API sends all channels in one UDP packet at 50 Hz |
| DTLS library | `hue-entertainment-pykit` (wraps mbedTLS) | Python `ssl` module is TLS-over-TCP only; bridge requires DTLS 1.2 with `TLS_PSK_WITH_AES_128_GCM_SHA256`; no stdlib solution exists |
| Python version | 3.12 (pinned) | `hue-entertainment-pykit` mbedTLS bindings do not support Python 3.13+ |
| Backend framework | FastAPI + Uvicorn + asyncio | Native asyncio event loop shares capture loop, WebSocket push, and REST handling in one thread |
| Capture | OpenCV headless, 640x480 MJPEG, V4L2 backend | Sufficient resolution for color analysis; headless avoids GUI deps in Docker |
| Color extraction | Pre-computed polygon masks + `cv2.mean()` | Zero per-frame mask overhead; masks recomputed only on region change |
| Color conversion | RGB → CIE xy with Gamut C clamping | Required by Entertainment API; Gamut C is the widest gamut supported by Hue lights |
| Frontend | React 19 + Konva.js + Zustand + Vite | Largest canvas annotation ecosystem; Konva handles scene graph + Transformer natively |
| Live preview | WebSocket binary JPEG at 10-15 fps | Adequate for a config UI; WebRTC adds STUN/TURN complexity with no user-visible benefit |
| Config persistence | SQLite via aiosqlite | Single-file DB, async writes, no separate DB service needed |
| Docker networking | Backend: host network; Frontend: bridge + nginx | Host network required for DTLS/UDP and mDNS; nginx proxies `/api/` and `/ws` to `127.0.0.1:8000` |

## Coverage

| Requirement | Phase | Status |
|-------------|-------|--------|
| BRDG-01 | Phase 1 | Pending |
| BRDG-02 | Phase 1 | Pending |
| BRDG-03 | Phase 1 | Pending |
| BRDG-04 | Phase 5 | Pending |
| BRDG-05 | Phase 1 | Pending |
| CAPT-01 | Phase 2 | Pending |
| CAPT-02 | Phase 2 | Pending |
| CAPT-03 | Phase 3 | Pending |
| CAPT-04 | Phase 3 | Pending |
| CAPT-05 | Phase 2 | Pending |
| REGN-01 | Phase 4 | Pending |
| REGN-02 | Phase 4 | Pending |
| REGN-03 | Phase 4 | Pending |
| REGN-04 | Phase 4 | Pending |
| REGN-05 | Phase 4 | Pending |
| REGN-06 | Phase 4 | Pending |
| STRM-01 | Phase 3 | Pending |
| STRM-02 | Phase 3 | Pending |
| STRM-03 | Phase 3 | Pending |
| STRM-04 | Phase 3 | Pending |
| STRM-05 | Phase 3 | Pending |
| STRM-06 | Phase 3 | Pending |
| GRAD-01 | Phase 5 | Pending |
| GRAD-02 | Phase 5 | Pending |
| GRAD-03 | Phase 5 | Pending |
| GRAD-04 | Phase 5 | Pending |
| GRAD-05 | Phase 3 | Pending |
| UI-01 | Phase 4 | Pending |
| UI-02 | Phase 1 | Pending |
| UI-03 | Phase 4 | Pending |
| UI-04 | Phase 4 | Pending |
| UI-05 | Phase 4 | Pending |
| UI-06 | Phase 4 | Pending |
| INFR-01 | Phase 1 | Pending |
| INFR-02 | Phase 1 | Pending |
| INFR-03 | Phase 1 | Pending |
| INFR-04 | Phase 6 | Pending |
| INFR-05 | Phase 1 | Pending |

**Coverage: 38/38 v1 requirements mapped. No orphans.**

Note: REQUIREMENTS.md header states "36 total" — the actual count of listed requirements is 38 (5 BRDG + 5 CAPT + 6 REGN + 6 STRM + 5 GRAD + 6 UI + 5 INFR). All 38 are mapped.

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure and DTLS Spike | 3/4 | In Progress|  |
| 2. Capture Pipeline and Color Extraction | 0/2 | Planned | - |
| 3. Entertainment API Streaming Integration | 0/TBD | Not started | - |
| 4. Frontend Canvas Editor | 0/TBD | Not started | - |
| 5. Gradient Device Support and Polish | 0/TBD | Not started | - |
| 6. Hardening and Deployment | 0/TBD | Not started | - |

---
*Roadmap created: 2026-03-23*
