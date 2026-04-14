# Phase 8: Capture Registry - Research

**Researched:** 2026-04-03
**Domain:** Python resource pool, asyncio/threading concurrency, FastAPI lifespan wiring
**Confidence:** HIGH

## Summary

Phase 8 replaces a global `CaptureBackend` singleton with a `CaptureRegistry` — a dict-backed pool of `CaptureBackend` instances keyed by device path, with reference counting to manage lifetime. All decisions are locked in CONTEXT.md with high specificity, so there is very little design ambiguity.

The core challenge is thread-safety: `CaptureBackend.open()` and `release()` are blocking/synchronous, the registry is called from async FastAPI handlers, and two concurrent `start()` calls for different streaming zones must not race on the same device path. The existing codebase already uses `asyncio.to_thread` for blocking V4L2 operations and `threading.Lock` for per-backend frame protection — the same patterns apply here.

The second challenge is wiring: five files currently reference `app.state.capture` directly. Each consumer's migration scope is clearly bounded: `streaming_service.py` gets a full registry-aware rewrite of `start()`/`stop()`; `routers/capture.py` snapshot/debug endpoints need a fallback default device; `routers/preview_ws.py` keeps backward compatibility via a registry default (full per-zone routing is Phase 9).

**Primary recommendation:** Implement `CaptureRegistry` as a standalone class in `capture_service.py` (same file as `CaptureBackend` and `create_capture`). Use `threading.Lock` for registry mutations because callers mix sync and async contexts. Expose `acquire(device_path)` / `release(device_path)` / `shutdown()` public methods and a private `_get_default_backend()` helper for backward-compatible consumers.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** CaptureRegistry uses lazy instantiation — CaptureBackend instances are created on first `get(device_path)` call, not at startup.
- **D-02:** CaptureRegistry stored on `app.state.capture_registry`. Existing `app.state.capture` singleton is replaced — all consumers migrate to the registry.
- **D-03:** `create_capture(device_path)` factory (already in `capture_service.py`) is reused by the registry. No change to the factory itself.
- **D-04:** Reference counting tracks active StreamingService sessions per device. When ref count reaches zero the backend is released (handle freed).
- **D-05:** `acquire(device_path)` increments ref count (creates backend if first ref). `release(device_path)` decrements and destroys at zero.
- **D-06:** Forced cleanup during shutdown clears all refs and calls backend `release()` for all entries. Lifespan shutdown calls `registry.shutdown()`.
- **D-07:** StreamingService constructor changes to `__init__(self, db, capture_registry, broadcaster)`. `start(config_id)` looks up camera assignment from DB, then calls `registry.acquire(device_path)`.
- **D-08:** `stop()` calls `registry.release(device_path)` for the device it acquired.
- **D-09:** If no camera assignment exists for a config, fall back to `CAPTURE_DEVICE` env var (existing default behavior per CAMA-03).
- **D-10:** Each CaptureBackend instance has independent error/reconnect state. One failing camera does not affect other zones.
- **D-11:** Registry does NOT auto-reconnect failed backends. That is handled by StreamingService's existing `_capture_reconnect_loop` per-session.

### Claude's Discretion

- Thread safety strategy for the registry (threading.Lock vs asyncio.Lock) — Claude decides based on whether callers are sync or async.
- Whether `CaptureRegistry` is a standalone class or integrated into `capture_service.py` — either is fine.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MCAP-01 | StreamingService uses the assigned camera for each entertainment config instead of a global singleton | D-07/D-08/D-09: registry.acquire() in start(), registry.release() in stop(), DB lookup of camera_assignments |
| MCAP-03 | Multiple entertainment zones can stream simultaneously from different cameras | D-04/D-05: reference counting ensures two concurrent sessions hold independent CaptureBackend instances per device |

</phase_requirements>

## Standard Stack

### Core (all already in project — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `threading.Lock` | stdlib | Protect registry dict from concurrent mutations | Callers are mix of sync (open/release) and async (FastAPI routes via to_thread). asyncio.Lock would deadlock from sync context. |
| `asyncio.to_thread` | stdlib | Run `capture.open()` from async FastAPI context | Already the established pattern in `capture_service.py` and `streaming_service.py` |
| `aiosqlite` | >=0.20 | DB lookup of `camera_assignments` in StreamingService.start() | Already in requirements.txt |
| `os.getenv("CAPTURE_DEVICE")` | stdlib | Fallback device path per D-09/CAMA-03 | Already used in `capture_service.py` and `main.py` |

### No new packages required

The entire registry is pure Python using existing project dependencies. Do not add any new package to `requirements.txt`.

## Architecture Patterns

### Recommended Project Structure

No new files required. All changes are to existing files:

```
Backend/
├── services/
│   └── capture_service.py    # ADD CaptureRegistry class here (alongside CaptureBackend)
│   └── streaming_service.py  # MODIFY: accept registry, resolve device in start()
├── main.py                   # MODIFY: lifespan wiring
├── routers/
│   ├── capture.py            # MODIFY: snapshot/debug use registry default
│   └── preview_ws.py         # MODIFY: backward-compat default device (Phase 9 does routing)
└── tests/
    └── test_capture_registry.py    # NEW: registry unit tests
    └── test_streaming_service.py   # EXTEND: new registry-aware test cases
```

### Pattern 1: CaptureRegistry Class

**What:** A thread-safe dict pool with reference counting. `_backends` maps `device_path -> CaptureBackend`. `_ref_counts` maps `device_path -> int`. A single `threading.Lock` guards both dicts.

**When to use:** All acquisition and release of CaptureBackend instances goes through registry — never call `create_capture()` directly outside the registry.

**Structure:**
```python
# Source: project pattern from CaptureBackend + connection pool conventions
import threading
from services.capture_service import create_capture, CAPTURE_DEVICE, CaptureBackend

class CaptureRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, CaptureBackend] = {}
        self._ref_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, device_path: str) -> CaptureBackend:
        """Increment ref count; create and open backend if first ref."""
        with self._lock:
            if device_path not in self._backends:
                backend = create_capture(device_path)
                backend.open()
                self._backends[device_path] = backend
                self._ref_counts[device_path] = 0
            self._ref_counts[device_path] += 1
            return self._backends[device_path]

    def release(self, device_path: str) -> None:
        """Decrement ref count; destroy backend when count reaches zero."""
        with self._lock:
            if device_path not in self._ref_counts:
                return
            self._ref_counts[device_path] -= 1
            if self._ref_counts[device_path] <= 0:
                backend = self._backends.pop(device_path)
                self._ref_counts.pop(device_path)
                backend.release()

    def get_default(self) -> CaptureBackend | None:
        """Return backend for CAPTURE_DEVICE env var if present (backward compat)."""
        with self._lock:
            return self._backends.get(CAPTURE_DEVICE)

    def shutdown(self) -> None:
        """Release all backends regardless of ref count (called from lifespan)."""
        with self._lock:
            for backend in self._backends.values():
                try:
                    backend.release()
                except Exception:
                    pass
            self._backends.clear()
            self._ref_counts.clear()
```

**Why `threading.Lock` not `asyncio.Lock`:**

The registry `acquire()` call from `StreamingService.start()` runs inside the async event loop, but `backend.open()` inside `acquire()` is a blocking V4L2 ioctl. The caller wraps `registry.acquire()` in `asyncio.to_thread()` to avoid blocking the loop — meaning `acquire()` actually executes from a thread-pool thread. `asyncio.Lock` cannot be used from thread-pool threads; `threading.Lock` works from both sync and async contexts. This matches the existing pattern in `V4L2Capture._reader_loop` which uses `threading.Lock` for `_frame_lock`.

### Pattern 2: StreamingService Registry Integration

**What:** `StreamingService.__init__` accepts `capture_registry` instead of `capture`. `start()` looks up the camera assignment from DB, resolves `device_path` via `known_cameras`, then calls `registry.acquire()` wrapped in `asyncio.to_thread`. `stop()` / `_run_loop` finally block calls `registry.release()`.

**Critical detail — device_path lookup sequence in `start()`:**
1. Query `camera_assignments` for `config_id` → get `camera_stable_id`
2. Query `known_cameras` for `camera_stable_id` → get `last_device_path`
3. If no assignment or no known_cameras row: fall back to `CAPTURE_DEVICE` env var
4. Store resolved `device_path` on `self._device_path` for use in `stop()`/reconnect

```python
# Source: existing streaming_service.py patterns + D-07/D-08/D-09
async def start(self, config_id: str, target_hz: int = 50) -> None:
    if self._state not in ("idle", "error"):
        return
    # Resolve device path for this config
    device_path = await self._resolve_device_path(config_id)
    self._device_path = device_path
    # acquire is blocking (calls backend.open()) → run in thread
    self._capture = await asyncio.to_thread(self._capture_registry.acquire, device_path)
    ...

async def _resolve_device_path(self, config_id: str) -> str:
    """Look up camera assignment → known_cameras → fallback to env var."""
    async with await self._db.execute(
        "SELECT camera_stable_id FROM camera_assignments WHERE entertainment_config_id = ?",
        (config_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return CAPTURE_DEVICE
    async with await self._db.execute(
        "SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
        (row["camera_stable_id"],)
    ) as cursor:
        cam_row = await cursor.fetchone()
    if cam_row is None or not cam_row["last_device_path"]:
        return CAPTURE_DEVICE
    return cam_row["last_device_path"]
```

**`_run_loop` finally block change:**
```python
finally:
    # Replace: self._capture.release()
    # With:
    if self._device_path:
        await asyncio.to_thread(self._capture_registry.release, self._device_path)
```

**`_capture_reconnect_loop` change:** The reconnect loop calls `self._capture.release()` then `self._capture.open()`. With the registry, we should NOT call registry.release/acquire during reconnect — that would destroy and recreate the backend, losing the ref count. Instead, call `self._capture.release()` and `self._capture.open()` directly on the captured backend reference (`self._capture`) as before. The registry ref count stays at 1 throughout reconnect.

### Pattern 3: main.py Lifespan Wiring

**What:** Replace singleton creation with `CaptureRegistry()`. Remove `capture.open()` at startup (lazy per D-01). Pass `capture_registry` to `StreamingService`. Add `app.state.capture_registry`. Keep `app.state.capture` as a backward-compat shim pointing to the registry's default backend (or None).

```python
# Source: existing main.py pattern
from services.capture_service import create_capture, CaptureRegistry  # add CaptureRegistry

@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await init_db(DATABASE_PATH)
    app.state.db = db
    # ... region purge ...

    # Replace singleton with registry (lazy — no open() at startup)
    registry = CaptureRegistry()
    app.state.capture_registry = registry
    # Backward-compat shim for preview_ws and capture router snapshot
    # (Phase 9 will migrate preview_ws to per-zone routing)
    app.state.capture = registry  # registry exposes get_default() / fallback

    broadcaster = StatusBroadcaster()
    app.state.broadcaster = broadcaster

    streaming = StreamingService(db=db, capture_registry=registry, broadcaster=broadcaster)
    app.state.streaming = streaming

    yield

    if streaming.state not in ("idle",):
        await streaming.stop()
    registry.shutdown()
    await close_db(db)
```

**Note on `app.state.capture` backward compat:** `routers/capture.py` snapshot/debug and `routers/preview_ws.py` both do `app.state.capture.get_frame()` / `get_jpeg()`. Rather than touching those routers deeply in Phase 8, the simplest approach is to have the registry expose `get_frame()` and `get_jpeg()` as delegation to the default device — OR update the routers to call `app.state.capture_registry` with a fallback device. CONTEXT.md says preview migration is Phase 9. The planner should choose a minimal approach: update `capture.py` and `preview_ws.py` to use `app.state.capture_registry` with a helper that gets the default backend (falling back to `CAPTURE_DEVICE`).

### Pattern 4: Backward-compat for Snapshot and Preview Endpoints

**What:** `GET /api/capture/snapshot`, `GET /api/capture/debug/color`, `PUT /api/capture/device`, and `GET /ws/preview` all read `app.state.capture`. Phase 8 removes the singleton.

**Approach:** Add a helper function used by those endpoints:

```python
def _get_default_capture(registry):
    """Return CaptureBackend for CAPTURE_DEVICE, acquiring if needed."""
    from services.capture_service import CAPTURE_DEVICE
    backend = registry.get_default()
    if backend is None:
        # No session has opened it yet — open it directly for preview/snapshot use
        backend = registry.acquire(CAPTURE_DEVICE)
    return backend
```

This keeps Phase 8 backward-compatible without touching preview routing logic (Phase 9).

**`PUT /api/capture/device`** — this endpoint currently calls `capture_service.open(new_path)` to switch device. With the registry, this endpoint is largely superseded by camera assignments. For Phase 8, the simplest migration: update to use the registry's default device path, or deprecate by removing the handler and returning 410 Gone. The planner should deprecate it since camera assignment is the proper mechanism now. Document this in the plan.

### Anti-Patterns to Avoid

- **Calling `create_capture()` directly outside the registry:** All backend creation must go through `registry.acquire()` so ref counts are consistent.
- **Using `asyncio.Lock` for the registry:** Registry methods are called from thread-pool threads (via `asyncio.to_thread`). `asyncio.Lock` can only be acquired in a coroutine context, not from a thread.
- **Releasing the backend in `_capture_reconnect_loop`:** The reconnect loop calls `self._capture.release()` + `self._capture.open()` on the backend instance directly — this is intentional. Do NOT call `registry.release()` during reconnect as that would drop the ref count to zero and destroy the backend.
- **Opening the default device at startup:** D-01 says lazy instantiation. Snapshot/preview endpoints must handle the case where no backend is open yet (503 response is correct).
- **Shared `self._capture` between two concurrent zones on the same device:** If two zones are assigned the same device, `acquire()` returns the same `CaptureBackend` instance. Both zones share one reader thread. `release()` from zone 1 decrements to 1 (not zero), so zone 2 still has the device. This is correct behavior — the ref count prevents premature release.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Thread-safe reference counting | Custom atomic counter class | `threading.Lock` + plain dict — sufficient for this access pattern |
| Device path resolution | String manipulation or subprocess | DB query: `camera_assignments JOIN known_cameras` via aiosqlite |
| Async-safe registry methods | asyncio.Lock + coroutine wrappers | `threading.Lock` + `asyncio.to_thread()` at the call site |
| Reconnect logic | New reconnect in registry | Existing `_capture_reconnect_loop` in StreamingService — operates on `self._capture` directly |

## Common Pitfalls

### Pitfall 1: asyncio.Lock in thread-pool context

**What goes wrong:** If `CaptureRegistry` uses `asyncio.Lock`, calling `registry.acquire()` from inside `asyncio.to_thread()` raises `RuntimeError: no running event loop` or silently deadlocks because the lock belongs to a different event loop.

**Why it happens:** `asyncio.to_thread()` executes the function in a ThreadPoolExecutor thread. The thread has no running event loop, so `async with asyncio.Lock()` fails.

**How to avoid:** Use `threading.Lock`. It works from both coroutine context and thread-pool threads.

**Warning signs:** `RuntimeError: no running event loop` in test logs when registry.acquire() is called via to_thread.

### Pitfall 2: Double-release on shutdown when streaming is active

**What goes wrong:** Lifespan shutdown calls `streaming.stop()` (which calls `registry.release(device_path)`), then calls `registry.shutdown()` (which calls `backend.release()` on all remaining backends). If the ref count already reached zero during `streaming.stop()`, the backend was already released. `shutdown()` would try to release an already-released backend.

**Why it happens:** `registry.shutdown()` iterates `self._backends` — but if `release()` already popped the entry when count hit zero, there is nothing left to double-release. This is safe by design: `shutdown()` only releases entries still in `_backends` (i.e., with positive ref counts).

**How to avoid:** Ensure `release()` pops the entry from `_backends` when count hits zero. Then `shutdown()` finds an empty dict after a clean `streaming.stop()`.

**Warning signs:** `release()` called on an already-closed device raises `RuntimeError` from V4L2Capture.

### Pitfall 3: Two zones, same device — premature release

**What goes wrong:** Zone A and Zone B both acquire `/dev/video0`. Zone A stops first, calling `registry.release("/dev/video0")`. If ref counting is wrong, this destroys the backend while Zone B is still streaming.

**Why it happens:** Off-by-one in ref count, or release() doesn't check `> 0` before decrement.

**How to avoid:** `acquire()` always increments (starting from 0 → 1 on creation). `release()` decrements, destroys only when `<= 0`. Unit test: acquire twice, release once, verify backend still in registry.

**Warning signs:** Zone B's `_frame_loop` starts getting `RuntimeError("Capture device is not open")` immediately after Zone A stops.

### Pitfall 4: `_capture_reconnect_loop` bypasses registry

**What goes wrong:** `_capture_reconnect_loop` calls `self._capture.release()` then `self._capture.open()`. If someone adds a `registry.release()` call here, the ref count drops to zero and the backend is destroyed, breaking reconnect.

**Why it happens:** Confusion between "release the device for reconnect" (temporary, on the backend instance) and "release from the pool" (permanent, on the registry).

**How to avoid:** In `_capture_reconnect_loop`, keep calling `self._capture.release()` and `self._capture.open()` directly on the backend reference — never touch the registry inside the reconnect loop.

### Pitfall 5: No camera assignment + disconnected default device

**What goes wrong:** `_resolve_device_path()` returns `CAPTURE_DEVICE` as fallback. If `/dev/video0` is absent (no capture card plugged), `registry.acquire(CAPTURE_DEVICE)` calls `backend.open()` which raises `RuntimeError`. This exception propagates to `StreamingService.start()` and the state machine gets stuck.

**Why it happens:** The existing startup path (`capture.open()`) was wrapped in try/except in `main.py`. The new `acquire()` inside `start()` is not wrapped.

**How to avoid:** Wrap `await asyncio.to_thread(self._capture_registry.acquire, device_path)` in try/except in `start()`. On failure, transition to `error` state with a descriptive message. The state machine already handles `error` → `idle` transitions.

## Code Examples

### Registry unit test patterns

```python
# Source: existing test_capture_service.py pattern + threading.Lock conventions
from unittest.mock import MagicMock, patch

def test_acquire_creates_backend():
    with patch("services.capture_service.create_capture") as mock_factory:
        mock_backend = MagicMock()
        mock_factory.return_value = mock_backend
        registry = CaptureRegistry()
        backend = registry.acquire("/dev/video0")
        mock_factory.assert_called_once_with("/dev/video0")
        mock_backend.open.assert_called_once()
        assert backend is mock_backend

def test_acquire_twice_same_device_returns_same_backend():
    with patch("services.capture_service.create_capture") as mock_factory:
        mock_backend = MagicMock()
        mock_factory.return_value = mock_backend
        registry = CaptureRegistry()
        b1 = registry.acquire("/dev/video0")
        b2 = registry.acquire("/dev/video0")
        assert b1 is b2
        assert mock_factory.call_count == 1  # only created once
        assert mock_backend.open.call_count == 1

def test_release_at_zero_destroys_backend():
    with patch("services.capture_service.create_capture") as mock_factory:
        mock_backend = MagicMock()
        mock_factory.return_value = mock_backend
        registry = CaptureRegistry()
        registry.acquire("/dev/video0")
        registry.release("/dev/video0")
        mock_backend.release.assert_called_once()
        assert "/dev/video0" not in registry._backends

def test_two_zones_same_device_no_premature_release():
    with patch("services.capture_service.create_capture") as mock_factory:
        mock_backend = MagicMock()
        mock_factory.return_value = mock_backend
        registry = CaptureRegistry()
        registry.acquire("/dev/video0")
        registry.acquire("/dev/video0")
        registry.release("/dev/video0")  # zone A stops
        mock_backend.release.assert_not_called()  # zone B still holds it
        registry.release("/dev/video0")  # zone B stops
        mock_backend.release.assert_called_once()

def test_shutdown_releases_all():
    with patch("services.capture_service.create_capture") as mock_factory:
        mock_b0 = MagicMock(); mock_b1 = MagicMock()
        mock_factory.side_effect = [mock_b0, mock_b1]
        registry = CaptureRegistry()
        registry.acquire("/dev/video0")
        registry.acquire("/dev/video1")
        registry.shutdown()
        mock_b0.release.assert_called_once()
        mock_b1.release.assert_called_once()
```

### DB resolve pattern in StreamingService

```python
# Source: existing streaming_service.py aiosqlite pattern
async def _resolve_device_path(self, config_id: str) -> str:
    from services.capture_service import CAPTURE_DEVICE
    async with await self._db.execute(
        "SELECT camera_stable_id FROM camera_assignments WHERE entertainment_config_id = ?",
        (config_id,)
    ) as cursor:
        assign_row = await cursor.fetchone()
    if assign_row is None:
        return CAPTURE_DEVICE
    async with await self._db.execute(
        "SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
        (assign_row["camera_stable_id"],)
    ) as cursor:
        cam_row = await cursor.fetchone()
    if cam_row is None or not cam_row["last_device_path"]:
        return CAPTURE_DEVICE
    return cam_row["last_device_path"]
```

## Runtime State Inventory

> Not a rename/refactor phase — this section is omitted.

## Environment Availability

Step 2.6: SKIPPED — Phase 8 is a pure Python code change with no new external dependencies. All tools (Python 3.12, pytest, aiosqlite, V4L2 ioctls) are already verified present and in use.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (async via pytest-asyncio) |
| Config file | `Backend/pytest.ini` (or `pyproject.toml` — use existing) |
| Quick run command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_capture_registry.py tests/test_streaming_service.py -x -q` |
| Full suite command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest --tb=short -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MCAP-01 | StreamingService.start() acquires the assigned camera (not global singleton) | unit | `pytest tests/test_streaming_service.py -k "test_start_uses_assigned_camera" -x` | Wave 0 |
| MCAP-01 | StreamingService.stop() releases the device back to registry | unit | `pytest tests/test_streaming_service.py -k "test_stop_releases_device" -x` | Wave 0 |
| MCAP-01 | Fallback to CAPTURE_DEVICE when no camera assignment exists | unit | `pytest tests/test_streaming_service.py -k "test_no_assignment_uses_default" -x` | Wave 0 |
| MCAP-03 | Two zones with different devices both acquire without error | unit | `pytest tests/test_capture_registry.py -k "test_two_zones_different_devices" -x` | Wave 0 |
| MCAP-03 | Two zones sharing same device don't get premature release | unit | `pytest tests/test_capture_registry.py -k "test_two_zones_same_device_no_premature_release" -x` | Wave 0 |
| Success criterion 3 | Mid-stream camera switch (stop→reassign→start) opens new device, closes old | unit | `pytest tests/test_streaming_service.py -k "test_camera_reassignment_mid_stream" -x` | Wave 0 |
| STATE.md blocker | Reference counting edge cases during mid-stream camera switches | unit | `pytest tests/test_capture_registry.py -k "ref_count" -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_capture_registry.py tests/test_streaming_service.py -x -q`
- **Per wave merge:** `python -m pytest --tb=short -q`
- **Phase gate:** Full suite green (167+ existing + new tests) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `Backend/tests/test_capture_registry.py` — new file, covers registry unit tests
- [ ] `Backend/tests/test_streaming_service.py` — extend existing file with registry-aware test cases (do not replace existing tests)

*(No framework gaps — pytest + pytest-asyncio already installed and configured.)*

## Sources

### Primary (HIGH confidence)

- Direct codebase read: `Backend/services/capture_service.py` — CaptureBackend ABC, `create_capture()`, `CAPTURE_DEVICE`
- Direct codebase read: `Backend/services/streaming_service.py` — full `__init__`, `start()`, `stop()`, `_run_loop`, `_capture_reconnect_loop`
- Direct codebase read: `Backend/main.py` — lifespan pattern, `app.state` assignments
- Direct codebase read: `Backend/routers/capture.py` — all consumers of `app.state.capture`
- Direct codebase read: `Backend/routers/preview_ws.py` — `app.state.capture` usage
- Direct codebase read: `Backend/database.py` — `camera_assignments` + `known_cameras` schema
- Direct codebase read: `Backend/routers/cameras.py` — Phase 7 implementation of assignments endpoints
- Direct codebase read: `Backend/tests/conftest.py` + `test_streaming_service.py` — existing mock patterns
- Python docs: `threading.Lock` — confirmed safe from both sync and asyncio.to_thread contexts
- Python docs: `asyncio.to_thread` — confirmed wraps blocking calls in ThreadPoolExecutor

### Secondary (MEDIUM confidence)

- Python resource pool conventions (connection pool pattern): `acquire()` / `release()` naming is idiomatic for reference-counted pools

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — all libraries already in project, verified in codebase
- Architecture: HIGH — patterns directly derived from existing code; no new frameworks
- Pitfalls: HIGH — derived from code analysis of actual integration points
- Test patterns: HIGH — derived from existing conftest.py and test_streaming_service.py

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (stable codebase, no external API dependencies)
