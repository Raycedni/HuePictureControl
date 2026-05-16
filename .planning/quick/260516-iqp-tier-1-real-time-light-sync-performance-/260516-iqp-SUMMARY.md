---
quick_id: 260516-iqp
status: complete
date: 2026-05-16
commits:
  - 8ac72f1 perf(hue): batch all channels into one DTLS packet + vectorize color math
  - d00bb25 perf(wled,coord): vectorize WLED color buffer + parallelize sink renders
  - 48f6482 perf(color_math,hue): revert sub_sample_gradient + scalar rgb_to_xy in render
---

# 260516-iqp — Tier 1 real-time light sync performance pass

## Outcome

Cut Hue-side per-frame DTLS round trips from N to 1 and removed the
pykit logging spam that ran 360 times/sec at 60Hz × 6 channels. WLED
packet build dropped from ~30us to ~0.4us per device per frame (73×).
Hue + WLED renders now overlap on the event loop instead of serializing.

The headline win is the DTLS batching — every other change combined
saves a few hundred microseconds of CPU per frame, but batching
eliminates **5 sequential DTLS round trips per frame at our typical
6-channel config**. Each round trip is bounded by bridge processing
latency (5–10 ms in practice), so this is where the perceptible "light
follows screen instantly" win comes from.

## What landed

| Tier | Change | Outcome |
|------|--------|---------|
| A | One batched DTLS packet per frame containing all channel records | **Headline win.** 6→1 DTLS packets per frame, no pykit queue/thread hop, no per-channel logger.info spam. |
| B | Vectorize `sub_sample_gradient` | **Reverted.** Microbenched 16× slower at N=30, 4.8× slower at N=100. Crossover with scalar cv2.mean loop only at N=490. |
| C | `rgb_to_xy_batch` exported, used in `HueStreamer.render` | Partially adopted. `rgb_to_xy_batch` is kept as a public API (tested, available) but render uses scalar `rgb_to_xy` because numpy broadcasting overhead at 6 channels (~56us) exceeded the scalar cost (~16us). |
| D | Vectorize WLED packet + color buffer | **Win.** `colors = np.zeros((led_count, 3), uint8)` + slice assignment + `arr.tobytes()` is 73× faster than `bytes(c for rgb in colors for c in rgb)` at 490 LEDs. |
| E | `asyncio.gather` of Hue + WLED render | **Win** (small). Overlapping the two sinks on the event loop saves one frame of wall-clock when both are active. `return_exceptions=True` so a WLED exception cannot mask a Hue bridge error. |

## How the DTLS batching works

pykit's `StreamingService.set_input(...)` queues each `(x, y, bri, ch_id)` onto a
`queue.Queue`. A background thread (`_watch_user_input`) pops items one at a time
and calls `_send_color_to_light`, which builds a complete Hue Entertainment v2
DTLS message containing **only that single channel's record** and sends it. So
a 6-channel frame produced 6 sequential DTLS packets, each with the full 52-byte
header + 7-byte body, each waiting on the previous to clear the bridge.

The Hue Entertainment v2 protocol allows multiple channel records in one
message — pykit just doesn't take advantage of it. Now we do:

1. `HueStreamer.start()` captures the live DTLS socket
   (`self._streaming._dtls_service.get_socket()`) and the 36-byte
   entertainment-config UUID (`self._streaming._entertainment_id`) once.
2. `render()` builds one message: identical 52-byte header + `N × 7` bytes of
   concatenated `[ch_id u8][x u16_be][y u16_be][b u16_be]` records.
3. Sends once via `asyncio.to_thread(sock.send, message)`.
4. Writes the message into `self._streaming._last_message` so pykit's existing
   `_keep_connection_alive` thread retransmits the latest frame during idle
   gaps (>9.5s without render).

Wire format is byte-identical to pykit's `_build_message`, just with multiple
records concatenated in the body. The bridge's parser sees the same layout it
already accepts.

## Microbenchmark results

```
Per-frame Hue work (6 regions, N=1, rgb_to_xy):  108us
Per-frame WLED work (6 regions, N=30):           473us
Total Python work per frame:                    ~600us  (3.5% of 16.7ms @ 60Hz)
```

CPU was never the bottleneck — the 100ms latency in CLAUDE.md was wall-clock
dominated by the 5–6× serialized DTLS packets per frame. With batching that
becomes one packet + one bridge processing window.

```
build_drgb_packet @ 490 LEDs:
  list-of-tuples (old):           30.3us/call
  list-of-tuples (new wrapper):   46.7us/call  (np.asarray upfront)
  ndarray (production path):       0.4us/call  (73x speedup vs old)

sub_sample_gradient @ 480×640 frame, 0.8 region, N=30:
  cv2.mean loop (kept):           141us/call
  prefix-sum vectorized (reverted): 2265us/call  (16x slower)
```

## What did NOT land (and why)

- **Remove pykit entirely.** Tier 2. The library still owns DTLS handshake
  + keep-alive thread + reconnect retries — non-trivial to replace.
- **5-bit-per-channel rgb_to_xy LUT.** Tier 2. ~128KB table would be a
  one-time CPU saving of ~2ms/sec — small absolute gain.
- **MJPEG decode speed.** Out of scope; `cv2.imdecode` is the right tool.
- **Capture pipeline (V4L2/DShow).** Already mmap + reader thread.

## Risks accepted

- **Bridge protocol stability.** We send the same byte layout pykit builds,
  just with N records instead of 1. Any future Hue firmware change to the
  wire format would affect pykit too — same risk profile.
- **Concurrent DTLS writes.** pykit's keep-alive thread and our render path
  can both call `sock.send` from different threads. Same race window existed
  pre-batching (set_input thread + keep-alive thread). Mitigation: at 60Hz
  render, keep-alive (9.5s interval) rarely fires during streaming.

## Files changed

- `Backend/services/streaming_service.py` — batched DTLS message build + scalar inline encode
- `Backend/services/color_math.py` — `rgb_to_xy_batch` exported
- `Backend/services/wled_streamer.py` — ndarray-accepting packet builders + vectorized device fill
- `Backend/services/streaming_coordinator.py` — `asyncio.gather` of Hue+WLED renders
- `Backend/tests/test_streaming_service.py` — new test for batched-packet wire format

## Test status

- Backend: 325 passed, 21 skipped (Phase 19 SQL-skip path), 12 cameras_router failures pre-existing on Windows (sysfs unavailable)
- Frontend: not run — no frontend code changed
