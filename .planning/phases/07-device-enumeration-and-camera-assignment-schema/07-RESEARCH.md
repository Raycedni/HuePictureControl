# Phase 7: Device Enumeration and Camera Assignment Schema — Research

**Researched:** 2026-04-03
**Domain:** V4L2 device enumeration, USB device identity (sysfs), aiosqlite schema migration, FastAPI router patterns
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Use sysfs first (`/sys/class/video4linux/videoX/device/idVendor`, `idProduct`, `serial`) for stable USB identity. Fall back to VIDIOC_QUERYCAP card name if sysfs is inaccessible (expected in Docker/WSL2).
- **D-02:** If sysfs is unavailable, show a UI alert indicating degraded identity mode (not a silent fallback). This transparency matters if the user has multiple identical capture cards.
- **D-03:** `GET /api/cameras` response includes all three: `device_path` (/dev/videoN), `stable_id` (VID:PID:serial or card name), and `display_name`. Frontend shows name, backend uses stable_id for persistence, path for device access.
- **D-04:** Manual reconnect (DEVC-05) triggers a full device re-scan, matches the disconnected camera by its stable ID, and updates the device path if the kernel reassigned it. If the camera is truly gone, report it as still disconnected.
- **D-05:** Dedicated endpoint: `POST /api/cameras/reconnect` with device `stable_id` in the body. Returns updated status (connected with new path, or still disconnected).
- **D-06:** When a zone's assigned camera is disconnected (and streaming is NOT active), show "disconnected" status with the previously assigned camera's display name preserved. No auto-fallback to default camera — the assignment stays pointing to the original camera.
- **D-07:** New `camera_assignments` table: `(entertainment_config_id TEXT PK, camera_stable_id TEXT, camera_name TEXT)`. Clean separation from existing tables.
- **D-08:** New `known_cameras` table: `(stable_id TEXT PK, display_name TEXT, last_seen_at TEXT, last_device_path TEXT)`. Tracks all cameras ever discovered. `camera_assignments.camera_stable_id` references `known_cameras.stable_id`.
- **D-09:** `known_cameras` is updated on every successful scan — `last_seen_at` and `last_device_path` reflect the most recent state.

### Claude's Discretion

- Default camera fallback (CAMA-03): Claude may decide the fallback strategy (likely `CAPTURE_DEVICE` env var or first discovered device) during planning.
- `linuxpy` vs extending existing ctypes code in `capture_v4l2.py` for enumeration: Claude may decide based on research findings.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DEVC-01 | Backend enumerates all V4L2 video capture devices, filtering out metadata nodes via VIDIOC_QUERYCAP capability check | VIDIOC_QUERYCAP already used in `capture_v4l2.py`; `V4L2_CAP_VIDEO_CAPTURE = 0x01` bit in `device_caps` at offset 88 |
| DEVC-02 | API endpoint (`GET /api/cameras`) returns list of available cameras with device path and human-readable name | New `routers/cameras.py` follows exact pattern of existing routers |
| DEVC-03 | Device list refreshes on demand when user opens camera selector (re-scans /dev/video*) | No caching needed; `glob.glob('/dev/video*')` + ioctl per request |
| DEVC-04 | Devices are identified by stable identity (sysfs VID/PID/serial) to survive USB re-plug path changes | sysfs path confirmed unavailable in WSL2 host environment (degraded mode is the default here); container with real USB will have sysfs |
| DEVC-05 | User can trigger a manual reconnect for a disconnected camera device | `POST /api/cameras/reconnect` re-runs scan, matches by stable_id, updates `known_cameras.last_device_path` |
| CAMA-01 | Camera assigned per entertainment config (zone), not per-region | `camera_assignments` table keyed by `entertainment_config_id` |
| CAMA-02 | Camera-to-entertainment-config mapping persists in database and survives restarts | New `camera_assignments` table with `CREATE TABLE IF NOT EXISTS` + ALTER TABLE migration pattern |
| CAMA-03 | When no camera is explicitly assigned, system falls back to default capture device | `CAPTURE_DEVICE` env var (already in `capture_service.py`) is the correct fallback |
</phase_requirements>

---

## Summary

Phase 7 delivers the data layer and API surface for multi-camera support. The work is almost entirely backend: a new `routers/cameras.py` module with two endpoints (`GET /api/cameras` and `POST /api/cameras/reconnect`), a new device enumeration service using either `linuxpy` or the existing ctypes infrastructure in `capture_v4l2.py`, two new database tables (`known_cameras` and `camera_assignments`), and a single new frontend element (the sysfs-unavailable alert banner in `EditorPage.tsx`).

The critical environmental finding is that `/sys/class/video4linux/` is **not present** in the WSL2 host environment. In Docker containers with USB passthrough, sysfs may be available depending on host configuration, but it cannot be relied upon. The sysfs-unavailable path (degraded identity mode) is therefore the primary code path for this project's deployment. The fallback to VIDIOC_QUERYCAP `card` field (already read in `_setup_device()`) is both sufficient and verified to work in the existing codebase.

The linuxpy vs. ctypes decision (left to Claude's discretion) is resolved by research: the existing `capture_v4l2.py` already has `_VIDIOC_QUERYCAP`, `fcntl.ioctl`, and the struct layout needed to enumerate devices. Extending it with a `glob('/dev/video*')` loop adds zero new dependencies and zero new abstractions. `linuxpy` would add a dependency for functionality already implemented in-project. The ctypes path is the correct choice.

**Primary recommendation:** Extend `capture_v4l2.py` with a `enumerate_capture_devices()` function using `glob('/dev/video*')` + existing VIDIOC_QUERYCAP ioctl. No new pip dependency required.

---

## Standard Stack

### Core (all already in requirements.txt — nothing new needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `fastapi` | `>=0.115` | HTTP router for `GET /api/cameras` and `POST /api/cameras/reconnect` | Already in stack |
| `aiosqlite` | `>=0.20` | Async SQLite for `known_cameras` and `camera_assignments` tables | Already in stack |
| `pydantic` | `>=2.10` | Request/response models for camera endpoints | Already in stack |
| Python `glob` | stdlib | Enumerate `/dev/video*` device nodes | Zero-dependency, already imported in other modules |
| Python `fcntl` | stdlib | VIDIOC_QUERYCAP ioctl calls | Already used in `capture_v4l2.py` |
| Python `struct` | stdlib | Unpack VIDIOC_QUERYCAP response buffer | Already used in `capture_v4l2.py` |

### Do NOT Add

| Package | Reason |
|---------|--------|
| `linuxpy>=0.24` | Adds a dependency for functionality already implemented via ctypes/fcntl in `capture_v4l2.py`. The existing `_VIDIOC_QUERYCAP` constant, ioctl call pattern, and `device_caps` unpack at offset 88 are directly reusable. No benefit justifies a new dependency. |

**Installation:** No new packages. Nothing to add to `Backend/requirements.txt`.

---

## Architecture Patterns

### Recommended Project Structure Changes

```
Backend/
├── routers/
│   ├── cameras.py          # NEW: GET /api/cameras, POST /api/cameras/reconnect
│   └── capture.py          # EXISTING: unchanged
├── services/
│   ├── capture_v4l2.py     # EXTEND: add enumerate_capture_devices()
│   └── device_identity.py  # NEW: sysfs read + fallback logic
├── database.py             # EXTEND: add known_cameras + camera_assignments tables
└── main.py                 # EXTEND: register cameras router
```

### Pattern 1: V4L2 Device Enumeration Function

**What:** A synchronous function that globs `/dev/video*`, issues VIDIOC_QUERYCAP on each node, filters to those with `V4L2_CAP_VIDEO_CAPTURE` (bit 0 of `device_caps` at offset 88), and returns structured results.

**When to use:** Called from `GET /api/cameras` and `POST /api/cameras/reconnect` on every request (no caching per DEVC-03).

**Implementation in `capture_v4l2.py`:**

```python
# Source: verified against existing _setup_device() in capture_v4l2.py
import glob
from dataclasses import dataclass

@dataclass
class V4L2DeviceInfo:
    device_path: str
    card: str          # human-readable name from VIDIOC_QUERYCAP card field
    driver: str        # driver name (e.g. "uvcvideo")
    bus_info: str      # bus info (e.g. "usb-0000:00:14.0-2")

def enumerate_capture_devices() -> list[V4L2DeviceInfo]:
    """Return all /dev/video* nodes that support VIDEO_CAPTURE.
    
    Uses existing VIDIOC_QUERYCAP ioctl infrastructure.
    Metadata nodes (V4L2_CAP_META_CAPTURE only) are excluded.
    """
    results = []
    for path in sorted(glob.glob("/dev/video*")):
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            cap_buf = bytearray(104)
            fcntl.ioctl(fd, _VIDIOC_QUERYCAP, cap_buf)
            device_caps = struct.unpack_from("<I", cap_buf, 88)[0]
            if not (device_caps & 0x01):  # V4L2_CAP_VIDEO_CAPTURE
                continue
            card = cap_buf[16:48].rstrip(b"\x00").decode("utf-8", errors="replace")
            driver = cap_buf[0:16].rstrip(b"\x00").decode("utf-8", errors="replace")
            bus_info = cap_buf[48:80].rstrip(b"\x00").decode("utf-8", errors="replace")
            results.append(V4L2DeviceInfo(
                device_path=path,
                card=card,
                driver=driver,
                bus_info=bus_info,
            ))
        except OSError:
            continue
        finally:
            os.close(fd)
    return results
```

**Key detail:** Use `O_NONBLOCK` when opening for enumeration to avoid blocking on devices that are already open by the capture backend.

### Pattern 2: Device Identity — sysfs with Fallback

**What:** A separate `device_identity.py` module that attempts to read VID/PID/serial from sysfs and falls back to the VIDIOC_QUERYCAP `card` + `bus_info` fields.

**When to use:** Called per device after VIDIOC_QUERYCAP succeeds.

```python
# Source: sysfs layout from kernel docs + verified NOT available on this WSL2 host
import os

def get_stable_id(device_path: str, bus_info: str, card: str) -> tuple[str, bool]:
    """Return (stable_id, sysfs_available).
    
    Attempts sysfs VID:PID:serial first. Falls back to card:bus_info.
    Returns sysfs_available=True only if the full sysfs path was readable.
    """
    # /dev/videoN -> /sys/class/video4linux/videoN/device/
    dev_name = os.path.basename(device_path)  # "video0"
    sysfs_base = f"/sys/class/video4linux/{dev_name}/device"
    
    try:
        vid = open(f"{sysfs_base}/idVendor").read().strip()
        pid = open(f"{sysfs_base}/idProduct").read().strip()
        # serial may be absent on some devices
        try:
            serial = open(f"{sysfs_base}/serial").read().strip()
        except FileNotFoundError:
            serial = ""
        stable_id = f"{vid}:{pid}:{serial}" if serial else f"{vid}:{pid}"
        return stable_id, True
    except (FileNotFoundError, OSError):
        # Degraded: use card + bus_info as stable identifier
        stable_id = f"{card}@{bus_info}"
        return stable_id, False
```

**Identity mode is per-device, but the response reports the worst case.** If ANY device falls back to degraded mode, `identity_mode: "degraded"` is returned in `GET /api/cameras`.

### Pattern 3: Database Tables — New Schema

**What:** Two new tables added to `database.py` using the existing `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE` migration pattern.

```python
# Source: verified pattern from database.py init_db()
await db.execute("""
    CREATE TABLE IF NOT EXISTS known_cameras (
        stable_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        last_seen_at TEXT,
        last_device_path TEXT
    )
""")
await db.execute("""
    CREATE TABLE IF NOT EXISTS camera_assignments (
        entertainment_config_id TEXT PRIMARY KEY,
        camera_stable_id TEXT NOT NULL,
        camera_name TEXT NOT NULL
    )
""")
await db.commit()
```

**No ALTER TABLE migrations needed for these tables** — they are new tables created with `IF NOT EXISTS`. Existing databases will have the tables added on first startup after upgrade.

### Pattern 4: GET /api/cameras Endpoint

**What:** Synchronous scan wrapped in `asyncio.get_event_loop().run_in_executor` to avoid blocking the async event loop. VIDIOC_QUERYCAP ioctl calls are synchronous OS calls.

```python
# Source: FastAPI docs on blocking operations + existing router pattern
import asyncio
from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/cameras", tags=["cameras"])

class CameraDevice(BaseModel):
    device_path: str
    stable_id: str
    display_name: str
    connected: bool
    last_seen_at: str | None

class CamerasResponse(BaseModel):
    devices: list[CameraDevice]
    identity_mode: str  # "stable" | "degraded"

@router.get("", response_model=CamerasResponse)
async def list_cameras(request: Request):
    loop = asyncio.get_event_loop()
    raw_devices = await loop.run_in_executor(None, enumerate_capture_devices)
    # ... build response, upsert known_cameras, determine identity_mode
```

### Pattern 5: known_cameras Upsert on Scan

**What:** Every successful scan upserts all found devices into `known_cameras` using SQLite's `INSERT OR REPLACE`. Devices not found in current scan remain in the table (they show as `connected: False` with preserved `display_name`).

```python
from datetime import datetime, timezone

async def upsert_known_camera(db, stable_id: str, display_name: str, device_path: str):
    now = datetime.now(timezone.utc).isoformat()
    await db.execute("""
        INSERT INTO known_cameras (stable_id, display_name, last_seen_at, last_device_path)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(stable_id) DO UPDATE SET
            display_name = excluded.display_name,
            last_seen_at = excluded.last_seen_at,
            last_device_path = excluded.last_device_path
    """, (stable_id, display_name, now, device_path))
    await db.commit()
```

### Pattern 6: CAMA-03 Default Camera Fallback

**Resolution of Claude's Discretion item.** When `GET /api/cameras` is used during streaming setup (Phase 8), zones with no entry in `camera_assignments` fall back to `CAPTURE_DEVICE` env var. The `capture_service.py` already defines:

```python
CAPTURE_DEVICE: str = os.getenv("CAPTURE_DEVICE", "/dev/video0")
```

The fallback logic lives in the Phase 8 streaming layer, not in Phase 7. Phase 7 only needs to **document** the fallback contract in the router's docstring: "absent assignment = use `CAPTURE_DEVICE`."

### Anti-Patterns to Avoid

- **Opening devices with `O_RDWR` (blocking) during scan:** This can block indefinitely if the device is held by another process. Always use `O_RDWR | O_NONBLOCK` when opening for enumeration-only.
- **Caching the device list across requests:** DEVC-03 requires on-demand refresh. Do not store the enumerated list in `app.state`.
- **Using integer indices (`/dev/video0`, `/dev/video1`):** Glob `/dev/video*` instead so the scan handles gaps in numbering (e.g., `/dev/video10` for v4l2loopback).
- **Running VIDIOC_QUERYCAP inside the async event loop:** These are blocking syscalls. Wrap with `run_in_executor`.
- **Storing `/dev/videoN` path as the primary key:** Paths change on USB re-plug. `stable_id` is the key; `last_device_path` is the cache.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ISO 8601 timestamps for `last_seen_at` | Custom time formatting | `datetime.now(timezone.utc).isoformat()` | Standard, timezone-aware, sortable |
| SQLite upsert | SELECT + INSERT/UPDATE logic | `INSERT OR REPLACE` or `INSERT ... ON CONFLICT DO UPDATE` | SQLite native, atomic, one statement |
| Glob `/dev/video*` | Custom `/dev` directory scanner | `glob.glob("/dev/video*")` | stdlib, handles gaps in numbering |
| Detecting V4L2 metadata nodes | Custom capability parsing | `device_caps & 0x01` check (reuse from `_setup_device`) | Already validated in this codebase |

**Key insight:** The enumeration problem is already 80% solved by the existing `capture_v4l2.py`. The only new code is a loop around existing patterns.

---

## Common Pitfalls

### Pitfall 1: sysfs Unavailable in WSL2 and Docker
**What goes wrong:** Code checks `/sys/class/video4linux/video0/device/idVendor` and raises FileNotFoundError; the whole scan fails.
**Why it happens:** WSL2 does not expose USB sysfs by default. Docker containers on WSL2 also lack sysfs access unless the host explicitly exposes it.
**How to avoid:** Always wrap the sysfs read in try/except and fall back gracefully. **This is the normal case for this deployment.**
**Verified:** `ls /sys/class/video4linux/` returns empty on this WSL2 host. The path does not exist.

### Pitfall 2: Blocking ioctl in Async Event Loop
**What goes wrong:** `fcntl.ioctl(fd, _VIDIOC_QUERYCAP, buf)` blocks the event loop, starving WebSocket heartbeats and other async operations.
**Why it happens:** V4L2 ioctls are synchronous OS syscalls. FastAPI runs on an async event loop that cannot yield during a syscall.
**How to avoid:** Wrap the entire `enumerate_capture_devices()` call in `await loop.run_in_executor(None, enumerate_capture_devices)`.

### Pitfall 3: Metadata Device Nodes Passing the Filter
**What goes wrong:** `/dev/video1` appears in the list even though it is a UVC metadata node (no actual video frames).
**Why it happens:** Metadata nodes exist alongside capture nodes on many UVC devices. They appear as `/dev/videoX` but lack `V4L2_CAP_VIDEO_CAPTURE`.
**How to avoid:** Check `device_caps & 0x01` (not `capabilities & 0x01`). The `device_caps` field (offset 88) reflects the individual node's capabilities; `capabilities` (offset 84) reflects the whole device and may have both bits set.
**Warning signs:** Two consecutive `/dev/videoN` paths from the same USB device (e.g., `/dev/video0` and `/dev/video1` for one capture card).

### Pitfall 4: `known_cameras` Drift When Camera Is Removed
**What goes wrong:** After unplugging a camera, its row in `known_cameras` has stale `last_device_path`. If the kernel assigns that path to a new camera, the old `last_device_path` points to wrong hardware.
**Why it happens:** `last_device_path` is a cache, not a guarantee.
**How to avoid:** When serving `GET /api/cameras`, merge the current scan results with `known_cameras`. A device is `connected: true` only if it appears in the **current scan** result. The `last_device_path` in `known_cameras` is only authoritative after a successful reconnect.

### Pitfall 5: `camera_assignments` Referencing a `stable_id` Not in `known_cameras`
**What goes wrong:** A camera assignment is saved but the camera was never discovered (e.g., set via direct DB manipulation or a race condition). Foreign key check fails or silent NULL join.
**Why it happens:** SQLite does not enforce foreign keys by default; aiosqlite does not enable `PRAGMA foreign_keys = ON` unless explicitly set.
**How to avoid:** Always upsert into `known_cameras` before inserting into `camera_assignments`. This is enforced by the endpoint flow: assignment endpoint validates that `stable_id` exists in `known_cameras`.

### Pitfall 6: `O_RDWR` Blocking on Open Device
**What goes wrong:** `os.open("/dev/video0", os.O_RDWR)` hangs if the capture backend already holds the device open with exclusive access.
**Why it happens:** V4L2 devices can be opened by multiple processes in read-write mode, but some drivers serialize access. `O_NONBLOCK` prevents indefinite blocking.
**How to avoid:** Always use `os.O_RDWR | os.O_NONBLOCK` when opening for enumeration (not for capture). Catch `OSError` (errno EWOULDBLOCK / EBUSY).

---

## Code Examples

### VIDIOC_QUERYCAP Buffer Layout (verified against `capture_v4l2.py`)

```python
# Source: existing capture_v4l2.py _setup_device() + kernel V4L2 docs
# v4l2_capability struct layout (104 bytes total):
# Offset  0: driver[16]       — "uvcvideo\x00..."
# Offset 16: card[32]         — "AV.io HD Capture\x00..."
# Offset 48: bus_info[32]     — "usb-0000:00:14.0-2\x00..."
# Offset 80: version[4]       — kernel version uint32
# Offset 84: capabilities[4]  — full device capabilities (uint32)
# Offset 88: device_caps[4]   — this node's capabilities (uint32)
# Offset 92: reserved[12]

cap_buf = bytearray(104)
fcntl.ioctl(fd, _VIDIOC_QUERYCAP, cap_buf)

driver   = cap_buf[0:16].rstrip(b"\x00").decode("utf-8", errors="replace")
card     = cap_buf[16:48].rstrip(b"\x00").decode("utf-8", errors="replace")
bus_info = cap_buf[48:80].rstrip(b"\x00").decode("utf-8", errors="replace")
device_caps = struct.unpack_from("<I", cap_buf, 88)[0]
is_capture = bool(device_caps & 0x01)  # V4L2_CAP_VIDEO_CAPTURE
```

### Database Schema Migration Pattern (from database.py)

```python
# Source: existing database.py init_db() — CREATE TABLE IF NOT EXISTS for new tables
# No ALTER TABLE needed for brand-new tables
await db.execute("""
    CREATE TABLE IF NOT EXISTS known_cameras (
        stable_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        last_seen_at TEXT,
        last_device_path TEXT
    )
""")
await db.execute("""
    CREATE TABLE IF NOT EXISTS camera_assignments (
        entertainment_config_id TEXT PRIMARY KEY,
        camera_stable_id TEXT NOT NULL,
        camera_name TEXT NOT NULL
    )
""")
await db.commit()
```

### Router Registration Pattern (from main.py)

```python
# Source: existing main.py router registration
from routers.cameras import router as cameras_router
app.include_router(cameras_router)
```

### Frontend Alert Banner Pattern (from EditorPage.tsx line 53)

```tsx
// Source: EditorPage.tsx — existing channel-count warning uses identical styling
{identityMode === "degraded" && (
  <div className="bg-amber-500/10 border border-amber-500/25 text-amber-400 text-xs px-3 py-2 text-center">
    Device identity is limited to capture card name. Devices may be misidentified
    if multiple identical cards are connected.
  </div>
)}
```

The sysfs alert renders above the channel-count warning when both are active (flex-col wrapper order).

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| OpenCV `cv2.VideoCapture(index)` probe | Direct VIDIOC_QUERYCAP ioctl | Phase 2 (v1.0) | Already done — ctypes infrastructure exists |
| `v4l2py` (PyPI) | `linuxpy` (direct) — but project uses ctypes directly | Before Phase 7 | `linuxpy` is the "right" library but ctypes is already in-place |
| SQLite without migration pattern | ALTER TABLE in try/except | Phase 3 (v1.0) | Pattern established — use for schema additions |

**On `linuxpy` vs ctypes (Claude's Discretion resolved):**
The project has a complete, tested V4L2 ctypes implementation in `capture_v4l2.py`. Adding `linuxpy` would introduce a dependency to replicate functionality already present. The CLAUDE.md listing `linuxpy` as "Recommended Stack Additions" was written before the research step — the ctypes alternative is explicitly listed as viable ("If `linuxpy` adds unacceptable image size or dependency complexity. The existing `capture_v4l2.py` already has `VIDIOC_QUERYCAP` partially implemented"). Research confirms ctypes is the better choice here.

---

## Open Questions

1. **sysfs availability inside the actual Docker container with USB passthrough**
   - What we know: sysfs is absent on the WSL2 host shell. Docker containers on Linux hosts typically inherit sysfs device entries when a USB device is passed through via `--device`.
   - What's unclear: Whether the Docker container on WSL2 gets `/sys/class/video4linux/` populated when `/dev/video0` is passed via `devices:` in docker-compose.
   - Recommendation: Implement degraded mode as the robust primary path. The sysfs path is a best-effort bonus. The UI alert handles the degraded case transparently. No blocking concern — just document in comments.

2. **`camera_assignments` endpoint — which phase delivers it?**
   - What we know: Phase 7 creates the table and its schema. The PUT endpoint to write assignments is needed by Phase 10 (camera dropdown UI).
   - What's unclear: Should Phase 7 include `PUT /api/cameras/assignments/{entertainment_config_id}` as a stub, or leave it entirely to Phase 10?
   - Recommendation: Phase 7 should include the PUT endpoint as a thin DB write — it is pure data layer with no streaming dependencies. This keeps Phase 10 focused on UI and prevents Phase 10 needing to understand the DB schema details.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python `glob` | Device enumeration | ✓ | stdlib | — |
| Python `fcntl` | VIDIOC_QUERYCAP ioctl | ✓ | stdlib | — |
| Python `struct` | Buffer unpacking | ✓ | stdlib | — |
| `/sys/class/video4linux/` | Stable device identity | ✗ (WSL2 host) | — | VIDIOC_QUERYCAP card+bus_info (degraded mode) |
| `/dev/video*` | Any device enumeration | ✗ (WSL2 host, no capture card attached) | — | Empty list — scan returns [] |
| `aiosqlite` | DB migrations | ✓ | `>=0.20` in requirements.txt | — |
| `fastapi` + `pydantic` | Router + models | ✓ | `>=0.115` in requirements.txt | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- `/sys/class/video4linux/` — absent on WSL2 host; degraded identity mode handles this gracefully.
- `/dev/video*` devices — absent without capture card; scan returns empty list, which is correct behavior.

**Note:** Tests for device enumeration will use mocked `glob.glob` and `fcntl.ioctl` — no actual `/dev/video*` devices required in the test environment.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3 + pytest-asyncio 0.24 |
| Config file | `Backend/pytest.ini` (`asyncio_mode = auto`) |
| Quick run command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_cameras_router.py tests/test_database.py -x` |
| Full suite command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DEVC-01 | Metadata nodes excluded from scan results | unit | `pytest tests/test_device_enum.py::test_metadata_node_excluded -x` | ❌ Wave 0 |
| DEVC-01 | Only nodes with `V4L2_CAP_VIDEO_CAPTURE` included | unit | `pytest tests/test_device_enum.py::test_only_capture_nodes_returned -x` | ❌ Wave 0 |
| DEVC-02 | `GET /api/cameras` returns 200 with `devices` and `identity_mode` fields | unit | `pytest tests/test_cameras_router.py::TestListCameras::test_returns_200 -x` | ❌ Wave 0 |
| DEVC-02 | Response includes `device_path`, `stable_id`, `display_name` per device | unit | `pytest tests/test_cameras_router.py::TestListCameras::test_device_fields -x` | ❌ Wave 0 |
| DEVC-03 | Each call to `GET /api/cameras` triggers fresh scan (no cached state) | unit | `pytest tests/test_cameras_router.py::TestListCameras::test_no_cache -x` | ❌ Wave 0 |
| DEVC-04 | sysfs available: stable_id uses VID:PID:serial format | unit | `pytest tests/test_device_identity.py::test_sysfs_stable_id -x` | ❌ Wave 0 |
| DEVC-04 | sysfs unavailable: stable_id falls back to card@bus_info | unit | `pytest tests/test_device_identity.py::test_degraded_stable_id -x` | ❌ Wave 0 |
| DEVC-04 | sysfs unavailable: `identity_mode` is "degraded" in response | unit | `pytest tests/test_cameras_router.py::TestListCameras::test_degraded_identity_mode -x` | ❌ Wave 0 |
| DEVC-05 | `POST /api/cameras/reconnect` returns 200 with updated path when device found | unit | `pytest tests/test_cameras_router.py::TestReconnect::test_reconnect_found -x` | ❌ Wave 0 |
| DEVC-05 | `POST /api/cameras/reconnect` returns connected=false when device not found | unit | `pytest tests/test_cameras_router.py::TestReconnect::test_reconnect_not_found -x` | ❌ Wave 0 |
| CAMA-01 | `camera_assignments` table keyed by entertainment_config_id | unit | `pytest tests/test_database.py::test_camera_assignments_table_created -x` | ❌ Wave 0 |
| CAMA-02 | Assignment survives db close+reopen (persistence check) | unit | `pytest tests/test_database.py::test_camera_assignment_persists -x` | ❌ Wave 0 |
| CAMA-03 | Zone with no assignment: API returns no entry (fallback to env var handled upstream) | unit | `pytest tests/test_cameras_router.py::TestAssignment::test_no_assignment_returns_404 -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_cameras_router.py tests/test_device_enum.py tests/test_device_identity.py tests/test_database.py -x`
- **Per wave merge:** `python -m pytest` (full suite)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `Backend/tests/test_cameras_router.py` — covers DEVC-02, DEVC-03, DEVC-04, DEVC-05, CAMA-03
- [ ] `Backend/tests/test_device_enum.py` — covers DEVC-01; mock `glob.glob` + `fcntl.ioctl`
- [ ] `Backend/tests/test_device_identity.py` — covers DEVC-04 sysfs path; mock `builtins.open` for sysfs reads
- [ ] `Backend/services/device_identity.py` — new module (must exist before tests)
- [ ] `Backend/routers/cameras.py` — new router (must exist before router tests)

Note: `conftest.py` already has the `db` fixture and `app_client` pattern needed. New test files follow the `_make_capture_app_client` pattern from conftest.py — no new conftest additions required.

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 7 |
|-----------|-------------------|
| Python 3.12 pinned | No issue — all stdlib modules used are 3.12 compatible |
| No third-party Hue wrapper libraries | Not applicable to this phase |
| No `cv2.VideoCapture` for V4L2 | Confirmed — enumeration uses direct ioctl, not OpenCV |
| No `v4l2py` (it is a linuxpy shim) | Confirmed — not using either |
| No `pyudev` | Confirmed — using sysfs file reads directly |
| No `privileged: true` in docker-compose | Not changed in this phase (Docker changes are Phase 11) |
| No new camera manager service/process | `enumerate_capture_devices()` is a pure function, not a service |
| GSD workflow enforcement | Research/plan/execute through GSD only |
| Tests must pass: `python -m pytest` (167+) | New tests for cameras router and device enumeration modules |
| Frontend tests: `npx vitest run` (30+) | One new component change (sysfs alert in EditorPage.tsx) needs test coverage |

---

## Sources

### Primary (HIGH confidence)

- Existing `Backend/services/capture_v4l2.py` — VIDIOC_QUERYCAP constant `0x80685600`, buffer layout at offsets 0/16/48/80/84/88, `fcntl.ioctl` call pattern — all directly verified by reading the file
- Existing `Backend/database.py` — `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE try/except` migration pattern — directly verified
- Existing `Backend/routers/capture.py` — FastAPI `APIRouter(prefix=...)` + Pydantic `BaseModel` + `request.app.state` access pattern — directly verified
- Existing `Backend/main.py` — lifespan pattern, `app.include_router` pattern — directly verified
- Existing `Backend/tests/conftest.py` — `db` fixture (in-memory aiosqlite), `_make_capture_app_client` pattern — directly verified
- Kernel V4L2 docs: `v4l2_capability` struct layout, `V4L2_CAP_VIDEO_CAPTURE = 0x00000001` at `device_caps` field — confirmed against existing code
- WSL2 sysfs probe: `ls /sys/class/video4linux/` → NOT FOUND on this host — directly verified via bash

### Secondary (MEDIUM confidence)

- PyPI `linuxpy 0.24.0` — verified as current version via `pip3 index versions linuxpy`; CLAUDE.md recommendation to use ctypes fallback over linuxpy confirmed valid
- SQLite `INSERT OR REPLACE` / `INSERT ... ON CONFLICT DO UPDATE` (upsert) — standard SQLite behavior, well-documented, compatible with aiosqlite

### Tertiary (LOW confidence)

- sysfs availability in Docker containers with USB passthrough on WSL2 — expected to work on a real Linux host but unverified in this specific WSL2 setup; treated as bonus path only

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in requirements.txt; ctypes approach verified against existing code
- Architecture: HIGH — patterns directly traced from existing codebase; no novel patterns introduced
- Pitfalls: HIGH — sysfs absence verified directly; O_NONBLOCK and metadata node issues are documented kernel behaviors
- DB schema: HIGH — design directly from CONTEXT.md decisions, migration pattern verified from database.py
- Test architecture: HIGH — test patterns directly from conftest.py; no new framework needed

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (stable stdlib + SQLite domain; no fast-moving dependencies)
