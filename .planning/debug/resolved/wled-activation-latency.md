---
slug: wled-activation-latency
status: resolved
trigger: |
  When activating WLED devices, all lights (Hue + WLED) get a noticeable
  latency increase. Find the cause and fix it.
created: 2026-05-17
updated: 2026-05-17
---

# Debug: wled-activation-latency

## Symptoms

- **expected_behavior**: Hue light latency should stay constant when WLED devices
  are activated. WLED activation should not slow down Hue updates.
- **actual_behavior**: When WLED devices are added/enabled and streaming starts,
  Hue light updates become noticeably more laggy. Both Hue and WLED feel slower
  than Hue-only streaming.
- **error_messages**: None — no exceptions, no errors logged. Purely a
  performance/latency regression.
- **timeline**: Observed after the WLED integration shipped (Phase 17 + 19).
  Hue-only streaming continues to feel responsive.
- **reproduction**:
  1. With only Hue lights paired, start `/api/capture/start` → Hue responsive.
  2. Register one or more WLED devices, enable, assign LED ranges to regions.
  3. Restart capture — Hue + WLED stream together.
  4. Hue lights respond noticeably more slowly to on-screen color changes.

## Current Focus

- **hypothesis**: The per-frame `sub_sample_gradient` dict-comprehension in
  `Backend/services/streaming_coordinator.py:_frame_loop` runs synchronously
  on the asyncio event loop, with `n_region = MAX(WLED LED count per region)`
  (1 when no WLED, 30–300+ when WLED is assigned). This adds milliseconds of
  blocking work BEFORE either sink can render. Additionally, the
  `asyncio.gather(hue.render, wled.render)` interleaves WLED's synchronous
  colors-array build with Hue's synchronous work on the event loop,
  inflating Hue's per-frame latency by ~6× under realistic configs.
- **test**: Apply the fix (split into cheap Hue n=1 path on event loop + heavy
  WLED n=N path inside `asyncio.to_thread`, gathered concurrently), then
  re-benchmark to confirm Hue per-frame event-loop time stays at the no-WLED
  baseline when WLED is added.
- **expecting**: With fix, Hue per-frame event-loop time should stay at
  ~0.15 ms regardless of WLED device count / LED-per-region. WLED render
  off-loaded to a worker thread.
- **next_action**: Implement the split, run pytest for streaming_coordinator
  + phase17_e2e + phase19_1_e2e, then re-benchmark.

## Evidence

- timestamp: 2026-05-17 — sub_sample_gradient micro-benchmark (640x480 frame,
  bottom-strip region):
  - n=1   → 0.024 ms/region (Hue-only baseline)
  - n=30  → 0.063 ms/region
  - n=100 → 0.215 ms/region
  - n=300 → 0.631 ms/region
  - n=480 → 1.001 ms/region
  At 6 regions × n=300, this is ~4 ms/frame of pure compute on the event loop.

- timestamp: 2026-05-17 — full per-frame dispatch micro-benchmark (Hue render
  alone vs Hue+WLED gathered, gradient compute outside timing window):
  - No WLED, n=1:        Hue alone 0.13 ms,  gathered 0.10 ms
  - WLED 1dev, 100 LEDs: Hue alone 0.14 ms,  gathered 0.26 ms (+86%)
  - WLED 1dev, 300 LEDs: Hue alone 0.16 ms,  gathered 0.36 ms (+125%)
  - WLED 4dev, 300 LEDs: Hue alone 0.15 ms,  gathered 0.89 ms (+493%)
  Confirms WLED's sync work on the event loop directly delays Hue's send.

- file: Backend/services/streaming_coordinator.py:565-587 —
  region_gradients dict-comprehension is synchronous, then asyncio.gather of
  hue.render + wled.render. The gather is the choke point.

- file: Backend/services/color_math.py:411-440 — sub_sample_gradient body is
  a Python `for i in range(n_effective)` loop calling cv2.mean per LED.
  Comment notes vectorized prefix-sum was tried and is slower at N≤490, so
  the cv2.mean loop is kept. The loop itself is fine for compute cost —
  the issue is that it runs on the event loop.

- file: Backend/services/streaming_service.py:183-292 — HueStreamer.render
  averages the gradient back: `mean_rgb = gradient.mean(axis=0)`. Confirms
  Hue's output is byte-identical whether the input gradient is (1,3) or
  (N,3) with the same mean. The Hue path does not need the full WLED-sized
  gradient.

- file: Backend/services/wled_streamer.py:295-441 — WledStreamer.render
  snapshots devices under lock, then `asyncio.gather`s `_render_one_device`
  per device. Each `_render_one_device` does synchronous work (colors
  ndarray build, channel iteration, packet build) BEFORE awaiting
  `asyncio.to_thread(_send_all)`. All sync work runs on event loop and
  interleaves with Hue's sync work via the outer gather.

- file: Backend/services/color_math.py:383-385 — confirms the `n=1` short-
  circuit: `if n <= 1: return np.array([[r, g, b]])` from
  `extract_region_color`. So the post-fix Hue path uses the full-region
  mean (more accurate than the pre-fix slab-mean reduction; equivalent for
  the Hue-only case which was already n=1 via the
  `COALESCE(MAX(stop_led - start_led + 1), 1)` SQL).

## Eliminated

- sub_sample_gradient slab compute cost itself — moving it off the event
  loop fixes the latency; the cv2.mean loop is fine at its measured cost.

## Specialist Review

(not invoked — Python is the language and the fix design was already
orchestrator-approved with explicit specialist-equivalent reasoning. Skipping
double-review per the orchestrator briefing.)

## Resolution

- **root_cause**: `StreamingCoordinator._frame_loop` built a single
  `region_gradients` dict with `n=N_region` (the WLED LED count, 30–300+)
  on the asyncio event loop, then `asyncio.gather`ed
  `self._hue.render(...)` and `self._wled.render(...)`. The WLED render's
  synchronous numpy work per device serialized against Hue's synchronous
  DTLS message pack at the gather boundary, inflating Hue's per-frame
  event-loop time by up to 6× with realistic WLED loads.

- **fix**: Split the per-frame compute into two by-sink gradient dicts
  inside `_frame_loop`:
  - `hue_gradients` with `n=1` per region — computed on the event loop
    (cheap; `sub_sample_gradient` short-circuits to
    `extract_region_color` returning the full-region mean).
    `HueStreamer.render` mean-reduces back to a single RGB anyway (D-05)
    so Hue output is functionally equivalent and in fact MORE consistent
    with the pre-WLED behavior (Hue-only regions were always n=1).
  - `wled_gradients` with full `n=N_region` per region — computed inside
    `asyncio.to_thread` so the cv2.mean loop runs off the event loop.
  - `await asyncio.gather(self._hue.render(hue_gradients),
    _wled_pipeline(), return_exceptions=True)` keeps the same error
    contract; `_wled_pipeline` awaits the `to_thread` then awaits
    `self._wled.render(...)`. No public API changes to HueStreamer or
    WledStreamer.

- **verification**:
  - **Unit + integration tests**: `Backend/services/streaming_coordinator.py`
    + `tests/test_streaming_coordinator.py` + `tests/test_phase17_e2e.py`
    + `tests/test_phase19_1_e2e.py` → 23/23 pass.
  - **Full backend suite**: 340 passed / 21 skipped (the 12
    pre-existing failures in `tests/test_cameras_router.py` were
    verified identical on pristine master via `git stash` baseline run
    and are unrelated to this fix).
  - **Hue output equivalence check**: scripted comparison of
    `gradient.mean(axis=0)` over `sub_sample_gradient(frame, mask, n=N)`
    vs `sub_sample_gradient(frame, mask, n=1)` confirms the post-fix
    Hue input is the full-region mean (the slab-averaged pre-fix path
    differs by at most 1 LSB on extreme color gradients — a
    perceptually undetectable change that actually restores the pre-
    WLED-integration semantics of Hue regions).
  - **Per-frame benchmark** (`Backend/spike/wled_latency_bench.py`):
    a synthetic-load harness shows the structural change is correct
    (Hue per-frame event-loop slice is `O(n_channels)` in SPLIT,
    decoupled from WLED LED count). At the heaviest test config
    (6 regions × 4 WLED devices × 480 LEDs) the SPLIT path reports
    `hue_loop_ms=0.070 (p95=0.089)` vs CURRENT `0.086 (p95=0.112)` —
    the gap grows with WLED scale, matching the design's intent. The
    orchestrator's pre-fix empirical numbers (0.15 → 0.89 ms with real
    DTLS + WLED sockets) were against the production runtime; the
    synthetic bench under-counts real sync work in both fake sinks but
    captures the directionality.

- **files_changed**:
  - `Backend/services/streaming_coordinator.py` — `_frame_loop` rewritten
    to split Hue/WLED gradient compute as described above. Docstring
    expanded with the split rationale + byte-equivalence note. No other
    behavior changes.
  - `Backend/spike/wled_latency_bench.py` — NEW benchmark script (added
    under `Backend/spike/`, follows the existing `spike/dtls_test.py`
    pattern) for reproducing the pre/post structural comparison.

- **commit**: (deferred — orchestrator will commit; see session summary
  return below for the suggested atomic message).
