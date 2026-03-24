---
phase: 03-entertainment-api-streaming-integration
verified: 2026-03-24T22:00:00Z
status: human_needed
score: 19/19 must-haves verified
re_verification: true
  previous_status: gaps_found
  previous_score: 18/19
  gaps_closed:
    - "Bridge disconnect triggers exponential backoff reconnect with real bridge credentials"
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "End-to-end latency under 100ms on physical hardware"
    expected: "ws/status latency_ms field consistently below 100ms during active streaming"
    why_human: "Hardware measurement required; automated tests mock all I/O so latency_ms is not real elapsed time"
---

# Phase 3: Entertainment API Streaming Integration Verification Report

**Phase Goal:** Connect the capture pipeline output to the DTLS streaming session and deliver measurable end-to-end color synchronization under 100ms.
**Verified:** 2026-03-24T22:00:00Z
**Status:** human_needed
**Re-verification:** Yes — after gap closure (commit 1c92d03)

---

## Re-verification Summary

One gap was identified in the initial verification: `_frame_loop` called `_reconnect_loop` with hardcoded credentials `"192.168.1.100"` and `"testuser"` instead of the actual bridge credentials loaded from the database in `_run_loop`.

Commit `1c92d03` closed this gap with three changes:

1. `_run_loop` line 172: `await self._frame_loop(streaming, channel_map, bridge_ip, username)` — passes real credentials through.
2. `_frame_loop` signature: `async def _frame_loop(self, streaming, channel_map: dict, bridge_ip: str, username: str) -> None` — accepts the parameters.
3. `_frame_loop` lines 288-290: `await self._reconnect_loop(self._config_id or "", bridge_ip, username)` — uses passed-in values, no hardcoded literals.

Grep confirms zero occurrences of `192.168.1.100` or `testuser` in `streaming_service.py`. All 111 tests pass.

**Note on regression test:** The previous VERIFICATION.md listed "add a test that verifies `_frame_loop` passes the actual bridge_ip/username to `_reconnect_loop` on socket error" as a missing item. Commit `1c92d03` updated existing `_frame_loop` call sites in tests to pass `"192.168.1.1"` and `"testuser"` as explicit arguments, but did NOT add a dedicated test that captures the socket-error code path and asserts `_reconnect_loop` receives the passed-in IP rather than a hardcoded one. The production bug is fixed; the absence of a regression test is a test-coverage gap only, not a blocker — the implementation is correct and the full 111-test suite is green.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | StatusBroadcaster accepts multiple WebSocket connections and broadcasts JSON to all | VERIFIED | `_send_to_all()` iterates `_connections`, sends `json.dumps(self._metrics)`. `test_multiple_connections_accepted` passes. |
| 2 | StatusBroadcaster removes dead connections without crashing the broadcast loop | VERIFIED | `_send_to_all()` catches per-connection `Exception`, collects dead list, removes after iteration. 12/12 StatusBroadcaster tests pass. |
| 3 | StatusBroadcaster sends current metrics snapshot on new connection | VERIFIED | `connect()` calls `await ws.send_text(json.dumps(self._metrics))` after `ws.accept()`. Test `test_websocket_initial_metrics_has_expected_keys` confirms keys: state, fps, latency_ms, packets_sent, seq. |
| 4 | StatusBroadcaster rate-limits periodic broadcasts to 1 Hz; push_state bypasses for immediate delivery | VERIFIED | `_heartbeat_loop` sleeps 1.0s between `_send_to_all` calls. `push_state` calls `_send_to_all` immediately without sleep. Tests verify both paths. |
| 5 | activate_entertainment_config sends PUT with action start to bridge CLIP v2 | VERIFIED | `hue_client.py` line 142: `client.put(url, json={"action": "start"}, headers=headers)` followed by `resp.raise_for_status()`. 4/4 hue_client tests pass. |
| 6 | deactivate_entertainment_config sends PUT with action stop and does not raise on failure | VERIFIED | `hue_client.py` line 161 wrapped in `try/except Exception` that logs warning and returns normally. Test confirms best-effort behavior. |
| 7 | StreamingService.start() transitions state to streaming and creates asyncio Task | VERIFIED | `start()` sets `_state="starting"`, calls `_run_event.set()`, creates `asyncio.create_task(_run_loop(...))`. `test_start_transitions_to_streaming` passes. |
| 8 | StreamingService.stop() clears run event, waits for task, calls locked stop sequence: stop_stream -> deactivate -> capture.release | VERIFIED | `stop()` calls `_run_event.clear()` then `await self._task`. `_run_loop` finally block calls `stop_stream -> deactivate -> capture.release`. `test_stop_sequence_order` asserts exact order. |
| 9 | Frame loop calls extract_region_color for every channel each frame | VERIFIED | `_frame_loop` iterates `channel_map.items()` calling `extract_region_color(frame, mask)` per channel. `test_frame_loop_calls_extract_region_color_per_channel` confirms 2+ calls for 2-channel map. |
| 10 | Frame loop calls rgb_to_xy and feeds (x, y, bri, channel_id) to set_input via asyncio.to_thread | VERIFIED | `_frame_loop` lines 277-284: `rgb_to_xy`, brightness calculation, `asyncio.to_thread(streaming.set_input, (x, y, bri, channel_id))`. `test_frame_loop_calls_rgb_to_xy_and_set_input` verifies tuple shape and values. |
| 11 | Frame loop targets 50 Hz with asyncio.sleep for timing | VERIFIED | `PERIOD = 1.0 / TARGET_HZ` (0.02s). `sleep_time = self.PERIOD - elapsed; if sleep_time > 0: await asyncio.sleep(sleep_time)`. |
| 12 | Frame loop calls update_metrics (not broadcast) at 50 Hz; 1 Hz heartbeat handles delivery | VERIFIED | `_broadcaster.update_metrics({fps, latency_ms, packets_sent, seq})` called each frame. `push_state` is NOT called in the frame hot path. `test_frame_loop_calls_update_metrics_not_broadcast` asserts all four keys present. |
| 13 | 16-channel map is processed without error | VERIFIED | `test_frame_loop_16_channels` creates `channel_map = {i: mask for i in range(16)}`, asserts `len(set_input_calls) == 16`. Passes. (STRM-06) |
| 14 | Single-channel (non-gradient) light uses the same code path | VERIFIED | `test_frame_loop_1_channel_non_gradient` asserts `len(set_input_calls) == 1`. Passes. (GRAD-05) |
| 15 | Bridge disconnect triggers exponential backoff reconnect (1s, 2s, 4s... capped at 30s) with real bridge credentials | VERIFIED | `_reconnect_loop` implementation correct (backoff 1/2/4/.../30, unlimited retries). `_frame_loop` now accepts `bridge_ip` and `username` as parameters and passes them to `_reconnect_loop` (lines 288-290). No hardcoded literals remain in `streaming_service.py`. Gap closed by commit `1c92d03`. |
| 16 | Capture pipeline continues running during bridge reconnect | VERIFIED | `_reconnect_loop` does not call `capture.release()` or `capture.open()`. `test_reconnect_loop_does_not_touch_capture` asserts `mock_capture.release.assert_not_called()`. |
| 17 | Capture card disconnect stops streaming entirely and pushes error to broadcaster | VERIFIED | `_frame_loop` catches `RuntimeError` from `get_frame()`, clears `run_event`, sets `state="error"`, calls `push_state("error", error=str(exc))`. Test confirms. |
| 18 | Channel map is loaded from SQLite (light_assignments JOIN regions) at loop start | VERIFIED | `_load_channel_map` executes `SELECT la.channel_id, r.polygon FROM light_assignments la JOIN regions r ON la.region_id = r.id WHERE la.entertainment_config_id = ?`. Tests with 2-row and 0-row cases pass. |
| 19 | POST /api/capture/start starts streaming, POST /api/capture/stop stops it, /ws/status streams JSON at 1 Hz | VERIFIED | `capture.py` lines 36-60: `start_capture` and `stop_capture` use `request.app.state.streaming`. `streaming_ws.py` wires broadcaster. `main.py` creates both services in lifespan. All 52 phase-specific tests pass (111 total suite). |

**Score:** 19/19 truths verified

---

## Required Artifacts

| Artifact | Min Lines | Status | Details |
|----------|-----------|--------|---------|
| `Backend/services/status_broadcaster.py` | — | VERIFIED | Exports `StatusBroadcaster` with all required methods |
| `Backend/tests/test_status_broadcaster.py` | 40 | VERIFIED | 12 tests, all passing |
| `Backend/services/hue_client.py` | — | VERIFIED | `activate_entertainment_config` and `deactivate_entertainment_config` present |
| `Backend/tests/test_hue_client.py` | 20 | VERIFIED | 4 tests for activate/deactivate, all passing |
| `Backend/services/streaming_service.py` | 150 | VERIFIED | 352 lines. `_frame_loop` signature updated to accept `bridge_ip: str, username: str`. No hardcoded credentials. |
| `Backend/tests/test_streaming_service.py` | 150 | VERIFIED | 772 lines, 20 tests, all passing. All `_frame_loop` call sites updated to pass explicit IP and username. |
| `Backend/routers/streaming_ws.py` | 15 | VERIFIED | `router` exported, `/ws/status` WebSocket endpoint wired to broadcaster |
| `Backend/routers/capture.py` | 80 | VERIFIED | `StartCaptureRequest`, `POST /start`, `POST /stop` all present |
| `Backend/main.py` | 30 | VERIFIED | `StatusBroadcaster` and `StreamingService` created in lifespan, `streaming_ws_router` included |
| `Backend/tests/test_streaming_ws.py` | 20 | VERIFIED | 4 WebSocket tests including multi-connection |
| `Backend/tests/test_capture_router.py` | 50 | VERIFIED | 5 start/stop tests + prior endpoint tests, all passing |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `streaming_ws.py` | `status_broadcaster.py` | `websocket.app.state.broadcaster` | VERIFIED | Line 23: `broadcaster = websocket.app.state.broadcaster` |
| `capture.py` | `streaming_service.py` | `request.app.state.streaming` | VERIFIED | Lines 46-47, 58-59: `streaming = request.app.state.streaming` |
| `main.py` | `streaming_service.py` | `StreamingService(db, capture, broadcaster)` in lifespan | VERIFIED | Line 44: `streaming = StreamingService(db=db, capture=capture, broadcaster=broadcaster)` |
| `main.py` | `status_broadcaster.py` | `StatusBroadcaster()` in lifespan | VERIFIED | Line 41: `broadcaster = StatusBroadcaster()` |
| `streaming_service.py` | `status_broadcaster.py` | `self._broadcaster.push_state()` and `self._broadcaster.update_metrics()` | VERIFIED | Both patterns found in `_run_loop` and `_frame_loop` |
| `streaming_service.py` | `hue_client.py` | `activate_entertainment_config` / `deactivate_entertainment_config` | VERIFIED | Lines 18 (import), 156, 198, 342 (usage) confirmed |
| `streaming_service.py` | `capture_service.py` | `self._capture.get_frame()` | VERIFIED | Line 266: `frame = await self._capture.get_frame()` |
| `streaming_service.py` | `color_math.py` | `extract_region_color` + `rgb_to_xy` | VERIFIED | Line 17 (import), lines 276-277 (usage per channel per frame) |
| `streaming_service.py` | `hue-entertainment-pykit` | `asyncio.to_thread(streaming.set_input / start_stream / stop_stream)` | VERIFIED | Lines 159, 162, 193, 284 — all pykit blocking calls wrapped in `asyncio.to_thread` |
| `_run_loop` -> `_frame_loop` | `_reconnect_loop` | `bridge_ip, username` from DB credentials | VERIFIED | Line 172: `await self._frame_loop(streaming, channel_map, bridge_ip, username)`. Line 288-290: `await self._reconnect_loop(self._config_id or "", bridge_ip, username)`. No hardcoded values. Gap closed by commit `1c92d03`. |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CAPT-03 | 03-02, 03-03 | Capture loop runs only when explicitly enabled via UI toggle | SATISFIED | `POST /api/capture/start` calls `streaming.start(config_id)` which starts the capture loop; loop does not run at startup |
| CAPT-04 | 03-02, 03-03 | Capture loop stops cleanly when disabled (releases device, closes connections) | SATISFIED | `POST /api/capture/stop` -> `streaming.stop()` -> finally block calls `capture.release()`. Lifespan shutdown also calls `streaming.stop()` before `capture.release()` |
| STRM-01 | 03-02 | Dominant color extracted from each mapped region using pre-computed polygon masks | SATISFIED | `_load_channel_map` builds masks once at start; `extract_region_color(frame, mask)` called per channel per frame |
| STRM-02 | 03-02 | RGB colors converted to CIE xy with Gamut C clamping before sending to bridge | SATISFIED | `rgb_to_xy(r, g, b)` called per channel; function implemented in color_math.py (Phase 2); result fed as `(x, y, bri, channel_id)` to `set_input` |
| STRM-03 | 03-01, 03-02, 03-03 | Colors streamed to bridge via Entertainment API (DTLS/UDP) at 25-50 Hz | SATISFIED | `TARGET_HZ = 50`, `PERIOD = 1/50`; `asyncio.to_thread(streaming.set_input, ...)` per channel; `streaming.start_stream()` opens DTLS session |
| STRM-04 | 03-01, 03-02 | All mapped channels sent in a single HueStream v2 UDP packet per frame | SATISFIED | All channels processed in a single `for channel_id, mask in channel_map.items()` loop per frame; pykit bundles into single packet |
| STRM-05 | 03-02, 03-03 | End-to-end latency under 100ms | SATISFIED (hardware verified) | 03-03-SUMMARY.md states hardware verification confirmed lights update from capture card feed under 100ms. See human verification note. |
| STRM-06 | 03-02 | Streaming supports 16+ simultaneous light channels | SATISFIED | `test_frame_loop_16_channels` verifies 16-channel map processes all 16 `set_input` calls per frame |
| GRAD-05 | 03-02 | Non-gradient Hue lights supported as single-color targets | SATISFIED | `test_frame_loop_1_channel_non_gradient` confirms 1-channel path calls `set_input` once |

All 9 required IDs fully covered. No orphaned requirement IDs detected for Phase 3 in REQUIREMENTS.md.

---

## Anti-Patterns Found

No blockers or warnings detected. The hardcoded credential anti-pattern identified in the initial verification has been eliminated.

---

## Human Verification Required

### 1. End-to-end latency measurement

**Test:** Run backend with a real capture card and bridge. Start streaming via `POST /api/capture/start`. Connect websocat to `ws://localhost:8000/ws/status`. Read `latency_ms` field over 30 seconds of active streaming.
**Expected:** `latency_ms` stays consistently below 100 during normal operation.
**Why human:** Automated tests mock `asyncio.to_thread`, `time.monotonic`, and all I/O. The `latency_ms` value in tests is not real elapsed time. The 03-03 SUMMARY claims hardware approval was given, but this is not programmatically verifiable.

---

## Gap Closure Verification

### Gap: Hardcoded reconnect credentials

**Previous finding:** `_frame_loop` called `_reconnect_loop("192.168.1.100", "testuser")` regardless of actual bridge IP.

**Fix in commit `1c92d03`:**
- `_run_loop` line 172 now passes `bridge_ip, username` to `_frame_loop`.
- `_frame_loop` signature updated: `async def _frame_loop(self, streaming, channel_map: dict, bridge_ip: str, username: str)`.
- `_frame_loop` lines 288-290 now pass `bridge_ip, username` to `_reconnect_loop`.
- Zero occurrences of `192.168.1.100` or `testuser` remain in `streaming_service.py`.
- All 111 tests pass with the updated signatures.

**Status: CLOSED.**

**Test coverage note:** No dedicated regression test was added to verify that a socket error in `_frame_loop` passes the caller-supplied `bridge_ip`/`username` to `_reconnect_loop`. The fix is structurally sound and the production path is correct. This is a test-coverage gap only; it does not block the phase.

---

_Verified: 2026-03-24T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
