# Phase 12: Virtual Device Infrastructure - Pattern Map

**Mapped:** 2026-04-14
**Files analyzed:** 5 (3 new, 2 modified)
**Analogs found:** 5 / 5

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Backend/services/pipeline_manager.py` | service | event-driven (subprocess lifecycle) | `Backend/services/streaming_service.py` | role-match (same lifecycle pattern: start/stop/task/event) |
| `Backend/routers/wireless.py` | router | request-response | `Backend/routers/cameras.py` | exact (same: APIRouter + app.state service access + Pydantic models) |
| `Backend/models/wireless.py` | model | — | `Backend/models/hue.py` | exact (same: pure Pydantic BaseModel file, no logic) |
| `Backend/main.py` | config | — | `Backend/main.py` (self) | self-modification (add PipelineManager to lifespan) |
| `Backend/database.py` | config | — | `Backend/database.py` (self) | self-modification (idempotent table/migration pattern) |

---

## Pattern Assignments

### `Backend/services/pipeline_manager.py` (service, event-driven)

**Analog:** `Backend/services/streaming_service.py`

**Imports pattern** (`streaming_service.py` lines 1-25):
```python
import asyncio
import logging

from services.capture_service import CaptureRegistry

logger = logging.getLogger(__name__)
```
Copy only the imports needed: `asyncio`, `logging`, `subprocess` (stdlib), and `CaptureRegistry` from `services.capture_service`.

**Class constructor pattern** (`streaming_service.py` lines 50-61):
```python
class StreamingService:
    def __init__(self, db, capture_registry, broadcaster) -> None:
        self._db = db
        self._capture_registry = capture_registry
        self._capture = None
        self._device_path = None
        self._broadcaster = broadcaster
        self._run_event: asyncio.Event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._state: str = "idle"
```
For `PipelineManager`: replace per-stream state with `_sessions: dict[str, WirelessSessionState]`. Keep constructor signature `__init__(self, capture_registry: CaptureRegistry)`.

**asyncio.Task launch pattern** (`streaming_service.py` lines 103-104):
```python
self._run_event.set()
self._task = asyncio.create_task(self._run_loop(config_id))
```
For `PipelineManager`: each session gets its own `asyncio.Task` for `_supervise_session(session_id)`.

**Exponential backoff reconnect loop** (`streaming_service.py` lines 454-501):
```python
async def _capture_reconnect_loop(self) -> bool:
    delay = 1
    max_delay = 30

    while self._run_event.is_set():
        try:
            self._capture.release()
            await asyncio.to_thread(self._capture.open)
            # ... success check ...
            return True
        except Exception as exc:
            logger.warning("Capture reconnect failed: %s, retrying in %ds", exc, delay)
            try:
                self._capture.release()
            except Exception:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)

    return False
```
For `PipelineManager._supervise_session()`: same `delay = 1.0 / max_delay = 30 / max_retries = 5` structure but limited retries. Sequence: 1s, 2s, 4s, 8s, 16s.

**asyncio.to_thread for blocking calls** (`streaming_service.py` lines 96-97, 223-226):
```python
self._capture = await asyncio.to_thread(self._capture_registry.acquire, device_path)
# ...
await asyncio.to_thread(streaming.start_stream)
await asyncio.to_thread(streaming.set_color_space, "xyb")
```
All `subprocess.run(["sudo", "v4l2loopback-ctl", ...])` calls must use `await asyncio.to_thread(subprocess.run, [...], check=True, capture_output=True, text=True)`.

**Clean shutdown pattern** (`streaming_service.py` lines 58-66 in `main.py` lifespan + `streaming_service.py` lines 251-269):
```python
# finally block — guaranteed cleanup regardless of error path
finally:
    if streaming is not None:
        try:
            await asyncio.to_thread(streaming.stop_stream)
        except Exception:
            logger.warning("stop_stream failed (best-effort)")
    # ...
    if self._device_path:
        try:
            await asyncio.to_thread(self._capture_registry.release, self._device_path)
        except Exception:
            logger.warning("Registry release failed (best-effort)")
        self._device_path = None
```
For `stop_session()`: SIGTERM → `wait(timeout=5)` → SIGKILL, then `registry.release(device_path)`, then `v4l2loopback-ctl delete`. Wrap each step in try/except with `logger.warning`.

**asyncio.Event producer-ready gate** (RESEARCH.md Pattern 2):
```python
# Simple reliable implementation from RESEARCH.md
async def _wait_for_producer(proc: asyncio.subprocess.Process, event: asyncio.Event, delay: float = 1.5) -> None:
    await asyncio.sleep(delay)
    if proc.returncode is None:  # process still alive
        event.set()
    # else: process died — _supervise_session handles the error
```
Store `producer_ready: asyncio.Event` on `WirelessSessionState`. Call `await asyncio.wait_for(session.producer_ready.wait(), timeout=15.0)` before `registry.acquire()`.

**asyncio.create_subprocess_exec for FFmpeg** (RESEARCH.md Pattern 5):
```python
proc = await asyncio.create_subprocess_exec(
    "ffmpeg",
    "-rtsp_transport", "tcp",
    "-i", rtsp_url,
    "-vf", "scale=640:480",
    "-pix_fmt", "yuyv422",
    "-f", "v4l2",
    device_path,
    "-loglevel", "quiet",
    "-nostats",
    stderr=asyncio.subprocess.DEVNULL,
    stdout=asyncio.subprocess.DEVNULL,
)
```

**Process termination sequence** (RESEARCH.md VCAM-02):
```python
proc.terminate()
try:
    await asyncio.wait_for(proc.wait(), timeout=5.0)
except asyncio.TimeoutError:
    proc.kill()
    await proc.wait()
```

---

### `Backend/routers/wireless.py` (router, request-response)

**Analog:** `Backend/routers/cameras.py`

**Imports and router declaration** (`cameras.py` lines 1-29):
```python
"""Wireless session and capabilities REST endpoints.

Exports:
    router -- APIRouter for /api/wireless prefix
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wireless", tags=["wireless"])
```

**app.state service access pattern** (`cameras.py` lines 152-154, 235-237):
```python
@router.get("", response_model=CamerasResponse)
async def list_cameras(request: Request) -> CamerasResponse:
    db = request.app.state.db
    # ...
```
For wireless: `pipeline_manager = request.app.state.pipeline_manager`

**HTTPException 404 pattern** (`cameras.py` lines 252-256):
```python
if known_row is None:
    raise HTTPException(
        status_code=404,
        detail=f"stable_id '{body.stable_id}' not found in known cameras.",
    )
```
Use identical pattern for `GET /api/wireless/sessions/{session_id}` when session not found.

**Pydantic response model inline in router** (`cameras.py` lines 37-77):
```python
class CameraDevice(BaseModel):
    device_path: str
    stable_id: str
    display_name: str
    connected: bool
    last_seen_at: str | None
```
For wireless: define `WirelessSessionResponse` and `CapabilitiesResponse` in `models/wireless.py` (not inline) following the pattern in `models/hue.py`.

**One-shot async subprocess for tool detection** (RESEARCH.md Pattern 6):
```python
async def _check_tool(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        return True, stdout.decode().splitlines()[0] if stdout else ""
    except (FileNotFoundError, asyncio.TimeoutError):
        return False, ""
```
Called from `GET /api/wireless/capabilities` handler at request time (no caching per D-09).

---

### `Backend/models/wireless.py` (model, N/A)

**Analog:** `Backend/models/hue.py`

**File structure pattern** (`models/hue.py` lines 1-43):
```python
from pydantic import BaseModel


class ToolInfo(BaseModel):
    available: bool
    version: str


class NicCapability(BaseModel):
    p2p_supported: bool
    interface: str | None = None


class CapabilitiesResponse(BaseModel):
    ffmpeg: ToolInfo
    scrcpy: ToolInfo
    adb: ToolInfo
    iw: ToolInfo
    nic: NicCapability
    ready: bool


class WirelessSessionResponse(BaseModel):
    session_id: str
    source_type: str          # "miracast" | "android_scrcpy"
    device_path: str
    status: str               # "starting" | "active" | "error" | "stopped"
    error_message: str | None = None


class SessionsResponse(BaseModel):
    sessions: list[WirelessSessionResponse]
```
Pure Pydantic, no logic, no imports beyond `BaseModel`. Same single-file pattern as `models/hue.py`.

---

### `Backend/main.py` (modification — lifespan integration)

**Existing pattern to follow** (`main.py` lines 24-66):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open DB connection and initialize schema
    db = await init_db(DATABASE_PATH)
    app.state.db = db

    # Startup: create capture registry (lazy — no device opened at startup)
    registry = CaptureRegistry()
    app.state.capture_registry = registry

    # Startup: create StatusBroadcaster and StreamingService
    broadcaster = StatusBroadcaster()
    app.state.broadcaster = broadcaster

    streaming = StreamingService(db=db, capture_registry=registry, broadcaster=broadcaster)
    app.state.streaming = streaming

    yield

    # Shutdown: stop streaming if active (before releasing capture)
    if streaming.state not in ("idle",):
        await streaming.stop()

    # Shutdown: release all capture backends
    registry.shutdown()

    # Shutdown: close DB connection
    await close_db(db)
```

**Modification points:**
1. Add import: `from services.pipeline_manager import PipelineManager`
2. Add import: `from routers.wireless import router as wireless_router`
3. In startup block (after `registry = CaptureRegistry()`): `pipeline_manager = PipelineManager(capture_registry=registry)` then `app.state.pipeline_manager = pipeline_manager`
4. In shutdown block (BEFORE `registry.shutdown()`): `await asyncio.wait_for(pipeline_manager.stop_all(), timeout=5.0)`
5. After `app.include_router(preview_ws_router)`: `app.include_router(wireless_router)`

**Critical ordering in shutdown** (from RESEARCH.md Pattern 1): `pipeline_manager.stop_all()` MUST precede `registry.shutdown()`. Each `stop_session()` calls `registry.release(device_path)` — that must complete before the registry is forcibly torn down.

---

### `Backend/database.py` (modification — table addition)

**Existing idempotent migration pattern** (`database.py` lines 48-61):
```python
# Migration: add light_id column to existing databases that predate this column
try:
    await db.execute("ALTER TABLE regions ADD COLUMN light_id TEXT")
    await db.commit()
except Exception:
    # Column already exists — safe to ignore OperationalError
    pass
# Migration: add entertainment_config_id to regions for zone-camera join (Phase 9, D-08)
try:
    await db.execute("ALTER TABLE regions ADD COLUMN entertainment_config_id TEXT")
    await db.commit()
except Exception:
    # Column already exists — safe to ignore
    pass
```

**CREATE TABLE IF NOT EXISTS pattern** (`database.py` lines 63-84):
```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS known_cameras (
        stable_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        last_seen_at TEXT,
        last_device_path TEXT
    )
""")
```

**Modification:** Per D-01, wireless sessions are ephemeral (no DB table needed). `database.py` does NOT need modification unless Claude's discretion decides to add a `wireless_sessions` table for enumeration across restarts. Based on D-01 (memory-only), no DB change is warranted.

---

## Shared Patterns

### Logging Setup
**Source:** Every existing service and router
**Apply to:** `pipeline_manager.py`, `wireless.py`
```python
import logging
logger = logging.getLogger(__name__)
```
Always module-level `logger = logging.getLogger(__name__)`. Never pass loggers as constructor args.

### asyncio.to_thread for All Blocking Calls
**Source:** `Backend/services/streaming_service.py` lines 96-97, 223-226, 265-267
**Apply to:** `pipeline_manager.py` — all `subprocess.run()` calls (v4l2loopback-ctl add/delete) and `CaptureRegistry.acquire()/release()`
```python
# Correct pattern (non-blocking):
await asyncio.to_thread(subprocess.run, ["sudo", "v4l2loopback-ctl", ...], check=True, capture_output=True, text=True)
await asyncio.to_thread(self._capture_registry.acquire, device_path)
await asyncio.to_thread(self._capture_registry.release, device_path)

# Subprocess.run raises CalledProcessError on non-zero exit — catch and wrap as RuntimeError
```

### HTTPException Error Handling in Routers
**Source:** `Backend/routers/cameras.py` lines 252-256, `Backend/routers/capture.py` lines 75-83
**Apply to:** `routers/wireless.py`
```python
try:
    result = await backend.get_frame()
except RuntimeError as exc:
    logger.warning("...: %s", exc)
    raise HTTPException(status_code=503, detail=str(exc))
```
Service-level `RuntimeError` becomes HTTP 503. Missing resource becomes HTTP 404.

### Request Body + app.state Access Pattern
**Source:** `Backend/routers/capture.py` lines 37-48
**Apply to:** `routers/wireless.py` POST handler for session creation
```python
@router.post("/sessions")
async def start_session(body: StartSessionRequest, request: Request):
    pipeline_manager = request.app.state.pipeline_manager
    session_id = await pipeline_manager.start_miracast(rtsp_url=body.rtsp_url)
    return {"session_id": session_id, "status": "starting"}
```

### Test App Client Pattern
**Source:** `Backend/tests/conftest.py` lines 77-97 + `Backend/tests/test_cameras_router.py` lines 49-60
**Apply to:** `Backend/tests/test_wireless_router.py` and `Backend/tests/test_pipeline_manager.py`
```python
@asynccontextmanager
async def test_lifespan(app):
    app.state.pipeline_manager = mock_pipeline_manager
    yield

test_app = FastAPI(lifespan=test_lifespan)
test_app.include_router(wireless_router)
with TestClient(test_app) as client:
    yield client
```
Mock `PipelineManager` with `MagicMock()` and `AsyncMock()` for async methods (`start_miracast`, `stop_session`, `stop_all`, `get_sessions`).

---

## No Analog Found

All files have close analogs in the codebase. No files require purely research-based patterns.

| File | Role | Data Flow | Note |
|------|------|-----------|------|
| N/A | — | — | All files have analog matches |

---

## Metadata

**Analog search scope:** `Backend/services/`, `Backend/routers/`, `Backend/models/`, `Backend/main.py`, `Backend/database.py`, `Backend/tests/`
**Files scanned:** 22
**Pattern extraction date:** 2026-04-14
