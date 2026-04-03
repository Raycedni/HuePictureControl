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
| Frame capture (Linux) | Custom V4L2 ctypes/ioctl + mmap | — (in `capture_v4l2.py`) |
| Frame decode | opencv-python-headless | >=4.10 |
| Hue streaming | hue-entertainment-pykit | 0.9.4 |
| Python | 3.12 (pinned) | 3.12 |
| Frontend | React 19 + TypeScript + Konva.js + Zustand | — |
## Recommended Stack Additions
### Core Technologies
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `linuxpy` | `>=0.24` | Enumerate available V4L2 capture devices inside the container | Provides `iter_video_capture_devices()` — a stdlib-equivalent iterator that runs `VIDIOC_QUERYCAP` ioctl on every `/dev/video*` node and filters to those with `V4L2_CAP_VIDEO_CAPTURE`. No shell subprocess required, no `v4l2-ctl` binary dependency. Pure Python, no C extension. Python 3.10+ — compatible with pinned 3.12. Version 0.24.0 released Feb 2026 (current). |
### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python `glob` + `fcntl` stdlib | stdlib | Fallback device scan if `linuxpy` unavailable | Only if `linuxpy` import fails at startup (e.g., slim Docker image); scan `/dev/video*` + `VIDIOC_QUERYCAP` manually using the existing ctypes infrastructure already in `capture_v4l2.py` |
### Development Tools
| Tool | Purpose | Notes |
|------|---------|-------|
| `v4l2-ctl --list-devices` (host only) | Manual verification of device names during dev | Do NOT ship in Docker image — only used outside container for debugging |
| `usbipd` (Windows host) | Attach additional USB capture cards to WSL2 | Existing workflow, no change |
## Database Schema Addition
## API Surface Addition
- `PUT /api/capture/device` — already exists, already switches device path; no change needed
- `GET /api/regions` / `PUT /api/regions/{id}` — add `camera_device` field to the region model
## Docker Compose — Multiple Device Passthrough
### Recommended Approach: Explicit `devices` List
### Alternative: `device_cgroup_rules` Wildcard
### WSL2 Reality
## Installation
# Add to Backend/requirements.txt
# Install in venv
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|------------------------|
| `linuxpy.video.device.iter_video_capture_devices()` | `subprocess.run(["v4l2-ctl", "--list-devices"])` | Never — requires `v4l2-utils` installed in the Docker image, adds a binary dependency, and produces text that must be parsed. Pure Python ioctl is already the pattern in this codebase. |
| `linuxpy.video.device.iter_video_capture_devices()` | Extend existing ctypes code in `capture_v4l2.py` | If `linuxpy` adds unacceptable image size or dependency complexity. The existing `capture_v4l2.py` already has `VIDIOC_QUERYCAP` partially implemented — a pure-stdlib fallback using `glob('/dev/video*')` + the existing `_VIDIOC_QUERYCAP` constant is a viable alternative with zero new dependencies. |
| `linuxpy.video.device.iter_video_capture_devices()` | `cv2.VideoCapture(index)` probe loop | Never — OpenCV's V4L2 backend in `opencv-python-headless` is broken on Linux (that is exactly why the project already replaced it with direct ioctls). Probing by integer index also produces silent failures rather than a clean device list. |
| Explicit `devices` list in docker-compose.yaml | `device_cgroup_rules: 'c 81:* rw'` wildcard | Only if the number of capture cards is dynamic at runtime and unpredictable. For this project (1-4 cards max, plugged before container start), explicit mapping is more reliable across Compose versions. |
| `camera_device` column in existing `regions` table | New `zone_camera_assignments` join table | Only if the same zone ever needs to switch cameras per entertainment config. Current requirement is one camera per zone globally. A nullable column in `regions` is simpler and backward compatible. |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `v4l2py` (PyPI) | Version 3.0.0 is explicitly a shim re-exporting `linuxpy` — use the real library directly | `linuxpy>=0.24` |
| `capture-devices` (PyPI) | Thin wrapper around OpenCV integer probing; inherits the broken Linux V4L2 backend problem | `linuxpy` + existing ctypes approach |
| `pyudev` | Adds libudev C dependency; overkill for simple device listing when V4L2 ioctl achieves the same | `linuxpy` or glob+ioctl |
| `cv2.VideoCapture(index)` probe loop | Broken V4L2 backend — this is documented in project history as why `capture_v4l2.py` was written from scratch | Direct `VIDIOC_QUERYCAP` ioctl via `linuxpy` or existing ctypes |
| `privileged: true` in docker-compose | Security: grants host-level access far beyond what video capture needs | Explicit `devices` list + `group_add: [video]` |
| New camera manager service / process | Overengineering: the existing `CaptureBackend` pool pattern (one instance per active device) is sufficient | Extend `app.state` to hold a dict of `CaptureBackend` instances keyed by device path |
## Version Compatibility
| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `linuxpy>=0.24` | Python 3.10–3.12 | Tested with 3.12; uses `fcntl`/`ctypes` stdlib only; no conflict with `opencv-python-headless` |
| `linuxpy>=0.24` | `fastapi>=0.115` | No interaction; used only in a new synchronous device-scan function called from a FastAPI route |
| `linuxpy>=0.24` | Docker `python:3.12-slim` base image | Pure Python, no apt packages needed |
## Integration Points with Existing Code
### `capture_service.py` — `create_capture(device_path)` factory
### `database.py` — schema migration
### `routers/capture.py` — new `/devices` endpoint
### `streaming_service.py`
## Sources
- [linuxpy PyPI page](https://pypi.org/project/linuxpy/) — version 0.24.0, Python >=3.10, HIGH confidence
- [linuxpy async FastAPI example](https://github.com/tiagocoutinho/linuxpy/blob/master/examples/video/web/async.py) — `iter_video_capture_devices()` API confirmed, HIGH confidence
- [Docker Compose `services` reference](https://docs.docker.com/reference/compose-file/services/) — `devices` list and `device_cgroup_rules` syntax, HIGH confidence
- [docker/compose #9059](https://github.com/docker/compose/issues/9059) — `device_cgroup_rules` instability history, MEDIUM confidence
- [docker/compose #12102](https://github.com/docker/compose/issues/12102) — cgroup rules bug resolved as user error in v2.29.2, MEDIUM confidence
- [VIDIOC_QUERYCAP kernel docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-querycap.html) — `V4L2_CAP_VIDEO_CAPTURE` capability flag, HIGH confidence
- v4l2py PyPI page — confirmed v3.0 is a linuxpy shim, HIGH confidence
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
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
