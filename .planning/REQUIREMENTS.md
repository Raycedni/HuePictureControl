# Requirements: HuePictureControl

**Defined:** 2026-03-23
**Core Value:** Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.

## v1.0 Requirements (Validated)

### Bridge Integration

- [x] **BRDG-01**: User can pair with Hue Bridge via link button press from the web UI
- [x] **BRDG-02**: Bridge credentials (application key + client key) are persisted and survive restarts
- [x] **BRDG-03**: Application discovers all lights, rooms, and entertainment configurations from the bridge
- [x] **BRDG-04**: Gradient-capable devices (Festavia, Flux, Play Gradient) are identified with their per-segment channel count
- [x] **BRDG-05**: Entertainment configuration can be selected from the UI (lists available configs from bridge)

### Frame Capture

- [x] **CAPT-01**: Backend captures frames from a USB UVC device (HDMI capture card) at 640x480 MJPEG
- [x] **CAPT-02**: Capture device path is configurable (e.g. `/dev/video0`)
- [x] **CAPT-03**: Capture loop runs only when explicitly enabled via the UI toggle
- [x] **CAPT-04**: Capture loop stops cleanly when disabled (releases device, closes connections)
- [x] **CAPT-05**: A snapshot of the current camera frame is available via REST endpoint

### Region Mapping

- [x] **REGN-01**: User can draw freeform polygon regions on a camera snapshot in the web UI
- [x] **REGN-02**: User can edit existing regions (move vertices, drag region, delete)
- [x] **REGN-03**: User can assign each region to a Hue light or gradient segment channel
- [x] **REGN-04**: Region coordinates are stored as normalized [0..1] values (resolution-independent)
- [x] **REGN-05**: Region-to-light mappings persist across restarts

### Color Processing

- [x] **COLR-01**: Dominant color is extracted from each mapped region per frame
- [x] **COLR-02**: RGB values are converted to CIE xy color space for Hue compatibility
- [x] **COLR-03**: Color extraction runs at ≥25 fps to match Entertainment API rate

### Streaming

- [x] **STRM-01**: Backend connects to Hue Bridge Entertainment API via DTLS/UDP
- [x] **STRM-02**: Extracted colors are streamed to assigned lights at ≥25 Hz
- [x] **STRM-03**: Streaming session is tied to one entertainment configuration
- [x] **STRM-04**: User can start/stop streaming from the web UI
- [x] **STRM-05**: End-to-end latency from frame capture to light update is under 100ms

### Frontend

- [x] **FRNT-01**: Web UI with canvas editor for drawing/editing regions
- [x] **FRNT-02**: Live camera preview via WebSocket stream
- [x] **FRNT-03**: Status bar showing streaming metrics (FPS, latency, active lights)
- [x] **FRNT-04**: Drag-and-drop light/segment assignment onto regions

### Infrastructure

- [x] **INFR-01**: Backend and frontend run as separate Docker Compose services
- [x] **INFR-02**: USB capture device passed through to backend container
- [x] **INFR-03**: Backend uses host network for DTLS/UDP and mDNS access

## v1.1 Requirements

### Device Enumeration

- [ ] **DEVC-01**: Backend enumerates all V4L2 video capture devices, filtering out metadata nodes via VIDIOC_QUERYCAP capability check
- [ ] **DEVC-02**: API endpoint (`GET /api/cameras`) returns list of available cameras with device path and human-readable name
- [ ] **DEVC-03**: Device list refreshes on demand when user opens camera selector (re-scans /dev/video*)
- [ ] **DEVC-04**: Devices are identified by stable identity (sysfs VID/PID/serial) to survive USB re-plug path changes
- [ ] **DEVC-05**: User can trigger a manual reconnect for a disconnected camera device

### Camera Assignment

- [ ] **CAMA-01**: Camera is assigned per entertainment config (zone), not per-region — all regions in a zone share one camera
- [ ] **CAMA-02**: Camera-to-entertainment-config mapping is persisted in the database and survives restarts
- [ ] **CAMA-03**: When no camera is explicitly assigned, the system falls back to the default capture device
- [ ] **CAMA-04**: UI shows camera health status (connected/disconnected) per entertainment zone

### Multi-Camera Capture

- [ ] **MCAP-01**: StreamingService uses the assigned camera for each entertainment config instead of a global singleton
- [ ] **MCAP-02**: Preview WebSocket serves frames from the zone's assigned camera, not a global device
- [ ] **MCAP-03**: Multiple entertainment zones can stream simultaneously from different cameras

### Camera UI

- [ ] **CMUI-01**: Camera dropdown selector per entertainment zone in the editor UI
- [ ] **CMUI-02**: Dropdown shows device name and path for each available camera
- [ ] **CMUI-03**: Live preview updates immediately when camera selection changes

### Docker

- [ ] **DOCK-01**: Docker Compose supports multiple video device passthrough
- [ ] **DOCK-02**: Documentation for adding/configuring multiple capture devices

## Out of Scope

| Feature | Reason |
|---------|--------|
| Per-region camera assignment | Streaming is per entertainment config; per-region adds complexity with no benefit |
| udev hot-plug monitoring | Overkill — manual refresh/reconnect is sufficient |
| Live thumbnails in dropdown | Nice-to-have deferred; adds bandwidth overhead |
| Audio capture | Video/color only — out of project scope |
| Non-V4L2 devices (Windows DirectShow) | Docker deployment targets Linux only |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEVC-01 | — | Pending |
| DEVC-02 | — | Pending |
| DEVC-03 | — | Pending |
| DEVC-04 | — | Pending |
| DEVC-05 | — | Pending |
| CAMA-01 | — | Pending |
| CAMA-02 | — | Pending |
| CAMA-03 | — | Pending |
| CAMA-04 | — | Pending |
| MCAP-01 | — | Pending |
| MCAP-02 | — | Pending |
| MCAP-03 | — | Pending |
| CMUI-01 | — | Pending |
| CMUI-02 | — | Pending |
| CMUI-03 | — | Pending |
| DOCK-01 | — | Pending |
| DOCK-02 | — | Pending |

**Coverage:**
- v1.1 requirements: 17 total
- Mapped to phases: 0
- Unmapped: 17 ⚠️

---
*Requirements defined: 2026-03-23*
*Last updated: 2026-04-03 after milestone v1.1 definition*
