---
phase: 13-scrcpy-android-integration
plan: 03
completed: 2026-04-18
status: complete
requirements: [SCPY-01, SCPY-03, SCPY-04]
---

# Plan 13-03: PipelineManager Unit Tests — Summary

## What Was Built

Added 18 new unit tests across 6 test classes to `Backend/tests/test_pipeline_manager.py`, covering all Phase 13 PipelineManager changes from Plan 01. All tests mock subprocess calls (adb, scrcpy, v4l2loopback-ctl) so they run on any platform — no Linux dependencies required.

## Test Classes Added

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestAdbConnect` | 6 | `_run_adb_connect()` — success, already-connected, unauthorized, refused, timeout, disconnect-first ordering |
| `TestScrcpyStartAdb` | 4 | `start_android_scrcpy()` ADB integration — device_ip storage, ADB connect called, failure raises, `--no-video-playback` flag |
| `TestStaleFrameMonitor` | 4 | `_stale_frame_monitor()` — stops on stopped/missing session, skips on error status, triggers restart on stale frame |
| `TestRestartSessionScrcpy` | 3 | `_restart_session()` android_scrcpy branch — ADB cycle called, error code on ADB failure, no-ip early return |
| `TestStopSessionAdbDisconnect` | 3 | `stop_session()` — ADB disconnect for scrcpy only, no ADB for miracast, stale_monitor_task cancelled |
| `TestGetSessionByIp` | 2 | `get_session_by_ip()` — matching session returned, unknown IP returns None |

## Key Decisions Applied

- **D-01 (stale-frame detection ~3s):** `test_monitor_triggers_restart_on_stale_frame` sets `last_frame_time` 5s in the past and verifies `_restart_session` is invoked with `error_code = "wifi_timeout"`.
- **D-02 (full ADB cycle on reconnect):** `test_adb_connect_calls_disconnect_first` verifies the first subprocess call is `disconnect` before `connect`.
- **D-03 (store device_ip):** `test_start_stores_device_ip` verifies `session.device_ip` is populated after `start_android_scrcpy`.
- **D-04 (error codes):** Tests verify `adb_unauthorized`, `adb_refused`, `wifi_timeout` are set in the correct failure paths.

## Key Files

- **Modified:** `Backend/tests/test_pipeline_manager.py` — added 420 lines covering 18 new tests
- **Tested against:** `Backend/services/pipeline_manager.py`, `Backend/services/capture_service.py`

## Deviations

- **Test `test_adb_connect_unauthorized` stderr wording:** Adjusted the mocked `stderr` to realistic ADB output (`"adb: device unauthorized..."` instead of stdout containing `"connected to"` with `"unauthorized"` in stderr). The implementation checks `"connected to" in output` first, so the original plan fixture would have incorrectly returned success. The corrected fixture matches how real ADB behaves on an unauthorized device.
- **Test `test_stop_cancels_stale_monitor_task` task mock:** Used a `FakeTask` class with a custom `__await__` that raises `CancelledError` instead of `MagicMock.__await__ = lambda ...`. `MagicMock` objects cannot have `__await__` assigned at the instance level due to dunder resolution rules.

## Commits

- `2c4b4cd` — test(13-03): add 18 unit tests for Phase 13 PipelineManager changes

## Verification

- `pytest tests/test_pipeline_manager.py -x -q` → 41 passed (23 existing + 18 new)
- `pytest tests/test_pipeline_manager.py tests/test_wireless_router.py -x -q` → 52 passed (no regressions)

## Requirements Coverage

- **SCPY-01:** ADB connect and scrcpy launch tested (TestAdbConnect + TestScrcpyStartAdb)
- **SCPY-03:** Stop session ADB disconnect tested (TestStopSessionAdbDisconnect)
- **SCPY-04:** Stale-frame monitor and restart lifecycle tested (TestStaleFrameMonitor + TestRestartSessionScrcpy)

## Next

Wave 2 complete. Phase 13 verification can proceed.
