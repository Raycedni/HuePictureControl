# Feature Research

**Domain:** Multi-camera device management for ambient lighting capture application
**Researched:** 2026-04-03
**Confidence:** HIGH (based on direct codebase analysis + verified patterns)

---

## Context: What Already Exists

This is a subsequent milestone on a working system. The following are already built and out of scope:

- Single capture device at `/dev/video0` via V4L2 mmap backend
- `PUT /api/capture/device` endpoint (device path switching already exists)
- `CaptureBackend.open(device_path)` (already accepts a new path)
- Freeform region drawing per entertainment zone
- Live preview WebSocket stream (`/ws/preview`)
- Start/stop streaming controls with per-zone channel maps

The existing `PUT /api/capture/device` endpoint switches the single global capture device. The v1.1 milestone replaces this single global device model with a per-zone camera assignment.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features required for "multi-camera support" to be meaningful. Without these, the feature is incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Enumerate available /dev/video* devices | Without device list, user must know device paths manually — unusable | LOW | Glob `/dev/video*`, open each, call `VIDIOC_QUERYCAP`, filter for `V4L2_CAP_VIDEO_CAPTURE`. Filter out metadata/subdevice nodes (which also appear as `/dev/video*` but have no capture capability). Already have the ioctl infrastructure in `capture_v4l2.py`. |
| Return device label alongside path | `/dev/video0` is meaningless; user needs "USB Capture Card" not a path | LOW | `VIDIOC_QUERYCAP` returns `card` field (up to 32 bytes) — already parsed in existing V4L2 backend struct. Expose as `{"path": "/dev/video0", "name": "USB Capture Card"}`. |
| `GET /api/capture/devices` endpoint | Frontend needs to populate device dropdowns | LOW | New router endpoint. Calls the enumerate function, returns JSON list. Should be callable at any time, including during active streaming. |
| Per-zone camera assignment in the DB | System needs to persist which camera each zone uses | MEDIUM | Schema change: add `camera_device` column to `regions` table (nullable string, defaults to global device). Or a separate `zone_camera_assignments` table keyed by entertainment config + channel group. |
| Camera dropdown in the Editor/Preview UI per zone or config | User must be able to set the camera without editing config files | MEDIUM | A `<select>` populated from `GET /api/capture/devices`. The scope question (per-zone vs per-config) drives complexity — see Anti-Features section. |
| Multi-device capture pool in the backend | Streaming service currently holds a single `CaptureBackend`; must hold N | HIGH | `StreamingService` and `app.state.capture` are tightly coupled to one instance. Need a `CapturePool` or dict of `device_path -> CaptureBackend`. Each device runs its own reader thread. Frame lookup in `_frame_loop` must resolve the correct backend per channel. |
| Live preview reflects selected camera | Preview WebSocket (`/ws/preview`) currently streams from the single global capture; must stream from the zone's assigned camera | MEDIUM | Either make preview device-selectable via query param (e.g. `?device=/dev/video0`), or tie preview to the currently selected config's primary device. |

### Differentiators (Competitive Advantage)

Features that go beyond the table stakes but would meaningfully improve the experience.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Device health indicator in the dropdown | Shows which devices are currently open/streaming vs disconnected; avoids selecting a dead device | LOW | `CapturePool` already knows open state per device. Return `{"path": ..., "name": ..., "available": bool}` from the enumerate endpoint. |
| Hot-reload on USB re-attach | Device path can change on USB re-insert (e.g., `/dev/video0` becomes `/dev/video2`); reconnect by name/USB ID | HIGH | Requires udev monitoring inside Docker, which is non-trivial. The existing reconnect loop retries the same path. Could poll enumerate periodically and attempt re-open on first device with matching name. Memory note: feedback_docker_native.md documents this exact problem. |
| Per-device preview thumbnails in the selector | Small static snapshots showing what each camera is seeing | MEDIUM | Grab one JPEG from each device on enumerate, return as data URL. Useful when user has multiple capture cards doing different sources. |
| "Test capture" button for a device | User can preview a specific device without reassigning it | LOW | Frontend-only: open a temp modal with a `<img>` pointing to `/api/capture/snapshot?device=/dev/video0`. Backend needs device param on the snapshot endpoint. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem natural but are wrong for this use case.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Per-region (polygon) camera assignment | "Each polygon could capture from a different camera" | A single entertainment zone has one streaming session to the bridge. Regions within a zone all contribute to a single color computation cycle. Splitting at region granularity means one capture device per frame per region — N devices * M regions = unbounded open handles. Adds massive complexity for zero real-world gain (no real setup has more polygons than cameras). | Per-entertainment-config (or per-zone-group) assignment: all regions in a config share one camera. This is what the PROJECT.md specifies. |
| Global device fallback hierarchy (primary/secondary) | "If camera 0 fails, fall back to camera 1 automatically" | Ambiguous per-zone behavior — which zone gets which fallback? Creates invisible state that's hard to debug. The existing reconnect loop (exponential backoff on the same device) is the right model. | Keep single-device reconnect per zone. Surface the error clearly in the UI. Let the user manually switch devices if needed. |
| Automatic device-to-zone matching by USB position | "Auto-assign USB port 1 to zone 1" | USB port topology is opaque inside Docker; `/dev/video*` numbers are not stable (CLAUDE.md memory: feedback_docker_native.md). Silent auto-assignment breaks when hardware changes. | Enumerate + show a one-time assignment prompt in the UI. Persist the assignment explicitly. |
| Video format / resolution selection per device | "Let me pick 4K vs 720p per camera" | The V4L2 backend hardcodes 640x480 MJPEG. Changing this requires resizing all precomputed polygon masks. Adds configuration surface for no ambient-lighting benefit — region colors are sampled, not displayed. | Keep 640x480 MJPEG fixed. The existing backend is tuned for this. |
| Multiple preview streams simultaneously | "Show all cameras at once in a grid" | Would require one WebSocket per device, all streaming at ~30fps JPEG — enormous bandwidth overhead for a local web UI. The preview is diagnostic, not a monitoring panel. | Single-device preview, switchable via query param or config selection. |

---

## Feature Dependencies

```
GET /api/capture/devices (enumerate + label)
    └──required by──> Camera dropdown in UI
    └──required by──> Device health indicator
    └──required by──> Per-device preview thumbnails

Per-zone camera assignment in DB
    └──required by──> Camera dropdown in UI (to persist selection)
    └──required by──> Multi-device capture pool (to know which pool entries to open)

Multi-device capture pool
    └──required by──> Per-zone streaming (frame loop must look up device by zone)
    └──required by──> Per-zone preview (preview WebSocket must resolve device by config)
    └──enhances──> Hot-reload on USB re-attach (pool can manage re-open per device)

Live preview reflects selected camera
    └──requires──> GET /api/capture/devices
    └──requires──> Per-zone camera assignment in DB
```

### Dependency Notes

- **Enumerate requires DB assignment for persistence:** The enumerate endpoint is read-only (stateless), but camera assignments must be saved to DB so they survive container restart.
- **Capture pool is the critical structural change:** It touches `StreamingService._frame_loop` (must look up device per channel_id/config), `app.state.capture` (currently a single object), and `preview_ws.py` (currently calls `app.state.capture.get_jpeg()`). Everything downstream of a device read depends on this pool existing.
- **Preview device selection enhances but doesn't block:** Preview can initially default to the config's assigned device without a query param. Query param is an enhancement.

---

## MVP Definition

### Launch With (v1.1)

Minimum viable multi-camera support — what's needed to actually use two cameras.

- [ ] `GET /api/capture/devices` — enumerate `/dev/video*` nodes, filter capture-capable, return path + name
- [ ] Per-config camera assignment stored in DB — new column or table; default to current global `CAPTURE_DEVICE`
- [ ] Camera `<select>` dropdown in the Preview page UI, scoped per entertainment config
- [ ] `CapturePool` in backend — dict of `device_path -> CaptureBackend`; opens devices on demand, releases unused ones
- [ ] `StreamingService._frame_loop` uses the pool to look up the per-config device when grabbing frames
- [ ] Preview WebSocket resolves device from config assignment (not global `app.state.capture`)

### Add After Validation (v1.1.x)

- [ ] Device health/availability field on the enumerate endpoint — add when pool exists and device state is trackable
- [ ] "Test capture" button — add once users report confusion about which device is which

### Future Consideration (v2+)

- [ ] Per-device preview thumbnails in the selector — defer; needs snapshot bandwidth analysis
- [ ] Hot-reload on USB re-attach by device name matching — defer; requires udev monitoring or polling, Docker-specific complications

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| GET /api/capture/devices | HIGH | LOW | P1 |
| Per-config camera assignment in DB | HIGH | LOW | P1 |
| Camera dropdown in UI | HIGH | LOW | P1 |
| CapturePool (multi-device backend) | HIGH | HIGH | P1 |
| Per-config device in frame loop | HIGH | MEDIUM | P1 |
| Preview resolves per-config device | MEDIUM | MEDIUM | P1 |
| Device health indicator | MEDIUM | LOW | P2 |
| Test capture button | LOW | LOW | P2 |
| Per-device preview thumbnails | LOW | MEDIUM | P3 |
| Hot-reload on USB re-attach | MEDIUM | HIGH | P3 |

**Priority key:**
- P1: Must have for launch (v1.1 ships with these or it's not "multi-camera")
- P2: Should have, add when possible
- P3: Nice to have, future consideration

---

## Competitor Feature Analysis

| Feature | Hyperion | OBS/vMix | HuePictureControl v1.1 |
|---------|----------|----------|----------------------|
| Device enumeration | v4l2-ctl list-devices, shows all nodes | OS-level device picker in Add Input dialog | GET /api/capture/devices returning name + path |
| Per-source device assignment | Per-grabber config (one grabber = one device) | Per-scene input (any input can have any device) | Per entertainment config (one config = one device) |
| Device label display | Uses kernel card name | Uses DirectShow friendly name / v4l2 card name | VIDIOC_QUERYCAP card field |
| Live preview during selection | No (static config) | Yes (preview pane per input) | Single WebSocket, switched per config selection |
| Hot-plug detection | Supported via udev integration | Supported (OS-level) | Not planned for v1.1 |

**Key design choice vs competitors:** Scope camera assignment to entertainment configs, not individual regions. This matches the architecture (one streaming session per config) and keeps UI simple — one dropdown, not per-polygon camera selection. Hyperion and OBS both scope camera assignment at the "grabber/input" level, not at the per-zone level.

---

## Sources

- Direct codebase analysis: `capture_service.py`, `capture_v4l2.py`, `streaming_service.py`, `main.py`, `docker-compose.yaml`
- V4L2 device enumeration: [VIDIOC_QUERYCAP kernel docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-querycap.html)
- V4L2 multi-device Python patterns: [v4l2py on PyPI](https://pypi.org/project/v4l2py/)
- Docker multi-device passthrough: [Docker community thread](https://forums.docker.com/t/accessing-a-usb-camera-from-a-docker-container-in-linux/125361)
- Competitor reference: [Hyperion project](https://github.com/hyperion-project/hyperion), [vMix camera setup](https://www.vmix.com/help25/Capture.html)
- Project memory: `/home/lukas/.claude/projects/-mnt-c-Users-Lukas-IdeaProjects-HuePictureControl/memory/feedback_docker_native.md` (device path instability on USB re-attach)

---
*Feature research for: multi-camera device management in ambient lighting capture*
*Researched: 2026-04-03*
