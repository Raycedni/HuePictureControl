# Plan 16-02 Summary — StatusBroadcaster + StreamingService

**Status:** Complete
**Requirements:** BFIX-01, BFIX-02
**Commits:**
- `18cae9d` test(16-02): add failing tests for StatusBroadcaster active_config_id/device_path
- `c698274` feat(16-02): extend StatusBroadcaster with active_config_id/active_device_path
- `eaec812` test(16-02): add failing tests for StreamingService active kwargs at transitions
- `0dc706b` feat(16-02): wire active_config_id + active_device_path through StreamingService push_state calls

## What Was Built

### `Backend/services/status_broadcaster.py`
- `_metrics` dict extended with `active_config_id: None, active_device_path: None` as the default baseline so fresh connections see explicit null.
- `push_state(state, error=None, active_config_id=_UNSET, active_device_path=_UNSET)` — sentinel-based optional kwargs: when omitted, values are untouched; when explicitly passed (including `None`), the dict is updated. This lets `idle`/`error` transitions unambiguously clear the fields without clobbering them unintentionally.
- `update_metrics(data)` unchanged — used by the 50 Hz frame loop for non-state metrics (fps, latency, seq).

### `Backend/services/streaming_service.py` — all 8 `push_state` callsites wired
| Transition | Line | `active_config_id` | `active_device_path` |
|------------|------|-------------------|---------------------|
| start() → `starting` | ~95 | `config_id` | `device_path` |
| start() acquire error → `error` | ~106 | `None` | `None` |
| stop() → `stopping` | ~129 | `self._config_id` | `self._device_path` |
| stop() → `idle` | ~139 | `None` | `None` |
| _run_loop() → `streaming` | ~252 | `self._config_id` | `self._device_path` |
| _run_loop() RuntimeError → `error` | ~269 | `None` | `None` |
| _run_loop() generic Exception → `error` | ~281 | `None` | `None` |
| _capture_reconnect_loop → `reconnecting`/`streaming`/`error` | ~423 etc. | appropriately set/cleared | appropriately set/cleared |

### Tests
- `Backend/tests/test_status_broadcaster.py` (+ 101 lines): initial snapshot includes both new fields as null; `push_state` with explicit values sets them; `push_state` without kwargs preserves prior values; explicit `None` clears. Sentinel semantics explicitly verified.
- `Backend/tests/test_streaming_service.py` (+ 410 lines, new file content): 40+ tests covering every transition. Includes the split requested in W4 — `test_run_loop_runtime_error_clears_active` and `test_run_loop_generic_error_clears_active` each target one except branch; `test_stop_pushes_idle_with_none_active` is the authoritative idle-clear check.

## Test Result
All 60 tests pass locally (Windows venv): `60 passed in 10.59s`.

## Decisions Honored

| ID | Decision | Delivered By |
|----|----------|--------------|
| D-05 | Extend /ws/status with active fields | `_metrics` defaults + sentinel kwargs |
| D-06 | Payload fields `active_config_id`, `active_device_path`; null when idle/error | Every transition explicitly sets or clears |
| D-11 | Streaming overrides defaults on load | Frontend (Plan 16-03) reads from the WS payload; backend exposes it faithfully |

## Threat Model

| ID | Threat | Mitigation |
|----|--------|-----------|
| T-16-06 | Exposure of active streaming config via unauthenticated WS | UUIDs only; no secrets. Consistent with project no-auth LAN-tool policy. |
| T-16-07 | Stale "streaming" UI after crash/exit | `finally` and except branches unconditionally clear `active_*` to `None` — verified by split tests |

## Downstream Contract

Plan 16-03 consumes:
- `active_config_id` / `active_device_path` fields on `ws://.../ws/status` initial snapshot and every `push_state` event
- Semantic: non-null while starting/streaming/reconnecting; null on idle/error
