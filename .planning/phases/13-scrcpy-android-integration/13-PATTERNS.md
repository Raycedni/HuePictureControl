# Phase 13: scrcpy Android Integration - Pattern Map

**Mapped:** 2026-04-16
**Files analyzed:** 5 new/modified files
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `Backend/services/pipeline_manager.py` | service | event-driven + streaming | itself (Phase 12 skeleton) | exact — modify in place |
| `Backend/routers/wireless.py` | route | request-response | itself (Phase 12 skeleton) | exact — extend in place |
| `Backend/models/wireless.py` | model | request-response | itself (Phase 12 skeleton) | exact — extend in place |
| `Backend/routers/cameras.py` | route | request-response | itself (current) | exact — small addition |
| `Backend/tests/test_pipeline_manager.py` | test | — | itself (Phase 12 tests) | exact — add test classes |
| `Backend/tests/test_wireless_router.py` | test | — | itself (Phase 12 tests) | exact — add test class |

---

## Pattern Assignments

### `Backend/services/pipeline_manager.py` (service, event-driven)

**Analog:** itself — this is a modify-in-place task extending the Phase 12 skeleton

**Imports pattern** (lines 1-20):
```python
import asyncio
import ipaddress
import logging
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from services.capture_service import CaptureRegistry
```
Add `import time` for stale-frame monitor — not yet present.

**WirelessSessionState dataclass pattern** (lines 24-40):
```python
@dataclass
class WirelessSessionState:
    session_id: str
    source_type: str               # "miracast" | "android_scrcpy"
    device_path: str
    device_nr: int
    card_label: str
    status: str = "starting"       # starting | active | error | stopped
    error_message: Optional[str] = None
    proc: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    producer_ready: asyncio.Event = field(default_factory=asyncio.Event)
    supervisor_task: Optional[asyncio.Task] = field(default=None, repr=False)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```
Phase 13 adds three new fields in the same style:
- `error_code: Optional[str] = None` — after `error_message` (D-04)
- `device_ip: Optional[str] = None` — after `error_code` (D-03)
- `stale_monitor_task: Optional[asyncio.Task] = field(default=None, repr=False)` — after `supervisor_task`

**asyncio.to_thread subprocess pattern** (lines 71-87 for `_create_v4l2_device`):
```python
await asyncio.to_thread(
    subprocess.run,
    ["sudo", "v4l2loopback-ctl", "add", "-n", card_label,
     "--exclusive_caps=1", device_path],
    check=True,
    capture_output=True,
    text=True,
)
```
The new `_run_adb_connect()` method follows this exact pattern — `asyncio.to_thread(subprocess.run, [...], capture_output=True, text=True, timeout=N)`. No `check=True` for ADB (returncode is unreliable; parse stdout/stderr instead).

**asyncio.create_subprocess_exec pattern** (lines 113-125 for `_launch_ffmpeg`):
```python
return await asyncio.create_subprocess_exec(
    "ffmpeg",
    "-rtsp_transport", "tcp",
    ...
    stderr=asyncio.subprocess.DEVNULL,
    stdout=asyncio.subprocess.DEVNULL,
)
```
The scrcpy launch in `start_android_scrcpy()` (lines 333-339) uses the same pattern but is missing `--no-video-playback`. Phase 13 adds that flag:
```python
session.proc = await asyncio.create_subprocess_exec(
    "scrcpy",
    "--v4l2-sink=/dev/video11",
    "--no-video-playback",      # NEW — headless server fix (Pitfall 1)
    f"--tcpip={device_ip}",
    stderr=asyncio.subprocess.DEVNULL,
    stdout=asyncio.subprocess.DEVNULL,
)
```

**producer-ready gate pattern** (lines 131-143 `_wait_for_producer`, lines 266-277 in `start_miracast`):
```python
asyncio.create_task(self._wait_for_producer(session))
try:
    await asyncio.wait_for(session.producer_ready.wait(), timeout=15.0)
except asyncio.TimeoutError:
    session.status = "error"
    session.error_message = "Producer did not start within 15s timeout"
    logger.error("Session %s: producer_ready timeout", session_id)
    raise RuntimeError(session.error_message)
```
Phase 13 adds `session.error_code = "producer_timeout"` before the `raise` line (D-04).

**supervised restart skeleton** (lines 195-222 `_restart_session`):
```python
async def _restart_session(self, session_id: str) -> None:
    session = self._sessions.get(session_id)
    if session is None:
        return
    try:
        if session.source_type == "miracast":
            logger.warning("Session %s: restart not fully supported...", session_id)
            return
        elif session.source_type == "android_scrcpy":
            logger.warning("Session %s: restart not fully supported...", session_id)
            return
        session.producer_ready.clear()
        asyncio.create_task(self._wait_for_producer(session))
        session.status = "active"
    except Exception as exc:
        logger.error("Session %s: restart failed: %s", session_id, exc)
        session.status = "error"
        session.error_message = f"Restart failed: {exc}"
```
Phase 13 replaces the `android_scrcpy` stub branch with the full ADB cycle + scrcpy relaunch (see RESEARCH.md code example).

**stop_session SIGTERM/SIGKILL pattern** (lines 378-420):
```python
session.status = "stopped"
if session.proc is not None:
    try:
        session.proc.terminate()
        try:
            await asyncio.wait_for(session.proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            session.proc.kill()
            await session.proc.wait()
    except Exception as exc:
        logger.warning("Session %s: process termination error: %s", session_id, exc)
# Cancel supervisor task
if session.supervisor_task is not None:
    session.supervisor_task.cancel()
    try:
        await session.supervisor_task
    except asyncio.CancelledError:
        pass
```
Phase 13 extends `stop_session` with:
1. Cancel `stale_monitor_task` — identical pattern to the supervisor_task cancellation block.
2. ADB disconnect after process kill — insert before `_cleanup_session_resources()`:
```python
if session.source_type == "android_scrcpy" and session.device_ip:
    try:
        await asyncio.to_thread(
            subprocess.run,
            ["adb", "disconnect", f"{session.device_ip}:5555"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as exc:
        logger.warning("Session %s: adb disconnect failed (best-effort): %s", session_id, exc)
```

**get_sessions dict serialization pattern** (lines 435-447):
```python
def get_sessions(self) -> list[dict]:
    return [
        {
            "session_id": s.session_id,
            "source_type": s.source_type,
            "device_path": s.device_path,
            "status": s.status,
            "error_message": s.error_message,
            "started_at": s.started_at,
        }
        for s in self._sessions.values()
    ]
```
Phase 13 adds `"error_code": s.error_code` to the dict (to match the updated model).

**New method: `_run_adb_connect()`** — no existing analog; follows `_create_v4l2_device` pattern (asyncio.to_thread + subprocess.run + parse output + return structured result):
```python
async def _run_adb_connect(self, device_ip: str) -> tuple[bool, str | None]:
    """Disconnect stale ADB state then connect. Returns (success, error_code | None)."""
    await asyncio.to_thread(
        subprocess.run,
        ["adb", "disconnect", f"{device_ip}:5555"],
        capture_output=True, text=True, timeout=5,
    )
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["adb", "connect", f"{device_ip}:5555"],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        return False, "adb_refused"
    output = (result.stdout + result.stderr).lower()
    if "connected to" in output or "already connected to" in output:
        return True, None
    if "unauthorized" in output:
        return False, "adb_unauthorized"
    return False, "adb_refused"
```

**New method: `_stale_frame_monitor()`** — follows `_supervise_session` task structure (asyncio loop + session status check + logger.warning + call _restart_session):
```python
async def _stale_frame_monitor(self, session_id: str) -> None:
    POLL_INTERVAL = 1.0
    STALE_THRESHOLD = 3.0
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        session = self._sessions.get(session_id)
        if session is None or session.status == "stopped":
            return
        if session.status == "error":
            continue  # _supervise_session already handling restart
        backend = self._capture_registry.get(session.device_path)
        if backend is None or backend._last_frame_time == 0:
            continue  # Not yet acquired or no first frame written
        elapsed = time.monotonic() - backend._last_frame_time
        if elapsed > STALE_THRESHOLD:
            logger.warning(
                "Session %s: stale frame (%.1fs) — triggering reconnect",
                session_id, elapsed,
            )
            session.status = "error"
            session.error_code = "wifi_timeout"
            session.error_message = f"No frame for {elapsed:.1f}s — reconnecting"
            await self._restart_session(session_id)
```
Note: `backend._last_frame_time` is a private attribute of `CaptureBackend` (line 47 of capture_service.py). Research recommends adding a public `@property last_frame_time -> float` to `CaptureBackend` base class to avoid accessing private state across modules.

**Task launch pattern for stale_monitor_task** (mirrors supervisor_task launch, lines 280-282):
```python
session.stale_monitor_task = asyncio.create_task(
    self._stale_frame_monitor(session_id)
)
```
This goes immediately after `session.supervisor_task = asyncio.create_task(...)` in `start_android_scrcpy()`.

---

### `Backend/routers/wireless.py` (route, request-response)

**Analog:** itself — extend in place

**Imports pattern** (lines 1-19):
```python
import asyncio
import logging

from fastapi import APIRouter, Request

from models.wireless import (
    CapabilitiesResponse,
    NicCapability,
    SessionsResponse,
    ToolInfo,
    WirelessSessionResponse,
)
```
Phase 13 adds to the import list:
```python
from fastapi import APIRouter, HTTPException, Request
from models.wireless import (
    ...,
    ScrcpyStartRequest,   # NEW
)
```

**app.state access pattern** (lines 94-96 in `list_sessions`):
```python
pipeline_manager = request.app.state.pipeline_manager
raw_sessions = pipeline_manager.get_sessions()
```
All new endpoints follow this pattern to access `pipeline_manager`.

**GET endpoint pattern** (lines 91-97):
```python
@router.get("/sessions", response_model=SessionsResponse)
async def list_sessions(request: Request) -> SessionsResponse:
    pipeline_manager = request.app.state.pipeline_manager
    raw_sessions = pipeline_manager.get_sessions()
    sessions = [WirelessSessionResponse(**s) for s in raw_sessions]
    return SessionsResponse(sessions=sessions)
```

**POST endpoint pattern** — copy from `list_sessions` structure but with body, 404/422 error handling:
```python
@router.post("/scrcpy", status_code=200)
async def start_scrcpy(
    body: ScrcpyStartRequest, request: Request
) -> WirelessSessionResponse:
    """Start an Android scrcpy session. Blocks until producer-ready (~15s max)."""
    pipeline_manager = request.app.state.pipeline_manager
    try:
        session_id = await pipeline_manager.start_android_scrcpy(body.device_ip)
    except RuntimeError as exc:
        session = pipeline_manager.get_session_by_ip(body.device_ip)
        error_code = session.error_code if session else "unknown"
        raise HTTPException(status_code=422, detail={
            "error_code": error_code,
            "message": str(exc),
        })
    session = pipeline_manager.get_session(session_id)
    return WirelessSessionResponse(
        session_id=session.session_id,
        source_type=session.source_type,
        device_path=session.device_path,
        status=session.status,
        error_message=session.error_message,
        error_code=session.error_code,
        started_at=session.started_at,
    )
```
Note: `get_session_by_ip()` is a new lookup helper on `PipelineManager` needed to find the session after a failed start. Alternative: store the session before raising in `start_android_scrcpy()` and look it up by session_id tracked in the exception.

**DELETE endpoint pattern** — 404 guard then delegate to service:
```python
@router.delete("/scrcpy/{session_id}", status_code=204)
async def stop_scrcpy(session_id: str, request: Request) -> None:
    """Stop a scrcpy session: kill scrcpy, disconnect ADB, destroy device."""
    pipeline_manager = request.app.state.pipeline_manager
    if pipeline_manager.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await pipeline_manager.stop_session(session_id)
```
The `HTTPException` with 404 pattern appears in `cameras.py` lines 247-250 and 306-309 — copy that guard structure exactly.

---

### `Backend/models/wireless.py` (model, request-response)

**Analog:** itself — extend in place

**Existing BaseModel pattern** (lines 1-35):
```python
from pydantic import BaseModel

class WirelessSessionResponse(BaseModel):
    session_id: str
    source_type: str
    device_path: str
    status: str
    error_message: str | None = None
    started_at: str
```

**Phase 13 changes:**

1. Add `error_code` field to `WirelessSessionResponse` after `error_message`:
```python
class WirelessSessionResponse(BaseModel):
    session_id: str
    source_type: str
    device_path: str
    status: str
    error_message: str | None = None
    error_code: str | None = None    # NEW — D-04
    started_at: str
```

2. Add new `ScrcpyStartRequest` model (follow `NicCapability` pattern — single-field BaseModel):
```python
class ScrcpyStartRequest(BaseModel):
    device_ip: str   # Validated by ipaddress.ip_address() in PipelineManager
```

---

### `Backend/routers/cameras.py` (route, request-response)

**Analog:** itself — small addition to `list_cameras` and `CameraDevice`

**CameraDevice model pattern** (lines 37-43):
```python
class CameraDevice(BaseModel):
    device_path: str
    stable_id: str
    display_name: str
    connected: bool
    last_seen_at: str | None
```
Phase 13 adds `is_wireless: bool = False` as the last field (D: open question 3 in RESEARCH.md — recommendation is to add explicit field).

**list_cameras endpoint pattern** (lines 151-231):
```python
@router.get("", response_model=CamerasResponse)
async def list_cameras(request: Request) -> CamerasResponse:
    db = request.app.state.db
    scan_results, any_degraded = await _scan_devices()
    ...
    devices.append(
        CameraDevice(
            device_path=device_path,
            stable_id=sid,
            display_name=row["display_name"],
            connected=connected,
            last_seen_at=row["last_seen_at"],
        )
    )
```
Phase 13 adds pipeline_manager access via `request.app.state.pipeline_manager` (same pattern as `wireless.py` line 94), builds `wireless_paths: set[str]`, and passes `is_wireless=device_path in wireless_paths` to `CameraDevice(...)`.

**app.state multi-attribute pattern** — `cameras.py` currently only reads `request.app.state.db`. After Phase 13 it will also read `pipeline_manager`. Copy the access pattern from `wireless.py`:
```python
pipeline_manager = getattr(request.app.state, "pipeline_manager", None)
wireless_paths: set[str] = set()
if pipeline_manager:
    for s in pipeline_manager.get_sessions():
        if s["status"] in ("active", "starting"):
            wireless_paths.add(s["device_path"])
```
Using `getattr(..., None)` is defensive — avoids AttributeError if cameras router is tested without pipeline_manager on app.state (as in existing `test_cameras_router.py` fixtures).

---

### `Backend/tests/test_pipeline_manager.py` (test, —)

**Analog:** itself — add new test classes to existing file

**Test class structure pattern** (lines 46-73, `TestDeviceCreation`):
```python
class TestDeviceCreation:
    @pytest.mark.asyncio
    @patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
    async def test_create_v4l2_device_correct_args(self, mock_to_thread, pm):
        mock_to_thread.return_value = MagicMock()
        result = await pm._create_v4l2_device(10, "Miracast Input")
        assert result == "/dev/video10"
        mock_to_thread.assert_called_once()
        call_args = mock_to_thread.call_args
        assert call_args[0][0] is subprocess.run
        cmd_list = call_args[0][1]
        assert "adb" in cmd_list   # pattern for new ADB tests
```

**Mock process factory** (lines 31-38):
```python
def _make_mock_process(returncode=None):
    proc = MagicMock()
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode or 0)
    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    return proc
```
Reuse unchanged for all Phase 13 process tests.

**Patching asyncio.create_subprocess_exec pattern** (lines 142-143, `TestSessionStart`):
```python
@patch("services.pipeline_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock)
@patch("services.pipeline_manager.asyncio.to_thread", new_callable=AsyncMock)
async def test_start_android_scrcpy_creates_session(self, mock_to_thread, mock_exec, pm):
    mock_proc = _make_mock_process(returncode=None)
    mock_exec.return_value = mock_proc
    mock_to_thread.return_value = MagicMock()
    async def fake_wait(session, delay=1.5):
        session.producer_ready.set()
    with patch.object(pm, "_wait_for_producer", side_effect=fake_wait):
        session_id = await pm.start_android_scrcpy("192.168.1.50")
```
New `TestScrcpyStart` class follows this exact fixture and patching pattern.

**WirelessSessionState direct construction pattern** (lines 204-213, `TestSessionStop`):
```python
session = WirelessSessionState(
    session_id="s1",
    source_type="android_scrcpy",
    device_path="/dev/video11",
    device_nr=11,
    card_label="Test",
)
session.proc = proc
pm._sessions["s1"] = session
```
New test classes for stale-frame monitor and restart tests follow this pattern to seed `_sessions` directly.

**New test classes to add:**
- `TestScrcpyStart` — tests for `_run_adb_connect()`, ADB connect called before scrcpy in `start_android_scrcpy`, `device_ip` stored on session, `--no-video-playback` in scrcpy args, producer_timeout error_code
- `TestStaleFrameMonitor` — tests for monitor stopping when session status="stopped", triggering restart when `_last_frame_time` stale, skipping restart when status="error"
- `TestRestartSession` — tests for android_scrcpy branch: ADB cycle called, scrcpy relaunched, error_code set on ADB failure
- `TestStopSessionAdbDisconnect` — tests for adb disconnect called for android_scrcpy sessions (not miracast)

---

### `Backend/tests/test_wireless_router.py` (test, —)

**Analog:** itself — add `TestScrcpyEndpoints` class

**App client factory pattern** (lines 12-25):
```python
def _make_wireless_app_client(mock_pm=None):
    if mock_pm is None:
        mock_pm = MagicMock()
        mock_pm.get_sessions = MagicMock(return_value=[])

    @asynccontextmanager
    async def lifespan(app):
        app.state.pipeline_manager = mock_pm
        yield

    test_app = FastAPI(lifespan=lifespan)
    test_app.include_router(wireless_router)
    return TestClient(test_app)
```
Reuse unchanged. New tests construct a `mock_pm` with `start_android_scrcpy` and `stop_session` mocked:
```python
mock_pm = MagicMock()
mock_pm.start_android_scrcpy = AsyncMock(return_value="sess-abc")
mock_pm.get_session = MagicMock(return_value=MagicMock(
    session_id="sess-abc",
    source_type="android_scrcpy",
    device_path="/dev/video11",
    status="active",
    error_message=None,
    error_code=None,
    started_at="2026-04-16T12:00:00Z",
))
mock_pm.stop_session = AsyncMock()
```

**Existing test assertion pattern** (lines 61-71, `TestSessionsEndpoint`):
```python
with _make_wireless_app_client(mock_pm) as client:
    resp = client.get("/api/wireless/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["sessions"]) == 1
```
New `TestScrcpyEndpoints` class follows this exact `with ... as client:` + `client.post()/client.delete()` + status code assertion pattern.

---

## Shared Patterns

### asyncio.to_thread for blocking subprocess calls
**Source:** `Backend/services/pipeline_manager.py` lines 71-87 (`_create_v4l2_device`)
**Apply to:** `_run_adb_connect()`, `stop_session()` ADB disconnect extension
```python
await asyncio.to_thread(
    subprocess.run,
    [...args...],
    capture_output=True,
    text=True,
    timeout=N,
)
```

### asyncio.create_subprocess_exec for long-running processes
**Source:** `Backend/services/pipeline_manager.py` lines 113-125 (`_launch_ffmpeg`)
**Apply to:** scrcpy launch in `start_android_scrcpy()` and `_restart_session()`
```python
proc = await asyncio.create_subprocess_exec(
    "tool", "--arg1", "--arg2",
    stderr=asyncio.subprocess.DEVNULL,
    stdout=asyncio.subprocess.DEVNULL,
)
```

### Asyncio task cancellation guard
**Source:** `Backend/services/pipeline_manager.py` lines 407-414 (`stop_session`)
**Apply to:** `stale_monitor_task` cancellation in `stop_session()`
```python
if session.supervisor_task is not None:
    session.supervisor_task.cancel()
    try:
        await session.supervisor_task
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.warning("Session %s: supervisor task error on cancel: %s", session_id, exc)
```

### HTTPException 404 guard
**Source:** `Backend/routers/cameras.py` lines 247-250 and 306-309
**Apply to:** `DELETE /api/wireless/scrcpy/{session_id}`
```python
if some_lookup is None:
    raise HTTPException(
        status_code=404,
        detail="Session not found",
    )
```

### Best-effort async operation with warning log
**Source:** `Backend/services/pipeline_manager.py` lines 224-237 (`_cleanup_session_resources`)
**Apply to:** ADB disconnect in `stop_session()` — always best-effort
```python
try:
    await asyncio.to_thread(...)
except Exception as exc:
    logger.warning("Session %s: <operation> failed (best-effort): %s", session_id, exc)
```

### IP address injection prevention
**Source:** `Backend/services/pipeline_manager.py` lines 313-319 (`start_android_scrcpy`)
**Apply to:** Retain as-is; `_run_adb_connect()` receives pre-validated IP from `start_android_scrcpy()`
```python
try:
    ipaddress.ip_address(device_ip)
except ValueError as exc:
    raise RuntimeError(f"Invalid device_ip '{device_ip}': must be a valid IP address") from exc
```

### Pydantic optional field with None default
**Source:** `Backend/models/wireless.py` line 30
**Apply to:** `error_code` in `WirelessSessionResponse`, `device_ip` and `error_code` in `WirelessSessionState`
```python
error_message: str | None = None
error_code: str | None = None    # same pattern
```

---

## No Analog Found

All Phase 13 files have close existing analogs in the codebase. No file requires falling back to external reference patterns.

---

## Metadata

**Analog search scope:** `Backend/services/`, `Backend/routers/`, `Backend/models/`, `Backend/tests/`
**Files scanned:** 6 source files + 2 test files read in full
**Pattern extraction date:** 2026-04-16
