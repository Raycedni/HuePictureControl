# Project Research Summary

**Project:** HuePictureControl v1.1 — Multi-Camera Device Management
**Domain:** Per-zone V4L2 device assignment for ambient lighting capture (Docker/Linux)
**Researched:** 2026-04-03
**Confidence:** HIGH

## Executive Summary

HuePictureControl v1.1 adds multi-camera support to a working single-camera ambient lighting system. The existing stack (FastAPI + aiosqlite + custom V4L2 ctypes backend + React 19/Konva.js frontend) is validated and must not change. The migration path is well-defined: replace the single global `CaptureBackend` with a `CaptureRegistry` (a reference-counted dict keyed by device path), add a `CameraEnumerator` service that probes `/dev/video*` with `VIDIOC_QUERYCAP`, and persist camera selection per entertainment config via a new `camera_device` column on the `regions` table.

The critical architectural decision is scoping camera assignment to entertainment configs (one camera per config), not to individual region polygons. This matches the existing streaming model — one session per config — and avoids unbounded device-handle proliferation. The recommended enumeration library is `linuxpy>=0.24` (pure Python, zero C extensions, uses the same ctypes/ioctl approach already in `capture_v4l2.py`), with a stdlib fallback using the existing `VIDIOC_QUERYCAP` constants already in the codebase.

The biggest risks are all correctness failures, not performance failures: storing raw `/dev/videoN` paths in the database (they shift on USB re-attach), exposing metadata nodes in the camera dropdown (they open without error but produce no frames), and calling `CaptureBackend.open()` synchronously in API handlers (stalls the asyncio event loop). All three have clear mitigations documented in research. The single most important design gate is settling device identity before any persistence is implemented — the database schema must store a stable key (USB VID/PID/serial) rather than a kernel-assigned path.

---

## Key Findings

### Recommended Stack

The existing stack requires no major additions. The only new dependency is `linuxpy>=0.24` for V4L2 device enumeration — it is pure Python, uses the same `fcntl`/ctypes approach already established in `capture_v4l2.py`, and requires no apt packages or C extensions in the Docker image. A zero-dependency stdlib fallback (glob `/dev/video*` + existing `VIDIOC_QUERYCAP` ioctl constant) is viable if library footprint is a concern.

Docker device passthrough moves from the current single commented-out `devices: [/dev/video0]` entry to either explicit per-card entries or `device_cgroup_rules: ["c 81:* rmw"]`. Explicit entries are more reliable across Compose versions on WSL2; the cgroup-rules wildcard is more maintainable when card count is variable. The two approaches are not mutually exclusive.

**Core technologies:**
- `linuxpy>=0.24`: V4L2 device enumeration — pure Python ioctl, matches existing ctypes approach, zero C-extension conflicts
- Existing `V4L2Capture`: per-device capture (already parameterized by `device_path`, no changes needed to the class itself)
- Existing `aiosqlite` + raw SQL: `camera_device` column migration follows existing `ALTER TABLE` pattern in `database.py`
- `asyncio.to_thread()`: all blocking device operations (open, release, enumerate) must use this — already the pattern in `_capture_reconnect_loop`

**Critical version constraint:** Python 3.12 pinned (hue-entertainment-pykit incompatible with 3.13+). `linuxpy>=0.24` is compatible with Python 3.10–3.12.

### Expected Features

**Must have (table stakes — v1.1 ships with these or multi-camera is not usable):**
- `GET /api/cameras` endpoint: enumerate capture-capable `/dev/video*` nodes, return `{path, name, index}` per device
- Per-config camera assignment in DB: `camera_device TEXT` column on `regions` table (NULL = use default device, backward compatible)
- Camera `<select>` dropdown in the LightPanel/Preview UI, populated from `GET /api/cameras`
- `CaptureRegistry` in backend: dict of `device_path -> CaptureBackend`, lazy-open, reference-counted
- `StreamingService._frame_loop` per-zone camera dispatch: group channels by device, `asyncio.gather` frame reads
- Preview WebSocket device routing: `?device=/dev/videoN` query param selects which backend to stream from

**Should have (differentiators — add once core is validated):**
- Device availability field on `GET /api/cameras`: show which devices are currently open vs inaccessible
- "Test capture" button: preview a specific device without reassigning it

**Defer (v2+):**
- Hot-reload on USB re-attach by device name matching (requires udev monitoring inside Docker)
- Per-device preview thumbnails in the selector (bandwidth analysis needed)
- Multiple simultaneous preview streams (one WebSocket is sufficient for diagnostic use)

**Anti-features (explicitly excluded):**
- Per-region (polygon) camera assignment — unbounded handle proliferation, no real-world use case
- Global fallback hierarchy (primary/secondary camera) — ambiguous per-zone behavior, hard to debug
- Automatic USB-port-to-zone matching — device topology is opaque inside Docker, silent mis-assignments

### Architecture Approach

The target architecture replaces `app.state.capture` (single `CaptureBackend`) with `app.state.capture_registry` (a `CaptureRegistry` pool). The `StreamingService` is refactored to accept the registry instead of a single capture instance, and the streaming frame loop groups channels by their assigned device, acquiring backends from the registry and reading frames concurrently via `asyncio.gather`. The preview WebSocket gains an optional `?device=` query param to route to the correct backend. All other components (bridge, regions CRUD, light assignments, entertainment configs) are unchanged.

**Major new components:**
1. `CaptureRegistry` (`services/capture_registry.py`) — pool of `CaptureBackend` instances keyed by device path; lazy-open, ref-counted; `release_all()` on streaming stop
2. `CameraEnumerator` (`services/camera_enumerator.py`) — probes `/dev/video0..31` via `VIDIOC_QUERYCAP`, filters for `V4L2_CAP_VIDEO_CAPTURE`, returns `[{path, name, index}]`
3. `cameras.py` router — thin `GET /api/cameras` wrapper over `CameraEnumerator`, runs via `asyncio.to_thread`
4. `CameraSelector.tsx` (frontend) — per-config dropdown, calls `PUT /api/regions/{id}` with `camera_device` field

**Modified components:**
5. `StreamingService` — replace `self._capture` with registry dispatch; `_load_channel_map` returns `(mask, device_path)` tuples
6. `preview_ws.py` — add `?device=` param support, route to registry instance
7. `database.py` — `ALTER TABLE regions ADD COLUMN camera_device TEXT` migration
8. `main.py` lifespan — replace `create_capture(CAPTURE_DEVICE)` with `CaptureRegistry` initialization

### Critical Pitfalls

1. **Device path instability** (`/dev/videoN` shifts on USB re-attach) — store camera identity as USB VID/PID/serial from `/sys/class/video4linux/videoX/device/`, resolve to current path at runtime; never store raw path as the persistent key
2. **Metadata node confusion** (UVC cards register 2 nodes; metadata node opens without error but produces no frames) — filter enumeration results to nodes where `device_caps & V4L2_CAP_VIDEO_CAPTURE (0x1)` is set; verify count matches physical device count via `v4l2-ctl --list-devices`
3. **Event loop blocking** (`CaptureBackend.open()` takes 200–1500ms) — wrap every `open()`, `release()`, and enumeration call in `asyncio.to_thread()`; grep for direct `capture.open(` calls outside `to_thread` as a verification step
4. **Shared `CaptureBackend` race** (switching device in-place while reader thread writes `_latest_frame`) — `CaptureRegistry` with reference counting is the only correct fix; one backend instance per device path regardless of how many zones reference it
5. **Docker compose incomplete device list** — enumerate all camera nodes on WSL2 host before starting stack; prefer `device_cgroup_rules: ["c 81:* rmw"]` over static `devices:` list for multi-card setups

---

## Implications for Roadmap

Based on the architecture build-order dependency graph (ARCHITECTURE.md §Build Order), five natural phases emerge:

### Phase 1: Infrastructure Foundation
**Rationale:** Database schema and device enumeration have no upstream dependencies and unblock all subsequent work. Device identity design must be locked here — before any persistence of camera selection is implemented. Both changes are low-risk and well-understood.
**Delivers:** `GET /api/cameras` returning capability-filtered capture devices; `camera_device` column live in SQLite; migrations backward-compatible with all existing regions
**Addresses:** Table-stakes features "Enumerate /dev/video* devices" and "Return device label alongside path"
**Avoids:** Pitfall 1 (device path instability) — identity scheme decision gates DB schema; Pitfall 2 (metadata node confusion) — capability check is part of the enumeration implementation, not a later hardening step

### Phase 2: Backend Capture Registry
**Rationale:** `CaptureRegistry` is the structural change all other backend work depends on. Streaming and preview changes require the registry to exist first. Building it as an independently testable unit before integrating it into the streaming loop reduces risk.
**Delivers:** `CaptureRegistry` service with lazy-open and ref-counting; `main.py` lifespan updated; `StreamingService` refactored for per-zone dispatch with `asyncio.gather` across devices
**Uses:** `linuxpy>=0.24` (or stdlib fallback) for device probing; `asyncio.to_thread` for all blocking calls
**Implements:** CaptureRegistry pattern and concurrent frame-read pattern from ARCHITECTURE.md
**Avoids:** Pitfall 3 (event loop blocking), Pitfall 4 (shared backend race)

### Phase 3: Preview Routing and Region CRUD
**Rationale:** Preview WebSocket device routing and the `regions.py` CRUD update (adding `camera_device` to responses) are independent of each other but both depend on Phase 2 completing. They can be developed in parallel and merged together.
**Delivers:** Preview WebSocket accepts `?device=` param and routes to registry; `GET/PUT /api/regions` includes `camera_device` field; frontend `Region` type updated with `camera_device`
**Avoids:** UX pitfall "zone preview shows wrong camera after switch"; correctness issue where existing `app.state.capture` reference in preview bypasses registry lifecycle

### Phase 4: Frontend Camera Selector
**Rationale:** All backend endpoints exist after Phase 3; frontend work is fully unblocked. UI integration is the final step and can be developed against the live API without backend changes.
**Delivers:** `cameras.ts` API client (`fetchCameras()`); `CameraSelector.tsx` dropdown per config; `LightPanel.tsx` integration; `useRegionStore` updated with `camera_device` in Region model
**Addresses:** Table-stakes feature "Camera dropdown in UI"; UX requirement "show device name, not raw path"
**Avoids:** UX pitfall — raw `/dev/videoN` in dropdown; UX pitfall — no feedback when device inaccessible in Docker

### Phase 5: Docker Infrastructure Update
**Rationale:** Compose changes can be made at any point after Phase 2 but are listed last because they only affect container-startup behavior. The enumeration endpoint (Phase 1) works without this change, but multi-camera streaming requires both devices mounted in the container.
**Delivers:** `docker-compose.yaml` updated with `device_cgroup_rules` or explicit device list for 2+ capture cards; verified with `ls /dev/video*` inside the backend container
**Avoids:** Pitfall 5 (Docker compose device list incomplete)

### Phase Ordering Rationale

- Phase 1 before Phase 2: `_load_channel_map` SQL query must be able to read `camera_device`; enumeration endpoint must exist for manual testing before registry integration
- Phase 2 before Phase 3: registry must exist before preview routing can acquire backends from it
- Phase 3 before Phase 4: backend API must be complete before frontend can be tested against real data
- Phase 5 is independent but must complete before end-to-end multi-camera streaming tests
- Phases 3 and 4 (backend/frontend tracks) can overlap once Phase 2 is complete
- Natural test gate after Phase 1: `GET /api/cameras` should return the correct filtered device list before any streaming changes are touched

### Research Flags

Phases needing deeper research during planning:
- **Phase 2 (CaptureRegistry):** Reference counting edge cases during mid-stream camera switches need explicit test scenarios. Verify `asyncio.gather` frame-timing budget stays within 50Hz with 2+ cameras empirically before finalizing the frame loop design.
- **Phase 1 (Device identity):** The VID/PID/serial approach via `/sys/class/video4linux/` is well-documented on native Linux but WSL2 sysfs behavior inside Docker may differ. Verify `/sys/class/video4linux/videoX/device/idVendor` is accessible inside the container before committing to this identity scheme. Fallback: store `card` name from `VIDIOC_QUERYCAP` as a soft identity.

Phases with standard patterns (skip research-phase):
- **Phase 3:** FastAPI WebSocket query params and Pydantic model field additions are well-documented; pattern is already used elsewhere in this codebase
- **Phase 4:** React dropdown + Zustand store update + REST PUT are established patterns already in use in this frontend
- **Phase 5:** Docker Compose `device_cgroup_rules` syntax is stable; WSL2-specific notes are documented in STACK.md

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | `linuxpy` confirmed on PyPI with correct API; ioctl approach validated against existing `capture_v4l2.py`; Compose device syntax verified in official docs |
| Features | HIGH | Based on direct codebase analysis; scope matches existing `CaptureBackend` interface; competitor analysis (Hyperion/OBS) confirms config-level scoping |
| Architecture | HIGH | All coupling points identified via direct code inspection of `main.py`, `streaming_service.py`, `preview_ws.py`, `database.py`; no speculative claims |
| Pitfalls | HIGH | Six pitfalls grounded in codebase analysis + verified community sources; Pitfalls 1 and 6 independently confirmed by project memory (`feedback_docker_native.md`) |

**Overall confidence:** HIGH

### Gaps to Address

- **Device identity on WSL2/Docker sysfs:** Whether `/sys/class/video4linux/videoX/device/` with VID/PID/serial fields is accessible inside the Docker container on WSL2 needs empirical verification before the DB schema is finalized. If sysfs is not available, fall back to storing the `card` name from `VIDIOC_QUERYCAP` as a soft identity (less stable but better than raw path).
- **Preview WebSocket device lifecycle:** The exact acquire/release pattern for the preview WebSocket needs explicit definition. Recommendation: acquire on WebSocket connect, release on disconnect — but this must be implemented carefully to avoid keeping devices open when no preview client is connected.
- **`docker-compose.yaml` current device state:** The file has the `devices:` section commented out. The approach (explicit list vs `device_cgroup_rules`) should be decided based on current WSL2 host device count before the Docker phase is planned.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `Backend/services/capture_service.py`, `capture_v4l2.py`, `streaming_service.py`, `main.py`, `routers/capture.py`, `routers/preview_ws.py`, `database.py`
- Direct codebase inspection: `Frontend/src/api/regions.ts`, `src/store/useRegionStore.ts`, `src/components/LightPanel.tsx`
- [linuxpy PyPI page](https://pypi.org/project/linuxpy/) — version 0.24.0, `iter_video_capture_devices()` API confirmed
- [VIDIOC_QUERYCAP kernel docs](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-querycap.html) — `V4L2_CAP_VIDEO_CAPTURE` capability flag
- [Docker Compose services reference](https://docs.docker.com/reference/compose-file/services/) — `devices` and `device_cgroup_rules` syntax

### Secondary (MEDIUM confidence)
- [docker/compose #9059](https://github.com/docker/compose/issues/9059) — `device_cgroup_rules` instability history on older Compose versions
- [docker/compose #12102](https://github.com/docker/compose/issues/12102) — cgroup rules bug resolved in Compose v2.29.2
- [Multiple /dev/video for one physical device — Ubuntu Launchpad](https://answers.launchpad.net/ubuntu/+question/683647) — metadata node behavior
- [Assign v4l2 device a static name — Formant docs](https://docs.formant.io/docs/assign-v4l2-device-a-static-name) — udev persistent symlinks

### Tertiary (project-specific, needs validation in this environment)
- Project memory `feedback_docker_native.md` — device path shift on USB re-attach (confirms Pitfalls 1 and 6 in this specific setup)
- [linuxpy async FastAPI example](https://github.com/tiagocoutinho/linuxpy/blob/master/examples/video/web/async.py) — `iter_video_capture_devices()` usage confirmed but not tested in this exact Docker configuration

---
*Research completed: 2026-04-03*
*Ready for roadmap: yes*
