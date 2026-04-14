# Milestones

## v1.1 Multi-Camera Support (Shipped: 2026-04-14)

**Phases completed:** 5 phases (7-11), 10 plans, 79 commits
**Timeline:** 22 days (2026-03-23 → 2026-04-14)
**Files changed:** 103 (13,952 insertions, 2,978 deletions)

**Key accomplishments:**

- Device enumeration with V4L2 QUERYCAP capability filtering and stable sysfs identity (VID/PID/serial)
- CaptureRegistry — ref-counted, thread-safe pool for concurrent multi-camera capture
- Device-routed preview WebSocket with `?device=` per-zone camera routing
- Frontend camera selector — zone dropdown + per-zone camera dropdown with live preview switching
- Docker multi-device passthrough via `device_cgroup_rules` with SETUP.md documentation

### Known Gaps

7 v1.1 requirements left unchecked at close:

- DEVC-01: Backend enumerates V4L2 devices filtering out metadata nodes via VIDIOC_QUERYCAP
- DEVC-04: Stable identity via sysfs VID/PID/serial to survive USB re-plug
- CAMA-01: Camera assigned per entertainment config (zone), not per-region
- CAMA-02: Camera-to-config mapping persisted in DB and survives restarts
- MCAP-01: StreamingService uses assigned camera per config instead of global singleton
- DOCK-01: Docker Compose supports multiple video device passthrough
- DOCK-02: Documentation for adding/configuring multiple capture devices

**Archives:**
- [v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md)
- [v1.1-REQUIREMENTS.md](milestones/v1.1-REQUIREMENTS.md)

---
