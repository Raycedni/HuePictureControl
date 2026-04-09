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
- [x] **DEVC-02**: API endpoint (`GET /api/cameras`) returns list of available cameras with device path and human-readable name
- [x] **DEVC-03**: Device list refreshes on demand when user opens camera selector (re-scans /dev/video*)
- [ ] **DEVC-04**: Devices are identified by stable identity (sysfs VID/PID/serial) to survive USB re-plug path changes
- [x] **DEVC-05**: User can trigger a manual reconnect for a disconnected camera device

### Camera Assignment

- [ ] **CAMA-01**: Camera is assigned per entertainment config (zone), not per-region — all regions in a zone share one camera
- [ ] **CAMA-02**: Camera-to-entertainment-config mapping is persisted in the database and survives restarts
- [x] **CAMA-03**: When no camera is explicitly assigned, the system falls back to the default capture device
- [x] **CAMA-04**: UI shows camera health status (connected/disconnected) per entertainment zone

### Multi-Camera Capture

- [ ] **MCAP-01**: StreamingService uses the assigned camera for each entertainment config instead of a global singleton
- [x] **MCAP-02**: Preview WebSocket serves frames from the zone's assigned camera, not a global device
- [x] **MCAP-03**: Multiple entertainment zones can stream simultaneously from different cameras

### Camera UI

- [x] **CMUI-01**: Camera dropdown selector per entertainment zone in the editor UI
- [x] **CMUI-02**: Dropdown shows device name and path for each available camera
- [x] **CMUI-03**: Live preview updates immediately when camera selection changes

### Docker

- [ ] **DOCK-01**: Docker Compose supports multiple video device passthrough
- [ ] **DOCK-02**: Documentation for adding/configuring multiple capture devices

## v1.2 Requirements

### Virtual Camera Infrastructure

- [ ] **VCAM-01**: Backend manages v4l2loopback virtual camera devices — creates on demand when a wireless source starts, destroys on stop/shutdown
- [ ] **VCAM-02**: Virtual cameras appear in `GET /api/cameras` alongside physical devices, tagged with `source_type: "wireless"` and the originating protocol
- [ ] **VCAM-03**: All virtual devices and feeding pipelines are cleaned up on service shutdown or container stop

### Miracast Receiver

- [ ] **MIRA-01**: Backend runs a Miracast (WiFi Direct) receiver via MiracleCast that Windows and older Android devices can discover and connect to
- [ ] **MIRA-02**: API endpoint reports WiFi adapter P2P/WiFi Direct capability before user attempts to start Miracast
- [ ] **MIRA-03**: Miracast receiver advertises a configurable display name on the network (default: "HuePictureControl")
- [ ] **MIRA-04**: Connected Miracast H.264 RTP stream is piped to a virtual V4L2 device via FFmpeg in real time

### scrcpy Android Fallback

- [ ] **SCPY-01**: Backend manages ADB wireless connections to Android devices given an IP address
- [ ] **SCPY-02**: scrcpy mirrors an Android device's screen to a virtual V4L2 device via v4l2loopback
- [ ] **SCPY-03**: Starting a scrcpy session requires only the Android device IP — backend handles `adb connect` and scrcpy launch

### Wireless Pipeline

- [ ] **WPIP-01**: FFmpeg subprocesses pipe wireless input streams (Miracast RTP, scrcpy output) to v4l2loopback virtual devices
- [ ] **WPIP-02**: Pipeline health is monitored — stalled or crashed FFmpeg processes are detected and reported via status API
- [ ] **WPIP-03**: Stopping a wireless source kills the FFmpeg pipeline and releases the virtual device within 5 seconds

### Wireless API

- [ ] **WAPI-01**: `GET /api/wireless/capabilities` reports available protocols, NIC status, and installed dependency versions
- [ ] **WAPI-02**: `POST /api/wireless/miracast/start` and `POST /api/wireless/miracast/stop` control the Miracast receiver lifecycle
- [ ] **WAPI-03**: `POST /api/wireless/scrcpy/start` (with `android_ip` body) and `POST /api/wireless/scrcpy/{id}/stop` control scrcpy sessions
- [ ] **WAPI-04**: `GET /api/wireless/sources` lists active wireless input sessions with state, protocol, virtual device path, and connected client info

### Wireless Docker

- [ ] **WDCK-01**: Docker image includes v4l2loopback-dkms, MiracleCast, scrcpy, FFmpeg, ADB, and `iw` utilities
- [ ] **WDCK-02**: Container runs with necessary Linux capabilities (`NET_ADMIN`, `SYS_MODULE`) for WiFi Direct and kernel module loading
- [ ] **WDCK-03**: WiFi adapter is passed through to the container alongside video capture devices

### Wireless Frontend (minimal)

- [ ] **WFNT-01**: Wireless input sources appear in the camera selector alongside physical cameras
- [ ] **WFNT-02**: UI provides controls to start/stop Miracast receiver and scrcpy sessions

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
| BRDG-01 | Phase 1 | Validated |
| BRDG-02 | Phase 1 | Validated |
| BRDG-03 | Phase 1 | Validated |
| BRDG-04 | Phase 5 | Validated |
| BRDG-05 | Phase 1 | Validated |
| CAPT-01 | Phase 2 | Validated |
| CAPT-02 | Phase 2 | Validated |
| CAPT-03 | Phase 3 | Validated |
| CAPT-04 | Phase 3 | Validated |
| CAPT-05 | Phase 2 | Validated |
| REGN-01 | Phase 4 | Validated |
| REGN-02 | Phase 4 | Validated |
| REGN-03 | Phase 4 | Validated |
| REGN-04 | Phase 3.1 | Validated |
| REGN-05 | Phase 3.1 | Validated |
| COLR-01 | Phase 2 | Validated |
| COLR-02 | Phase 2 | Validated |
| COLR-03 | Phase 3 | Validated |
| STRM-01 | Phase 3 | Validated |
| STRM-02 | Phase 3 | Validated |
| STRM-03 | Phase 3 | Validated |
| STRM-04 | Phase 3 | Validated |
| STRM-05 | Phase 3 | Validated |
| FRNT-01 | Phase 4 | Validated |
| FRNT-02 | Phase 4 | Validated |
| FRNT-03 | Phase 3 | Validated |
| FRNT-04 | Phase 4 | Validated |
| INFR-01 | Phase 1 | Validated |
| INFR-02 | Phase 1 | Validated |
| INFR-03 | Phase 1 | Validated |
| DEVC-01 | Phase 7 | Pending |
| DEVC-02 | Phase 7 | Complete |
| DEVC-03 | Phase 7 | Complete |
| DEVC-04 | Phase 7 | Pending |
| DEVC-05 | Phase 7 | Complete |
| CAMA-01 | Phase 7 | Pending |
| CAMA-02 | Phase 7 | Pending |
| CAMA-03 | Phase 7 | Complete |
| CAMA-04 | Phase 9 | Complete |
| MCAP-01 | Phase 8 | Pending |
| MCAP-02 | Phase 9 | Complete |
| MCAP-03 | Phase 8 | Complete |
| CMUI-01 | Phase 10 | Complete |
| CMUI-02 | Phase 10 | Complete |
| CMUI-03 | Phase 10 | Complete |
| DOCK-01 | Phase 11 | Pending |
| DOCK-02 | Phase 11 | Pending |

| VCAM-01 | Phase 12 | Pending |
| VCAM-02 | Phase 12 | Pending |
| VCAM-03 | Phase 12 | Pending |
| MIRA-01 | Phase 13 | Pending |
| MIRA-02 | Phase 13 | Pending |
| MIRA-03 | Phase 13 | Pending |
| MIRA-04 | Phase 13 | Pending |
| SCPY-01 | Phase 14 | Pending |
| SCPY-02 | Phase 14 | Pending |
| SCPY-03 | Phase 14 | Pending |
| WPIP-01 | Phase 12 | Pending |
| WPIP-02 | Phase 12 | Pending |
| WPIP-03 | Phase 12 | Pending |
| WAPI-01 | Phase 12 | Pending |
| WAPI-02 | Phase 13 | Pending |
| WAPI-03 | Phase 14 | Pending |
| WAPI-04 | Phase 12 | Pending |
| WDCK-01 | Phase 15 | Pending |
| WDCK-02 | Phase 15 | Pending |
| WDCK-03 | Phase 15 | Pending |
| WFNT-01 | Phase 14 | Pending |
| WFNT-02 | Phase 14 | Pending |

**Coverage:**
- v1.0 requirements: 30 total — all validated
- v1.1 requirements: 17 total, mapped: 17, unmapped: 0 ✓
- v1.2 requirements: 22 total, mapped: 22, unmapped: 0 ✓

---
*Requirements defined: 2026-03-23*
*Last updated: 2026-04-03 after v1.2 milestone creation*
