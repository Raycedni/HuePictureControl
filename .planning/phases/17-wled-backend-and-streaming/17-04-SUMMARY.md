---
phase: 17-wled-backend-and-streaming
plan: 04
status: complete
completed: 2026-04-26
commits:
  - 64fffdb test(17-04-01): RED — failing lifecycle tests
  - 6b08fe2 feat(17-04-01): GREEN — lifecycle + lock + udp_port kwarg
  - e9016ba test(17-04-02): RED — failing render tests
  - a25f672 feat(17-04-02): GREEN — render with per-device gather + sub-sampling
key-files:
  created: []
  modified:
    - Backend/services/wled_streamer.py
    - Backend/tests/test_wled_streamer.py
---

# Plan 17-04 — WledStreamer lifecycle + render

## What shipped

`WledStreamer` class in `Backend/services/wled_streamer.py` extending the Plan 03 packet builders with a stateful per-frame UDP sink. Class is the WLED sibling of `HueStreamer` per D-03; driven by `StreamingCoordinator.render()` (Plan 05) and surfaces per-device health via `health_snapshot()` (Plan 06 broadcaster).

## State diagram

```
                         start([rows])           stop()
                  ┌────────────────────┐  ┌────────────────────┐
                  │                    ▼  ▼                    │
   not started ──►│   started, all enabled, none in cooldown   │──► not started
                  │                    │                       │
                  │                    │ render(grad)          │
                  │           per device, per frame:           │
                  │           ┌──────────────────────────┐     │
                  │           │ enabled? cooldown?       │     │
                  │           │   no → skip              │     │
                  │           │   yes → build + sendto   │     │
                  │           │     fail → increment     │     │
                  │           │     ≥30 fail → cooldown  │     │
                  │           │     30s → auto-clear     │     │
                  │           └──────────────────────────┘     │
                  └─────────────────────────────────────────────┘
```

## Tuning constants chosen

| Constant | Value | Rationale |
|---|---|---|
| `WLED_FAILURE_COOLDOWN_THRESHOLD` | 30 | ~0.5 s of failures at 60 Hz before flagging a bad device — fast enough to stop spamming a downed device, slow enough to ride out brief LAN hiccups. Anchored to D-15. |
| `WLED_COOLDOWN_DURATION_SECONDS` | 30.0 | Caps misbehaving-device traffic at ~30 packets/min. Long enough that a half-bricked WLED ESP32 has time to recover. |
| `WLED_ERROR_LOG_RATE_LIMIT_SECONDS` | 5.0 | Per-device log throttle. With 30 fail/min during cooldown, this keeps logs at ~6 lines/min/device. |

## udp_port kwarg rationale

`WledStreamer(udp_port: int = UDP_PORT)` — chosen over `patch.object(module, "UDP_PORT", ...)` for Plan 06's integration test. Two reasons:

1. **Hermetic**: monkey-patching a module constant leaks to any other test running in the same interpreter (xdist parallel workers, even pytest's natural import cache). Constructor injection is process-local to the streamer instance.
2. **Single source of truth**: `self._udp_port` is read in three places (`render`, `_render_one_device._send_all`, `_blackout_and_close`). Module-constant patching would require asserting at every call site that the module reference, not a local copy, is being read.

Plan 06's test uses `WledStreamer(udp_port=41324)` paired with `udp_listener(port=41324)` — no module patching anywhere.

## Test-listener strategy

`Backend/tests/fixtures/wled_loopback.py` `udp_listener` context manager binds a real `SOCK_DGRAM` socket on `127.0.0.1:port` in a daemon thread, queues every datagram, releases on exit. Tests use `pkt = q.get(timeout=1.0)` and assert exact byte contents. No mocking of socket internals.

## Cooldown test trace

`test_cooldown_after_30_failures`: swap the device's stored socket with `_FailingSocket` (raises `OSError` on every `sendto`). Render 30 times → `health_snapshot()["d1"]["in_cooldown"]` is True, `last_error` contains "OSError". Subsequent renders are skipped (`test_cooldown_skips_render_no_further_failure_increments` proves `consecutive_failures` does not advance past 30). `test_cooldown_auto_clears_after_30_seconds` monkeypatches `time.monotonic` past `in_cooldown_until` and asserts `health_snapshot()["d1"]["in_cooldown"]` flips to False.

## Verification

`source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_streamer.py -x -v`
→ 19 tests pass (8 lifecycle + 11 render/cooldown/blackout).

## Hand-off to Plan 06

Plan 06 will:
- Construct `WledStreamer()` (default port 21324) inside `StreamingCoordinator.__init__`
- Test the wiring with `WledStreamer(udp_port=41324)` + `udp_listener(port=41324)` per the udp_port rationale above
- Read `health_snapshot()` per frame and pass into `StatusBroadcaster.update_metrics({"wled_devices": ...})`

## Self-Check: PASSED

All Task 1 + Task 2 acceptance criteria green. No regressions in unrelated tests (full suite gate runs at end of phase per single-pytest rule).
