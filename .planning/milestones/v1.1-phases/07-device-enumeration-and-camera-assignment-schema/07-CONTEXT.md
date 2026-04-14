# Phase 7: Device Enumeration and Camera Assignment Schema - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Enumerate all V4L2 video capture devices via a new backend API endpoint, establish stable device identity across USB re-plugs, persist camera-to-entertainment-zone assignments in the database, and provide a manual reconnect mechanism for disconnected cameras. This phase delivers the data layer and API surface that all subsequent multi-camera phases (8-11) build on.

</domain>

<decisions>
## Implementation Decisions

### Device Identity & Stability
- **D-01:** Use sysfs first (`/sys/class/video4linux/videoX/device/idVendor`, `idProduct`, `serial`) for stable USB identity. Fall back to VIDIOC_QUERYCAP card name if sysfs is inaccessible (expected in Docker/WSL2).
- **D-02:** If sysfs is unavailable, show a UI alert indicating degraded identity mode (not a silent fallback). This transparency matters if the user has multiple identical capture cards.
- **D-03:** `GET /api/cameras` response includes all three: `device_path` (/dev/videoN), `stable_id` (VID:PID:serial or card name), and `display_name`. Frontend shows name, backend uses stable_id for persistence, path for device access.

### Reconnect Behavior
- **D-04:** Manual reconnect (DEVC-05) triggers a full device re-scan, matches the disconnected camera by its stable ID, and updates the device path if the kernel reassigned it. If the camera is truly gone, report it as still disconnected.
- **D-05:** Dedicated endpoint: `POST /api/cameras/reconnect` with device `stable_id` in the body. Returns updated status (connected with new path, or still disconnected).
- **D-06:** When a zone's assigned camera is disconnected (and streaming is NOT active), show "disconnected" status with the previously assigned camera's display name preserved. No auto-fallback to default camera — the assignment stays pointing to the original camera.

### DB Schema Design
- **D-07:** New `camera_assignments` table: `(entertainment_config_id TEXT PK, camera_stable_id TEXT, camera_name TEXT)`. Clean separation from existing tables.
- **D-08:** New `known_cameras` table: `(stable_id TEXT PK, display_name TEXT, last_seen_at TEXT, last_device_path TEXT)`. Tracks all cameras ever discovered. `camera_assignments.camera_stable_id` references `known_cameras.stable_id`.
- **D-09:** `known_cameras` is updated on every successful scan — `last_seen_at` and `last_device_path` reflect the most recent state. This enables the UI to show "previously seen but disconnected" cameras and when they were last available.

### Claude's Discretion
- Default camera fallback (CAMA-03): Claude may decide the fallback strategy (likely `CAPTURE_DEVICE` env var or first discovered device) during planning.
- `linuxpy` vs extending existing ctypes code in `capture_v4l2.py` for enumeration: Claude may decide based on research findings.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Codebase
- `Backend/services/capture_v4l2.py` — Existing V4L2 ctypes/ioctl infrastructure; has VIDIOC constants and struct definitions
- `Backend/services/capture_service.py` — CaptureBackend ABC + `create_capture()` factory; `CAPTURE_DEVICE` env var default
- `Backend/database.py` — Current schema: `bridge_config`, `entertainment_configs`, `regions`, `light_assignments` tables; migration pattern (ALTER TABLE + try/except)
- `Backend/routers/capture.py` — Existing `PUT /api/capture/device` endpoint for switching device path

### Project Docs
- `.planning/REQUIREMENTS.md` — DEVC-01 through DEVC-05, CAMA-01 through CAMA-03 requirements
- `.planning/ROADMAP.md` — Phase 7 success criteria and dependency chain
- `CLAUDE.md` — Technology stack (linuxpy>=0.24 recommended), alternatives considered, integration points

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `capture_v4l2.py` V4L2 ctypes infrastructure: ioctl number computation, struct definitions, `_VIDIOC_QUERYCAP` constant — can be extended for device enumeration
- `database.py` migration pattern (ALTER TABLE in try/except) — use same pattern for new tables
- `routers/capture.py` `PUT /device` endpoint — similar pattern for reconnect endpoint

### Established Patterns
- FastAPI routers under `routers/` with `APIRouter(prefix="/api/...")` and Pydantic request models
- `app.state` for service instances (capture, streaming, broadcaster)
- aiosqlite with `db.row_factory = aiosqlite.Row`
- Tests in `Backend/tests/` using pytest with conftest fixtures

### Integration Points
- New `GET /api/cameras` router needs registering in `main.py`
- `POST /api/cameras/reconnect` in same router
- New tables in `database.py` `init_db()` function
- `known_cameras` table updated during device scan operations

</code_context>

<specifics>
## Specific Ideas

- Disconnected camera status must preserve the camera's display name so the user knows which device was previously assigned (not just "disconnected")
- `last_seen_at` timestamp in `known_cameras` helps distinguish "just unplugged" from "gone for days"
- UI alert when sysfs is unavailable — user needs transparency about device identity limitations

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-device-enumeration-and-camera-assignment-schema*
*Context gathered: 2026-04-03*
