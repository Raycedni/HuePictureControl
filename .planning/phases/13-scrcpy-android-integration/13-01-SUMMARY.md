---
phase: 13-scrcpy-android-integration
plan: "01"
subsystem: backend-wireless
tags: [pipeline-manager, adb, scrcpy, android, stale-frame-monitor, async]
dependency_graph:
  requires: [12-02]
  provides: [scrcpy-adb-lifecycle, stale-frame-watchdog, error-codes]
  affects: [Backend/services/pipeline_manager.py, Backend/models/wireless.py, Backend/services/capture_service.py]
tech_stack:
  added: []
  patterns:
    - "ADB WiFi lifecycle via subprocess: disconnect-first then connect for clean state"
    - "Stale-frame watchdog asyncio task polling CaptureBackend.last_frame_time every 1s"
    - "_run_adb_connect helper returning (success, error_code) tuple"
key_files:
  created: []
  modified:
    - Backend/services/pipeline_manager.py
    - Backend/models/wireless.py
    - Backend/services/capture_service.py
    - Backend/tests/test_pipeline_manager.py
decisions:
  - "Used _run_adb_connect as separate helper (not inlined) for testability and reuse in both start and restart paths"
  - "Stale-frame monitor uses public last_frame_time property (not private _last_frame_time) per plan guidance"
  - "Concurrent restart guard: stale monitor checks session.status == error before triggering restart, preventing double-restart race"
metrics:
  duration_minutes: 18
  completed_date: "2026-04-16"
  tasks_completed: 2
  files_modified: 4
---

# Phase 13 Plan 01: scrcpy Android Integration — Service Layer Summary

**One-liner:** ADB WiFi connect/disconnect lifecycle with stale-frame watchdog, functional restart, and structured error codes for Android scrcpy sessions.

## What Was Built

Closed three gaps in the Phase 12 PipelineManager skeleton that prevented real scrcpy usage:

1. **ADB lifecycle** — `_run_adb_connect(device_ip)` helper performs disconnect-first/connect cycle per D-02. Returns `(success, error_code)` where error codes are `adb_refused` or `adb_unauthorized`. Called in both `start_android_scrcpy` and `_restart_session`.

2. **Stale-frame watchdog** — `_stale_frame_monitor(session_id)` asyncio task polls `CaptureBackend.last_frame_time` every 1 second. If >3 seconds elapsed since last frame, marks session `error` with `error_code="wifi_timeout"` and calls `_restart_session`. Guard against double-restart: checks `session.status == "error"` before re-triggering.

3. **Functional restart** — `_restart_session` android_scrcpy branch now performs: kill old proc, full ADB cycle via `_run_adb_connect`, relaunch scrcpy with `--no-video-playback` flag (headless, no SDL window), reset producer_ready gate.

4. **Stop extension** — `stop_session` now cancels `stale_monitor_task` and runs `adb disconnect <ip>:5555` (best-effort) for android_scrcpy sessions per SCPY-03.

5. **Model updates** — `ScrcpyStartRequest(device_ip: str)` added to `models/wireless.py`. `error_code: str | None = None` added to `WirelessSessionResponse`. `get_sessions()` now returns `error_code` in dicts. `get_session_by_ip()` helper added.

6. **CaptureBackend property** — Public `last_frame_time -> float` property added to abstract base class, eliminating cross-module access to private `_last_frame_time`.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | `535c749` | Add ScrcpyStartRequest model, error_code field, last_frame_time property |
| Task 2 | `9cd4cef` | Extend PipelineManager with ADB lifecycle, stale-frame monitor, restart fix |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed broken test after new ADB step was added to start_android_scrcpy**

- **Found during:** Task 2 test run
- **Issue:** `test_start_android_scrcpy_creates_session` mocked `asyncio.to_thread` globally but the new `_run_adb_connect` call also uses `asyncio.to_thread`. The mock returned `MagicMock()` which had no `.stdout`/`.stderr` attributes, causing the ADB output check to fall through to `adb_refused` error code, making the test fail.
- **Fix:** Added `patch.object(pm, "_run_adb_connect", side_effect=fake_adb_connect)` to the test alongside the existing `_wait_for_producer` patch. Also asserts `session.device_ip == "192.168.1.50"` to verify D-03 storage.
- **Files modified:** `Backend/tests/test_pipeline_manager.py`
- **Commit:** `9cd4cef`

## Verification

All plan verification checks passed:
1. `from services.pipeline_manager import PipelineManager, WirelessSessionState` — imports OK
2. `from models.wireless import ScrcpyStartRequest, WirelessSessionResponse` — models OK
3. `hasattr(CaptureBackend, "last_frame_time")` — property OK
4. 68 directly-affected tests passed (pipeline_manager, wireless_router, capture_service, capture_registry)
5. 159 additional tests across all other test files — all passing

## Acceptance Criteria Status

- [x] WirelessSessionState has `error_code: Optional[str] = None` field
- [x] WirelessSessionState has `device_ip: Optional[str] = None` field
- [x] WirelessSessionState has `stale_monitor_task: Optional[asyncio.Task]` field
- [x] pipeline_manager.py contains `import time`
- [x] pipeline_manager.py contains `async def _run_adb_connect(self, device_ip: str) -> tuple[bool, str | None]:`
- [x] `_run_adb_connect` contains `"adb", "disconnect"` and `"adb", "connect"` subprocess calls
- [x] `_run_adb_connect` checks for `"unauthorized"` in output and returns `"adb_unauthorized"`
- [x] pipeline_manager.py contains `async def _stale_frame_monitor(self, session_id: str) -> None:`
- [x] `_stale_frame_monitor` accesses `backend.last_frame_time` (public property)
- [x] `_stale_frame_monitor` sets `session.error_code = "wifi_timeout"` on stale detection
- [x] `_restart_session` for `android_scrcpy` calls `self._run_adb_connect(session.device_ip)` and relaunches scrcpy with `--no-video-playback`
- [x] `start_android_scrcpy` calls `self._run_adb_connect(device_ip)` before scrcpy launch
- [x] `start_android_scrcpy` stores `session.device_ip = device_ip`
- [x] `start_android_scrcpy` includes `"--no-video-playback"` in scrcpy args
- [x] `start_android_scrcpy` sets `session.error_code = "producer_timeout"` on timeout
- [x] `start_android_scrcpy` creates `session.stale_monitor_task`
- [x] `stop_session` cancels `stale_monitor_task` if not None
- [x] `stop_session` calls `adb disconnect` for `android_scrcpy` sessions before cleanup
- [x] `get_sessions` returns dicts containing `"error_code"` key
- [x] `get_session_by_ip` method exists and returns session matching device_ip
- [x] Backend/models/wireless.py contains `class ScrcpyStartRequest(BaseModel):`
- [x] Backend/models/wireless.py contains `error_code: str | None = None` inside WirelessSessionResponse
- [x] Backend/services/capture_service.py contains `def last_frame_time(self) -> float:` decorated with `@property`

## Known Stubs

None — all functionality is fully wired. The stale-frame monitor and restart path are complete implementations, not stubs.

## Threat Flags

No new security surface introduced beyond what the plan's threat model addresses. `_run_adb_connect` receives pre-validated IP (validated by `ipaddress.ip_address()` in `start_android_scrcpy`), and subprocess calls use list args (no `shell=True`).

## Self-Check: PASSED

- `Backend/services/pipeline_manager.py` — modified, contains `_run_adb_connect`, `_stale_frame_monitor`, `get_session_by_ip`
- `Backend/models/wireless.py` — modified, contains `ScrcpyStartRequest`, `error_code` field
- `Backend/services/capture_service.py` — modified, contains `last_frame_time` property
- `Backend/tests/test_pipeline_manager.py` — modified, 19 tests all passing
- Commit `535c749` — verified in git log
- Commit `9cd4cef` — verified in git log
