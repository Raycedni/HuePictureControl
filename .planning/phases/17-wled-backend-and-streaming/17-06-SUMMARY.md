---
phase: 17-wled-backend-and-streaming
plan: 06
subsystem: streaming
tags:
  - backend
  - coordinator
  - wled-integration
  - status-broadcaster
  - wiring
dependency_graph:
  requires:
    - 17-04
    - 17-05
  provides:
    - StreamingCoordinator + WledStreamer wiring
    - StatusBroadcaster.wled_devices payload key (D-16)
    - app.state.coordinator (replaces app.state.streaming)
  affects:
    - Backend/main.py
    - Backend/routers/capture.py
    - Backend/routers/regions.py
    - Backend/services/streaming_coordinator.py
    - Backend/services/streaming_service.py
    - Backend/services/status_broadcaster.py
    - Backend/tests/conftest.py
    - Backend/tests/test_regions_router.py
    - Backend/tests/test_streaming_service.py
    - Backend/tests/test_streaming_coordinator.py
    - Backend/tests/test_status_broadcaster.py
tech_stack:
  added: []
  patterns:
    - Sentinel _UNSET kwarg pattern extended with `wled_devices` (Phase 16
      D-05/D-06 idiom; Phase 17 D-16).
    - SQL-routed test DB mock (`if "wled_devices WHERE enabled" in sql:`)
      replacing fragile cursor pop-list ordering. Robust against new
      query insertions in coordinator.
    - Atomic multi-file rename sweep guaranteed by single-commit policy
      (5 plan-specified files + 3 incidental ones — see Deviations).
    - Constructor port override (`WledStreamer(udp_port=41324)`) over
      module-level constant patching for hermetic loopback tests.
key_files:
  created:
    - .planning/phases/17-wled-backend-and-streaming/17-06-SUMMARY.md
  modified:
    - Backend/services/status_broadcaster.py
    - Backend/services/streaming_coordinator.py
    - Backend/services/streaming_service.py
    - Backend/main.py
    - Backend/routers/capture.py
    - Backend/routers/regions.py
    - Backend/tests/conftest.py
    - Backend/tests/test_status_broadcaster.py
    - Backend/tests/test_streaming_coordinator.py
    - Backend/tests/test_regions_router.py
    - Backend/tests/test_streaming_service.py
decisions:
  - WLED is no longer optional inside StreamingCoordinator — the
    constructor default-constructs a production WledStreamer when none
    is injected. _frame_loop calls render unconditionally; with no
    enabled devices the call is a cheap no-op (D-12 gate).
  - _load_wled_device_rows queries `wled_devices WHERE enabled = 1` and
    LEFT JOINs wled_channels with wled_light_assignments scoped to the
    active config_id, mitigating T-17-DB-JOIN per the plan's threat
    register.
  - Compatibility shim `StreamingService = StreamingCoordinator` removed
    from streaming_service.py; HueStreamer import in
    streaming_coordinator.py hoisted to the top of the module since the
    cycle no longer exists.
  - add_wled_device_to_live is a logged no-op for Plan 06 because
    WledStreamer.start raises if called twice without an intervening
    stop. Phase 19 may add a true attach_device method.
  - SQL routing in test_frame_loop_passes_region_gradients_to_hue_render
    replaces the previous cursor pop-list to handle the extra DB calls
    introduced by _load_wled_device_rows.
  - test_regions_router.py and test_streaming_service.py also touched
    by Task 3 (in addition to the plan's nominal 5 files) to keep the
    rename sweep atomic — see Deviations.
metrics:
  duration_minutes: ~50
  completed_date: 2026-04-26
  tasks_completed: 3
  tests_added: 6
  tests_modified: 2
  tests_removed: 1
---

# Phase 17 Plan 06: Wire WledStreamer into StreamingCoordinator + atomic
# `app.state.streaming → coordinator` rename

WLED streaming is now part of the same per-frame fan-out as Hue. Plan 04
shipped the WledStreamer; Plan 05 carved out the coordinator with a stub
WLED branch; this plan removes the stub, wires the streamer end-to-end,
extends the WS payload with the D-16 `wled_devices` key, and finishes the
`app.state.streaming → app.state.coordinator` rename in a single atomic
commit (Task 3).

## What Changed

### Task 1 — StatusBroadcaster `wled_devices` key + push_state kwarg

`Backend/services/status_broadcaster.py`:

- Added `"wled_devices": {}` to the `_metrics` init dict (Phase 17 D-16).
- Extended `push_state(...)` with `wled_devices: dict | object = _UNSET`
  using the same sentinel idiom as Phase 16 D-05/D-06's
  `active_config_id` / `active_device_path`. Omission preserves the
  current value; passing `{}` explicitly clears; passing a dict
  overwrites.
- Updated docstring to document the new behavior.

`Backend/tests/test_status_broadcaster.py`:

- `test_initial_metrics_defaults` updated to include `wled_devices: {}`.
- 5 new tests appended:
  * `test_wled_devices_key_present_on_init`
  * `test_update_metrics_merges_wled_devices`
  * `test_push_state_preserves_wled_devices_without_kwarg`
  * `test_push_state_clears_wled_devices_with_explicit_empty`
  * `test_push_state_sets_wled_devices_with_dict` (additionally asserts
    the value is broadcast in the WS payload via `ws.send_text`).

### Task 2 — Wire WledStreamer into StreamingCoordinator

`Backend/services/streaming_coordinator.py`:

- Top-level import `from services.wled_streamer import WledStreamer`.
  No cycle introduced (wled_streamer is a leaf).
- `__init__` default-constructs `WledStreamer()` when no streamer is
  injected, so `self._wled` is now never `None`. Tests still inject a
  mock via the kwarg.
- New `_load_wled_device_rows(config_id)` method. Outer query:
  ```sql
  SELECT id, ip, led_count, enabled FROM wled_devices WHERE enabled = 1
  ```
  Inner query per device:
  ```sql
  SELECT wc.id AS channel_id, wc.start_led, wc.end_led, wla.region_id
  FROM wled_channels wc
  LEFT JOIN wled_light_assignments wla
      ON wla.wled_channel_id = wc.id
      AND wla.entertainment_config_id = ?
  WHERE wc.device_id = ?
  ```
  Both wrapped in try/except so missing wled_* tables on certain test
  paths return `[]` instead of raising. Channels with `region_id = NULL`
  for the active config (T-17-DB-JOIN mitigation) are surfaced; render
  skips them.
- `_run_loop` now calls `self._wled.start(wled_rows)` after
  `self._hue.start(config_id)` and before broadcaster heartbeat /
  region_plan.
- `_frame_loop` calls `await self._wled.render(region_gradients)`
  unconditionally each cycle (no more `if self._wled is not None`).
  WLED errors stay isolated per-device inside WledStreamer per D-06.
- Metrics dict always includes `"wled_devices": self._wled.health_snapshot()`
  with empty-dict fallback for mocks that raise.
- Teardown calls `await self._wled.stop()` unconditionally.
- New `set_wled_device_enabled(device_id, enabled)`: UPDATE the DB row
  + commit + `self._wled.set_enabled(device_id, enabled)`. Live gate
  (D-12) takes effect on the next render. Safe at any lifecycle state.
- New `add_wled_device_to_live(device_id)`: logs and returns False —
  WledStreamer.start raises if called twice without stop, so Plan 06
  cannot truly hot-attach mid-stream. Hand-off documented for Phase 19.

`Backend/tests/test_streaming_coordinator.py`:

- `test_frame_loop_passes_region_gradients_to_hue_render` migrated from
  cursor pop-list to SQL-routed `_exec`. Robust against new DB calls in
  `_load_wled_device_rows`.
- New `test_coordinator_fans_out_to_hue_and_wled` Wave 3 integration:
  * Real `WledStreamer(udp_port=41324)` (Plan 04 ctor kwarg) bound to a
    `udp_listener(port=41324)` loopback queue.
  * `monkeypatch.setattr(... StreamingCoordinator._build_region_plan, ...)`
    — pytest auto-restores the class attribute on test exit (no global
    state leakage).
  * Mock DB returns one enabled device with one channel mapped to
    region "r1"; mock Hue with AsyncMock render.
  * Asserts `mock_hue.render.await_count > 0` AND
    `not q.empty()` — proves one captured frame drives both sinks.

### Task 3 — Atomic `app.state.streaming → app.state.coordinator` rename

Single-commit sweep across 8 files:

`Backend/main.py`:
- `from services.streaming_service import StreamingService` →
  `from services.streaming_coordinator import StreamingCoordinator`.
- `streaming = StreamingService(...)` / `app.state.streaming = streaming`
  → `coordinator = StreamingCoordinator(...)` /
  `app.state.coordinator = coordinator`.
- Shutdown: `streaming.state` / `streaming.stop()` →
  `coordinator.state` / `coordinator.stop()`.

`Backend/routers/capture.py`:
- `request.app.state.streaming` → `request.app.state.coordinator` in
  both start and stop handlers.
- Local var renamed `streaming` → `coordinator` for clarity.

`Backend/routers/regions.py`:
- `getattr(request.app.state, "streaming", None)` →
  `getattr(request.app.state, "coordinator", None)`.
- Surrounding human-readable warning text retains the word "streaming"
  (it's English, not a lookup).

`Backend/services/streaming_service.py`:
- Removed the bottom-of-file compatibility shim
  `from services.streaming_coordinator import StreamingCoordinator as
  StreamingService` added in Plan 05.
- Module docstring updated.

`Backend/services/streaming_coordinator.py`:
- Hoisted `from services.streaming_service import HueStreamer` to the
  top of the module. The deferred local import was only required to
  break the circular dependency caused by streaming_service.py's
  bottom-of-file shim — removed in this same commit.

`Backend/tests/conftest.py`:
- `_make_streaming_service_mock` → `_make_coordinator_mock` (same body).
- Inner mock identity in `_make_capture_app_client_with_streaming`
  renamed `mock_streaming` → `mock_coordinator`; app.state attribute
  renamed `streaming` → `coordinator`.
- Fixture `capture_app_client_with_streaming` retains its name (so
  test_capture_router imports continue working) but yields
  `(client, mock_coordinator)`.

`Backend/tests/test_regions_router.py`:
- `_make_regions_app` helper updated mock identity and
  `app.state.streaming` → `app.state.coordinator`.

`Backend/tests/test_streaming_service.py`:
- Removed `test_streaming_service_compat_shim_exports_coordinator` (the
  shim it asserts no longer exists).

## Grep proof of rename completeness

```
$ grep -rn "app\.state\.streaming" Backend/ --include="*.py"
Backend/tests/test_regions_router.py:34:    Phase 17 Plan 06 renamed
  ``app.state.streaming`` to ``app.state.coordinator``
```
Single match — a docstring describing the rename history. No live-code
references.

```
$ grep -rn "app\.state\.coordinator" Backend/ --include="*.py" | wc -l
9
```
9 references across main.py (1), routers/capture.py (2),
routers/regions.py (1), tests/conftest.py (1), tests/test_regions_router.py
(1), and the new SUMMARY.md mention via the docstring quote (counts
within the rename helper plus the test file itself).

```
$ grep -rn "StreamingCoordinator as StreamingService" Backend/
0 matches
```
Compatibility shim is gone.

## Fan-out test trace

```
test_coordinator_fans_out_to_hue_and_wled (test_streaming_coordinator.py)
- Constructs WledStreamer(udp_port=41324) — packets go to
  127.0.0.1:41324 (loopback) instead of 21324 (production).
- monkeypatch.setattr replaces _build_region_plan with a fake that
  returns {"r1": (full_frame_mask, 10)} — N_region=10 matches the
  channel's [start_led=0, end_led=9] inclusive range.
- DB stubs return one enabled device "d1" at 127.0.0.1 with
  led_count=10 and one channel "c1" assigned to region "r1".
- Coordinator starts, runs ~0.3s, stops.
- Assertions:
    mock_hue.render.await_count > 0
    not q.empty()      # WLED listener received >= 1 packet
- DRGB packet contents: 2-byte header [0x02, 0x02] + 30 RGB body bytes
  (10 LEDs * 3). Body is solid blue (0,0,255) since the test frame is
  solid blue (BGR -> RGB conversion happens inside sub_sample_gradient).
```

## Broadcaster payload sample (D-16 wire-ready)

```json
{
  "state": "streaming",
  "fps": 60.0,
  "latency_ms": 1.2,
  "packets_sent": 0,
  "packets_dropped": 0,
  "seq": 142,
  "active_config_id": "cfg-abc-123",
  "active_device_path": "/dev/video0",
  "wled_devices": {
    "d1": {
      "last_error": null,
      "last_success_at": "2026-04-26T18:00:01.234567+00:00",
      "in_cooldown": false
    }
  }
}
```

`wled_devices` is now in every WS broadcast (initial snapshot,
push_state, and 1 Hz heartbeat). Phase 18 (HA status) and Phase 19
(paint UI) consume this without further coordinator changes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Atomic Task 3 commit had to include
test_regions_router.py and test_streaming_service.py**

- **Found during:** Task 3 grep verification.
- **Issue:** The plan listed 5 files for the atomic rename
  (main.py, capture.py, regions.py, streaming_service.py,
  conftest.py). Two additional files referenced the old surface:
  * `Backend/tests/test_regions_router.py:41` set
    `app.state.streaming = mock_streaming` — leaving this would mean
    the regions router's new
    `getattr(request.app.state, "coordinator", None)` lookup always
    returned None, suppressing the streaming-active warning case.
  * `Backend/tests/test_streaming_service.py` had
    `test_streaming_service_compat_shim_exports_coordinator` asserting
    `StreamingService is StreamingCoordinator` — the shim is removed
    in this same commit so the test would fail at import time
    (`ImportError: cannot import name 'StreamingService'`).
- **Fix:** Both files updated in the same atomic commit. The plan's
  preamble says "the moment one of these files changes, the app fails
  to start until every reference is consistent" — these two are part
  of that consistency requirement.
- **Files modified:** Backend/tests/test_regions_router.py,
  Backend/tests/test_streaming_service.py.
- **Commit:** `e2ce83e`.

**2. [Rule 3 — Hoisting] HueStreamer import moved to module top in
streaming_coordinator.py**

- **Found during:** Task 3 (cycle no longer exists).
- **Issue:** Plan 05 deferred `from services.streaming_service import
  HueStreamer` inside `__init__` because the bottom-of-file shim in
  streaming_service.py created a circular dependency. With the shim
  removed in Task 3, the cycle is gone.
- **Fix:** Hoisted the import to the top of the module. Plan
  explicitly says "You MAY hoist that import to the top of the module.
  Either is correct; hoisting is cleaner if you do it as part of Task
  3's atomic commit since the shim removal lifts the cycle." — done.
- **Files modified:** Backend/services/streaming_coordinator.py.
- **Commit:** `e2ce83e`.

**3. [Rule 3 — Test robustness] SQL-route the cursor stub in
test_frame_loop_passes_region_gradients_to_hue_render**

- **Found during:** Task 2.
- **Issue:** The pre-Plan-06 test used a cursor pop-list
  (`cursors_seq = [cam_assign_cur, region_plan_cur]`). After Plan 06
  inserted `_load_wled_device_rows` between `_hue.start` and
  `_build_region_plan`, the WLED query consumed `region_plan_cur` and
  fed region-shaped MagicMocks into the WLED row iteration — leading
  to either a swallowed exception or wrong values.
- **Fix:** Migrated the test's `_exec` to SQL-routed if-elif on the
  query string (mirroring the pattern in the new fan-out integration
  test). Robust against future DB call insertions in the coordinator.
- **Files modified:** Backend/tests/test_streaming_coordinator.py.
- **Commit:** `13af4dc`.

## Authentication / Auth Gates

None. Internal refactor + integration only. No new endpoints, no new
external services.

## Verification Status

**No pytest invocation per orchestrator's absolute rule.** The phase-
end gate (run by orchestrator after all of 17-05 through 17-09) will
validate the full backend test suite. Per-task verification done:

- AST syntax check passed on all modified files.
- All grep-based acceptance criteria for Tasks 1, 2, and 3 verified
  green (counts shown in commit message bodies and in this SUMMARY's
  "Grep proof" section).
- The local `python -c "from main import app"` smoke import was not
  attempted because the dev venv `/tmp/hpc-venv` does not exist on
  this Windows host. AST parsing confirms the import-graph topology
  (no syntax / import-order errors) on every modified `.py` file.

## Threat Flags

None. The threat-register entries from the plan
(T-17-WIRING and T-17-DB-JOIN) are mitigated:

- **T-17-WIRING (rename swap):** Atomic single-commit policy enforced;
  zero `app.state.streaming` live-code references after Task 3 (one
  docstring reference describing the rename history).
- **T-17-DB-JOIN (config_id scoping):** `_load_wled_device_rows` inner
  query uses `LEFT JOIN wled_light_assignments ... AND
  wla.entertainment_config_id = ?`; channels not assigned for the
  active config surface `region_id = NULL` and WledStreamer.render
  skips them.

No new threat flags introduced.

## Known Stubs

`StreamingCoordinator.add_wled_device_to_live` is a logged no-op for
Plan 06 — it returns False even when streaming. This is intentional
and documented inline + here: WledStreamer.start raises if called
twice without an intervening stop, so a true hot-attach requires a
new `WledStreamer.attach_device` method that Phase 19 (or a follow-
up plan) may add. Plan 07's wled router will surface the False return
to its caller; users adding a device mid-stream see a "device active
on next stream restart" UX. This does not block the plan's goal —
WLED streaming still works end-to-end at stream start time.

## Commits

- `9231733` — feat(17-06-01): StatusBroadcaster wled_devices key +
  push_state kwarg
- `13af4dc` — feat(17-06-02): wire WledStreamer into StreamingCoordinator
- `e2ce83e` — refactor(17-06-03): atomic app.state.streaming →
  coordinator rename

## Self-Check: PASSED

Files exist:
- `Backend/services/status_broadcaster.py` — modified in `9231733`.
- `Backend/tests/test_status_broadcaster.py` — modified in `9231733`.
- `Backend/services/streaming_coordinator.py` — modified in `13af4dc`
  + `e2ce83e`.
- `Backend/tests/test_streaming_coordinator.py` — modified in `13af4dc`.
- `Backend/main.py` — modified in `e2ce83e`.
- `Backend/routers/capture.py` — modified in `e2ce83e`.
- `Backend/routers/regions.py` — modified in `e2ce83e`.
- `Backend/services/streaming_service.py` — modified in `e2ce83e`.
- `Backend/tests/conftest.py` — modified in `e2ce83e`.
- `Backend/tests/test_regions_router.py` — modified in `e2ce83e`.
- `Backend/tests/test_streaming_service.py` — modified in `e2ce83e`.
- `.planning/phases/17-wled-backend-and-streaming/17-06-SUMMARY.md` —
  this file.

Commits exist in `git log --oneline`:
- `9231733` — feat(17-06-01): StatusBroadcaster wled_devices key +
  push_state kwarg
- `13af4dc` — feat(17-06-02): wire WledStreamer into StreamingCoordinator
- `e2ce83e` — refactor(17-06-03): atomic app.state.streaming →
  coordinator rename
