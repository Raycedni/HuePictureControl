---
quick_id: 260516-iqp
slug: tier-1-real-time-light-sync-performance-
description: Tier 1 real-time light sync performance pass
date: 2026-05-16
mode: quick
must_haves:
  truths:
    - Hue glass-to-light latency must be well under 100ms (CLAUDE.md constraint)
    - Existing test contracts that probe shape (region_gradients dict, RegionMask, packet bytes) preserved
  artifacts:
    - Backend/services/streaming_service.py (HueStreamer: batched DTLS path)
    - Backend/services/color_math.py (vectorized sub_sample_gradient + rgb_to_xy_batch)
    - Backend/services/wled_streamer.py (vectorized color buffer + packet build)
    - Backend/services/streaming_coordinator.py (asyncio.gather both sinks)
    - Backend/tests/test_streaming_service.py (assert batched DTLS packet bytes)
    - Backend/tests/test_color_math.py (regression tests for vectorized paths)
    - Backend/tests/test_wled_packet.py / test_wled_streamer.py (numpy build correctness)
  key_links:
    - Backend/.venv/Lib/site-packages/hue_entertainment_pykit/services/streaming_service.py:160 (set_input → queue)
    - Backend/.venv/Lib/site-packages/hue_entertainment_pykit/services/streaming_service.py:293 (per-channel send)
---

# 260516-iqp — Tier 1 real-time light sync performance pass

## Goal

Cut end-to-end glass-to-light latency well under 100ms by removing the per-channel DTLS round trip, vectorizing the per-frame CPU hot spots, and fanning out to sinks concurrently.

## Audit summary (why these specific changes)

1. **Hue pykit sends one DTLS packet per channel per frame.** `StreamingService.set_input()` queues onto a `queue.Queue`; a background thread pops items one at a time and sends a separate DTLS message containing only that channel's data (`pykit/services/streaming_service.py:160-184`, `:293-337`). For 6 channels at 60Hz that's 360 sequential packets/sec instead of 60 batched packets, plus 360 `logger.info("Setting color...")` calls/sec.
2. `sub_sample_gradient` runs a Python for-loop over N samples calling `cv2.mean` per slab (`color_math.py:276-292`).
3. `rgb_to_xy` is scalar pure-Python per channel (`color_math.py:88-124`).
4. `wled_streamer` builds color buffers as list-of-tuples and packets via `bytes(c for rgb in colors for c in rgb)` Python generator (`wled_streamer.py:62, 84, 312-345`).
5. Coordinator serializes `hue.render` then `wled.render` (`streaming_coordinator.py:556-557`).

## Tasks

### Task A — Batched Hue DTLS packet

**Files:** `Backend/services/streaming_service.py`, `Backend/tests/test_streaming_service.py`

**Action:** Add `_build_dtls_message(channel_records)` in `HueStreamer` that assembles a single Hue Entertainment v2 frame with all channel records concatenated, then sends it via `self._streaming._dtls_service.get_socket().send(message)` directly (or — preferred — exposes a helper). Replace the per-channel `set_input` loop in `HueStreamer.render` with one packet build + one send. Also store `_last_message` on pykit so the keep-alive thread continues to function. Update `test_render_calls_set_input_per_channel` and siblings to assert the bytes of the assembled message instead of per-channel call counts.

**Wire format reference (pykit_streaming_service.py:_build_message):**
```
HueStream + v2 + seq(0x07) + 0x00 0x00 + color_space(0x01=xyb) + 0x00 + entertainment_id(36 bytes) + channel_records...
```
Each channel record (xyb mode): `[channel_id_u8][x_u16_be][y_u16_be][b_u16_be]` where xyb floats are scaled by 65535.

**Verify:** Per-frame DTLS packet count = 1 regardless of channel count. Backend tests pass.

**Done:** `pytest -q Backend/tests/test_streaming_service.py` green.

### Task B — Vectorize sub_sample_gradient

**Files:** `Backend/services/color_math.py`, `Backend/tests/test_color_math.py`

**Action:** Replace the per-i Python loop with a single vectorized path:
- Compute slab center indices once via `np.linspace(0, longest-1, n).astype(int)`.
- Build a 3-wide window per center by extracting columns/rows via `np.add.outer(centers, [-1, 0, 1]).clip(0, longest-1)` — or simpler: process the entire ROI as `cv2.reduce` along the long axis (per-column or per-row mean of masked pixels), then index the resulting (longest, 3) array at `centers`.
- Apply mask in-loop only at the cv2.reduce stage by zeroing masked pixels first and dividing by per-column/row mask counts; this collapses the N×cv2.mean calls into 1 reduce + 1 division.
- Preserve `Orientation` and `reverse` semantics.

**Verify:** Existing color_math tests pass. Add a parity test that compares vectorized output to the old loop-based output for several random regions.

**Done:** Tests green; profile shows ≥5× speedup on a 6-region/N=30 frame.

### Task C — Vectorize rgb_to_xy

**Files:** `Backend/services/color_math.py`, `Backend/services/streaming_service.py`

**Action:** Add `rgb_to_xy_batch(rgb_array: np.ndarray) -> tuple[np.ndarray, np.ndarray]` that returns `(xy[N,2], bri[N])`. Implementation: numpy gamma expansion on (N,3) → (N,3) linear RGB; matmul with the Wide-RGB D65 matrix; XYZ→xy with safe divide; vectorized barycentric in-gamut test + per-row segment-projection clamp using broadcasting. Keep scalar `rgb_to_xy` as a one-row wrapper for back-compat.

**Verify:** Add parity test: 1000 random RGB triples produce same xy (±1e-4) as scalar path.

**Done:** Tests green; HueStreamer.render uses the batch path on the per-frame mean-RGB array.

### Task D — Vectorize WLED color/packet build

**Files:** `Backend/services/wled_streamer.py`, `Backend/tests/test_wled_packet.py`

**Action:**
- `build_drgb_packet` / `build_dnrgb_packets`: accept either list-of-tuples or `np.ndarray[uint8](N,3)`; emit body via `arr.astype(np.uint8, copy=False).tobytes()`.
- `_render_one_device`: use `colors = np.zeros((led_count, 3), dtype=np.uint8)`; fill ranges via slice assignment and `np.linspace` index for resampling; drop the per-LED Python loop.

**Verify:** `test_wled_packet.py` byte-exact unchanged. Add parity test ndarray vs list path produces identical bytes.

**Done:** Tests green.

### Task E — Parallel sink render

**Files:** `Backend/services/streaming_coordinator.py`

**Action:** Replace
```python
await self._hue.render(region_gradients)
await self._wled.render(region_gradients)
```
with `asyncio.gather(...)`. Preserve bridge-error handling: gather with `return_exceptions=True`, then route any Hue exception to `handle_bridge_error`. WLED errors stay isolated per D-06.

**Verify:** `pytest Backend/tests/test_streaming_coordinator.py` green; both sinks still invoked per frame.

**Done:** Tests green.

## Risk register

- **Bridge wire format mismatch.** Mitigated by reusing the exact pykit byte layout and asserting equality in tests against a known-good packet.
- **DTLS keep-alive thread.** pykit's `_keep_connection_alive` re-sends `self._last_message` every 9.5s. Keeping `last_message` updated after each batched send preserves keep-alive correctness.
- **Color drift from vectorized gamma.** Mitigated by parity test with tight ±1e-4 tolerance on xy.
- **N-sample tiny region.** Existing `n_effective = max(1, min(n, longest))` semantics preserved bit-for-bit.

## Out of scope

- Removing pykit entirely (Tier 2)
- LUT-based rgb_to_xy (Tier 2)
- Capture pipeline changes (MJPEG decode, V4L2)
- Frontend changes
