# Requirements: HuePictureControl

**Defined:** 2026-04-14
**Core Value:** Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.

## v1.2 Requirements

Requirements for wireless input milestone. Each maps to roadmap phases.

### Virtual Camera Management

- [ ] **VCAM-01**: Backend can create a v4l2loopback virtual camera device on demand with a static device number
- [ ] **VCAM-02**: Backend can destroy a virtual camera device, cleaning up the /dev/videoN node
- [ ] **VCAM-03**: Service shutdown destroys all virtual devices and kills all subprocesses within 5 seconds

### Wireless Pipeline

- [ ] **WPIP-01**: Backend manages FFmpeg subprocesses that pipe RTSP input into v4l2loopback devices
- [ ] **WPIP-02**: FFmpeg pipeline failures are detected within 3 seconds and trigger supervised restart with exponential backoff
- [ ] **WPIP-03**: CaptureRegistry does not acquire a virtual device until the producer has written its first frame (producer_ready gate)

### scrcpy Android Mirroring

- [ ] **SCPY-01**: User can provide an Android device IP and the backend connects via ADB WiFi and starts scrcpy with --v4l2-sink
- [ ] **SCPY-02**: The mirrored Android screen appears as a virtual camera in the camera selector alongside physical devices
- [ ] **SCPY-03**: Stopping a scrcpy session disconnects ADB and destroys the virtual device
- [ ] **SCPY-04**: scrcpy sessions survive brief WiFi interruptions via supervised watchdog with auto-reconnect

### Miracast Windows Mirroring

- [ ] **MIRA-01**: Backend detects NIC WiFi Direct P2P capability via iw and reports it through the API
- [ ] **MIRA-02**: A Windows PC on the same network sees the system as a Cast target in Win+K when Miracast receiver is active
- [ ] **MIRA-03**: Connecting from Windows delivers a live video stream that appears as a virtual camera consumable by the streaming pipeline
- [ ] **MIRA-04**: Disconnecting the Miracast client cleans up the FFmpeg pipeline and virtual device automatically

### Wireless API

- [ ] **WAPI-01**: GET /api/wireless/capabilities reports NIC P2P support, installed dependency versions, and system readiness
- [ ] **WAPI-02**: POST and DELETE endpoints start/stop Miracast receiver sessions
- [ ] **WAPI-03**: POST and DELETE endpoints start/stop scrcpy sessions by Android device IP
- [ ] **WAPI-04**: GET endpoint lists active wireless sessions with status and source type

### Wireless Frontend

- [ ] **WFNT-01**: Dedicated wireless tab shows NIC status, active sessions, and start/stop controls
- [ ] **WFNT-02**: scrcpy section has an IP entry form and connect/disconnect buttons
- [ ] **WFNT-03**: Miracast section shows P2P availability and receiver start/stop (disabled when NIC lacks P2P)
- [ ] **WFNT-04**: Wireless sources appear in the camera selector dropdown alongside physical cameras

## Future Requirements (v1.3)

### WLED Integration

- **WLED-01**: WLED device discovery and management in a dedicated UI tab
- **WLED-02**: UDP realtime protocol (DRGB/DNRGB) streaming to WLED ESP32 devices
- **WLED-03**: Paint-on-strip UI for assigning LED pixel ranges to canvas zones
- **WLED-04**: Shared channel-per-area mapping abstraction for Hue and WLED

### Home Assistant

- **HASS-01**: Home Assistant REST endpoints: select camera, select zone, start/stop streaming

### Bug Fixes

- **BFIX-01**: Persist selected entertainment config per camera across page reloads
- **BFIX-02**: Dropdown reflects actual streaming state on reload

## Out of Scope

| Feature | Reason |
|---------|--------|
| Docker containerization | Dropped in v1.2 — native Linux simplifies kernel module and device access |
| Apple AirPlay | Scoped to Windows and Android only |
| Audio reactivity | Video/color only |
| Cloud connectivity | Fully local, Bridge on LAN |
| User authentication | Single-user local tool |
| Mobile app | Web UI is the only interface |
| MS-MICE (Miracast over Infrastructure) | No known open-source Linux implementation |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| VCAM-01 | TBD | Pending |
| VCAM-02 | TBD | Pending |
| VCAM-03 | TBD | Pending |
| WPIP-01 | TBD | Pending |
| WPIP-02 | TBD | Pending |
| WPIP-03 | TBD | Pending |
| SCPY-01 | TBD | Pending |
| SCPY-02 | TBD | Pending |
| SCPY-03 | TBD | Pending |
| SCPY-04 | TBD | Pending |
| MIRA-01 | TBD | Pending |
| MIRA-02 | TBD | Pending |
| MIRA-03 | TBD | Pending |
| MIRA-04 | TBD | Pending |
| WAPI-01 | TBD | Pending |
| WAPI-02 | TBD | Pending |
| WAPI-03 | TBD | Pending |
| WAPI-04 | TBD | Pending |
| WFNT-01 | TBD | Pending |
| WFNT-02 | TBD | Pending |
| WFNT-03 | TBD | Pending |
| WFNT-04 | TBD | Pending |

**Coverage:**
- v1.2 requirements: 22 total
- Mapped to phases: 0
- Unmapped: 22 (pending roadmap)

---
*Requirements defined: 2026-04-14*
*Last updated: 2026-04-14 after initial definition*
