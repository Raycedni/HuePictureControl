# Requirements: HuePictureControl

**Defined:** 2026-03-23
**Core Value:** Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.

## v1 Requirements

### Bridge Integration

- [ ] **BRDG-01**: User can pair with Hue Bridge via link button press from the web UI
- [ ] **BRDG-02**: Bridge credentials (application key + client key) are persisted and survive restarts
- [ ] **BRDG-03**: Application discovers all lights, rooms, and entertainment configurations from the bridge
- [ ] **BRDG-04**: Gradient-capable devices (Festavia, Flux, Play Gradient) are identified with their per-segment channel count
- [ ] **BRDG-05**: Entertainment configuration can be selected from the UI (lists available configs from bridge)

### Frame Capture

- [ ] **CAPT-01**: Backend captures frames from a USB UVC device (HDMI capture card) at 640x480 MJPEG
- [ ] **CAPT-02**: Capture device path is configurable (e.g. `/dev/video0`)
- [ ] **CAPT-03**: Capture loop runs only when explicitly enabled via the UI toggle
- [ ] **CAPT-04**: Capture loop stops cleanly when disabled (releases device, closes connections)
- [ ] **CAPT-05**: A snapshot of the current camera frame is available via REST endpoint

### Region Mapping

- [ ] **REGN-01**: User can draw freeform polygon regions on a camera snapshot in the web UI
- [ ] **REGN-02**: User can edit existing regions (move vertices, drag region, delete)
- [ ] **REGN-03**: User can assign each region to a Hue light or gradient segment channel
- [ ] **REGN-04**: Region coordinates are stored as normalized [0..1] values (resolution-independent)
- [ ] **REGN-05**: Region-to-light mappings persist across restarts
- [ ] **REGN-06**: Live camera preview is available in the web UI via WebSocket for verifying mappings

### Color Streaming

- [ ] **STRM-01**: Dominant color is extracted from each mapped region using pre-computed polygon masks
- [ ] **STRM-02**: RGB colors are converted to CIE xy with Gamut C clamping before sending to bridge
- [ ] **STRM-03**: Colors are streamed to the bridge via Entertainment API (DTLS/UDP) at 25-50 Hz
- [ ] **STRM-04**: All mapped channels are sent in a single HueStream v2 UDP packet per frame
- [ ] **STRM-05**: End-to-end latency from frame capture to light update is under 100ms
- [ ] **STRM-06**: Streaming supports 16+ simultaneous light channels

### Gradient Devices

- [ ] **GRAD-01**: Festavia string light segments are individually assignable to regions
- [ ] **GRAD-02**: Flux lightstrip segments are individually assignable to regions
- [ ] **GRAD-03**: Other gradient devices (Play Gradient Lightstrip) are supported with per-segment control
- [ ] **GRAD-04**: 20-channel Entertainment API limit is enforced with a warning in the UI
- [ ] **GRAD-05**: Non-gradient Hue lights are supported as single-color targets

### Web UI

- [ ] **UI-01**: Web UI is accessible without authentication on the local network
- [ ] **UI-02**: Bridge pairing flow is guided in the UI (instructions + status feedback)
- [ ] **UI-03**: Global start/stop toggle controls the capture and streaming loop
- [ ] **UI-04**: Real-time status display shows FPS, latency, bridge connection state, and errors
- [ ] **UI-05**: Light discovery panel shows all available lights with their type and segment count
- [ ] **UI-06**: Region canvas shows semi-transparent color overlay indicating what each region is "seeing"

### Infrastructure

- [ ] **INFR-01**: Backend and frontend run as separate Docker Compose services
- [ ] **INFR-02**: USB capture card is passed through to the backend container
- [ ] **INFR-03**: Backend uses host networking for DTLS/UDP and mDNS access to Hue Bridge
- [ ] **INFR-04**: Frontend is served via nginx with reverse proxy to backend API and WebSocket
- [ ] **INFR-05**: Configuration persists in SQLite database with volume mount

## v2 Requirements

### Advanced Color

- **COLR-01**: K-means dominant color extraction for multi-color regions
- **COLR-02**: Configurable color saturation boost / brightness scaling per light
- **COLR-03**: Color smoothing / transition interpolation (configurable curve)

### Advanced UI

- **AUI-01**: Preset region layouts (grid, edge sampling templates)
- **AUI-02**: Import/export configuration as JSON
- **AUI-03**: Entertainment configuration creation directly from the app (bypass Hue app)
- **AUI-04**: Per-light color preview widgets showing current output color

### Automation

- **AUTO-01**: Auto-start streaming on Docker container boot (optional)
- **AUTO-02**: Scene profiles (save/load different region+light configurations)

## Out of Scope

| Feature | Reason |
|---------|--------|
| User authentication | Single-user local network tool; adds complexity with no value |
| Non-Hue smart lights | Hue ecosystem only; other protocols (WLED, Z-Wave) are different projects |
| Audio reactivity | Video/color only; audio sync is a separate domain |
| Cloud / remote access | Fully local; Hue Bridge is on LAN only |
| Mobile app | Web UI is sufficient; responsive design covers tablet/phone |
| 4K capture | 640x480 is sufficient for color analysis; 4K is 6.7x more work for no perceptible gain |
| WebRTC preview | WebSocket JPEG is adequate for a config UI; WebRTC adds STUN/TURN complexity |

## Traceability

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

**Coverage:**
- v1 requirements: 38 total
- Mapped to phases: 38
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-23*
*Last updated: 2026-03-23 after initial definition*
