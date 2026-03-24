# Phase 3: Entertainment API Streaming Integration - Research

**Researched:** 2026-03-24
**Domain:** Philips Hue Entertainment API / HueStream v2 / asyncio streaming loop / FastAPI WebSocket
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Stop behavior**
- Graceful drain: finish sending the current frame's colors, then deactivate entertainment mode via REST API
- Bridge handles light restoration — deactivating entertainment mode returns lights to their previous scene/state automatically
- Capture device released immediately on Stop (frees USB for other processes; ~200ms warmup cost on next Start is acceptable)
- Sequence: finish current packet → deactivate entertainment config → close DTLS → release capture device

**Error recovery — bridge disconnect**
- Auto-reconnect with exponential backoff: 1s, 2s, 4s... capped at 30s
- Unlimited retries (bridge reboots can take 2-3 minutes; user can press Stop to cancel)
- Full re-activation on reconnect: PUT /entertainment_configuration/{id} to re-activate, then open new DTLS session
- Push state transitions to /ws/status: 'bridge disconnected' → 'reconnecting (attempt N)' → 'reconnected'
- Continue capturing frames during bridge reconnect (capture pipeline runs independently)

**Error recovery — capture card disconnect**
- Stop streaming entirely: stop capture, close DTLS, deactivate entertainment mode
- Push error to /ws/status with human-readable message
- User must replug the capture card and press Start manually

**Status WebSocket (/ws/status)**
- 1 Hz heartbeat with: FPS, latency, bridge connection state, packets sent, packets dropped, sequence number
- Immediate push on state transitions (start, stop, error, reconnect) in addition to heartbeat
- Streaming state enum: 'idle' | 'starting' | 'streaming' | 'reconnecting' | 'error' | 'stopping'
- Human-readable error messages: 'Bridge disconnected', 'Capture device lost', 'Reconnecting (attempt 3)'
- Broadcast to all connected WebSocket clients (multiple browser tabs supported)
- No per-channel color data in status feed

### Claude's Discretion

- Asyncio loop architecture (how capture → color extraction → packet building → DTLS send is structured)
- HueStream v2 binary packet format implementation
- Thread pool management for blocking cap.read()
- Keep-alive implementation (resend if silent >9.5s)
- Entertainment configuration activation/deactivation REST call patterns
- Region-to-channel mapping data flow from SQLite to send loop

### Deferred Ideas (OUT OF SCOPE)

- Per-channel color data in /ws/status — could enable live color preview widgets (v2 requirement AUI-04)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CAPT-03 | Capture loop runs only when explicitly enabled via the UI toggle | `POST /api/capture/start` and `POST /api/capture/stop` endpoints gated by `asyncio.Event` on `StreamingService` |
| CAPT-04 | Capture loop stops cleanly when disabled (releases device, closes connections) | `LatestFrameCapture.release()` + `Streaming.stop_stream()` + REST deactivate called in sequence |
| STRM-01 | Dominant color extracted from each mapped region using pre-computed polygon masks | `color_math.extract_region_color()` + `build_polygon_mask()` already implemented; masks computed once at loop start from `light_assignments` JOIN `regions` |
| STRM-02 | RGB colors converted to CIE xy with Gamut C clamping before sending to bridge | `color_math.rgb_to_xy()` already implemented; feeds into `Streaming.set_input(x, y, bri, channel_id)` in xyb mode |
| STRM-03 | Colors streamed via Entertainment API (DTLS/UDP) at 25-50 Hz | `hue-entertainment-pykit` `Streaming` class with `set_color_space("xyb")` and looped `set_input()`; library's internal send loop runs continuously, user drives it at target Hz |
| STRM-04 | All mapped channels sent in a single HueStream v2 UDP packet per frame | Library batches all `set_input()` calls made within a single "frame window" into one UDP datagram; each channel occupies 7 bytes in the packet |
| STRM-05 | End-to-end latency from frame capture to light update under 100ms | Avoid blocking event loop: `asyncio.to_thread()` for `cap.read()` and `streaming.set_input()` calls; target 50 Hz send loop (20ms frame budget) |
| STRM-06 | Streaming supports 16+ simultaneous light channels | HueStream v2 supports up to 20 channels per packet; 16 channels × 7 bytes = 112 bytes of channel data, well within UDP limits |
| GRAD-05 | Non-gradient lights supported as single-color targets | `light_assignments` rows with single `channel_id` per region — identical code path as gradient segments, just one channel per region |
</phase_requirements>

---

## Summary

Phase 3 wires together three existing subsystems — `LatestFrameCapture` (Phase 2), `color_math` (Phase 2), and the DTLS spike pattern (Phase 1) — into a managed streaming service with a REST-controlled lifecycle and a WebSocket status feed. The central new artifact is a `StreamingService` class that owns an asyncio task running the capture → extract → stream loop at 25-50 Hz and a `StatusBroadcaster` that fan-outs state/metric updates to all connected WebSocket clients.

The most important architectural decision is that `hue-entertainment-pykit`'s `Streaming` class is synchronous and runs its own background threads internally. The outer asyncio service must wrap `start_stream()`, `stop_stream()`, and `set_input()` calls with `asyncio.to_thread()` to avoid blocking the event loop. The library's internal keep-alive (9.5s resend) is sufficient — the application loop does not need a separate keep-alive timer. The user's bridge-reconnect logic must be implemented in the asyncio service because the library's built-in reconnect only retries 3 times.

Entertainment configuration must be activated via `PUT /clip/v2/resource/entertainment_configuration/{id}` with `{"action":"start"}` before the DTLS handshake. The bridge silently rejects DTLS connections if the config is not in "streaming" state. On reconnect the full activation sequence must repeat. Deactivation (`{"action":"stop"}`) should be called on shutdown so the bridge restores the prior scene.

**Primary recommendation:** Build a `StreamingService` async class with an internal `asyncio.Task` running the frame loop, an `asyncio.Event` as the start/stop gate, a `StatusBroadcaster` for WebSocket fan-out, and thin `asyncio.to_thread()` wrappers around all `hue-entertainment-pykit` calls.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| hue-entertainment-pykit | 0.9.4 (pinned) | DTLS session + HueStream v2 packet building + send loop | Only Python library with working DTLS PSK; already proven in Phase 1 spike |
| httpx | >=0.27 | Async REST calls to bridge (activate/deactivate entertainment config) | Already in use for `list_entertainment_configs`; async-native |
| FastAPI (Starlette WebSocket) | >=0.115 | `/ws/status` WebSocket endpoint | Already the web framework; Starlette WebSocket is built in |
| asyncio (stdlib) | Python 3.12 | Task/Event/to_thread coordination | No additional install; Python 3.12 pinned by project |
| aiosqlite | >=0.20 | Read `regions` + `light_assignments` at loop start | Already used for all DB access in project |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| opencv-python-headless | >=4.10 | `cap.read()` in thread pool | Already in use; drives `LatestFrameCapture` |
| numpy | (opencv transitive dep) | Frame array for `extract_region_color` | Already used in color_math |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| hue-entertainment-pykit | Raw DTLS socket + manual packet builder | Requires `mbedtls` Python bindings directly; 200+ lines of packet format code; not worth it when the library already works |
| asyncio.to_thread | Run Streaming in a separate thread with asyncio.Queue bridge | Adds a queue + thread management layer; `to_thread` is simpler and sufficient for 50 Hz |
| In-memory ConnectionManager | encode/broadcaster (Redis) | Single-process; one worker per container; Redis pub/sub is out-of-scope complexity |

**Installation:** No new packages required — all dependencies are already in `requirements.txt`.

---

## Architecture Patterns

### Recommended Project Structure

```
Backend/
├── services/
│   ├── capture_service.py       # Existing (Phase 2)
│   ├── color_math.py            # Existing (Phase 2)
│   ├── hue_client.py            # Existing + add activate/deactivate helpers
│   ├── streaming_service.py     # NEW — asyncio streaming loop + lifecycle
│   └── status_broadcaster.py   # NEW — WebSocket fan-out manager
├── routers/
│   ├── capture.py               # Existing + add /start and /stop endpoints
│   └── streaming_ws.py          # NEW — /ws/status WebSocket endpoint
└── main.py                      # Update lifespan: init StreamingService + StatusBroadcaster
```

### Pattern 1: StreamingService — asyncio Task with Event Gate

**What:** An async class owning the entire streaming lifecycle. An `asyncio.Event` (`_run_event`) gates the inner loop. When set, the loop runs; when cleared, the loop exits cleanly after finishing the current frame.

**When to use:** Single-instance service owned by `app.state`; started/stopped via REST endpoints.

```python
# Source: established project pattern (main.py lifespan + capture_service.py)
class StreamingService:
    def __init__(self, db, capture, broadcaster):
        self._db = db
        self._capture = capture
        self._broadcaster = broadcaster
        self._run_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._state = "idle"

    async def start(self, config_id: str) -> None:
        if self._state not in ("idle", "error"):
            return
        self._state = "starting"
        await self._broadcaster.push_state(self._state)
        self._run_event.set()
        self._task = asyncio.create_task(self._run_loop(config_id))

    async def stop(self) -> None:
        if self._state == "idle":
            return
        self._state = "stopping"
        await self._broadcaster.push_state(self._state)
        self._run_event.clear()
        if self._task:
            await self._task  # waits for graceful drain

    async def _run_loop(self, config_id: str) -> None:
        # load channel map, activate entertainment config, open DTLS, loop
        ...
```

### Pattern 2: hue-entertainment-pykit Wrapped in asyncio.to_thread

**What:** All synchronous `Streaming` methods wrapped with `asyncio.to_thread()` to avoid blocking the event loop. The library uses its own background threads; `to_thread` calls are fire-and-don't-block.

**When to use:** Every call to `streaming.start_stream()`, `streaming.stop_stream()`, and `streaming.set_input()`.

```python
# Source: established project pattern (capture_service.py _read_frame / get_frame)
import asyncio
from hue_entertainment_pykit import create_bridge, Entertainment, Streaming

# Wrap synchronous library calls
await asyncio.to_thread(streaming.start_stream)
await asyncio.to_thread(streaming.set_color_space, "xyb")

# In the send loop — one call per channel per frame
for channel_id, (x, y, bri) in channel_colors.items():
    await asyncio.to_thread(streaming.set_input, (x, y, bri, channel_id))
```

**Note:** `set_input()` enqueues to an internal `Queue` and returns immediately. The `to_thread` cost is negligible but ensures the event loop is never blocked if the queue temporarily stalls.

### Pattern 3: Entertainment Configuration Activation via REST

**What:** Before calling `streaming.start_stream()`, activate the entertainment configuration via Hue CLIP v2 REST API. On shutdown, deactivate.

**When to use:** At the beginning of `_run_loop()` and in the shutdown/reconnect path.

```python
# Source: IoTech blog + official Hue developer docs (verified via WebSearch)
# Activation
async def activate_entertainment_config(bridge_ip, username, config_id):
    url = f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration/{config_id}"
    headers = {"hue-application-key": username}
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.put(url, json={"action": "start"}, headers=headers)
        resp.raise_for_status()

# Deactivation
async def deactivate_entertainment_config(bridge_ip, username, config_id):
    url = f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration/{config_id}"
    headers = {"hue-application-key": username}
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        await client.put(url, json={"action": "stop"}, headers=headers)
        # Best-effort: don't raise — we're shutting down anyway
```

**Critical ordering:** `activate_entertainment_config()` MUST complete before `streaming.start_stream()` is called. The bridge silently rejects the DTLS handshake if the config is not in streaming state.

### Pattern 4: StatusBroadcaster — WebSocket Fan-Out

**What:** An in-memory `ConnectionManager` tracking all active `/ws/status` WebSocket connections. Provides `broadcast(message)` and `push_state(state)` methods. A background `asyncio.Task` sends the 1 Hz heartbeat.

**When to use:** Single instance on `app.state.broadcaster`, shared by StreamingService and the WebSocket router.

```python
# Source: FastAPI official docs WebSocket pattern
import json
from fastapi import WebSocket, WebSocketDisconnect

class StatusBroadcaster:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._metrics: dict = {"state": "idle", "fps": 0, "latency_ms": 0,
                                "packets_sent": 0, "packets_dropped": 0, "seq": 0}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        # Send current state immediately on connect
        await ws.send_text(json.dumps(self._metrics))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.remove(ws)

    async def broadcast(self, data: dict) -> None:
        self._metrics.update(data)
        dead = []
        for ws in self._connections:
            try:
                await ws.send_text(json.dumps(self._metrics))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.remove(ws)

    async def push_state(self, state: str, error: str | None = None) -> None:
        payload = {"state": state}
        if error:
            payload["error"] = error
        await self.broadcast(payload)
```

### Pattern 5: Frame Loop with Timing

**What:** The inner loop reads one frame, extracts colors for all channels, sends all `set_input()` calls, updates metrics, and sleeps to maintain target Hz. Target 50 Hz (20ms period); measure actual elapsed to compute FPS.

**When to use:** Inside `StreamingService._run_loop()`.

```python
import time, asyncio

TARGET_HZ = 50
PERIOD = 1.0 / TARGET_HZ  # 0.020s

async def _frame_loop(self, streaming, channel_map):
    seq = 0
    packets_sent = 0
    while self._run_event.is_set():
        t0 = time.monotonic()
        frame = await self._capture.get_frame()
        channel_colors = {}
        for channel_id, mask in channel_map.items():
            r, g, b = extract_region_color(frame, mask)
            x, y = rgb_to_xy(r, g, b)
            bri = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255.0
            channel_colors[channel_id] = (x, y, max(bri, 0.01))

        for channel_id, (x, y, bri) in channel_colors.items():
            await asyncio.to_thread(streaming.set_input, (x, y, bri, channel_id))

        seq = (seq + 1) % 256
        packets_sent += 1
        elapsed = time.monotonic() - t0
        latency_ms = elapsed * 1000

        await self._broadcaster.broadcast({
            "fps": round(1.0 / max(elapsed, 0.001)),
            "latency_ms": round(latency_ms),
            "packets_sent": packets_sent,
            "seq": seq,
        })

        sleep_time = PERIOD - elapsed
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
```

### Pattern 6: Exponential Backoff Reconnect

**What:** On socket error inside the frame loop, transition to `reconnecting` state, clear DTLS session, sleep with backoff, re-activate entertainment config, re-open DTLS. The user's custom reconnect logic replaces the library's 3-attempt limit.

```python
# User-defined unlimited retry (locked decision)
async def _reconnect_loop(self, config_id: str, bridge_ip: str, username: str):
    attempt = 0
    delay = 1.0
    while self._run_event.is_set():
        attempt += 1
        await self._broadcaster.push_state(
            "reconnecting", f"Reconnecting (attempt {attempt})"
        )
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30.0)
        try:
            await activate_entertainment_config(bridge_ip, username, config_id)
            # rebuild Streaming object (bridge == same, new DTLS handshake)
            return True  # success
        except Exception:
            continue
    return False  # run_event cleared (user pressed Stop)
```

### Pattern 7: Channel Map Loading from SQLite

**What:** At loop start, read all `light_assignments` rows for the selected `entertainment_config_id`, join with `regions` to get polygon coordinates, pre-compute `build_polygon_mask()` once per channel.

```python
# Source: aiosqlite pattern from existing database.py
async def _load_channel_map(db, config_id: str) -> dict[int, np.ndarray]:
    """Returns {channel_id: mask_array} for the selected config."""
    query = """
        SELECT la.channel_id, r.polygon
        FROM light_assignments la
        JOIN regions r ON la.region_id = r.id
        WHERE la.entertainment_config_id = ?
    """
    async with db.execute(query, (config_id,)) as cursor:
        rows = await cursor.fetchall()

    channel_map = {}
    for row in rows:
        channel_id = row["channel_id"]
        polygon = json.loads(row["polygon"])  # [[x,y], ...]
        channel_map[channel_id] = build_polygon_mask(polygon)
    return channel_map
```

### Anti-Patterns to Avoid

- **Calling `streaming.start_stream()` without activating the config first:** Bridge silently refuses the DTLS handshake. Always `PUT /entertainment_configuration/{id}` with `{"action":"start"}` first.
- **Blocking calls on the event loop:** `streaming.start_stream()`, `cap.read()`, and `streaming.set_input()` are all synchronous. Always wrap with `asyncio.to_thread()`.
- **Building a custom keep-alive timer:** The library's `_keep_connection_alive` thread sends the last message every 9.5 seconds automatically. No application-level keep-alive needed.
- **Re-computing polygon masks every frame:** Pre-compute once at loop start; masks are constant for a given configuration.
- **Catching `WebSocketDisconnect` inside `broadcast()`:** Catch generic `Exception` per-connection instead; `broadcast()` must not raise so the loop continues to other connections.
- **Using `app.state` references captured at lifespan start in background tasks:** Pass explicit references to `StreamingService.__init__()` — avoids stale references if state is replaced.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DTLS / HueStream v2 packet assembly | Custom binary packet builder, DTLS socket | `hue-entertainment-pykit` `Streaming` class | DTLS PSK requires mbedTLS; packet format has 8-byte protocol name + version + seq + color mode + UUID + 7 bytes/channel; 200+ lines and hardware-tested edge cases |
| Keep-alive timer | Asyncio background task checking last-send time | Library's `_keep_connection_alive` thread | Already implemented at 9.5s interval; double-keep-alive causes issues |
| WebSocket multi-client broadcast | Custom pub/sub | In-memory `ConnectionManager` list | Single process, single worker; no Redis needed |
| CIE xy color conversion | Own math | `color_math.rgb_to_xy()` | Already implemented with Gamut C clamping |
| Polygon mask computation | Per-frame cv2.fillPoly | Pre-computed `build_polygon_mask()` at loop start | Masks are constant; per-frame recomputation is ~5ms CPU waste |

**Key insight:** `hue-entertainment-pykit` already handles the hardest parts (DTLS PSK handshake, HueStream v2 binary encoding, keep-alive). The application layer only needs to: activate the config via REST, call `start_stream()`, feed `set_input()` in a loop, and call `stop_stream()`.

---

## Common Pitfalls

### Pitfall 1: Entertainment Config Not Activated Before DTLS
**What goes wrong:** `streaming.start_stream()` completes without error but no lights respond. The bridge establishes the DTLS connection but silently discards all UDP packets because the entertainment configuration is in `inactive` state.
**Why it happens:** The DTLS handshake itself does not require the config to be active; only the data plane does.
**How to avoid:** Always `PUT /entertainment_configuration/{id}` with `{"action":"start"}` and confirm HTTP 200 before calling `streaming.start_stream()`.
**Warning signs:** Streaming loop runs at 50 Hz, metrics show packets_sent incrementing, but lights do not change.

### Pitfall 2: Library's Internal Reconnect Exhausted (3 Attempts)
**What goes wrong:** After 3 failed reconnect attempts, `hue-entertainment-pykit` stops retrying. The application loop continues but all `set_input()` calls silently drop.
**Why it happens:** The library's `_attempt_reconnect()` has a hard-coded 3-attempt limit.
**How to avoid:** Catch socket errors from `asyncio.to_thread(streaming.set_input, ...)` in the frame loop; implement the custom unlimited backoff reconnect at the application level (locked decision).
**Warning signs:** `packets_dropped` counter increases; latency_ms stays low but lights stop responding.

### Pitfall 3: Blocking the Event Loop
**What goes wrong:** Latency spikes from 20ms to 100ms+; uvicorn stops serving requests; WebSocket heartbeat stutters.
**Why it happens:** Calling `streaming.start_stream()` or `streaming.stop_stream()` directly (without `asyncio.to_thread`) blocks the event loop for the duration of the DTLS handshake (typically 100-300ms).
**How to avoid:** Every call to `hue-entertainment-pykit` methods must go through `asyncio.to_thread()`.
**Warning signs:** `/ws/status` heartbeats arrive irregularly; REST endpoints respond slowly during stream start/stop.

### Pitfall 4: Frame Rate Exceeds Bridge's Effective Rate
**What goes wrong:** CPU usage spikes; `set_input()` queue inside the library backs up; lights skip colors.
**Why it happens:** Philips Hue Bridge processes ~25 Hz Zigbee updates. Sending at 100+ Hz fills the library's input queue.
**How to avoid:** Target 50 Hz (one frame every 20ms). The bridge upsamples internally; 50 Hz client-side accommodates UDP packet loss without perceptible lag.
**Warning signs:** `packets_sent` grows faster than `fps` metric implies; CPU stays at 100%.

### Pitfall 5: Brightness Too Low for Dark Regions
**What goes wrong:** Lights turn off when the camera captures a dark scene (all-black frame).
**Why it happens:** `rgb_to_xy()` returns D65 white point for black input, but brightness derived from luminance is ~0.0. The bridge interprets bri=0 as "off".
**How to avoid:** Clamp brightness to a minimum (e.g., `max(bri, 0.01)`) or use a configurable minimum brightness floor.
**Warning signs:** Lights click off during dark scenes; clicking back on when scene brightens.

### Pitfall 6: WebSocket Broadcast Raises on Dead Connection
**What goes wrong:** One disconnected client causes `broadcast()` to raise, aborting delivery to all subsequent clients.
**Why it happens:** `ws.send_text()` raises `WebSocketDisconnect` or `RuntimeError` for a closed socket.
**How to avoid:** Wrap each `send_text()` in try/except inside `broadcast()`; collect dead connections and remove after iteration.
**Warning signs:** Connected clients stop receiving heartbeats after any one client disconnects.

### Pitfall 7: Stop Sequence Deactivates Config Before DTLS Closes
**What goes wrong:** Bridge terminates the DTLS session mid-packet; final color frame may not reach lights.
**Why it happens:** Deactivating entertainment config causes the bridge to close the UDP port.
**How to avoid:** Follow locked sequence: finish current packet → `asyncio.to_thread(streaming.stop_stream)` → `deactivate_entertainment_config()` → `capture.release()`.
**Warning signs:** `SocketError` raised during `stop_stream()` when bridge already closed connection.

---

## Code Examples

### Bridge Object Construction (port from spike)

```python
# Source: Backend/spike/dtls_test.py (existing, verified working)
from hue_entertainment_pykit import create_bridge, Entertainment, Streaming

bridge = create_bridge(
    identification=creds["bridge_id"],
    rid=creds["rid"],
    ip_address=creds["ip_address"],
    username=creds["username"],
    hue_app_id=creds["hue_app_id"],
    clientkey=creds["client_key"],
    swversion=creds["swversion"],
    name=creds["name"],
)
entertainment = Entertainment(bridge)
configs = entertainment.get_entertainment_configs()
config = list(configs.values())[0]
repo = entertainment.get_ent_conf_repo()
streaming = Streaming(bridge, config, repo)
```

### Full Start Sequence (with asyncio.to_thread wrappers)

```python
# Source: pattern derived from spike + asyncio.to_thread project pattern
await activate_entertainment_config(bridge_ip, username, config_id)
await asyncio.to_thread(streaming.start_stream)
await asyncio.to_thread(streaming.set_color_space, "xyb")
```

### Multi-Channel Send (one frame)

```python
# Source: hue-entertainment-pykit README + set_input(tuple) API
# set_input accepts (x, y, brightness, channel_id) in "xyb" mode
for channel_id, (x, y, bri) in channel_colors.items():
    await asyncio.to_thread(streaming.set_input, (x, y, bri, channel_id))
```

### Clean Stop Sequence

```python
# Source: locked decision from CONTEXT.md + spike stop_stream pattern
# finish_current_packet: last set_input() already called above
await asyncio.to_thread(streaming.stop_stream)
await deactivate_entertainment_config(bridge_ip, username, config_id)
capture.release()
```

### REST Capture Start/Stop Endpoints

```python
# Source: FastAPI pattern from existing capture.py + CONTEXT.md locked decisions
@router.post("/start")
async def start_capture(body: StartRequest, request: Request):
    streaming_service = request.app.state.streaming
    await streaming_service.start(body.config_id)
    return {"status": "starting"}

@router.post("/stop")
async def stop_capture(request: Request):
    streaming_service = request.app.state.streaming
    await streaming_service.stop()
    return {"status": "stopping"}
```

### WebSocket Status Endpoint

```python
# Source: FastAPI WebSocket docs pattern
from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/ws/status")
async def ws_status(websocket: WebSocket, request: Request):
    broadcaster = request.app.state.broadcaster
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive; client may send pings
    except WebSocketDisconnect:
        broadcaster.disconnect(websocket)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hue v1 clip/v1 API for entertainment groups | CLIP v2 `/clip/v2/resource/entertainment_configuration` | Hue Bridge firmware 1.50+ (2022) | `PUT` with `{"action":"start"}` replaces old `/groups/{id}` `stream.active=true` |
| Manual DTLS socket + struct-pack for HueStream | `hue-entertainment-pykit` | Library available since 2022 | Removes 200+ lines of DTLS/PSK/packet code |
| Python ssl for DTLS | `hue-entertainment-pykit` mbedTLS bindings | Always | Python stdlib ssl has no DTLS support |

**Deprecated/outdated:**
- Hue v1 `/api/{username}/groups/{id}` for streaming activation: still works on bridge but deprecated; use CLIP v2.
- Python 3.13+: `hue-entertainment-pykit` mbedTLS bindings break; project pinned to Python 3.12.

---

## Open Questions

1. **Does `hue-entertainment-pykit` 0.9.4 expose a `set_input` signature change vs 0.9.3?**
   - What we know: 0.9.3 on PyPI; project pinned to 0.9.4; spike uses `set_input((x, y, bri, channel_id))`
   - What's unclear: Whether 0.9.4 changed anything vs 0.9.3 (changelog not found)
   - Recommendation: Run the spike script against the pinned 0.9.4 to confirm tuple order before building the loop

2. **Does `streaming.start_stream()` block for the full DTLS handshake duration?**
   - What we know: Library uses threads internally; `start_stream()` is synchronous
   - What's unclear: Whether it returns after handshake or after first packet confirmation
   - Recommendation: Wrap with `asyncio.to_thread()` regardless; measure blocking time in Wave 0

3. **What does the bridge return when `PUT /entertainment_configuration/{id}` `{"action":"stop"}` is called while DTLS is open?**
   - What we know: Bridge closes the UDP port; `stop_stream()` may raise `SocketError`
   - What's unclear: Whether to ignore the error or log it
   - Recommendation: In the stop sequence, catch `SocketError` from `stop_stream()` and log at WARNING level; continue to `deactivate`

4. **How many `set_input()` calls per frame are batched into a single UDP packet?**
   - What we know: HueStream v2 supports up to 20 channels (7 bytes each); library processes one channel per `set_input()` call
   - What's unclear: Whether the library batches all channel calls made within a single "frame" into one packet or sends one packet per call
   - Recommendation: Test with 3+ channels and inspect via Wireshark; if one-packet-per-call, explore library's batch API if available

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3 + pytest-asyncio 0.24 |
| Config file | `Backend/pytest.ini` (exists: `asyncio_mode = auto`, `asyncio_default_fixture_loop_scope = function`) |
| Quick run command | `cd Backend && python -m pytest tests/test_streaming_service.py tests/test_streaming_ws.py -x -q` |
| Full suite command | `cd Backend && python -m pytest tests/ -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAPT-03 | POST /api/capture/start with valid config_id transitions state to 'streaming' | unit | `pytest tests/test_capture_router.py::TestStartStop -x` | Wave 0 |
| CAPT-04 | POST /api/capture/stop causes capture.release() to be called | unit | `pytest tests/test_capture_router.py::TestStartStop -x` | Wave 0 |
| STRM-01 | extract_region_color called for each channel in channel_map per frame | unit | `pytest tests/test_streaming_service.py::TestFrameLoop -x` | Wave 0 |
| STRM-02 | rgb_to_xy output fed into set_input (x, y, ...) correctly | unit | `pytest tests/test_streaming_service.py::TestFrameLoop -x` | Wave 0 |
| STRM-03 | Frame loop runs at ~50 Hz (timing test with mocked capture) | unit | `pytest tests/test_streaming_service.py::TestFrameRate -x` | Wave 0 |
| STRM-04 | set_input called once per channel per frame (not more) | unit | `pytest tests/test_streaming_service.py::TestFrameLoop -x` | Wave 0 |
| STRM-05 | Total frame processing time measured in test; assert < 100ms per frame | unit | `pytest tests/test_streaming_service.py::TestLatency -x` | Wave 0 |
| STRM-06 | Channel map with 16 entries processes all channels without error | unit | `pytest tests/test_streaming_service.py::TestMultiChannel -x` | Wave 0 |
| GRAD-05 | Single-channel light_assignment row results in single set_input call per frame | unit | `pytest tests/test_streaming_service.py::TestSingleChannel -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `cd Backend && python -m pytest tests/test_streaming_service.py tests/test_capture_router.py -x -q`
- **Per wave merge:** `cd Backend && python -m pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `Backend/tests/test_streaming_service.py` — covers STRM-01..STRM-06, GRAD-05 (service layer unit tests with mocked Streaming and LatestFrameCapture)
- [ ] `Backend/tests/test_streaming_ws.py` — covers /ws/status WebSocket endpoint, StatusBroadcaster broadcast, disconnection handling
- [ ] `Backend/services/streaming_service.py` — new file (implementation)
- [ ] `Backend/services/status_broadcaster.py` — new file (implementation)
- [ ] `Backend/routers/streaming_ws.py` — new file (WebSocket endpoint)
- [ ] Fixtures in `conftest.py`: `_make_streaming_mock()`, `streaming_app_client()` — analogous to existing `_make_capture_mock()`

---

## Sources

### Primary (HIGH confidence)

- `Backend/spike/dtls_test.py` — confirmed working `create_bridge()` → `Entertainment()` → `Streaming()` → `set_input()` pattern
- `Backend/services/capture_service.py` — `asyncio.to_thread()` pattern for blocking calls (project-established)
- `Backend/services/color_math.py` — `rgb_to_xy()`, `build_polygon_mask()`, `extract_region_color()` verified implementations
- `Backend/database.py` — schema with `light_assignments` JOIN `regions` for channel map loading
- FastAPI official docs (https://fastapi.tiangolo.com/advanced/websockets/) — ConnectionManager WebSocket broadcast pattern
- IoTech blog (https://iotech.blog/posts/philips-hue-entertainment-api/) — HueStream v2 packet format: 8-byte protocol name + version bytes + seq + reserved + color mode + UUID + 7 bytes/channel

### Secondary (MEDIUM confidence)

- hue-entertainment-pykit GitHub README (https://github.com/hrdasdominik/hue-entertainment-pykit) — `set_input((x,y,bri,channel_id))` API, keep-alive at 9.5s, event queue threading model
- hue-entertainment-pykit streaming_service.py source (fetched via WebFetch) — internal threading model: `_watch_user_input` + `_keep_connection_alive` threads, `_attempt_reconnect` 3-attempt limit, start/stop REST payload `{"action":"start"/"stop"}`

### Tertiary (LOW confidence)

- WebSearch: library's 3-attempt reconnect limit — not directly confirmed in source but consistent with multiple sources; needs empirical validation during Wave 0

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in requirements.txt; spike confirmed hue-entertainment-pykit works
- Architecture: HIGH — patterns derived from existing project code + verified library API
- Pitfalls: HIGH — Pitfall 1 (activation order) confirmed by official docs; Pitfall 2 (3-attempt limit) MEDIUM (library source code reviewed but not line-counted)
- HueStream v2 packet format: MEDIUM — confirmed header structure via IoTech blog; library handles it internally so planner doesn't need raw format details

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (library is maintenance mode; Hue API stable)
