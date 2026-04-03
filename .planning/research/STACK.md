# Stack Research

**Domain:** Multi-camera V4L2 device enumeration and per-zone assignment — HuePictureControl v1.1
**Researched:** 2026-04-03
**Confidence:** HIGH (core enumeration pattern), MEDIUM (Docker multi-device strategy)

---

## Context: What Already Exists (Do Not Re-Research)

The existing stack is validated and must not change:

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend framework | FastAPI | >=0.115 |
| Async DB | aiosqlite | >=0.20 |
| Frame capture (Linux) | Custom V4L2 ctypes/ioctl + mmap | — (in `capture_v4l2.py`) |
| Frame decode | opencv-python-headless | >=4.10 |
| Hue streaming | hue-entertainment-pykit | 0.9.4 |
| Python | 3.12 (pinned) | 3.12 |
| Frontend | React 19 + TypeScript + Konva.js + Zustand | — |

The existing `V4L2Capture` backend already performs direct ioctl/mmap against a single device path. The enumeration feature must integrate with this backend, not replace it.

---

## Recommended Stack Additions

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `linuxpy` | `>=0.24` | Enumerate available V4L2 capture devices inside the container | Provides `iter_video_capture_devices()` — a stdlib-equivalent iterator that runs `VIDIOC_QUERYCAP` ioctl on every `/dev/video*` node and filters to those with `V4L2_CAP_VIDEO_CAPTURE`. No shell subprocess required, no `v4l2-ctl` binary dependency. Pure Python, no C extension. Python 3.10+ — compatible with pinned 3.12. Version 0.24.0 released Feb 2026 (current). |

No other new backend libraries are needed. The existing `V4L2Capture` class already handles per-device open/stream/release — the only gap is discovery.

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python `glob` + `fcntl` stdlib | stdlib | Fallback device scan if `linuxpy` unavailable | Only if `linuxpy` import fails at startup (e.g., slim Docker image); scan `/dev/video*` + `VIDIOC_QUERYCAP` manually using the existing ctypes infrastructure already in `capture_v4l2.py` |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `v4l2-ctl --list-devices` (host only) | Manual verification of device names during dev | Do NOT ship in Docker image — only used outside container for debugging |
| `usbipd` (Windows host) | Attach additional USB capture cards to WSL2 | Existing workflow, no change |

---

## Database Schema Addition

The `regions` table needs a `camera_device` column for per-zone camera assignment:

```sql
-- Migration: add camera_device column to existing regions table
ALTER TABLE regions ADD COLUMN camera_device TEXT DEFAULT NULL;
-- NULL means "use default device" (backward compatible with all existing regions)
```

No new tables needed. No new Python ORM library needed — existing aiosqlite + raw SQL is already the pattern.

---

## API Surface Addition

One new endpoint on the existing FastAPI backend:

```
GET /api/capture/devices
```

Returns a JSON array of available capture devices:

```json
[
  {"path": "/dev/video0", "card": "USB Capture HDMI", "driver": "uvcvideo", "index": 0},
  {"path": "/dev/video2", "card": "v4l2 loopback", "driver": "v4l2loopback", "index": 2}
]
```

Existing endpoints that change behavior:
- `PUT /api/capture/device` — already exists, already switches device path; no change needed
- `GET /api/regions` / `PUT /api/regions/{id}` — add `camera_device` field to the region model

---

## Docker Compose — Multiple Device Passthrough

### Recommended Approach: Explicit `devices` List

```yaml
services:
  backend:
    devices:
      - "/dev/video0:/dev/video0"
      - "/dev/video2:/dev/video2"
      - "/dev/video4:/dev/video4"
    group_add:
      - video
```

Add each UVC device node explicitly. UVC cards on Linux typically register two nodes: `/dev/videoN` (capture) and `/dev/videoN+1` (metadata). Only the even node handles `V4L2_CAP_VIDEO_CAPTURE`; `iter_video_capture_devices()` filters this automatically.

### Alternative: `device_cgroup_rules` Wildcard

```yaml
services:
  backend:
    device_cgroup_rules:
      - 'c 81:* rw'    # major 81 = all V4L2 video devices
    group_add:
      - video
```

This grants cgroup permission to all `/dev/video*` nodes without enumerating them upfront. However, it does NOT bind-mount the device nodes into the container — the kernel nodes must still be present in the container filesystem. On Docker Desktop for WSL2 this approach is less reliable (confirmed open issues in docker/compose #9059 and #12102 re: cgroup rules behavior varying by Compose version). Use explicit `devices` list for reliability.

### WSL2 Reality

The existing `docker-compose.yaml` already has the `devices` block commented out with note "INFR-02: USB capture card passthrough". For v1.1, uncomment and add entries per card:

```yaml
    devices:
      - "/dev/video0:/dev/video0"   # primary capture card
      - "/dev/video2:/dev/video2"   # second capture card (if present)
      # Add more as needed; enumerate with: ls /dev/video* on WSL2 host
    group_add:
      - video
```

Device node numbers shift when USB devices are detached and reattached (documented in project memory). At startup, `GET /api/capture/devices` reflects whatever nodes are currently mounted in the container — the frontend should always fetch this list live rather than caching it.

---

## Installation

No new Python package installs for the enumeration pattern itself if using the stdlib fallback. If using `linuxpy`:

```bash
# Add to Backend/requirements.txt
linuxpy>=0.24,<1
```

```bash
# Install in venv
source /tmp/hpc-venv/bin/activate
pip install linuxpy>=0.24
```

`linuxpy` has zero C-extension dependencies — it is pure Python using ctypes and stdlib `fcntl`/`ioctl`, identical to the approach already used in `capture_v4l2.py`. It will not conflict with the `opencv-python-headless` wheels.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|------------------------|
| `linuxpy.video.device.iter_video_capture_devices()` | `subprocess.run(["v4l2-ctl", "--list-devices"])` | Never — requires `v4l2-utils` installed in the Docker image, adds a binary dependency, and produces text that must be parsed. Pure Python ioctl is already the pattern in this codebase. |
| `linuxpy.video.device.iter_video_capture_devices()` | Extend existing ctypes code in `capture_v4l2.py` | If `linuxpy` adds unacceptable image size or dependency complexity. The existing `capture_v4l2.py` already has `VIDIOC_QUERYCAP` partially implemented — a pure-stdlib fallback using `glob('/dev/video*')` + the existing `_VIDIOC_QUERYCAP` constant is a viable alternative with zero new dependencies. |
| `linuxpy.video.device.iter_video_capture_devices()` | `cv2.VideoCapture(index)` probe loop | Never — OpenCV's V4L2 backend in `opencv-python-headless` is broken on Linux (that is exactly why the project already replaced it with direct ioctls). Probing by integer index also produces silent failures rather than a clean device list. |
| Explicit `devices` list in docker-compose.yaml | `device_cgroup_rules: 'c 81:* rw'` wildcard | Only if the number of capture cards is dynamic at runtime and unpredictable. For this project (1-4 cards max, plugged before container start), explicit mapping is more reliable across Compose versions. |
| `camera_device` column in existing `regions` table | New `zone_camera_assignments` join table | Only if the same zone ever needs to switch cameras per entertainment config. Current requirement is one camera per zone globally. A nullable column in `regions` is simpler and backward compatible. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `v4l2py` (PyPI) | Version 3.0.0 is explicitly a shim re-exporting `linuxpy` — use the real library directly | `linuxpy>=0.24` |
| `capture-devices` (PyPI) | Thin wrapper around OpenCV integer probing; inherits the broken Linux V4L2 backend problem | `linuxpy` + existing ctypes approach |
| `pyudev` | Adds libudev C dependency; overkill for simple device listing when V4L2 ioctl achieves the same | `linuxpy` or glob+ioctl |
| `cv2.VideoCapture(index)` probe loop | Broken V4L2 backend — this is documented in project history as why `capture_v4l2.py` was written from scratch | Direct `VIDIOC_QUERYCAP` ioctl via `linuxpy` or existing ctypes |
| `privileged: true` in docker-compose | Security: grants host-level access far beyond what video capture needs | Explicit `devices` list + `group_add: [video]` |
| New camera manager service / process | Overengineering: the existing `CaptureBackend` pool pattern (one instance per active device) is sufficient | Extend `app.state` to hold a dict of `CaptureBackend` instances keyed by device path |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `linuxpy>=0.24` | Python 3.10–3.12 | Tested with 3.12; uses `fcntl`/`ctypes` stdlib only; no conflict with `opencv-python-headless` |
| `linuxpy>=0.24` | `fastapi>=0.115` | No interaction; used only in a new synchronous device-scan function called from a FastAPI route |
| `linuxpy>=0.24` | Docker `python:3.12-slim` base image | Pure Python, no apt packages needed |

---

## Integration Points with Existing Code

### `capture_service.py` — `create_capture(device_path)` factory

No change to the factory signature. The new multi-camera behavior is achieved by calling `create_capture(path)` multiple times (once per active zone-camera pair) and storing the resulting backends in `app.state`. The abstract `CaptureBackend` interface is already designed for this — `device_path` is an instance variable, not a module global.

Remove or demote `CAPTURE_DEVICE` module global — it becomes the default when `camera_device IS NULL` in the database (backward compat for zones that haven't been explicitly assigned).

### `database.py` — schema migration

Add the `camera_device` column migration (nullable TEXT) to `init_db()` in the same try/except ALTER TABLE pattern already used for the `light_id` migration.

### `routers/capture.py` — new `/devices` endpoint

Add a synchronous scan function (linuxpy or glob+ioctl fallback) and expose it as `GET /api/capture/devices`. The scan should run on each request (not cached) because device topology can change when USB cards are re-attached.

### `streaming_service.py`

When the streaming loop starts for a config, it must resolve the camera backend for each region's assigned `camera_device` (or fall back to the default). This is the only place where multi-capture-backend fan-out logic lives.

---

## Sources

- [linuxpy PyPI page](https://pypi.org/project/linuxpy/) — version 0.24.0, Python >=3.10, HIGH confidence
- [linuxpy async FastAPI example](https://github.com/tiagocoutinho/linuxpy/blob/master/examples/video/web/async.py) — `iter_video_capture_devices()` API confirmed, HIGH confidence
- [Docker Compose `services` reference](https://docs.docker.com/reference/compose-file/services/) — `devices` list and `device_cgroup_rules` syntax, HIGH confidence
- [docker/compose #9059](https://github.com/docker/compose/issues/9059) — `device_cgroup_rules` instability history, MEDIUM confidence
- [docker/compose #12102](https://github.com/docker/compose/issues/12102) — cgroup rules bug resolved as user error in v2.29.2, MEDIUM confidence
- [VIDIOC_QUERYCAP kernel docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-querycap.html) — `V4L2_CAP_VIDEO_CAPTURE` capability flag, HIGH confidence
- v4l2py PyPI page — confirmed v3.0 is a linuxpy shim, HIGH confidence

---
*Stack research for: HuePictureControl v1.1 multi-camera device enumeration*
*Researched: 2026-04-03*
