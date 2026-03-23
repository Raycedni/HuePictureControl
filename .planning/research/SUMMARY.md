# Project Research Summary

**Project:** HuePictureControl
**Domain:** Real-time ambient lighting — HDMI capture → per-segment Hue light control
**Researched:** 2026-03-23
**Confidence:** MEDIUM-HIGH

## Executive Summary

HuePictureControl is a local-network ambient lighting system that captures HDMI video via a USB UVC capture card, extracts per-region color averages from the frame, and drives Philips Hue lights in real time. The correct expert implementation uses two entirely separate Hue API surfaces: the CLIP v2 REST API (HTTPS) for configuration and device discovery, and the Entertainment API (DTLS/UDP on port 2100) for real-time color streaming. REST alone is architecturally insufficient — at 20 requests/second, driving 16+ gradient channels would take ~800ms per update cycle. The Entertainment API sends all channels in a single UDP packet at 50 Hz, achieving ~10ms network latency. This distinction is the single most important architectural decision in the project.

The recommended stack is Python 3.12 + FastAPI + asyncio on the backend, with OpenCV (headless) for UVC capture at 640x480 MJPEG and pre-computed polygon masks for zero-overhead per-frame region extraction. The frontend is React + Konva.js + Zustand + Vite, serving a canvas-based region editor with live camera preview via WebSocket JPEG frames. Docker Compose runs two containers: the backend on host networking (required for DTLS/UDP and mDNS) and the frontend on bridge networking behind nginx. Config is persisted to SQLite via aiosqlite.

The critical risks are concentrated in two areas. First, the DTLS transport layer: Python's standard `ssl` module has no DTLS support, and the Hue bridge accepts only one specific cipher suite (`TLS_PSK_WITH_AES_128_GCM_SHA256`). This must be solved with `hue-entertainment-pykit` (which wraps mbedTLS), and it must be proven working before any other streaming work begins — it is the single highest-risk item in the project. Second, the 20-channel hard limit of the Entertainment API: two 7-segment gradient strips plus a Festavia (~5-7 channels) can reach or exceed 20 total channels, requiring careful entertainment configuration design.

## Key Findings

### Recommended Stack

The backend is Python 3.12 (pinned — `hue-entertainment-pykit` does not support 3.13+) with FastAPI + Uvicorn. FastAPI's native asyncio event loop allows the capture loop, WebSocket frame push, and REST request handling to share a single thread without locks. The capture loop runs as an `asyncio.Task` (not a `BackgroundTask`, which cannot be cancelled) and is toggled via REST endpoints. OpenCV is used as `opencv-python-headless` to avoid GUI dependencies in Docker. SQLite via `aiosqlite` stores bridge credentials, region polygons, and light assignments.

The frontend is React 19 + TypeScript + Vite. Konva.js with `react-konva` handles the interactive canvas: layer 0 shows the live JPEG preview, layer 1 overlays semi-transparent region polygons with sampled colors, layer 2 renders selection handles. Zustand manages the region/light/mapping state. shadcn/ui + Tailwind CSS v4 provides the light-assignment panel.

**Core technologies:**
- Python 3.12: Runtime — pinned due to `hue-entertainment-pykit` mbedTLS constraint
- FastAPI + Uvicorn: Backend framework — native asyncio, WebSocket, Pydantic validation
- OpenCV (headless): Frame capture + region extraction — V4L2 backend, pre-computed masks, `cv2.mean()`
- `hue-entertainment-pykit`: DTLS transport — only viable Python solution for PSK DTLS 1.2
- aiosqlite: Config persistence — async SQLite, atomic writes, schema evolution
- React 19 + TypeScript: Frontend — largest canvas annotation ecosystem
- Konva.js + react-konva: Canvas engine — scene graph, polygon draw, image underlay, Transformer
- Zustand: Frontend state — region/light/mapping graph, minimal boilerplate
- Vite 6: Build tool — instant HMR, esbuild TS compilation
- nginx: Frontend serving + API proxy — static asset caching, WebSocket upgrade

### Expected Features

The research files did not include a dedicated FEATURES.md. Features are inferred from the architecture and hue-api research. This section consolidates them.

**Must have (table stakes):**
- HDMI capture via USB UVC device with configurable device path
- Live preview of capture feed in browser (WebSocket JPEG, 10-15 fps)
- Interactive polygon region drawing on the preview canvas
- Per-region assignment to Hue light channels (including gradient segments)
- Real-time color streaming via Entertainment API at 25-50 Hz
- Bridge pairing flow (link button → application key + client key storage)
- Capture loop start/stop control via UI
- Persistence of regions, light assignments, and bridge credentials

**Should have (differentiators):**
- Per-segment independent control of gradient devices (Festavia, Flux, Play Gradient Lightstrip)
- Semi-transparent color overlay on regions showing live sampled color
- Entertainment configuration discovery and selection (not just manual UUID entry)
- Status WebSocket showing FPS, latency, bridge state, and errors
- Graceful recovery from capture card disconnect and bridge TCP/UDP failures
- udev rule guidance for stable `/dev/videoN` assignment

**Defer to v2+:**
- Entertainment configuration creation via API (use Hue app for initial setup)
- K-means dominant color extraction (mean color is sufficient for ambient use)
- WebRTC for sub-50ms preview (WebSocket JPEG is adequate for a config UI)
- Multi-user session support (single-user local tool)
- 4K capture (640x480 MJPEG is sufficient; 6.7x more work for no perceptual gain)

### Architecture Approach

The backend is a single FastAPI process on the asyncio event loop. The capture loop runs as a managed `asyncio.Task` and drives both the DTLS Entertainment API stream and the WebSocket preview push. REST endpoints handle configuration CRUD and loop control. All shared state (task handle, WebSocket client registry, current config) lives in `app.state`. The frontend is a separate nginx container that reverse-proxies `/api/` and `/ws` to the backend. The backend container uses `network_mode: host` so DTLS/UDP and mDNS function correctly on the LAN.

**Major components:**
1. Capture loop (asyncio Task) — reads frames from `/dev/video0`, extracts region colors, sends DTLS stream, pushes preview JPEG to WebSocket clients
2. CLIP v2 REST client — bridge discovery, device enumeration, entertainment config activation (plain HTTPS with `verify=False` for local use)
3. Entertainment API streamer — DTLS session via `hue-entertainment-pykit`, binary HueStream v2 packet builder, 50 Hz send loop with keep-alive
4. FastAPI REST layer — config CRUD, capture control, snapshot endpoint, health checks
5. WebSocket layer — `/ws/preview` (binary JPEG) and `/ws/status` (JSON) channels
6. SQLite config store — bridge credentials, region polygons, light assignments via aiosqlite
7. React frontend — Konva.js canvas editor, Zustand state, WebSocket consumers, shadcn/ui panel

### Critical Pitfalls

1. **DTLS transport has no stdlib solution** — Python's `ssl` module is TLS-over-TCP only. The Hue bridge requires DTLS 1.2 with `TLS_PSK_WITH_AES_128_GCM_SHA256`. Use `hue-entertainment-pykit` for the transport layer. Spike and verify DTLS connectivity before building anything else. This is the single highest-risk item.

2. **Entertainment mode must be activated before DTLS** — calling `PUT /entertainment_configuration/{id}` with `{"action": "start"}` is mandatory before opening the DTLS socket. The bridge silently rejects connections otherwise. Add health-check logic to re-activate if the connection drops.

3. **20-channel hard limit** — entertainment configurations cap at 20 total channels. A Play Gradient Lightstrip (7 channels) + Flux (7 channels) + Festavia (~5-7 channels) = 19-21 channels. Plan entertainment zones carefully; consider separate zones per device group.

4. **OpenCV blocking on `cap.read()`** — `VideoCapture.read()` is a blocking C call. At 25 fps it blocks for ~40ms, which can starve the asyncio event loop and delay REST/WebSocket responses. Use `asyncio.get_event_loop().run_in_executor(None, cap.read)` if starvation is observed in testing.

5. **`clientkey` is unrecoverable** — the DTLS PSK (`clientkey`) is returned once during bridge pairing and cannot be re-fetched. Store it immediately on first receipt. A lost `clientkey` requires pressing the physical link button again and re-pairing.

6. **nginx `proxy_pass` with host-network backend** — when the backend uses `network_mode: host`, it is not reachable by Docker service name from the frontend container. nginx must proxy to `127.0.0.1:8000` (same host) or an explicit LAN IP, not `http://backend:8000`. This must be verified before the first integration test.

7. **Festavia channel count is underdocumented** — the Festavia exposes ~5-7 entertainment channels (not 250 individual LEDs). This is confirmed via Home Assistant source and community research but not official Philips docs. Design region mappings for the actual channel count and verify empirically with the physical device.

8. **V1 Entertainment API ignores gradient segments** — the v1 API sends a single channel per gradient strip regardless of segment count. Only the v2 Entertainment API exposes per-segment channels. Verify the HueStream packet header specifies API version 2.0 (bytes: `0x02 0x00`).

## Implications for Roadmap

Based on the research, this project has a clear dependency chain. The DTLS transport is a prerequisite for all streaming work. The capture pipeline is independent and can be developed in parallel but cannot be end-to-end tested without the bridge. The frontend editor is fully independent of the streaming stack. This suggests a spike-first, then parallel-track structure.

### Phase 1: Infrastructure and DTLS Spike

**Rationale:** The DTLS transport is the highest-risk technical unknown. It must be proven working before committing to an architecture around it. This phase also establishes the Docker environment, device passthrough, and bridge pairing flow that everything else depends on.

**Delivers:**
- Working Docker Compose with host-network backend and bridge-network frontend
- USB device passthrough verified with the actual capture card
- Bridge pairing endpoint (link button → application key + client key)
- DTLS connection established to bridge using `hue-entertainment-pykit`
- Single Entertainment API packet sent and acknowledged (one light changes color)
- SQLite schema created with aiosqlite

**Must avoid:** Skipping the DTLS spike and designing the streaming architecture assuming it works.

**Research flag:** Needs dedicated spike. Do not proceed to Phase 2 until a real DTLS session is confirmed with the physical bridge.

### Phase 2: Capture Pipeline and Color Extraction

**Rationale:** Once the infrastructure is proven, build the frame capture and color analysis pipeline in isolation. This can be tested without the Hue bridge by logging extracted colors or displaying them in a debug endpoint.

**Delivers:**
- `LatestFrameCapture` threaded capture class at 640x480 MJPEG
- Pre-computed polygon mask infrastructure
- `cv2.mean()` region extraction with configurable polygon coordinates
- RGB to CIE xy gamut-clamped conversion (Gamut C)
- asyncio task wrapper with `run_in_executor` for the blocking `cap.read()` call
- Snapshot REST endpoint (`GET /api/capture/snapshot`) returning a JPEG

**Uses:** OpenCV headless, numpy, rgbxy (or inline conversion)

**Research flag:** Standard pattern, well-documented. No additional research phase needed. Do verify `run_in_executor` behavior empirically.

### Phase 3: Entertainment API Streaming Integration

**Rationale:** Connect the capture pipeline output to the DTLS streaming session. This is where the full latency budget becomes measurable end-to-end.

**Delivers:**
- HueStream v2 packet builder (binary, XY color space, all channels in one UDP packet)
- 50 Hz asyncio send loop with sequence number increment and keep-alive (resend if silent >9.5s)
- Entertainment configuration activation/deactivation lifecycle (start before DTLS, stop on shutdown)
- Per-channel region-to-segment mapping from config
- Capture loop start/stop via REST, stop event via `asyncio.Event`
- `/ws/status` WebSocket with FPS, latency, bridge connection state

**Must avoid:** Sending at 25 Hz only; sending at 50 Hz gives 2x UDP redundancy against packet loss.

**Research flag:** Standard pattern once DTLS is working. The packet format is fully documented in hue-api.md (Section 7.4). No additional research phase needed.

### Phase 4: Frontend Canvas Editor

**Rationale:** The frontend is independent of the streaming stack and can be built in parallel with Phases 2-3. It is sequenced here because the backend REST and WebSocket APIs must exist for end-to-end integration.

**Delivers:**
- Vite + React + TypeScript scaffold
- Konva.js canvas with two layers: JPEG preview (WebSocket) and region polygon overlay
- Interactive polygon draw tool: click to place vertices, close polygon, drag anchors to edit
- Light discovery panel populated from `GET /api/hue/lights`
- Region-to-channel assignment via click-to-assign interaction
- Semi-transparent color overlay on regions updated at ~5 Hz from status WebSocket
- Zustand store for Region, Light, Mapping state
- REST calls to save/load config

**Research flag:** Well-documented. react-konva polygon annotation patterns are abundant. No research phase needed.

### Phase 5: Gradient Device Support and Polish

**Rationale:** Per-segment gradient control (the core differentiator) is built after the base streaming pipeline is working. Gradient devices add complexity in entertainment configuration channel mapping and UI (segments need individual region assignments).

**Delivers:**
- Gradient device detection at discovery time (read `gradient.pixel_count` and `points_capable` from CLIP v2)
- Entertainment configuration channel enumeration (channel_id → segment index → light service)
- Per-segment region assignment in UI (a gradient strip's 7 segments appear as 7 assignable channels)
- Festavia `random_pixelated` mode configuration
- 20-channel limit validation with warning in UI
- Error recovery: capture card disconnect retry, bridge UDP failure with exponential backoff

**Research flag:** The Festavia channel count and behavior needs empirical verification with the physical device. Plan a validation sprint with the actual hardware before finalizing the segment mapping UI.

### Phase 6: Hardening and Deployment

**Rationale:** Production-quality error handling, logging, and deployment automation.

**Delivers:**
- Structured logging with configurable `LOG_LEVEL`
- `/health` (liveness) and `/health/ready` (readiness) endpoints
- udev rule documentation for stable `/dev/videoN` assignment
- Multi-stage Docker builds (Python 3.12-slim + runtime deps; node:20-alpine + nginx:alpine)
- docker-compose.yaml with healthcheck, restart policies, and volume for SQLite
- nginx config with correct WebSocket upgrade headers and host-network proxy_pass

**Research flag:** Well-documented patterns. No additional research phase needed.

### Phase Ordering Rationale

- Phase 1 (DTLS spike) must come first — it is the only true blocker. Every other phase depends on knowing the transport layer works.
- Phases 2 and 4 are parallel-safe after Phase 1. The capture pipeline (Phase 2) and frontend (Phase 4) have no dependency on each other.
- Phase 3 requires both Phase 1 (DTLS) and Phase 2 (capture pipeline).
- Phase 5 requires Phase 3 (streaming working) and Phase 4 (UI can display segments).
- Phase 6 is a hardening pass and can begin incrementally during Phase 4/5.

### Cross-Cutting Risks

These risks span multiple phases and must be tracked throughout:

- **20-channel limit:** Drives entertainment zone design decisions in Phase 1 and segment UI decisions in Phase 5. Count channels before designing any entertainment configuration.
- **DTLS session stability:** `hue-entertainment-pykit` is a community library. Session re-establishment after bridge reboot must be tested in Phase 3 and exercised in Phase 6 error recovery.
- **nginx + host-network proxy:** The `proxy_pass http://127.0.0.1:8000` configuration must be verified during Phase 1 Docker setup. If it fails, the fallback is sharing the host network for both containers.
- **Python 3.12 pin:** The entire Docker image must be pinned to Python 3.12. Upgrading Python later is a breaking change until `hue-entertainment-pykit` updates its mbedTLS bindings.

### Critical Path

```
[Phase 1: DTLS spike + Docker]
    |
    +---> [Phase 2: Capture pipeline] ---> [Phase 3: End-to-end streaming]
    |                                                   |
    +---> [Phase 4: Frontend editor]  ---------------> [Phase 5: Gradient + polish]
                                                                |
                                                       [Phase 6: Hardening]
```

The DTLS verification in Phase 1 is the single gate. Once it passes, Phases 2 and 4 can run concurrently.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Backend stack (FastAPI, asyncio pattern) | HIGH | FastAPI official docs verified; asyncio task pattern confirmed via GitHub discussions |
| Capture pipeline (OpenCV, V4L2, masks) | HIGH | Matches HarmonizeProject and multiple ambilight reference implementations |
| Entertainment API protocol (packet format) | HIGH | Binary format documented in IoTech blog, verified against aiohue source and HyperHDR |
| DTLS transport (`hue-entertainment-pykit`) | MEDIUM | Library works per community reports; session recovery behavior not fully documented |
| Gradient device channel counts | MEDIUM | Play Gradient (7) confirmed; Festavia (~5-7) inferred from Home Assistant source, not official docs |
| Flux Lightstrip specifics | MEDIUM | Product released Sept 2025; limited developer documentation; assume 7 channels like Play Gradient |
| Frontend (React, Konva, Zustand) | HIGH | Well-documented stack; react-konva polygon annotation patterns are abundant |
| Docker networking (host + bridge split) | MEDIUM | Host network recommendation is established practice; DTLS-through-NAT behavior less verified |
| nginx + host-network proxy_pass | MEDIUM | Known nuance; requires empirical verification before integration |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Festavia entertainment channel count:** Must verify empirically with physical device. Research is based on Home Assistant source code, not official Philips documentation. Do not finalize the segment mapping UI until tested.
- **DTLS session recovery:** `hue-entertainment-pykit` session re-establishment after bridge reboot is not documented. Build a test harness for this in Phase 3 and add to error recovery work in Phase 6.
- **nginx proxy_pass with host-network backend:** The exact configuration (`proxy_pass http://127.0.0.1:8000` vs host LAN IP) must be verified during Phase 1 Docker setup. Document the working configuration for deployment.
- **Entertainment configuration creation via API:** Research indicates it is possible but recommends using the Hue app for initial setup. If the API path is required (e.g., for automated provisioning), it needs a dedicated research spike.
- **OpenCV `cap.read()` blocking duration:** The 40ms blocking estimate is theoretical. Measure empirically at 640x480 MJPEG on the actual deployment hardware to determine if `run_in_executor` is required.

## Sources

### Primary (HIGH confidence)
- [IoTech Blog — Entertainment API](https://iotech.blog/posts/philips-hue-entertainment-api/) — binary packet format, DTLS flow
- [aiohue source code](https://github.com/home-assistant-libs/aiohue) — v2 data models, entertainment channel structure
- [hue-python-rgb-converter](https://github.com/benknight/hue-python-rgb-converter) — RGB to xy gamut conversion
- [Philips Hue SDK RGB to xy notes](https://github.com/johnciech/PhilipsHueSDK) — color conversion algorithm
- [HyperHDR discussions](https://github.com/awawa-dev/HyperHDR/discussions/512) — real-world segment count confirmation
- [FastAPI official docs](https://fastapi.tiangolo.com/) — WebSocket, lifespan, BackgroundTasks limitations
- [openHAB v2 binding docs](https://www.openhab.org/addons/bindings/hue/) — rate limits, SSE behavior
- [openhue-api OpenAPI spec](https://github.com/openhue/openhue-api) — resource type enumeration
- [HarmonizeProject](https://github.com/MCPCapital/HarmonizeProject) — Python OpenCV ambilight reference

### Secondary (MEDIUM confidence)
- [hue-entertainment-pykit](https://github.com/hrdasdominik/hue-entertainment-pykit) — DTLS transport solution; community library, not Philips-official
- [Home Assistant Issue #82264](https://github.com/home-assistant/core/issues/82264) — Festavia effects and channel structure
- [HueBlog — Flux Lightstrip](https://hueblog.com/2025/09/16/hue-flux-lightstrip-new-light-strip-now-available/) — Flux product details (Sept 2025, limited dev docs)
- [HueBlog — Segmented mode](https://hueblog.com/2026/01/03/segmented-new-mode-for-philips-hue-gradient-products/) — Flux segmented mode
- [Philips Hue Developer Program](https://developers.meethue.com/new-hue-api/) — login-gated; general overview only

### Tertiary (LOW confidence)
- Festavia channel count (~5-7): inferred from aiohue model and Home Assistant source; needs empirical hardware validation
- Flux segment independence in Entertainment API: inferred by analogy to Play Gradient Lightstrip; not directly documented

---
*Research completed: 2026-03-23*
*Ready for roadmap: yes*
