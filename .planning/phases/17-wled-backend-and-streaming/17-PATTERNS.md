# Phase 17: WLED Backend and Streaming - Pattern Map

**Mapped:** 2026-04-20
**Files analyzed:** 18 (10 new / 8 modified)
**Analogs found:** 18 / 18 (all have strong codebase matches — project already ships every primitive pattern this phase needs)

## File Classification

### Backend — New
| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Backend/services/streaming_coordinator.py` | service (orchestrator) | frame-loop fan-out | `Backend/services/streaming_service.py` | exact (same domain, this IS the refactor target) |
| `Backend/services/wled_streamer.py` | service (sink) | per-frame UDP send | `Backend/services/streaming_service.py` | role-match (different protocol — DTLS→UDP) |
| `Backend/services/wled_client.py` | service (HTTP client) | request-response (JSON) | `Backend/services/hue_client.py` (`list_entertainment_configs`, `activate_entertainment_config`) | exact (same httpx/async pattern) |
| `Backend/services/wled_discovery.py` | service (discovery) | one-shot scan | `Backend/services/device_identity.py` + cameras `_scan_devices` helper | role-match (new primitive — zeroconf — but same `asyncio.to_thread`/one-shot pattern) |
| `Backend/routers/wled.py` | router (CRUD) | request→DB / request→device probe | `Backend/routers/cameras.py` | exact (CRUD + scan + enable toggle mirrors cameras CRUD + assignments + reconnect) |

### Backend — Modify
| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Backend/services/streaming_service.py` → `HueStreamer` | service (sink refactor) | per-frame DTLS send | (self — strip capture loop, keep bridge + set_input) | refactor-in-place |
| `Backend/services/status_broadcaster.py` | service (WS fan-out) | DB→WS payload | (self — extend `_metrics` and `push_state` kwargs) | extend-in-place |
| `Backend/routers/capture.py` | router (global start/stop) | request→service | (self — swap `streaming` for `coordinator` on `app.state`) | in-place-swap |
| `Backend/database.py` | schema | DDL at startup | (self — follow existing `CREATE TABLE IF NOT EXISTS` block pattern) | in-place-extend |
| `Backend/main.py` | lifespan | app-state wiring | (self — swap `StreamingService` → `StreamingCoordinator` in lifespan) | in-place-swap |
| `Backend/requirements.txt` | manifest | — | (self — add `zeroconf>=0.148,<2` line) | in-place-add |

### Frontend — New
| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Frontend/src/api/wled.ts` | API client | request-response | `Frontend/src/api/cameras.ts` | exact (same typed-fetch wrapper pattern, CRUD + scan) |
| `Frontend/src/components/Settings/WledDevicesPanel.tsx` | component (CRUD UI) | store→render + handler→API | `Frontend/src/components/LightPanel.tsx` (subsections: camera selector, streaming toggle) | role-match (panel with list + toggles + buttons; draggable items deferred to Phase 19) |
| `Frontend/src/components/Settings/SettingsPanel.tsx` | component (container) | layout-only | `Frontend/src/components/EditorPage.tsx` (flex layout + slot for LightPanel) | role-match (container that hosts panels) |
| `Frontend/src/hooks/useWledDevices.ts` (likely — not in CONTEXT but implied by pattern) | hook | polling + refresh | `Frontend/src/hooks/useCameras.ts` | exact |

### Frontend — Modify
| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Frontend/src/components/EditorPage.tsx` | component | entry point | (self — add Settings drawer trigger alongside `LightPanel`) | in-place-extend |
| `Frontend/src/store/useStatusStore.ts` | store | WS payload→state | (self — extend with `wledDevices` field mirroring D-16) | in-place-extend |
| `Frontend/src/hooks/useStatusWS.ts` | hook | WS message→store | (self — parse `wled_devices` into store) | in-place-extend |

### Backend — Tests (New)
| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Backend/tests/test_wled_streamer.py` | test | unit / packet bytes | `Backend/tests/test_streaming_service.py` (`_make_mocks`, frame-loop tests) | role-match |
| `Backend/tests/test_wled_router.py` | test | integration (TestClient + in-memory DB) | `Backend/tests/test_cameras_router.py` | exact |
| `Backend/tests/test_wled_client.py` | test | unit (mocked httpx) | `Backend/tests/test_hue_client.py` | exact |
| `Backend/tests/test_wled_discovery.py` | test | unit (mocked zeroconf) | (no direct analog — follow `test_hue_client.py` mock/patch idiom) | partial |
| `Backend/tests/test_database.py` (extend) | test | DDL assertions | (self — add `test_wled_tables_created`, `test_wled_device_persists` mirroring `test_known_cameras_table_created`) | in-place-extend |

---

## Pattern Assignments

### `Backend/services/streaming_coordinator.py` (service, orchestrator)

**Analog:** `Backend/services/streaming_service.py`

**Imports pattern** (lines 1-25):
```python
"""StreamingService: async class that owns the capture-to-DTLS streaming loop.
... """
import asyncio
import json
import logging
import time

from hue_entertainment_pykit import create_bridge, Entertainment, Streaming

from services.capture_service import CAPTURE_DEVICE
from services.color_math import extract_region_color, rgb_to_xy, build_polygon_mask
from services.hue_client import (
    activate_entertainment_config,
    deactivate_entertainment_config,
    resolve_light_to_channel_map,
)

logger = logging.getLogger(__name__)
```
Coordinator should drop `hue_entertainment_pykit` + `hue_client` imports (move to `HueStreamer`) and keep the capture/color_math imports.

**Lifecycle state-machine pattern** (lines 48-143, the `start`/`stop` pair):
```python
DEFAULT_HZ = 60

def __init__(self, db, capture_registry, broadcaster) -> None:
    self._db = db
    self._capture_registry = capture_registry
    self._capture = None
    self._device_path = None
    self._broadcaster = broadcaster
    self._run_event: asyncio.Event = asyncio.Event()
    self._task: asyncio.Task | None = None
    self._state: str = "idle"
    self._config_id: str | None = None
    ...

@property
def state(self) -> str:
    """Current streaming state: idle | starting | streaming | stopping | error."""
    return self._state

async def start(self, config_id: str, target_hz: int = DEFAULT_HZ) -> None:
    if self._state not in ("idle", "error"):
        return
    ...
    await self._broadcaster.push_state(
        self._state,
        active_config_id=config_id,
        active_device_path=device_path,
    )
    ...
    self._run_event.set()
    self._task = asyncio.create_task(self._run_loop(config_id))

async def stop(self) -> None:
    if self._state == "idle":
        return
    self._state = "stopping"
    await self._broadcaster.push_state(
        self._state,
        active_config_id=self._config_id,
        active_device_path=self._device_path,
    )
    self._run_event.clear()
    if self._task:
        await self._task
    self._state = "idle"
    await self._broadcaster.push_state(
        self._state,
        active_config_id=None,
        active_device_path=None,
    )
```
Keep this exact state surface — `state`, `start(config_id, target_hz)`, `stop()` — on the coordinator so `routers/capture.py` does not change beyond `app.state.streaming` → `app.state.coordinator`.

**Device resolution pattern** (lines 149-182):
```python
async def _resolve_device_path(self, config_id: str) -> str:
    async with await self._db.execute(
        "SELECT camera_stable_id FROM camera_assignments WHERE entertainment_config_id = ?",
        (config_id,),
    ) as cursor:
        assign_row = await cursor.fetchone()
    if assign_row is None:
        return CAPTURE_DEVICE
    stable_id = assign_row["camera_stable_id"]
    async with await self._db.execute(
        "SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
        (stable_id,),
    ) as cursor:
        cam_row = await cursor.fetchone()
    if cam_row is None or not cam_row["last_device_path"]:
        return CAPTURE_DEVICE
    return cam_row["last_device_path"]
```
Coordinator owns this unchanged (the existing `StreamingService._resolve_device_path`).

**Capture acquire/release pattern** (lines 102-112, 301-307):
```python
try:
    self._capture = await asyncio.to_thread(self._capture_registry.acquire, device_path)
except RuntimeError as exc:
    self._state = "error"
    await self._broadcaster.push_state("error", error=str(exc), active_config_id=None, active_device_path=None)
    return
...
# teardown:
if self._device_path:
    try:
        await asyncio.to_thread(self._capture_registry.release, self._device_path)
    except Exception:
        logger.warning("Registry release failed (best-effort)")
```

**Frame loop + fan-out pattern** (lines 389-491 of `_frame_loop`):
Coordinator's new `_frame_loop` keeps the top half unchanged (frame acquire, metrics, capture reconnect branch) but replaces the `for channel_id, mask in channel_map.items(): extract_region_color → rgb_to_xy → streaming.set_input` block with:
```python
# Per-region gradient (D-04, D-05)
region_gradients: dict[str, np.ndarray] = {}
for region_id, (region_mask, n) in self._region_plan.items():
    region_gradients[region_id] = sub_sample_gradient(frame, region_mask, n)

await self._hue.render(region_gradients)
await self._wled.render(region_gradients)

self._broadcaster.update_metrics({
    "fps": ...,
    "latency_ms": ...,
    "wled_devices": self._wled.health_snapshot(),
})
```
`region_plan` is computed once at stream start from existing `light_assignments` JOIN + `wled_light_assignments` JOIN, with `N_region = max(wled_range_width for channels assigned to region, else 1)`.

---

### `Backend/services/wled_streamer.py` (service, sink)

**Analog:** `Backend/services/streaming_service.py` (for sink lifecycle idioms) + `Backend/services/capture_service.py` `CaptureRegistry` (for threading.Lock + dict pattern)

**Imports pattern** (following existing service-module header style):
```python
"""WledStreamer: UDP sink that streams per-frame RGB data to WLED ESP32 devices.

Owns one SOCK_DGRAM socket per enabled device for the streaming session.
Protocol auto-selects between DRGB (<=490 LEDs) and DNRGB (>490 LEDs).
"""
import asyncio
import logging
import socket
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)
```

**Thread-safe device pool** (from `capture_service.py` lines 161-215, `CaptureRegistry`):
```python
class CaptureRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, CaptureBackend] = {}
        self._ref_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, device_path: str) -> CaptureBackend:
        with self._lock:
            if device_path not in self._backends:
                ...
            self._ref_counts[device_path] += 1
            return self._backends[device_path]
```
Mirror `threading.Lock` + dict idiom for `WledStreamer._devices` — Pitfall 6 in RESEARCH.md says toggling `enabled` from a FastAPI handler while the frame loop iterates requires this exact lock discipline.

**Error handling pattern** (from `streaming_service.py` lines 264-286):
```python
except RuntimeError as exc:
    logger.error("Capture error in run loop: %s", exc)
    self._run_event.clear()
    self._state = "error"
    await self._broadcaster.push_state("error", error=str(exc), ...)
```
But WLED per-device errors are isolated — they do NOT halt the coordinator. Use per-device counters + cooldown (D-15) rather than propagating to coordinator state.

**`asyncio.to_thread` for blocking syscalls** (`streaming_service.py` line 103, 245, 294):
```python
await asyncio.to_thread(self._capture_registry.acquire, device_path)
await asyncio.to_thread(streaming.start_stream)
await asyncio.to_thread(streaming.stop_stream)
```
`WledStreamer._send_to_device` batches all packets for one device in a single `asyncio.to_thread(_send_all)` call — see RESEARCH Pattern 4 and Anti-Pattern "One `to_thread` call per packet per device".

---

### `Backend/services/wled_client.py` (service, HTTP client)

**Analog:** `Backend/services/hue_client.py` — `list_entertainment_configs` (lines 75-100), `activate_entertainment_config` (lines 157-172)

**Imports pattern** (lines 1-12 of `hue_client.py`):
```python
"""Hue Bridge client functions for pairing, metadata fetch, and device discovery."""
import asyncio
import collections
import logging
import urllib3
import requests
import httpx

logger = logging.getLogger(__name__)
```
For WLED drop `requests`, `urllib3`, `collections` — use only `httpx` + `logging`.

**httpx.AsyncClient with timeout pattern** (lines 85-100):
```python
async def list_entertainment_configs(bridge_ip: str, username: str) -> list[dict]:
    url = f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration"
    headers = {"hue-application-key": username}
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        response = await client.get(url, headers=headers)
        data = response.json()
    configs = []
    for item in data.get("data", []):
        configs.append({
            "id": item["id"],
            "name": item["metadata"]["name"],
            ...
        })
    return configs
```
WLED uses `http://` (no TLS, no `verify=False`), no auth headers, 5s timeout. The skeleton is exactly the form shown in RESEARCH §Code Examples `fetch_wled_info`.

**raise_for_status pattern** (line 172):
```python
async with httpx.AsyncClient(verify=False, timeout=10) as client:
    resp = await client.put(url, json={"action": "start"}, headers=headers)
    resp.raise_for_status()
```
Router catches `httpx.HTTPError` / `httpx.HTTPStatusError` and maps to 502 (see `routers/regions.py` lines 100-104).

---

### `Backend/services/wled_discovery.py` (service, discovery)

**Analog:** No direct codebase analog for mDNS, but the `asyncio.to_thread` + one-shot blocking-wait pattern is identical to `capture_service.CaptureBackend.wait_for_new_frame` (lines 79-96) and cameras router `_scan_devices` (cameras.py lines 97-136).

**One-shot async scan pattern** (cameras.py lines 110-114):
```python
loop = asyncio.get_event_loop()
# enumerate_capture_devices performs ioctl/DirectShow probing — must run in thread
devices = await loop.run_in_executor(None, enumerate_capture_devices)
```
`wled_discovery.scan_for_wled_devices` uses `AsyncZeroconf` (native async) directly per RESEARCH Pattern 5 — no thread wrapping needed since the library is asyncio-native. But the function signature/shape matches: `async def scan_for_wled_devices(timeout_seconds: float = 3.0) -> list[dict]` returning `[{"ip", "name"}]`.

---

### `Backend/routers/wled.py` (router, CRUD + scan)

**Analog:** `Backend/routers/cameras.py`

**Imports + router prefix** (lines 1-29):
```python
"""Cameras REST endpoints.

Provides:
  GET  /api/cameras  — list all known capture devices with identity_mode
  POST /api/cameras/reconnect  — re-scan and match a device by stable_id
  ...
Exports:
    router -- APIRouter for /api/cameras prefix
"""
import asyncio
import logging
...
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
...
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/cameras", tags=["cameras"])
```
Mirror: `router = APIRouter(prefix="/api/wled", tags=["wled"])`.

**Pydantic model pattern** (lines 37-89):
```python
class CameraDevice(BaseModel):
    device_path: str
    stable_id: str
    display_name: str
    connected: bool
    last_seen_at: str | None
    last_entertainment_config_id: str | None

class CamerasResponse(BaseModel):
    devices: list[CameraDevice]
    identity_mode: str
    cameras_available: bool
    zone_health: list[ZoneHealth]

class ReconnectRequest(BaseModel):
    stable_id: str

class AssignmentRequest(BaseModel):
    camera_stable_id: str
    camera_name: str
```
WLED equivalents (RESEARCH §Code Examples): `WledDeviceIn`, `WledDeviceOut`, `WledDevicesResponse`, `WledEnabledRequest`, `WledScanCandidate`, `WledScanResponse`.

**GET list pattern with SQL + live state merge** (lines 162-249):
```python
@router.get("", response_model=CamerasResponse)
async def list_cameras(request: Request) -> CamerasResponse:
    db = request.app.state.db
    scan_results, any_degraded = await _scan_devices()
    if scan_results:
        await _upsert_known_cameras(db, scan_results)
    async with db.execute(
        """SELECT k.stable_id, k.display_name, k.last_seen_at, k.last_device_path, ...
           FROM known_cameras k LEFT JOIN camera_last_zone clz ..."""
    ) as cursor:
        known_rows = await cursor.fetchall()
    devices: list[CameraDevice] = []
    for row in known_rows:
        sid = row["stable_id"]
        if sid in scan_results:
            device_path = scan_results[sid]["device_path"]
            connected = True
        else:
            device_path = row["last_device_path"] or ""
            connected = False
        devices.append(CameraDevice(...))
    return CamerasResponse(devices=devices, ...)
```
`GET /api/wled/devices` merges persisted `wled_devices` rows with live `coordinator._wled.health_snapshot()` the same way — per Open Question 2 in RESEARCH: `connected = (last_success_at within last 5s)` during streaming, `False` otherwise.

**POST with external fetch pattern** (routers/hue.py lines 27-70):
```python
@router.post("/pair", response_model=PairResponse)
async def pair(body: PairRequest, request: Request) -> PairResponse:
    db = request.app.state.db
    try:
        credentials = pair_with_bridge(body.bridge_ip)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        raise HTTPException(status_code=502, detail=f"Bridge unreachable: {exc}")
    ...
    await db.execute(
        """INSERT OR REPLACE INTO bridge_config (id, bridge_id, rid, ip_address, ...)
           VALUES (1, :bridge_id, :rid, :ip_address, ...)""",
        {"bridge_id": meta["bridge_id"], ...},
    )
    await db.commit()
    return PairResponse(status="paired", ...)
```
`POST /api/wled/devices`: call `fetch_wled_info(ip)`, catch `httpx.HTTPError`/`httpx.ConnectError`/`httpx.TimeoutException` → 502 "WLED device unreachable"; catch `ValueError`/`KeyError` on malformed JSON → 422. INSERT into `wled_devices` and INSERT the seed `wled_channels` row in one transaction, then `await db.commit()`.

**UPSERT pattern** (cameras.py lines 143-154):
```python
await db.execute(
    """INSERT INTO known_cameras (stable_id, display_name, last_seen_at, last_device_path)
       VALUES (?, ?, ?, ?)
       ON CONFLICT(stable_id) DO UPDATE SET
           display_name = excluded.display_name,
           last_seen_at = excluded.last_seen_at,
           last_device_path = excluded.last_device_path""",
    (stable_id, info["display_name"], now, info["device_path"]),
)
await db.commit()
```

**DELETE with cascade (explicit, not FK)** (routers/regions.py lines 242-270):
```python
@router.delete("/{region_id}", status_code=204)
async def delete_region(region_id: str, request: Request):
    db = request.app.state.db
    async with db.execute("SELECT id FROM regions WHERE id=?", (region_id,)) as cursor:
        existing = await cursor.fetchone()
    if existing is None:
        raise HTTPException(status_code=404, detail="Region not found")
    await db.execute("DELETE FROM regions WHERE id=?", (region_id,))
    await db.execute("DELETE FROM light_assignments WHERE region_id=?", (region_id,))
    await db.commit()
    return Response(status_code=204)
```
Critical: RESEARCH Assumption A5 says SQLite FKs are NOT enforced in this project. DELETE handler for `/api/wled/devices/{id}` must explicitly cascade to `wled_channels` AND `wled_light_assignments`.

**404 validation pattern** (cameras.py lines 263-274):
```python
async with db.execute(
    "SELECT stable_id, display_name FROM known_cameras WHERE stable_id = ?",
    (body.stable_id,),
) as cursor:
    known_row = await cursor.fetchone()
if known_row is None:
    raise HTTPException(
        status_code=404,
        detail=f"stable_id '{body.stable_id}' not found in known cameras.",
    )
```

---

### `Backend/services/streaming_service.py` → `HueStreamer` refactor

**Analog:** itself. Retain bridge/DTLS/set_input portions; excise capture/broadcaster/state-machine portions (those move to coordinator).

**What to keep** (lines 205-262, bridge setup through `streaming.set_color_space`):
```python
bridge = create_bridge(
    identification=bridge_id, rid=rid, ip_address=bridge_ip,
    username=username, hue_app_id=hue_app_id, clientkey=client_key,
    swversion=swversion, name=name,
)
entertainment = Entertainment(bridge)
configs = entertainment.get_entertainment_configs()
config = configs.get(config_id) or list(configs.values())[0]
repo = entertainment.get_ent_conf_repo()
streaming = Streaming(bridge, config, repo)

await activate_entertainment_config(bridge_ip, username, config_id)
await asyncio.to_thread(streaming.start_stream)
await asyncio.to_thread(streaming.set_color_space, "xyb")
```
Move into `HueStreamer.start(config_id)`.

**What to keep** (lines 440-456, set_input per-channel loop):
```python
for channel_id, mask in channel_map.items():
    r, g, b = extract_region_color(frame, mask)
    x, y = rgb_to_xy(r, g, b)
    bri = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255.0
    bri = max(bri, 0.01)
    inputs.append((x, y, bri, channel_id))
try:
    for inp in inputs:
        streaming.set_input(inp)
    packets_sent += len(inputs)
except Exception as exc:
    logger.warning("Bridge socket error: %s, starting reconnect", exc)
    success = await self._reconnect_loop(...)
```
Move into `HueStreamer.render(region_gradients)`. Hue averages each region's gradient back to a single RGB (per D-05): `rgb = np.mean(gradient, axis=0).astype(np.uint8)`.

**What to keep** (lines 316-383, `_load_channel_map`): Move to `HueStreamer._load_channel_map`. Extend to ALSO emit per-region `N_region` (max LED-range width across WLED channels referencing the region — query new `wled_light_assignments` JOIN `wled_channels`) so the coordinator can build its `region_plan`.

**What to keep** (lines 558-595, `_reconnect_loop` — Hue bridge reconnect): Move into `HueStreamer`. Capture reconnect loop (lines 497-556) moves into `StreamingCoordinator`.

**Teardown pattern** (lines 288-310):
```python
await self._broadcaster.stop_heartbeat()
if streaming is not None:
    try:
        await asyncio.to_thread(streaming.stop_stream)
    except Exception:
        logger.warning("stop_stream failed (best-effort)")
if bridge_ip and username and self._config_id:
    await deactivate_entertainment_config(bridge_ip, username, self._config_id)
```
`HueStreamer.stop()` keeps `stop_stream` + `deactivate_entertainment_config`. Broadcaster heartbeat ownership moves to coordinator.

---

### `Backend/services/status_broadcaster.py` extension

**Analog:** itself (lines 25-91).

**Pattern to extend** (lines 25-36, `_metrics` init):
```python
def __init__(self) -> None:
    self._connections: list[WebSocket] = []
    self._metrics: dict = {
        "state": "idle",
        "fps": 0,
        "latency_ms": 0,
        "packets_sent": 0,
        "packets_dropped": 0,
        "seq": 0,
        "active_config_id": None,
        "active_device_path": None,
    }
```
Add: `"wled_devices": {}` (dict of `{device_id: {last_error, last_success_at, in_cooldown}}` per D-16).

**push_state _UNSET sentinel pattern** (lines 13, 64-91):
```python
_UNSET = object()

async def push_state(
    self,
    state: str,
    error: str | None = None,
    active_config_id: str | None | object = _UNSET,
    active_device_path: str | None | object = _UNSET,
) -> None:
    self._metrics["state"] = state
    if error is not None:
        self._metrics["error"] = error
    elif "error" in self._metrics:
        del self._metrics["error"]
    if active_config_id is not _UNSET:
        self._metrics["active_config_id"] = active_config_id
    if active_device_path is not _UNSET:
        self._metrics["active_device_path"] = active_device_path
    await self._send_to_all()
```
If `wled_devices` is updated through `update_metrics` (silent path at 1 Hz via heartbeat), no `push_state` kwarg needed. If an immediate broadcast on device registration/removal is wanted, add `wled_devices: dict | object = _UNSET` following the exact sentinel idiom.

---

### `Backend/routers/capture.py` modification

**Analog:** itself (lines 37-61).

**Swap-in-place pattern:**
```python
@router.post("/start")
async def start_capture(body: StartCaptureRequest, request: Request):
    streaming = request.app.state.streaming   # BEFORE
    await streaming.start(body.config_id, target_hz=body.target_hz)
    return {"status": "starting"}
```
After:
```python
@router.post("/start")
async def start_capture(body: StartCaptureRequest, request: Request):
    coordinator = request.app.state.coordinator   # AFTER
    await coordinator.start(body.config_id, target_hz=body.target_hz)
    return {"status": "starting"}
```
Grep check per RESEARCH `Grep targets for planner`:
- `Backend/routers/regions.py` line 109: `streaming = getattr(request.app.state, "streaming", None)` — also update to `coordinator`.
- `Backend/routers/capture.py` lines 47, 59 — update.
- `Backend/main.py` lines 53-54, 59-60 — update.
- `Backend/tests/conftest.py` line 191, 203-205, 169-177 — update test fixture `app.state.streaming` → `app.state.coordinator` and rename `_make_streaming_service_mock` to `_make_coordinator_mock`.

---

### `Backend/database.py` extension

**Analog:** itself (lines 17-91).

**CREATE TABLE IF NOT EXISTS pattern** (lines 62-91):
```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS light_assignments (
        region_id TEXT NOT NULL,
        channel_id INTEGER NOT NULL,
        entertainment_config_id TEXT NOT NULL,
        PRIMARY KEY (region_id, channel_id, entertainment_config_id)
    )
""")
await db.execute("""
    CREATE TABLE IF NOT EXISTS known_cameras (
        stable_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        last_seen_at TEXT,
        last_device_path TEXT
    )
""")
...
await db.commit()
```
Add three new `CREATE TABLE IF NOT EXISTS` blocks (exact DDL from CONTEXT.md D-07 and RESEARCH §Code Examples): `wled_devices`, `wled_channels`, `wled_light_assignments`. Place before the final `await db.commit()`.

---

### `Backend/main.py` lifespan modification

**Analog:** itself (lines 24-66).

**App-state wiring pattern** (lines 49-60):
```python
# Startup: create StatusBroadcaster and StreamingService
broadcaster = StatusBroadcaster()
app.state.broadcaster = broadcaster

streaming = StreamingService(db=db, capture_registry=registry, broadcaster=broadcaster)
app.state.streaming = streaming

yield

# Shutdown: stop streaming if active
if streaming.state not in ("idle",):
    await streaming.stop()
```
Replace with:
```python
broadcaster = StatusBroadcaster()
app.state.broadcaster = broadcaster

coordinator = StreamingCoordinator(db=db, capture_registry=registry, broadcaster=broadcaster)
app.state.coordinator = coordinator

yield

if coordinator.state not in ("idle",):
    await coordinator.stop()
```

**Router registration pattern** (lines 78-84):
```python
app.include_router(health_router)
app.include_router(hue_router)
app.include_router(capture_router)
app.include_router(cameras_router)
...
```
Append `app.include_router(wled_router)` after `cameras_router`.

---

### `Frontend/src/api/wled.ts` (API client)

**Analog:** `Frontend/src/api/cameras.ts`

**Full file pattern** (cameras.ts, 56 lines):
```typescript
export interface CameraDevice {
  device_path: string
  stable_id: string
  display_name: string
  connected: boolean
  last_seen_at: string | null
  last_entertainment_config_id: string | null
}

export interface CamerasResponse {
  devices: CameraDevice[]
  identity_mode: string
  cameras_available: boolean
  zone_health: ZoneHealth[]
}

export async function getCameras(): Promise<CamerasResponse> {
  const res = await fetch('/api/cameras')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function putCameraAssignment(
  configId: string, cameraStableId: string, cameraName: string,
): Promise<void> {
  const res = await fetch(`/api/cameras/assignments/${configId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ camera_stable_id: cameraStableId, camera_name: cameraName }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}
```
WLED analogs (mirror exact function signatures):
```typescript
export interface WledDevice {
  id: string
  ip: string
  name: string
  led_count: number
  enabled: boolean
  created_at: string
  connected: boolean
  last_error: string | null
}
export interface WledDevicesResponse { devices: WledDevice[] }
export interface WledScanCandidate { ip: string; name: string }
export interface WledScanResponse { candidates: WledScanCandidate[] }

export async function getWledDevices(): Promise<WledDevicesResponse>
export async function addWledDevice(ip: string): Promise<WledDevice>
export async function deleteWledDevice(id: string): Promise<void>
export async function setWledDeviceEnabled(id: string, enabled: boolean): Promise<void>
export async function scanWledDevices(): Promise<WledScanResponse>
```
Use same fetch boilerplate + `if (!res.ok) throw new Error(`HTTP ${res.status}`)` as cameras.ts. The typed error pattern with `.status` attached (see hue.ts lines 44-48) is used when callers need to distinguish 4xx — WLED's scan/add should use this form so the UI can distinguish "device unreachable" (502) from "bad IP format" (422).

---

### `Frontend/src/components/Settings/WledDevicesPanel.tsx` (component)

**Analog:** `Frontend/src/components/LightPanel.tsx` — specifically the Camera selector subsection (lines 254-295) and Streaming button (lines 299-316).

**Imports pattern** (LightPanel.tsx lines 1-9):
```typescript
import { useEffect, useMemo, useState } from 'react'
import { getLights, getEntertainmentConfigs, ... } from '@/api/hue'
import { fetchRegions, startStreaming, stopStreaming, ... } from '@/api/regions'
import { putCameraAssignment, putLastZone, type CamerasResponse } from '@/api/cameras'
import { useStatusStore } from '@/store/useStatusStore'
import { useRegionStore } from '@/store/useRegionStore'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
```
For WledDevicesPanel: import from `@/api/wled`, `@/store/useStatusStore` (for `wledDevices`), `@/components/ui/button`, `@/components/ui/badge`.

**List with connected badge pattern** (LightPanel.tsx lines 275-295):
```tsx
<div className="flex flex-col gap-2">
  <div className="flex items-center justify-between">
    <div className="flex items-center gap-1.5">
      <h2 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Camera</h2>
      {selectedCameraDisconnected && (
        <Badge variant="destructive" className="text-[10px] px-1.5 py-0.5">
          Disconnected
        </Badge>
      )}
    </div>
    <button onClick={onCamerasRefresh} className="p-0.5 text-muted-foreground hover:text-foreground">
      <svg className="w-3.5 h-3.5" ...><path d="..."/></svg>
    </button>
  </div>
  <select ...>
    {camerasData.devices.filter((d) => d.connected).map((d) => (
      <option key={d.device_path} value={d.device_path}>
        {d.display_name} ({d.device_path})
      </option>
    ))}
  </select>
</div>
```
For WLED: each device gets a row with name / IP / LED count / connected Badge / enabled toggle (Switch or button) / Remove button. A refresh affordance in the header runs `getWledDevices()`.

**Button with loading state pattern** (LightPanel.tsx lines 175-191, 303-316):
```tsx
async function handleToggleStreaming() {
  setStreamError(null)
  try {
    if (isStreaming) { await stopStreaming() }
    else {
      if (!selectedConfigId) { setStreamError('Select a config first'); return }
      await startStreaming(selectedConfigId)
    }
  } catch (err) {
    console.error('Streaming toggle failed:', err)
    setStreamError('Streaming action failed')
  }
}
...
<Button size="sm" onClick={handleToggleStreaming}
  className={isStreaming ? 'w-full bg-red-500/15 ...' : 'w-full bg-hue-orange/15 ...'}>
  {isStreaming ? 'Stop' : 'Start'}
</Button>
{streamError && <p className="text-xs text-red-400">{streamError}</p>}
```
For WLED: Add button after IP input, Scan button, per-row Remove button all use this pattern.

**Drag-drop pattern** (LightPanel.tsx lines 403-432):
NOT needed in Phase 17 (D-17 says CRUD only; Phase 19 owns paint UI). Document the slot in SettingsPanel layout where the paint canvas will live.

---

### `Frontend/src/components/Settings/SettingsPanel.tsx` (container)

**Analog:** `Frontend/src/components/EditorPage.tsx` — the flex container hosting LightPanel (lines 59-101).

**Flex layout + child panel pattern** (EditorPage.tsx lines 59-101):
```tsx
<div className="flex flex-col md:flex-row flex-1 min-h-0 text-left">
  <div className="flex flex-col flex-1 md:flex-[7] min-h-0">
    {/* main content area */}
  </div>
  <div className="flex md:flex-[3] min-h-0 overflow-hidden max-h-[40vh] md:max-h-none border-t md:border-t-0 border-white/[0.06]">
    <LightPanel ... />
  </div>
</div>
```
SettingsPanel slots a left pane (future Phase 19 paint canvas — placeholder div) and a right pane (WledDevicesPanel). Per D-20 "Phase 17 must leave room".

---

### `Frontend/src/store/useStatusStore.ts` extension

**Analog:** itself (lines 1-24).

**Store extension pattern:**
```typescript
interface StatusState {
  fps: number
  latency: number
  bridgeState: string
  error: string | null
  isStreaming: boolean
  activeConfigId: string | null
  activeDevicePath: string | null
  setMetrics: (m: Partial<Omit<StatusState, 'setMetrics'>>) => void
}
```
Add:
```typescript
wledDevices: Record<string, {
  last_error: string | null
  last_success_at: string | null
  in_cooldown: boolean
}>
```
Default in `create<StatusState>`: `wledDevices: {}`.

---

### `Frontend/src/hooks/useStatusWS.ts` extension

**Analog:** itself (lines 15-40).

**WS payload→store parse pattern** (lines 15-40):
```typescript
ws.onmessage = (ev: MessageEvent) => {
  try {
    const raw = JSON.parse(ev.data as string) as Record<string, unknown>
    useStatusStore.getState().setMetrics({
      fps: typeof raw.fps === 'number' ? raw.fps : undefined,
      latency: typeof raw.latency_ms === 'number' ? raw.latency_ms : undefined,
      bridgeState: typeof raw.state === 'string' ? raw.state : undefined,
      isStreaming: raw.state === 'streaming',
      error: typeof raw.error === 'string' ? raw.error : null,
      activeConfigId:
        typeof raw.active_config_id === 'string' ? raw.active_config_id :
        raw.active_config_id === null ? null : undefined,
      ...
    })
  } catch {}
}
```
Add:
```typescript
wledDevices:
  raw.wled_devices && typeof raw.wled_devices === 'object' && !Array.isArray(raw.wled_devices)
    ? (raw.wled_devices as Record<string, {...}>)
    : undefined,
```
`undefined` preserves existing state (Phase 16 tri-state convention); explicit `{}` clears on idle.

---

## Shared Patterns

### Authentication / Guards
None — the project has no auth (CLAUDE.md: "No auth: Web UI is unauthenticated — local network tool only"). WLED devices also have no auth. Do not add guards.

### Error Handling — Router Layer
**Source:** `Backend/routers/hue.py` lines 27-47; `Backend/routers/regions.py` lines 95-104; `Backend/routers/cameras.py` lines 263-274.
**Apply to:** `Backend/routers/wled.py` endpoints.
```python
try:
    info = await fetch_wled_info(body.ip)
except httpx.TimeoutException as exc:
    raise HTTPException(status_code=502, detail=f"WLED device unreachable: {exc}")
except httpx.HTTPError as exc:
    raise HTTPException(status_code=502, detail=f"WLED device returned error: {exc}")
except (ValueError, KeyError) as exc:
    raise HTTPException(status_code=422, detail=f"Invalid WLED response: {exc}")
```

### Error Handling — Service Layer (best-effort teardown)
**Source:** `Backend/services/streaming_service.py` lines 288-307; `Backend/services/hue_client.py` lines 315-319.
**Apply to:** `WledStreamer.stop()` (D-13 blackout + socket close), `StreamingCoordinator` teardown.
```python
try:
    await asyncio.to_thread(streaming.stop_stream)
except Exception:
    logger.warning("stop_stream failed (best-effort)")
```

### Logging
**Source:** Every backend module uses `logger = logging.getLogger(__name__)` at module top.
**Apply to:** All new backend files. Use `.info` for lifecycle, `.warning` for expected-but-notable failures (reconnect, best-effort), `.error` for state-transitioning failures, `.debug` for high-frequency events. RESEARCH D-15 says rate-limit per-device error logs at 5s per device — implement with a per-device `last_error_log_at: float` field in `WledStreamer._devices`.

### Validation
**Source:** Pydantic models with `Field(..., pattern=r"...")` for format checks (RESEARCH §Code Examples `WledDeviceIn.ip`).
**Apply to:** `routers/wled.py` request bodies. IP regex `^(\d{1,3}\.){3}\d{1,3}$` is the starting point from RESEARCH; add explicit `{enabled: bool}` validator on `WledEnabledRequest`.

### Response Formatting
All existing routers return Pydantic models with `response_model=` in the decorator (cameras.py lines 162, 252, 308). Do not return raw dicts except for simple status payloads like `{"status": "starting"}` (capture.py line 49). Apply to `routers/wled.py` — all GET/POST endpoints use `response_model=Wled...Response`.

### Database Access
**Source:** `Backend/routers/cameras.py` line 173, 184-192.
**Apply to:** All `routers/wled.py` handlers.
```python
db = request.app.state.db
async with db.execute("SELECT ... FROM ... WHERE ... = ?", (val,)) as cursor:
    rows = await cursor.fetchall()
...
await db.execute("INSERT ...", (...,))
await db.commit()
```

### Threading / Async Boundary
**Source:** `Backend/services/capture_service.py` `CaptureRegistry` (threading.Lock) + `streaming_service.py` `asyncio.to_thread` usage.
**Apply to:** `WledStreamer._devices` dict (threading.Lock) + `WledStreamer._send_to_device` (`asyncio.to_thread` wrapping blocking socket sends).

### Pydantic Typing Style
**Source:** `Backend/models/hue.py` and `Backend/routers/cameras.py` — all use `str | None` (PEP 604) and `list[X]` (PEP 585), not `Optional[str]` or `List[X]`. Python 3.12 style.
**Apply to:** All new Pydantic models in `routers/wled.py`.

### Frontend Fetch Wrapper
**Source:** `Frontend/src/api/cameras.ts` (minimal) and `Frontend/src/api/hue.ts` (typed error with `.status`).
**Apply to:** `Frontend/src/api/wled.ts`.

### Frontend Store Extension (not new store)
**Source:** `Frontend/src/store/useStatusStore.ts`. Only two Zustand stores exist: `useStatusStore` and `useRegionStore`.
**Apply to:** WLED device health. Extend `useStatusStore` with `wledDevices` field, not a new store (CONTEXT.md "Zustand store extension (not new store) for shared frontend state").

---

## Test Patterns

### Backend — Router Integration Test
**Source:** `Backend/tests/test_cameras_router.py` lines 39-172 (fixture + `_make_db` in-memory SQLite + TestClient).
**Apply to:** `Backend/tests/test_wled_router.py`.
```python
async def _make_db():
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("""CREATE TABLE IF NOT EXISTS wled_devices (...)""")
    await conn.execute("""CREATE TABLE IF NOT EXISTS wled_channels (...)""")
    await conn.execute("""CREATE TABLE IF NOT EXISTS wled_light_assignments (...)""")
    await conn.commit()
    return conn

def _make_wled_app(db_conn):
    from routers.wled import router as wled_router
    @asynccontextmanager
    async def test_lifespan(app):
        app.state.db = db_conn
        yield
    test_app = FastAPI(lifespan=test_lifespan)
    test_app.include_router(wled_router)
    return test_app
```
Patch `services.wled_client.fetch_wled_info` and `services.wled_discovery.scan_for_wled_devices` with `unittest.mock.patch` / `AsyncMock` (see test_cameras_router.py lines 108-118 for `patch("routers.cameras.enumerate_capture_devices", return_value=[...])`).

### Backend — Service Unit Test (mocked httpx)
**Source:** `Backend/tests/test_hue_client.py` lines 20-61 (`_make_httpx_client` helper + `patch("services.hue_client.httpx.AsyncClient", return_value=mock_client)`).
**Apply to:** `Backend/tests/test_wled_client.py`.
```python
def _make_httpx_client(response):
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client

@pytest.mark.asyncio
async def test_fetch_wled_info_parses_json():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={"name": "WLED Test", "leds": {"count": 100}, "ver": "0.14"})
    mock_client = _make_httpx_client(mock_resp)
    with patch("services.wled_client.httpx.AsyncClient", return_value=mock_client):
        info = await fetch_wled_info("192.168.1.50")
    assert info["name"] == "WLED Test"
    assert info["led_count"] == 100
```

### Backend — Streamer Unit Test
**Source:** `Backend/tests/test_streaming_service.py` lines 26-113 (`_make_mocks` + mock db cursor helpers).
**Apply to:** `Backend/tests/test_wled_streamer.py`. Mock `socket.socket` / `sock.sendto`, assert the exact bytes sent match DRGB/DNRGB packet layout (RESEARCH Pitfall 1: 489 max for DNRGB). Per Claude's Discretion in CONTEXT.md, either a local UDP listener bound to `127.0.0.1:21324` OR a mocked `socket.sendto` — recommend mocked for determinism.

### Backend — DB Schema Test
**Source:** `Backend/tests/test_database.py` lines 62-85 (pattern used for `known_cameras`, `camera_assignments`, `camera_last_zone`).
**Apply to:** Extend same file with `test_wled_devices_table_created`, `test_wled_channels_table_created`, `test_wled_light_assignments_table_created`, plus persistence tests (mirror `test_camera_assignment_persists` lines 88-114).

### Backend — conftest Mock Helpers
**Source:** `Backend/tests/conftest.py` lines 171-205 (`_make_streaming_service_mock`, `capture_app_client_with_streaming`).
**Apply to:** Add `_make_coordinator_mock` with `start`/`stop` as AsyncMock and `state` property returning `"idle"`. Update `capture_app_client_with_streaming` fixture to set `app.state.coordinator` (new) instead of `app.state.streaming` (old) — this is the ONE breaking test-fixture change from the refactor.

### Frontend — Component Test
**Source:** `Frontend/src/components/LightPanel.test.tsx` exists (confirmed via Glob) but not read here — planner should follow its fixture setup idiom for `WledDevicesPanel.test.tsx`.

---

## No Analog Found

Files with no close match in the codebase — planner should use RESEARCH.md patterns:

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `Backend/services/wled_discovery.py` | service (mDNS) | one-shot zeroconf scan | No mDNS library has been used in this project. RESEARCH Pattern 5 is the authoritative template. The general shape (async def with 3s timeout, return `list[dict]`) matches `_scan_devices` in `routers/cameras.py` but the internals are net-new. |
| Packet builder helpers (DRGB/DNRGB) inside `wled_streamer.py` | protocol codec | RGB array → UDP bytes | RESEARCH Patterns 2 + 3 provide exact implementation. Codebase has no protocol-builder analog beyond the V4L2 ioctl structs. |

These two are primitives that do not exist elsewhere in the project — the only authoritative guide is the WLED spec cited in RESEARCH. Use the verified excerpts verbatim.

---

## Metadata

**Analog search scope:**
- `Backend/services/` (all 11 files)
- `Backend/routers/` (all 8 files)
- `Backend/models/` (1 file)
- `Backend/tests/` (20 files sampled for fixtures)
- `Backend/database.py`, `Backend/main.py`, `Backend/requirements.txt`
- `Frontend/src/api/` (4 files)
- `Frontend/src/components/` (top-level files)
- `Frontend/src/store/` (2 files)
- `Frontend/src/hooks/` (4 files)

**Files read in full:** `main.py`, `database.py`, `services/streaming_service.py`, `services/status_broadcaster.py`, `services/hue_client.py`, `services/color_math.py`, `services/capture_service.py`, `routers/capture.py`, `routers/cameras.py`, `routers/regions.py`, `routers/hue.py`, `tests/conftest.py`, `tests/test_database.py`, `tests/test_hue_client.py`, `tests/test_capture_router.py`, `requirements.txt`, `models/hue.py`, `Frontend/src/api/cameras.ts`, `Frontend/src/api/hue.ts`, `Frontend/src/api/regions.ts`, `Frontend/src/store/useStatusStore.ts`, `Frontend/src/hooks/useStatusWS.ts`, `Frontend/src/hooks/useCameras.ts`, `Frontend/src/components/LightPanel.tsx`, `Frontend/src/components/EditorPage.tsx`.

**Files read in targeted sections:** `tests/test_streaming_service.py` (mocks), `tests/test_cameras_router.py` (fixtures).

**Pattern extraction date:** 2026-04-20.
