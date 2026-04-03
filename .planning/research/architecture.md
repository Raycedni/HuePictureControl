# Architecture Research

**Domain:** Multi-camera device management integrated into an existing single-capture ambient lighting system
**Researched:** 2026-04-03
**Confidence:** HIGH — based on direct code inspection of the existing implementation, no speculative claims

> This document supersedes the 2026-03-23 architecture.md for v1.1 milestone planning.
> It focuses entirely on the integration question: what changes vs what stays for multi-camera support.

---

## Standard Architecture

### System Overview (Current State — v1.0)

```
+------------------------------------------------------------------+
|  FastAPI Application (single process, asyncio event loop)        |
|                                                                   |
|  +---------------+  +--------------+  +----------------------+   |
|  | REST Routers  |  |  WebSockets  |  |  StreamingService    |   |
|  | /api/capture  |  | /ws/preview  |  |  (asyncio.Task)      |   |
|  | /api/regions  |  | /ws/status   |  |  50 Hz frame loop    |   |
|  +-------+-------+  +------+-------+  +-----------+----------+   |
|          |                 |                       |              |
|          +-----------------+-----------------------+              |
|                            |                                      |
|                  +---------+----------+                           |
|                  |  app.state         |                           |
|                  |  .capture  --------+---> single CaptureBackend |
|                  |  .streaming        |     (V4L2 or DirectShow)  |
|                  |  .broadcaster      |                           |
|                  |  .db               |                           |
|                  +--------------------+                           |
+------------------------------------------------------------------+
         |                                        |
  +------+------+                        +--------+--------+
  |  SQLite DB  |                        |  Hue Bridge     |
  | bridge_cfg  |                        |  REST CLIP v2   |
  | regions     |                        |  Entertainment  |
  | light_asgn  |                        |  API (DTLS/UDP) |
  +-------------+                        +-----------------+
```

**Current single-capture coupling points (exact lines that must change):**

| Location | Coupling |
|----------|---------|
| `main.py` lifespan | `capture = create_capture(CAPTURE_DEVICE)` — one backend at startup |
| `main.py` lifespan | `StreamingService(db, capture, broadcaster)` — single capture injected |
| `StreamingService._frame_loop` | `frame = await self._capture.get_frame()` — all channels share one frame |
| `preview_ws.py` | `capture = websocket.app.state.capture` — single capture for all previews |
| `capture.py` `/snapshot` | `capture_service = request.app.state.capture` — single capture for snapshot |
| `docker-compose.yaml` | `devices: [/dev/video0]` — single device passthrough |
| `database.py` `regions` table | no `camera_device` column — regions have no camera association |

---

### Target Architecture (v1.1 Multi-Camera)

```
+------------------------------------------------------------------+
|  FastAPI Application                                             |
|                                                                   |
|  +---------------+  +--------------+  +----------------------+   |
|  | REST Routers  |  |  WebSockets  |  |  StreamingService    |   |
|  | + /api/cameras|  | /ws/preview  |  |  (asyncio.Task)      |   |
|  |   enumerate   |  | ?device=N    |  |  per-zone dispatch   |   |
|  +-------+-------+  +------+-------+  +-----------+----------+   |
|          |                 |                       |              |
|          +-----------------+-----------------------+              |
|                            |                                      |
|                  +---------+--------------------+                 |
|                  |  app.state                   |                 |
|                  |  .capture_registry -----------+-> CaptureRegistry
|                  |  .streaming                  |   {path: Backend}
|                  |  .broadcaster                |   lazy open     |
|                  |  .db                         |                 |
|                  +------------------------------+                 |
+------------------------------------------------------------------+
         |                                        |
  +------+------+                        +--------+--------+
  |  SQLite DB  |                        |  Hue Bridge     |
  | + regions   |                        |  (unchanged)    |
  |   camera_   |                        |                 |
  |   device col|                        |                 |
  +-------------+                        +-----------------+
```

---

## Component Responsibilities

### Existing Components — Keep vs Modify

| Component | Status | What Changes |
|-----------|--------|--------------|
| `CaptureBackend` (abstract base) | Keep as-is | Interface already accepts `device_path` argument — no change needed |
| `V4L2Capture` | Keep as-is | Already parameterized by device path |
| `DirectShowCapture` | Keep as-is | Already parameterized by device index |
| `create_capture()` factory | Keep as-is | Already accepts `device_path` argument |
| `StreamingService` | Modify | Replace `self._capture` with per-zone dispatch through registry (see frame loop section) |
| `preview_ws.py` | Modify | Accept optional `?device=` query param to preview a specific camera |
| `capture.py` router | Modify | `/snapshot` needs optional device param; existing `/device` PUT stays but targets registry |
| `main.py` lifespan | Modify | Replace single `create_capture` with `CaptureRegistry` initialization |
| `database.py` | Modify | Add `camera_device` column migration to `regions` table |
| `docker-compose.yaml` | Modify | Enumerate and add all available video device entries |

### New Components — Must Be Added

| Component | Location | Responsibility |
|-----------|----------|---------------|
| `CaptureRegistry` | `services/capture_registry.py` | Pool of `CaptureBackend` instances keyed by device path. Lazy-opens on first request, tracks reference counts, releases when no longer needed. |
| `CameraEnumerator` | `services/camera_enumerator.py` | Probes `/dev/video0`..`/dev/video31` with `VIDIOC_QUERYCAP` on Linux (or `cv2.VideoCapture` index loop on Windows). Returns `[{path, name, index}]`. |
| `/api/cameras` router | `routers/cameras.py` | `GET /api/cameras` — thin wrapper over `CameraEnumerator`. Runs enumeration in `asyncio.to_thread`. |
| `CameraSelector` component | `Frontend/src/components/CameraSelector.tsx` | Dropdown per zone or per region. Calls `PUT /api/regions/{id}` with `camera_device` field. |
| Camera API client | `Frontend/src/api/cameras.ts` | `fetchCameras()` and optional `setRegionCamera(regionId, devicePath)` helper. |

---

## Data Flow Changes

### Frame Loop: Current vs Target

**Current** — single capture, all channels share one frame:

```
capture.get_frame()
    |
    +---> for each channel_id in channel_map:
              extract_region_color(frame, mask) -> color
              send to bridge
```

**Target** — per-zone camera, frames fetched per unique device:

```
group channel_map by camera_device
    |
    +-- device /dev/video0 -> [channel_1, channel_3]
    |       capture_registry.get(/dev/video0).get_frame()
    |           +-> for channel_1: extract_region_color(frame, mask_1)
    |           +-> for channel_3: extract_region_color(frame, mask_3)
    |
    +-- device /dev/video2 -> [channel_2]
            capture_registry.get(/dev/video2).get_frame()
                +-> for channel_2: extract_region_color(frame, mask_2)

asyncio.gather() all device reads concurrently, then send all colors to bridge
```

Both `get_frame()` calls run concurrently via `asyncio.gather` since each backend has its own reader thread and `get_frame()` is non-blocking.

### Channel Map Loading: Required SQL Change

`StreamingService._load_channel_map()` currently returns:
```python
{channel_id: mask_ndarray}
```

Must be extended to:
```python
{channel_id: (mask_ndarray, camera_device_path)}
```

The SQL query in `_load_channel_map` must JOIN `regions.camera_device` so the streaming loop knows which device to read for each channel. NULL values fall back to `CAPTURE_DEVICE` env var default.

### Preview WebSocket: Change Details

Currently `ws_preview` reads `app.state.capture` (single backend). Target:

```
ws://backend/ws/preview?device=/dev/video2
```

`preview_ws.py` reads the `device` query param, calls `capture_registry.get_or_open(device)`, streams from that backend. Falls back to the first available device if param is absent (backward compatibility).

---

## Database Schema Changes

### Migration: Add `camera_device` to `regions`

```sql
-- Follows the existing migration pattern already in database.py
ALTER TABLE regions ADD COLUMN camera_device TEXT;
```

- NULL means "use the system default device" — backward compatible with all existing regions
- Non-NULL is an absolute device path (e.g., `/dev/video0`, `/dev/video2`)

No new table is needed. Camera assignment is a property of the region, parallel to `light_id`.

### Updated `regions` Schema

```sql
CREATE TABLE IF NOT EXISTS regions (
    id TEXT PRIMARY KEY,
    name TEXT,
    polygon TEXT NOT NULL,
    order_index INTEGER DEFAULT 0,
    light_id TEXT,
    camera_device TEXT      -- NULL = default device, else /dev/videoN
);
```

### No Changes Required

- `bridge_config` — unchanged, bridge is shared across all cameras
- `light_assignments` — unchanged, channel-to-region mapping is camera-independent
- `entertainment_configs` — unchanged

---

## Recommended Project Structure (Changes Only)

```
Backend/
+-- services/
|   +-- capture_service.py      UNCHANGED — abstract base + factory
|   +-- capture_v4l2.py         UNCHANGED
|   +-- capture_dshow.py        UNCHANGED
|   +-- capture_registry.py     NEW — pool of CaptureBackend instances
|   +-- camera_enumerator.py    NEW — /dev/videoN discovery via VIDIOC_QUERYCAP
|   +-- streaming_service.py    MODIFY — per-zone camera dispatch
+-- routers/
|   +-- cameras.py              NEW — GET /api/cameras
|   +-- capture.py              MODIFY — snapshot + device param
|   +-- preview_ws.py           MODIFY — ?device= query param support
|   +-- regions.py              MODIFY — camera_device in CRUD responses
+-- database.py                 MODIFY — camera_device migration
+-- main.py                     MODIFY — CaptureRegistry in lifespan

Frontend/src/
+-- api/
|   +-- cameras.ts              NEW — fetchCameras()
|   +-- regions.ts              MODIFY — camera_device in Region type
+-- components/
|   +-- CameraSelector.tsx      NEW — per-zone dropdown
|   +-- LightPanel.tsx          MODIFY — embed or link CameraSelector
+-- store/
    +-- useRegionStore.ts       MODIFY — camera_device in Region model
```

---

## Architectural Patterns

### Pattern 1: Lazy-Open Capture Registry

**What:** A dict-keyed pool of `CaptureBackend` instances that opens devices on first request and tracks reference counts to know when to release.

**When to use:** Multiple zones may share the same camera (two regions both mapped to `/dev/video0`). The registry ensures only one backend instance per device path is ever open, preventing `EBUSY` errors from double-opening the same V4L2 device.

**Trade-offs:** Adds one layer of indirection. Reference counting must be managed carefully — decrement on zone removal or camera reassignment, release when count reaches 0. The simplest mitigation: `release_all()` on `streaming.stop()`, acquire fresh on `streaming.start()`.

```python
class CaptureRegistry:
    def __init__(self):
        self._backends: dict[str, CaptureBackend] = {}
        self._refcounts: dict[str, int] = {}

    def acquire(self, device_path: str) -> CaptureBackend:
        if device_path not in self._backends:
            backend = create_capture(device_path)
            backend.open()
            self._backends[device_path] = backend
            self._refcounts[device_path] = 0
        self._refcounts[device_path] += 1
        return self._backends[device_path]

    def release(self, device_path: str) -> None:
        self._refcounts[device_path] -= 1
        if self._refcounts[device_path] <= 0:
            self._backends[device_path].release()
            del self._backends[device_path]
            del self._refcounts[device_path]

    def release_all(self) -> None:
        for backend in self._backends.values():
            backend.release()
        self._backends.clear()
        self._refcounts.clear()
```

### Pattern 2: V4L2 Device Enumeration by QUERYCAP Probe

**What:** Discover available video devices by iterating `/dev/video0` through `/dev/video31` and probing each with `VIDIOC_QUERYCAP` ioctl. Devices that respond and have `V4L2_CAP_VIDEO_CAPTURE` set are valid capture sources.

**When to use:** Linux deployment target. On Windows, use `cv2.VideoCapture(index)` probe loop in `DirectShowCapture`.

**Trade-offs:** Probing 32 indices is fast (microseconds per absent node, a few milliseconds for real devices). `v4l2loopback` virtual devices appear as valid — this is intentional, allows virtual sources. Must be called via `asyncio.to_thread` to avoid blocking the event loop.

```python
def enumerate_v4l2_devices() -> list[dict]:
    # Reuses same ioctl approach already proven in capture_v4l2.py
    devices = []
    for i in range(32):
        path = f"/dev/video{i}"
        if not os.path.exists(path):
            continue
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            cap_buf = bytearray(104)
            fcntl.ioctl(fd, 0x80685600, cap_buf)   # VIDIOC_QUERYCAP
            caps = struct.unpack_from("<I", cap_buf, 88)[0]
            if caps & 0x01:                          # V4L2_CAP_VIDEO_CAPTURE
                card = cap_buf[8:40].rstrip(b'\x00').decode('utf-8', errors='replace')
                devices.append({"path": path, "name": card, "index": i})
        except OSError:
            pass
        finally:
            try: os.close(fd)
            except: pass
    return devices
```

### Pattern 3: Null-Safe Camera Device Fallback

**What:** When `region.camera_device` is NULL (existing regions pre-migration, or user has not selected a camera), the streaming loop falls back to the default device rather than erroring.

**When to use:** Always. Ensures backward compatibility for all existing configurations after the schema migration runs.

**Trade-offs:** Implicit fallback may produce surprising behavior if multiple cameras are connected and the user expects a specific one. Log a WARNING when fallback is used. Make the fallback deterministic: `CAPTURE_DEVICE` env var (already used in `main.py`) is the correct default.

---

## Data Flow

### Camera Selection Flow (New, Frontend-Initiated)

```
User opens LightPanel/EditorPage
    |
    v
GET /api/cameras  (on mount)
    |
CameraEnumerator.enumerate() via asyncio.to_thread
    |
    v  [{path: "/dev/video0", name: "USB3 Capture"}, ...]
    |
User selects /dev/video2 for Zone "Left Wall"
    |
    v
PUT /api/regions/{id}  body: {camera_device: "/dev/video2"}
    |
SQLite UPDATE regions SET camera_device = ? WHERE id = ?
    |
    v
useRegionStore.updateRegion() refreshes UI state
```

### Streaming Loop Flow (Modified)

```
streaming.start(config_id)
    |
    v
_load_channel_map(config_id)
    SQL: SELECT la.channel_id, r.polygon, r.camera_device
         FROM light_assignments la JOIN regions r ON r.id = la.region_id
         WHERE la.entertainment_config_id = ?
    returns: {channel_id: (mask, device_path_or_None)}
    |
    v
Group channels by unique device_path (NULL -> CAPTURE_DEVICE default)
    |
    v  CaptureRegistry.acquire(device) for each unique device
    |
_frame_loop():
    frames = await asyncio.gather(*(
        registry.get(device).get_frame()
        for device in unique_devices
    ), return_exceptions=True)
    for each (device, frame) in zip(unique_devices, frames):
        for channel in channels_for_device:
            extract_region_color(frame, mask) -> color
    send all colors to bridge in one batch
    |
streaming.stop()
    |  CaptureRegistry.release_all()
```

### Preview WebSocket Flow (Modified)

```
Browser connects ws://host/ws/preview?device=/dev/video2
    |
preview_ws.py reads ?device= query param
    |
    +-- if device param present and valid:
    |       capture = app.state.capture_registry.acquire(device)
    +-- else (no param or unknown device):
            capture = first open backend in registry, or open default
    |
stream jpeg frames from that capture backend
    (same 60fps cap and reconnect logic as current implementation)
```

---

## Scaling Considerations

This is a single-user local tool. The relevant dimension is simultaneous camera count, not user count.

| Camera Count | Behavior |
|-------------|----------|
| 1 (current baseline) | Registry manages one backend. Functionally identical to current single-capture path. |
| 2-4 (target for v1.1) | Registry manages 2-4 open backends, each with its own reader thread. CPU impact is negligible (reader threads sleep between frames). Memory: ~4MB per backend for 4 MJPEG mmap buffers at 640x480. |
| 5+ (not a goal, but possible) | USB 3.0 bandwidth becomes the limiting factor before the software architecture does. 4 simultaneous 1080p30 MJPEG streams saturate ~80% of USB 3.0. This is a hardware constraint, not an architecture problem. |

---

## Anti-Patterns

### Anti-Pattern 1: Opening the Same Device Twice

**What people do:** Call `create_capture(device_path)` and `.open()` per region or per streaming start without checking if the path is already open.

**Why it's wrong:** V4L2 returns `EBUSY` when a second fd opens a device already streaming. The second `open()` raises `RuntimeError` and the streaming loop fails to start.

**Do this instead:** Route all capture access through `CaptureRegistry`. The key-by-path guarantee means one backend per physical device, regardless of how many regions reference it.

### Anti-Pattern 2: Storing Device Assignments as Integer Indices

**What people do:** Store `camera_device` as `0`, `1`, `2` matching `cv2.VideoCapture(0)`.

**Why it's wrong:** Device indices are not stable across reboots or USB re-attach (confirmed in project memory: `feedback_docker_native.md`). `/dev/video0` today may be `/dev/video2` after USB re-plug. An integer index silently points at the wrong camera after any USB event.

**Do this instead:** Store absolute device paths (`/dev/video0`, `/dev/video2`). Display the human-readable name from `VIDIOC_QUERYCAP` (`card` field) in the UI, but persist the path. Detect path-no-longer-valid at `CaptureRegistry.acquire()` time and surface the error to the frontend via the `/api/cameras` endpoint showing the device as unavailable.

### Anti-Pattern 3: Fetching Frames Serially Across Multiple Cameras

**What people do:** `await camera_a.get_frame()` then `await camera_b.get_frame()` sequentially in the frame loop.

**Why it's wrong:** Each `get_frame()` is non-blocking (reader thread runs independently), but if either camera is stale or mid-reconnect, sequential calls compound wait times. With N cameras, N timeouts stack up, blowing the 50Hz frame budget.

**Do this instead:**
```python
frames = await asyncio.gather(*(
    registry.get(device).get_frame()
    for device in unique_devices
), return_exceptions=True)
```
Handle `RuntimeError` per-device without blocking other cameras.

### Anti-Pattern 4: Blocking the Event Loop in the Enumerator

**What people do:** Call `enumerate_v4l2_devices()` directly in a FastAPI route handler.

**Why it's wrong:** Probing 32 `/dev/videoN` paths involves syscalls. On slow USB hubs or unresponsive virtual devices, a single probe can block for tens of milliseconds, starving other requests.

**Do this instead:**
```python
@router.get("/api/cameras")
async def list_cameras():
    devices = await asyncio.to_thread(enumerate_v4l2_devices)
    return devices
```

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| V4L2 kernel subsystem | Direct ioctl via `fcntl.ioctl` — same approach already used in `capture_v4l2.py` | `VIDIOC_QUERYCAP` ioctl constant `0x80685600` and capability flag `0x01` are already proven in the codebase |
| Docker device passthrough | `devices:` list in `docker-compose.yaml` | Compose does not support wildcards (`/dev/video*`). Must list devices explicitly or use `cgroup_rules` — see pitfalls. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `cameras.py` router ↔ `CameraEnumerator` | Direct async call via `to_thread` | Enumerator is stateless, no shared state |
| `StreamingService` ↔ `CaptureRegistry` | Registry passed in constructor: `StreamingService(db, capture_registry, broadcaster)` — replaces current single `capture` arg | `StreamingService` acquires needed backends at `start()` time, releases all at `stop()` |
| `preview_ws.py` ↔ `CaptureRegistry` | `app.state.capture_registry` — same pattern as current `app.state.capture` | Preview WS must not hold registry references between requests — acquire and release per connection |
| Frontend `CameraSelector` ↔ `/api/cameras` | REST GET on component mount | Camera list fetched once, refreshed on user request (no polling needed) |
| Frontend `CameraSelector` ↔ `regions.ts` | `updateRegion(id, {camera_device})` — reuses existing PUT `/api/regions/{id}` | Only adds `camera_device` field to the already-existing `UpdateRegionRequest` Pydantic model |

---

## Build Order

Dependencies between components determine implementation sequence:

```
Step 1: DB migration (camera_device column)
            |
            v  (required by all backend changes)
Step 2: CameraEnumerator service
        /api/cameras router
            |
            v  (required by streaming + preview changes)
Step 3: CaptureRegistry service
            |
            +-------------------------------+
            v                               v
Step 4a: StreamingService modification    Step 4b: preview_ws.py modification
         (per-zone camera dispatch)                 (?device= query param)
         regions.py CRUD update
            |
            +-------------------------------+
            v
Step 5: Frontend cameras.ts API client
        Region type update (camera_device field)
            |
            v
Step 6: CameraSelector component
        LightPanel integration
            |
            v
Step 7: docker-compose.yaml device list expansion
        (can be done anytime after step 3, listed last because
         it only matters at container startup)
```

Steps 4a and 4b are independent of each other and can be developed in parallel.
Steps 5-6 (frontend) are independent of 4a/4b (backend) and can be developed in parallel once step 1-3 are complete.

**Natural phase boundary:** Steps 1-3 (infrastructure: migration + enumerator + registry) form a unit that can be tested independently — `GET /api/cameras` should return device list before any streaming changes are made. Steps 4-7 are the integration phase.

---

## Sources

- Direct code inspection: `Backend/services/capture_service.py` — abstract base, `create_capture` factory
- Direct code inspection: `Backend/services/capture_v4l2.py` — ioctl constants, QUERYCAP pattern already established
- Direct code inspection: `Backend/services/streaming_service.py` — `_frame_loop`, `_load_channel_map`, reconnect logic
- Direct code inspection: `Backend/main.py` — lifespan, single `capture` instantiation, `app.state` layout
- Direct code inspection: `Backend/routers/capture.py` — capture router endpoints
- Direct code inspection: `Backend/routers/preview_ws.py` — WebSocket preview, single `app.state.capture` reference
- Direct code inspection: `Backend/database.py` — schema, existing `ALTER TABLE` migration pattern
- Direct code inspection: `Frontend/src/api/regions.ts` — Region type, `updateRegion` signature
- Direct code inspection: `Frontend/src/store/useRegionStore.ts` — Region model in store
- Direct code inspection: `Frontend/src/components/LightPanel.tsx` — current UI integration point
- Prior v1.0 architecture research: `.planning/research/architecture.md` (2026-03-23)
- Project memory: `feedback_docker_native.md` — device path instability on USB re-attach (informs anti-pattern 2)

---

*Architecture research for: HuePictureControl v1.1 Multi-Camera Support*
*Researched: 2026-04-03*
