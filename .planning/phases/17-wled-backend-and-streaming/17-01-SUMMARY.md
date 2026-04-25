---
phase: 17-wled-backend-and-streaming
plan: 01
subsystem: testing

requires:
  - phase: 16-zone-persistence-bug-fixes
    provides: clean streaming-state surface (active_config_id payload) reused by Wave 3 broadcaster extension
provides:
  - zeroconf>=0.148,<2 dependency in Backend/requirements.txt
  - Backend/tests/fixtures package marker
  - udp_listener context manager for asserting WLED packet bytes
  - make_mock_capture factory returning a deterministic 480x640x3 BGR frame
  - Windows-safe pytest collection (test_device_enum.py uses pytest.importorskip)
affects: ["17-02", "17-03", "17-04", "17-06", "17-09"]

tech-stack:
  added: ["zeroconf>=0.148,<2"]
  patterns:
    - "Test fixtures live in Backend/tests/fixtures/ (new package, no prior analog)"
    - "pytest.importorskip for OS-conditional test collection"

key-files:
  created:
    - "Backend/tests/fixtures/__init__.py"
    - "Backend/tests/fixtures/wled_loopback.py"
    - "Backend/tests/fixtures/mock_capture.py"
    - "Backend/tests/test_wled_loopback_fixture.py"
    - "Backend/tests/test_mock_capture_fixture.py"
  modified:
    - "Backend/requirements.txt"
    - "Backend/tests/test_device_enum.py"

key-decisions:
  - "Self-test ports use 41324 (ephemeral) not 21324 to avoid collision with any local WLED dev process"
  - "Fixture imports use 'tests.fixtures.X' (relative to Backend pytest rootdir), not 'Backend.tests.fixtures.X' — pytest config sets Backend as the rootdir"
  - "test_device_enum.py uses pytest.importorskip('fcntl') instead of pytest.mark.skipif because skipif does not prevent collection-time import failures"

patterns-established:
  - "udp_listener: SOCK_DGRAM + SO_REUSEADDR + threaded reader writing to thread-safe queue.Queue, settimeout 0.1s for clean shutdown"
  - "make_mock_capture: MagicMock + AsyncMock(return_value=frame) for wait_for_new_frame/get_frame, _last_frame_time=time.monotonic() for frame-age math"

requirements-completed:
  - WLED-01
  - WLED-02
  - WLED-03
  - WLED-04
  - WLED-05
  - WSTR-01
  - WSTR-02
  - WSTR-03
  - WSTR-04

duration: ~12min
completed: 2026-04-25
---

# Phase 17 Plan 01: Wave 0 Fixtures Summary

**zeroconf 0.148.0 pinned, UDP loopback listener + deterministic mock capture fixtures landed, Windows pytest collection unblocked.**

## Performance

- **Duration:** ~12 min (including venv reconstruction sub-fix)
- **Started:** 2026-04-25 inline
- **Completed:** 2026-04-25
- **Tasks:** 3 (plus 1 environmental side-fix)
- **Files modified:** 7 (5 created, 2 modified)

## Accomplishments

- `zeroconf>=0.148,<2` added to `Backend/requirements.txt` and installed in `/tmp/hpc-venv`. Verified `import zeroconf` and `from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf` both work. Version pinned away from yanked 1.0.0.
- `Backend/tests/fixtures/wled_loopback.py` exports `udp_listener(port, host)` — a context manager binding a `SOCK_DGRAM` socket on `127.0.0.1` with `SO_REUSEADDR`, draining packets on a background daemon thread into a thread-safe `queue.Queue`. Self-test sends a 5-byte DRGB payload and asserts byte-exact recv within 1 second.
- `Backend/tests/fixtures/mock_capture.py` exports `make_mock_capture(frame=None)` — returns a `MagicMock` with `AsyncMock` `wait_for_new_frame`/`get_frame`, no-op `open`/`release`, and `_last_frame_time` set to `time.monotonic()`. Default frame is a 480×640 BGR ndarray with three horizontal bands (red | green | blue) so downstream `sub_sample_gradient` tests can assert axis ordering.
- Side fix: `Backend/tests/test_device_enum.py` switched from bare `import fcntl` to `pytest.importorskip("fcntl")` so the test collects cleanly on Windows dev workstations (the project still runs natively on Linux for production).

## Task Commits

1. **Task 1: zeroconf dep in requirements.txt** — `16a4eb7` (feat)
2. **Task 2: udp_listener fixture + self-test** — `3b706cf` (test)
3. **Task 3: make_mock_capture fixture + self-test** — `d8b0f08` (test)
4. **Side fix: Windows pytest collection** — `d125cf0` (test)

## Files Created/Modified

- `Backend/requirements.txt` — added one line: `zeroconf>=0.148,<2`
- `Backend/tests/fixtures/__init__.py` — empty package marker
- `Backend/tests/fixtures/wled_loopback.py` — `udp_listener` context manager + `Packet` dataclass
- `Backend/tests/fixtures/mock_capture.py` — `make_mock_capture` factory + `_default_frame` helper
- `Backend/tests/test_wled_loopback_fixture.py` — fixture self-test
- `Backend/tests/test_mock_capture_fixture.py` — fixture self-tests (default frame + custom frame)
- `Backend/tests/test_device_enum.py` — replaced top-level `import fcntl` with `pytest.importorskip("fcntl")`

## Decisions Made

- **Ephemeral test port (41324) instead of 21324 in self-tests:** Avoids collision if a real WLED process is bound to the default WLED port on the dev machine. Production code still uses 21324 (set in Plan 03 module constants).
- **`pytest.importorskip` instead of `pytest.mark.skipif`:** `mark.skipif` runs at test execution time, but `import fcntl` fails at collection time on Windows. `importorskip` skips the whole module cleanly before any code below it runs.
- **Fixtures import path uses `tests.fixtures.X`:** The project's pytest rootdir is `Backend/` (per `pytest.ini`), so test files reference `tests.fixtures.wled_loopback` rather than `Backend.tests.fixtures.wled_loopback`. Matches existing test idioms in `Backend/tests/`.

## Deviations from Plan

**1. [Environmental] Recreated /tmp/hpc-venv from scratch**
- **Found during:** Task 1 (`pip install` step)
- **Issue:** Existing venv at `/tmp/hpc-venv` had a broken pip installation (`No module named pip.__main__` despite `pip-25.0.1.dist-info` present). The `pip/` package directory was missing its `__init__.py` — likely a corrupted state from a prior partially-failed install.
- **Fix:** `rm -rf /tmp/hpc-venv && py -3.12 -m venv /tmp/hpc-venv && python -m pip install -r Backend/requirements.txt`. New venv has working pip 25.0.1 and all backend deps.
- **Verification:** `python -c "import zeroconf; print(zeroconf.__version__)"` → `0.148.0`
- **Committed in:** N/A (venv is not tracked)

**2. [Plan completeness] Added Windows pytest skip side-fix**
- **Found during:** Task 1 verification (`python -m pytest -q`)
- **Issue:** Backend/tests/test_device_enum.py blocked test collection on Windows with `ModuleNotFoundError: No module named 'fcntl'`. This was a pre-existing gap (project targets native Linux per CLAUDE.md / user memory) but blocked our ability to do targeted test runs from Windows.
- **Fix:** Replaced `import fcntl` with `fcntl = pytest.importorskip("fcntl", reason=...)` so the module skips at collection time on Windows. Linux behavior unchanged.
- **Files modified:** Backend/tests/test_device_enum.py
- **Verification:** `pytest tests/test_device_enum.py -q` → `1 skipped` on Windows
- **Committed in:** d125cf0 (separate commit, not part of any task)

---

**Total deviations:** 2 (1 environmental, 1 environmental side-fix). Both essential to unblock execution on the dev workstation. No scope creep.

## Issues Encountered

- Three parallel executor agents crashed before producing commits (agent ae380cca made a partial requirements.txt edit but never committed; agents ad13c76d and aa0e39a4 never began work). User instructed inline sequential execution as fallback. Worktrees cleaned up; tasks executed inline against the main tree.

## User Setup Required

None — venv reconstruction handled inline; no external service configuration touched.

## Next Phase Readiness

- Wave 1 fixtures ready for Plans 17-02 (sub_sample_gradient tests use mock_capture's deterministic frame), 17-03 (packet builder tests assert exact bytes via udp_listener), 17-04 (WledStreamer integration tests against udp_listener), 17-06 (coordinator E2E tests).
- zeroconf importable, ready for Plan 17-03 wled_discovery and Plan 17-07 scan endpoint.

---
*Phase: 17-wled-backend-and-streaming*
*Plan: 01*
*Completed: 2026-04-25*
