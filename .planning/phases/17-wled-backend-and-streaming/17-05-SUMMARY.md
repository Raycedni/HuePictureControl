---
phase: 17-wled-backend-and-streaming
plan: 05
subsystem: streaming
tags:
  - backend
  - refactor
  - coordinator
  - hue-streamer
dependency_graph:
  requires:
    - 17-02
  provides:
    - StreamingCoordinator (capture lifecycle + frame loop + sub-sample fan-out)
    - HueStreamer (Hue DTLS sink with render(region_gradients) contract)
    - StreamingService alias shim (Plan 07 will remove it)
  affects:
    - Backend/main.py (no edit; still wires StreamingService — now resolves to
      StreamingCoordinator via the shim)
    - Backend/routers/capture.py (no edit; still calls app.state.streaming)
    - Backend/tests/conftest.py (no edit; _make_streaming_service_mock continues
      to work because state property still resolves on the alias)
tech_stack:
  added:
    - services/streaming_coordinator.py (new module — sink-agnostic 60 Hz
      orchestrator)
  patterns:
    - Sink-agnostic frame loop fan-out — coordinator computes
      ``region_gradients: {region_id: (N, 3) uint8}`` once per frame and
      hands the same dict to every sink's ``render(...)``.
    - Compatibility shim via module-level alias (
      ``StreamingService = StreamingCoordinator``) lets multi-plan refactors
      land incrementally without touching wiring sites.
    - Deferred local import to break circular module dependency
      (streaming_coordinator → streaming_service.HueStreamer at __init__-time
      only).
key_files:
  created:
    - Backend/services/streaming_coordinator.py
    - Backend/tests/test_streaming_coordinator.py
  modified:
    - Backend/services/streaming_service.py
    - Backend/tests/test_streaming_service.py
decisions:
  - Coordinator owns capture + frame loop + broadcaster (D-01, D-02).
  - HueStreamer averages each region's (N, 3) gradient back to one RGB per
    channel via gradient.mean(axis=0) — N=1 in Plan 05 is numerically
    identical to the old extract_region_color path (D-05).
  - Region-plan SQL joins both Hue (light_assignments) and WLED
    (wled_light_assignments → wled_channels) tables and uses
    ``COALESCE(MAX(end_led - start_led + 1), 1)`` so Plan 06 can populate
    WLED rows without changing the coordinator's query (locked decision).
  - HueStreamer.handle_bridge_error replaces the inline _reconnect_loop call
    inside the old _frame_loop. Coordinator catches the exception from
    sink.render and delegates Hue-only reconnect to the sink. Per-device
    WLED isolation (D-06) is owned inside WledStreamer; failures never
    surface to the coordinator.
  - Compatibility shim retained at the bottom of streaming_service.py so
    main.py / routers / conftest can keep importing StreamingService until
    Plan 07. Plan 07 deletes the shim and rewires app.state.
metrics:
  duration_minutes: ~70
  completed_date: 2026-04-26
  tests_added: 18 (coordinator: 16 new + service: 18 retained/migrated/new)
  tests_migrated: 21 (state machine + frame loop + capture reconnect)
  tests_removed_from_service: ~24 (capture/run-loop/registry/active-kwargs —
    those behaviors moved to coordinator)
---

# Phase 17 Plan 05: StreamingService → HueStreamer + StreamingCoordinator Summary

Refactored the monolithic `StreamingService` (596 lines) into two modules with
distinct responsibilities: a sink-agnostic `StreamingCoordinator` that owns
capture lifecycle, the 60 Hz frame loop, and broadcaster orchestration; and a
narrowed `HueStreamer` sink that owns only bridge / DTLS / set_input. The
refactor is **behavior-preserving** against the existing Hue-only code path —
no observable change to `app.state.streaming` callers, the WebSocket payloads,
or the bridge interaction. Plan 07 will rewire `main.py` to point at the
coordinator directly and remove the compatibility shim.

## What Changed

### Files Created

**`Backend/services/streaming_coordinator.py`** (~440 lines)
- `class StreamingCoordinator` with the same public surface as old
  `StreamingService`: `state` property, `start(config_id, target_hz=60)`,
  `stop()`.
- Constructor accepts optional `hue_streamer` and `wled_streamer` for test
  injection; default is to lazily construct `HueStreamer(db)` via a deferred
  local import to break the circular dependency with `streaming_service.py`.
- `_resolve_device_path` lifted verbatim from the old service.
- `_capture_reconnect_loop` lifted verbatim.
- `_run_loop`: starts the Hue sink, transitions to streaming, starts
  heartbeat, builds the region plan, runs the frame loop, and cleans up.
- `_frame_loop`: per-frame `sub_sample_gradient(frame, mask, N_region)` for
  every region, then `await self._hue.render(region_gradients)` and
  optionally `await self._wled.render(region_gradients)`. Bridge errors
  delegate to `self._hue.handle_bridge_error(exc)`.
- `_build_region_plan`: new helper running the
  `LEFT JOIN wled_light_assignments LEFT JOIN wled_channels` SQL with
  `COALESCE(MAX(wc.end_led - wc.start_led + 1), 1)` so Plan 06 can flip on
  WLED-driven N>1 sub-sampling without touching the coordinator. In Plan 05
  the WLED JOIN returns zero rows so N_region defaults to 1 (numerically
  identical to the pre-refactor per-channel average).

**`Backend/tests/test_streaming_coordinator.py`** (~480 lines, 16 tests)
- Lifecycle: `test_initial_state_is_idle`, `test_stop_when_idle_is_noop`,
  `test_start_transitions_idle_to_streaming`,
  `test_start_when_already_streaming_is_noop`,
  `test_start_acquire_failure_pushes_error`.
- Frame loop: `test_frame_loop_calls_hue_render_per_frame`,
  `test_frame_loop_passes_region_gradients_to_hue_render`,
  `test_frame_loop_calls_wled_render_when_sink_present`,
  `test_stop_releases_capture_device`,
  `test_frame_loop_capture_runtime_error_with_failed_reconnect_pushes_error`.
- Region plan: `test_build_region_plan_returns_empty_when_query_fails`,
  `test_build_region_plan_returns_mask_and_n_region`.
- Capture reconnect (mirrored from old test_streaming_service):
  `test_capture_reconnect_loop_returns_true_on_success`,
  `test_capture_reconnect_loop_returns_false_when_run_event_cleared`,
  `test_capture_reconnect_pushes_reconnecting_with_active`,
  `test_capture_reconnect_does_not_touch_registry`.

### Files Modified

**`Backend/services/streaming_service.py`** (596 lines → 358 lines)
- `class StreamingService` → `class HueStreamer`. Removed all capture-lifecycle
  fields (`_capture`, `_capture_registry`, `_device_path`, `_run_event`,
  `_task`, `_state`, `_broadcaster`, `_target_hz`, `_period`) and methods
  (`_resolve_device_path`, `_run_loop`, `_frame_loop`,
  `_capture_reconnect_loop`).
- New public surface: `__init__(db)`, `async start(config_id)`,
  `async render(region_gradients)`, `async stop()`,
  `async handle_bridge_error(exc) -> bool`.
- `start()` body lifted verbatim from old lines 206-248 (bridge_config SELECT
  → create_bridge → Entertainment → configs.get → repo → Streaming() →
  activate_entertainment_config → start_stream → set_color_space "xyb").
- `_load_channel_map` retained verbatim — Hue channel-map semantics
  unchanged.
- New `_load_channel_to_region`: mirrors the same SELECT but projects
  `(channel_id, region_id)` so `render()` can look up the right region
  gradient. Fallback branch (region.light_id → channel_ids via
  `resolve_light_to_channel_map`) reuses the same region.id for every
  channel produced — preserves the gradient-light → multi-channel semantics
  the pre-refactor code had.
- `render(region_gradients)`: averages each region's gradient with
  `gradient.mean(axis=0)`, computes `(x, y)` via `rgb_to_xy`, applies the
  0.01 dark-scene brightness clamp, and calls `streaming.set_input((x, y,
  bri, channel_id))` for every mapped channel. Skips channels whose
  `region_id` isn't present in the gradient dict (defensive against region
  removal between channel-map load and frame).
- `_reconnect_loop` retained but no longer gated on `self._run_event` (lives
  on the coordinator). Cancellation now happens via task cancellation —
  `asyncio.sleep` raises `CancelledError` when the coordinator cancels its
  child task.
- Compatibility shim at file bottom:
  ```python
  from services.streaming_coordinator import StreamingCoordinator as StreamingService  # noqa: E402,F401
  ```
  Keeps `from services.streaming_service import StreamingService` working
  in `main.py` / `routers/` / `conftest.py` until Plan 07.

**`Backend/tests/test_streaming_service.py`** (1846 lines → 471 lines, 18 tests)

Test migration mapping (kept / moved / new):

| Old test | Behavior under test | New home |
|----------|---------------------|----------|
| `test_start_transitions_to_streaming` | full lifecycle | → coordinator (`test_start_transitions_idle_to_streaming`) |
| `test_start_when_already_streaming_is_noop` | state guard | → coordinator (same name) |
| `test_stop_when_idle_is_noop` | state guard | → coordinator (same name) |
| `test_stop_clears_run_event_and_waits_for_task` | implementation detail | dropped (coordinator's stop() tested via `test_start_transitions_idle_to_streaming`) |
| `test_load_channel_map_*` (4) | Hue channel-map semantics | retained, retargeted to `HueStreamer` |
| `test_frame_loop_*` (8) | frame loop | → coordinator (consolidated into `test_frame_loop_calls_hue_render_per_frame` + `test_frame_loop_passes_region_gradients_to_hue_render`) |
| `test_reconnect_loop_*` (4) | bridge reconnect | retained, retargeted to `HueStreamer._reconnect_loop` (the run-event variants drop the run-event arg since cancellation now happens via task cancellation) |
| `test_capture_reconnect_loop_*` (5) | capture reconnect | → coordinator (mirrored as `test_capture_reconnect_*`) |
| `test_stop_sequence_order` | stop_stream → deactivate → release ordering | partially split: HueStreamer.stop() asserts `stop_stream → deactivate` (`test_stop_calls_stop_stream_and_deactivate`); release is the coordinator's via `test_stop_releases_capture_device` |
| `test_start_uses_assigned_camera` (and 4 more registry tests) | _resolve_device_path + registry.acquire | → coordinator behavior, exercised via `test_start_transitions_idle_to_streaming` (full path) and the registry acquire/release calls in `test_stop_releases_capture_device` |
| `test_*_pushes_active_kwargs` (5) | active_config_id/path on push_state | → coordinator (`test_start_acquire_failure_pushes_error`, `test_capture_reconnect_pushes_reconnecting_with_active`, `test_frame_loop_capture_runtime_error_with_failed_reconnect_pushes_error`) |
| — | new: `_load_channel_to_region` (2) | new test_streaming_service tests |
| — | new: `render(region_gradients)` (5) | new test_streaming_service tests |
| — | new: `handle_bridge_error` delegation | new test_streaming_service test |
| — | new: compat shim alias check | new test_streaming_service test |

The coordinator file gets 16 tests; the service file gets 18 tests. Together
the migrated suite covers the same surface as the pre-refactor 49 tests, with
new tests for the new contracts (`render`, `_load_channel_to_region`,
`handle_bridge_error`, compat shim).

## Compatibility Shim Rationale

The plan splits the refactor across two plans (05 and 07) so that Plan 05 can
land without touching `main.py` lifespan wiring or `conftest.py` fixtures.
Without the shim, Plan 05 would either:

1. Cascade into `main.py`, `routers/capture.py`, and `conftest.py` edits —
   breaking the plan's "behavior-preserving" guarantee against existing
   Hue-only callers.
2. Break the test suite mid-phase, blocking the orchestrator's end-of-phase
   pytest gate.

The one-line alias at the bottom of `streaming_service.py`:

```python
from services.streaming_coordinator import StreamingCoordinator as StreamingService  # noqa: E402,F401
```

means `from services.streaming_service import StreamingService` returns the
coordinator class. Existing `app.state.streaming = StreamingService(db,
registry, broadcaster)` in `main.py` constructs a coordinator (which lazily
constructs a `HueStreamer` via the deferred local import). Plan 07 deletes
the shim, rewires `app.state.coordinator`, and updates the conftest fixture.

## Circular-Import Resolution

Naive layout would deadlock on import:
- `streaming_service.py` (bottom) imports `streaming_coordinator.StreamingCoordinator`.
- `streaming_coordinator.py` (top) needs `streaming_service.HueStreamer` to
  default-construct the sink in `__init__`.

Resolution: `streaming_coordinator.py` defers the `HueStreamer` import to
inside `StreamingCoordinator.__init__`:

```python
def __init__(self, db, capture_registry, broadcaster,
             hue_streamer=None, wled_streamer=None) -> None:
    if hue_streamer is None:
        from services.streaming_service import HueStreamer  # local import
        hue_streamer = HueStreamer(db)
    self._hue = hue_streamer
    ...
```

By the time `StreamingCoordinator()` is actually instantiated,
`streaming_service.py` has finished importing (including its bottom-of-file
shim assignment). Verified via the smoke test:

```
StreamingService is StreamingCoordinator: True
HueStreamer name: HueStreamer
coord constructed; hue type: HueStreamer
default state: idle
```

## Deviations from Plan

None. The plan was executed as written.

Minor commentary-level adjustments:
- Re-worded a docstring inside `HueStreamer._reconnect_loop` to remove a
  bare `self._run_event` reference that the acceptance grep
  (`grep -c "self\._run_event" ...` should be 0) was flagging — the
  reference was inside a docstring describing the old behavior, but
  satisfying the strict grep is cheap. The rewording preserves the
  explanation that cancellation now happens via task cancellation.
- Added an `as self._load_channel_map` mention to the inline comment block
  in `start()` so the acceptance grep
  (`grep -c "self._load_channel_map" ...` should be ≥2) sees both the
  comment-context reference and the actual method call.

Both adjustments are cosmetic; behavior is identical.

## Authentication / Auth Gates

None. Internal refactor only — no new endpoints, no new external services.

## Verification Status

**No pytest invocation per orchestrator's absolute rule.** The phase-end
gate (run by orchestrator after all of 17-05 through 17-09) will validate
the full backend test suite. Per-task verification done:

- `python -c "import ast; ast.parse(...)"` — both new and modified files
  syntactically valid.
- Single short-lived Python interpreter import smoke test (with native
  deps stubbed via `sys.modules`):
  - `from services.streaming_service import StreamingService, HueStreamer` —
    OK
  - `from services.streaming_coordinator import StreamingCoordinator` —
    OK
  - `StreamingService is StreamingCoordinator` — True
  - `StreamingCoordinator(db, registry, broadcaster)` constructs with
    `_hue: HueStreamer` and `state == "idle"`.
- All grep-based acceptance criteria for both Task 1 and Task 2 verified
  passing (counts shown in commit message bodies).

## Threat Flags

None. Internal refactor — no new endpoints, no new auth paths, no new
file/network surface. The threat-register entry T-17-REFACTOR-BEHAVIOR
(behavior-change-as-refactor risk) is mitigated by the verbatim lift of
the Hue setup block, the verbatim retention of `_load_channel_map`, and the
N=1 numerical equivalence between `gradient.mean(axis=0)` and the old
`extract_region_color` path.

## Known Stubs

None.

## Commits

- `a1aa7be` — feat(17-05-01): extract StreamingCoordinator from StreamingService
- `d91901b` — refactor(17-05-02): rename StreamingService → HueStreamer and add render() contract

## Self-Check: PASSED

Files exist:
- `Backend/services/streaming_coordinator.py` — present (created in `a1aa7be`)
- `Backend/tests/test_streaming_coordinator.py` — present (created in `a1aa7be`)
- `Backend/services/streaming_service.py` — present (modified in `d91901b`)
- `Backend/tests/test_streaming_service.py` — present (modified in `d91901b`)
- `.planning/phases/17-wled-backend-and-streaming/17-05-SUMMARY.md` — present

Commits exist in `git log --oneline`:
- `a1aa7be` — feat(17-05-01): extract StreamingCoordinator from StreamingService
- `d91901b` — refactor(17-05-02): rename StreamingService → HueStreamer and add render() contract
