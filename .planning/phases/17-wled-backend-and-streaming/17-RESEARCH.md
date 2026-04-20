# Phase 17: WLED Backend and Streaming — Research

**Researched:** 2026-04-20
**Domain:** UDP realtime streaming, FastAPI service refactor, mDNS discovery, multi-sink capture pipeline
**Confidence:** HIGH (protocol specs, architecture) / MEDIUM (perf tuning at 60 Hz × N devices)

## Summary

Phase 17 introduces a second streaming sink (WLED) alongside the existing Hue pipeline. The central architectural move is extracting a `StreamingCoordinator` that owns the capture loop and fans out one decoded frame to two sinks (`HueStreamer`, `WledStreamer`). WLED talks to ESP32 devices via raw UDP using two WLED-specific protocols: **DRGB** (protocol byte `0x02`, ≤490 LEDs) and **DNRGB** (protocol byte `0x04`, >490 LEDs in 489-LED chunks with a 2-byte start index). Both carry a 1-byte timeout that the ESP32 uses to return to its normal mode if packets stop.

Every protocol decision is already locked in 17-CONTEXT.md and CLAUDE.md — research confirms byte-exact layouts, maximum LEDs per packet, `/json/info` schema fields, and the current `python-zeroconf` API for `AsyncServiceBrowser`. The dominant unknowns are tuning knobs (per-device socket send strategy at 60 Hz, error rate-limit window, re-probe delay after auto-disable) rather than capability questions.

**Primary recommendation:** Build the three new services (`StreamingCoordinator`, `WledStreamer`, `wled_client` httpx wrapper, `wled_discovery` zeroconf wrapper) as a single Wave. Refactor `StreamingService → HueStreamer` in the same wave (it is a contract change, not a diff). Add the three new tables before touching services. Use `socket.SOCK_DGRAM` with `asyncio.to_thread(sock.sendto, ...)` — no `DatagramTransport`, no `asyncudp`; stay consistent with the codebase's existing `asyncio.to_thread` pattern for blocking syscalls.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Coordinator architecture**
- **D-01:** Extract a new `StreamingCoordinator` class that owns `CaptureRegistry.acquire()`, the 60 Hz frame loop, `StatusBroadcaster` orchestration, and reconnect coordination. New entry point for `/api/capture/start` and `/api/capture/stop`.
- **D-02:** Refactor existing `StreamingService` into a `HueStreamer` sink — full extraction. Capture lifecycle moves out. `HueStreamer` accepts per-frame input from the coordinator and owns bridge create/activate, DTLS socket, `set_input` calls, and Hue-only reconnect.
- **D-03:** Add new `WledStreamer` sink as a sibling to `HueStreamer`. Owns one `socket.SOCK_DGRAM` per enabled WLED device (created on stream start, reused for the session, closed on stop). Runs in the same frame loop the coordinator drives — no independent loop.
- **D-04:** Color extraction runs **once** in the coordinator per frame. Region polygons are masked once; both sinks receive the result. No duplicate `extract_region_color` calls.
- **D-05:** Coordinator passes `{region_id: gradient_array}` per frame, where `gradient_array` is `N` sub-sampled RGBs along the region's bounding-box longest axis. `N = max LED-range width among WLED channels referencing that region (floor 1 for Hue-only regions)`. Hue averages the array back to a single RGB; WLED maps array slices to LED ranges.
- **D-06:** Per-sink reconnect policies are independent. Hue bridge disconnect uses existing backoff inside `HueStreamer`. WLED send failures are per-device inside `WledStreamer`; never block Hue or halt the coordinator loop.

**WLED channel data model**
- **D-07:** Three new tables, separate from Hue's `light_assignments`:
  - `wled_devices(id TEXT PRIMARY KEY, ip TEXT NOT NULL UNIQUE, name TEXT NOT NULL, led_count INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)`
  - `wled_channels(id TEXT PRIMARY KEY, device_id TEXT NOT NULL, name TEXT NOT NULL, start_led INTEGER NOT NULL, end_led INTEGER NOT NULL, color TEXT NOT NULL DEFAULT '#ffffff')` (color is a UI chip color, not streaming color)
  - `wled_light_assignments(region_id TEXT NOT NULL, wled_channel_id TEXT NOT NULL, entertainment_config_id TEXT NOT NULL, PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id))`
- **D-08:** WLED channel assignments are **per `entertainment_config_id`**, mirroring Hue `light_assignments`.
- **D-09:** On WLED device registration, auto-seed **one channel** covering the full strip: `start_led=0, end_led=led_count-1, name='Strip'`. Phase 17 is fully usable end-to-end without painting.
- **D-10:** Per-LED color = **linear sub-sample across the region's bounding box along its longest axis**. LED `i` of a range `[start, end]` of width `W` samples position `i/(W-1)` along the bounding box.

**Streaming lifecycle**
- **D-11:** Global `/api/capture/start` triggers the coordinator, which starts Hue **and** attaches all `wled_devices WHERE enabled = 1`. `/api/capture/stop` stops everything. One toggle.
- **D-12:** The `enabled` column is a **per-frame UDP-send gate**, not an attachment gate. Devices always live in the coordinator's device list; `enabled=false` skips that device in the per-frame send loop. Mid-stream toggle requires no restart.
- **D-13:** Stop sequence: (a) emit one final DRGB/DNRGB packet with all-zero RGB to every enabled device, then (b) close sockets.
- **D-14:** DRGB/DNRGB timeout byte = **2 seconds**.
- **D-15:** Per-device error handling: UDP `sendto` exceptions are logged at a rate limit (suggested 5s per device). After N consecutive send failures, the device is **auto-disabled for 30s** in-memory (DB `enabled` flag unchanged). After 30s it auto-re-probes. N is planner's call (see Claude's Discretion).
- **D-16:** `StatusBroadcaster._metrics` gains a `wled_devices` key: `{device_id: {last_error: str|None, last_success_at: iso8601|None, in_cooldown: bool}}`. Included in every WS broadcast. Phase 17 does not render — Phase 18 and 19 consume.

**Phase 17 UI scope**
- **D-17:** Minimal WLED device CRUD UI in a **Settings panel** (drawer/modal). Fields: IP input + Add button, device list (name/IP/LED count/connected state/enabled toggle/Remove), "Scan network" button.
- **D-18:** Device CRUD API (new `routers/wled.py`):
  - `GET /api/wled/devices` — list with live connection state
  - `POST /api/wled/devices` — body `{ip: string}`; fetches `/json/info`, persists `name`+`led_count`; auto-seeds one channel (D-09); returns full device record
  - `DELETE /api/wled/devices/{id}` — cascade channels + assignments
  - `PUT /api/wled/devices/{id}/enabled` — body `{enabled: bool}`; toggles gate (D-12)
  - `POST /api/wled/scan` — zeroconf `_wled._tcp.local.` discovery, 3s timeout, returns `{ip, name}` candidates
- **D-19:** Scan uses **`zeroconf` library** (`>=0.148,<2`). Add to `Backend/requirements.txt`. Native Linux (no Docker from v1.2 per user memory) — no bridge-network multicast caveat.
- **D-20:** **Phase 19 paint UI lives in the same Settings panel** as the WLED device CRUD. Phase 17 must leave room in the panel layout for a canvas-heavy paint area.

### Claude's Discretion
- Exact class naming (`StreamingCoordinator`, `HueStreamer`, `WledStreamer` proposed; planner may refine).
- Exponential backoff curve for per-device WLED re-probe after 30s cooldown.
- Rate-limit window for per-device error logs (suggested 5s).
- SQL upsert form for new tables (follow existing `database.py` `INSERT OR REPLACE` / `ON CONFLICT` conventions).
- How `GET /api/wled/devices` merges persisted rows with live connection state (probe on GET vs cache last-success timestamp).
- Sub-sample implementation for D-10: cache bounding-box axis per region vs recompute per frame (recompute at 60 Hz × 8–16 regions is likely fine).
- Test strategy for WLED sink: local UDP listener in integration tests vs mocked `socket.sendto`.
- UI visual language of the Settings panel (Phase 19 will refine).
- Value of `N` (consecutive send failures before cooldown). Suggested start: 30 frames = 0.5s at 60 Hz.

### Deferred Ideas (OUT OF SCOPE)
- Polygon-path LED mapping (perimeter/centerline instead of bounding-box axis).
- User-picks-axis per region.
- Per-device configurable timeout byte (fixed at 2s per D-14).
- Rendering per-device WLED health in the UI (payload shipped, render deferred to Phase 18/19).
- Startup auto-reconnect probe for WLED devices (first stream start probes them).
- Per-device start/stop endpoints (rejected in favor of global start + enabled gate).
- `python-wled` library.
- DDP protocol.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WLED-01 | User can add a WLED device by entering its IP address | `POST /api/wled/devices` + `wled_client.fetch_info()` via httpx; `wled_devices` row persisted |
| WLED-02 | User can remove a WLED device | `DELETE /api/wled/devices/{id}` cascades to `wled_channels` and `wled_light_assignments` |
| WLED-03 | User can see device info per device (name, LED count, firmware version, connection status) | `/json/info` exposes `name`, `leds.count`, `ver`; connection state derived from last-successful send timestamp (cached in-memory or live probe) |
| WLED-04 | WLED devices managed in a dedicated tab separate from Hue | Per D-17/D-20: WLED CRUD lives in a **Settings panel** (drawer), not a top-level tab. Planner should verify with user that "Settings panel" satisfies the "dedicated" intent — it does house WLED separately from Hue |
| WLED-05 | User can enable/disable individual WLED devices without removing | `PUT /api/wled/devices/{id}/enabled`; `enabled` column is the per-frame gate per D-12 |
| WSTR-01 | Backend streams to WLED devices via DRGB UDP protocol (port 21324) at 50-60 Hz | `WledStreamer.render()` called from coordinator frame loop; DRGB packet for ≤490 LEDs |
| WSTR-02 | Backend auto-uses DNRGB chunked packets for strips >490 LEDs | Packet builder chooses DNRGB when `led_count > 490`, chunks into 489-LED slices with `start_index` header |
| WSTR-03 | WLED and Hue streaming can run concurrently from the same captured frame | `StreamingCoordinator` calls both `HueStreamer.render()` and `WledStreamer.render()` with the same `{region_id: gradient_array}` dict per frame (D-04/D-05) |
| WSTR-04 | UDP timeout byte is set correctly to prevent strips getting stuck on last color | Byte 1 of every packet = `0x02` (2 seconds per D-14); explicit zeroed packet on stop (D-13) as belt-and-suspenders |

**Note on WLED-04 vs D-17/D-20:** The user's v1.3 discussion decided to merge "WLED tab" into a Settings panel that will hold both Phase 17 CRUD and Phase 19 paint UI. The underlying intent of WLED-04 — separate WLED management surface distinct from Hue config — is preserved; only the container widget changed from "tab" to "panel/drawer". Planner should reflect this in traceability notes.
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Frame capture / decode | Backend (CaptureRegistry) | — | Unchanged; existing ownership |
| Per-frame color extraction | Backend (`StreamingCoordinator`) | — | D-04 locks this as coordinator responsibility; sinks receive `{region_id: gradient}` |
| Hue DTLS streaming | Backend (`HueStreamer`) | — | Refactored from `StreamingService`; owns bridge + DTLS socket |
| WLED UDP streaming | Backend (`WledStreamer`) | — | Owns one `SOCK_DGRAM` per enabled device |
| WLED device discovery (mDNS) | Backend (`wled_discovery.py`) | — | `zeroconf.AsyncServiceBrowser` 3s one-shot; runs on user click, not continuously |
| WLED device info fetch (`/json/info`) | Backend (`wled_client.py`) | — | httpx, same pattern as `hue_client.py` |
| DB persistence (3 new tables) | Backend (`database.py`) | — | Follow existing `CREATE TABLE IF NOT EXISTS` at startup pattern |
| WLED CRUD API | Backend (`routers/wled.py`) | — | Router prefix `/api/wled`; Pydantic models matching `routers/cameras.py` |
| Global start/stop | Backend (`routers/capture.py` → `StreamingCoordinator`) | — | D-11: one toggle drives Hue + all enabled WLED |
| Active-streaming status payload | Backend (`StatusBroadcaster._metrics`) | — | D-16: adds `wled_devices` key; frontend receives but doesn't render in Phase 17 |
| WLED Settings panel UI (CRUD) | Frontend (`WledDevicesPanel.tsx`) | — | D-17: list/add/remove/enable/scan; sits in a drawer/modal, leaves room for Phase 19 paint canvas |
| Zustand state for WLED devices | Frontend (`useStatusStore.ts` extension) | — | Phase 16 pattern: extend the single status store, don't add a new one |
| WLED API client | Frontend (`api/wled.ts`) | — | Follow `api/cameras.ts` pattern: typed fetch wrappers |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `socket` | 3.12 | UDP DRGB/DNRGB packet send | [VERIFIED: WLED UDP docs + CLAUDE.md locked decision] — WLED realtime is a 2-byte header + raw RGB over `SOCK_DGRAM`. Matches codebase convention of building protocols from scratch (`capture_v4l2.py`, `hue_client.py`). No third-party dep. |
| `zeroconf` | `>=0.148,<2` | mDNS discovery of `_wled._tcp.local.` | [VERIFIED: pypi.org/project/zeroconf 0.148.0 released 2025-10-05] — pure Python, `AsyncZeroconf` + `AsyncServiceBrowser` integrate with asyncio loop; `1.0.0` was published then **yanked** (unintentional major bump), so 0.148.0 is current stable. Python 3.9–3.14 supported. |
| `httpx` | `>=0.27,<1` (already in requirements.txt) | `GET /json/info` at device registration | [VERIFIED: Backend/requirements.txt] — existing dep. Same pattern as `hue_client.py` async calls. |
| `aiosqlite` | `>=0.20` (already present) | Persist 3 new tables | [VERIFIED: Backend/requirements.txt] — existing. |
| Pydantic | `>=2.10` (already present) | Request/response models for `routers/wled.py` | [VERIFIED: Backend/requirements.txt] — mirror `routers/cameras.py` conventions. |
| FastAPI | `>=0.115` (already present) | Router for `/api/wled/*` | [VERIFIED: Backend/requirements.txt]. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio.to_thread` | stdlib | Wrap blocking `socket.sendto`, `zeroconf` blocking calls, and future syscalls | Per-frame for sends (or per-batch). Codebase-wide pattern (`capture_v4l2.py`, `streaming_service.py`). |
| `threading.Lock` | stdlib | Guard `WledStreamer._devices` dict if mutated from both coordinator thread and API handlers | Same pattern as `CaptureRegistry._lock` (documented in v1.1 retrospective lesson 3) |
| OpenCV (`cv2`) | existing | Reuse `build_polygon_mask` for bounding-box axis computation | Already in `color_math.py`; `RegionMask` already stores `x1/y1/x2/y2` — sub-sample implementation can piggyback |
| NumPy | existing | Sub-sample gradient array along longest axis | Already used throughout color_math |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `socket` | `asyncudp` (PyPI) | [CITED: asyncudp.readthedocs.io] — adds dep; codebase already uses `asyncio.to_thread` for blocking syscalls. No benefit. |
| stdlib `socket` | `loop.create_datagram_endpoint()` + `DatagramTransport.sendto` | [CITED: docs.python.org asyncio-protocol] — more ceremony per device; sendto is fire-and-forget anyway. Keep pattern uniform with capture card blocking calls. |
| stdlib `socket` | `python-wled` (PyPI v0.21.0) | [VERIFIED: CLAUDE.md locked] — JSON API only, **no UDP realtime support**. Rejected. |
| DNRGB | DDP (port 4048) | [VERIFIED: CLAUDE.md locked] — DDP has 10-byte header with push IDs; WLED ignores optional timecodes. DNRGB is simpler for same effect. Rejected. |
| DRGB/DNRGB | WARLS (protocol byte 1) | [VERIFIED: kno.wled.ge] — 255 LED limit, per-LED index byte. Superseded. Rejected. |
| `zeroconf` library | Manual SSDP / raw multicast | [ASSUMED] — `zeroconf` is the mature Python mDNS stack; hand-rolling SSDP/mDNS socket code would be a month of yak-shaving. |
| mDNS as primary | Manual IP entry as primary | [VERIFIED: 17-CONTEXT.md specifics] — manual IP is the primary path per user; scan is a convenience button. Both exist, but manual IP is mandatory and scan is additive. |

**Installation:**
```bash
# Add to Backend/requirements.txt:
zeroconf>=0.148,<2
```
```bash
# Install in venv:
pip install -r Backend/requirements.txt
```

**Version verification:**
```bash
pip index versions zeroconf  # confirm 0.148.0 is latest non-yanked
```

[VERIFIED: pypi.org/project/zeroconf — 0.148.0 released 2025-10-05; 1.0.0 yanked]

## Architecture Patterns

### System Architecture Diagram

```
                    ┌────────────────────────────────────────────────┐
                    │  POST /api/capture/start {config_id}           │
                    └────────────────────┬───────────────────────────┘
                                         │
                                         ▼
                    ┌────────────────────────────────────────────────┐
                    │         StreamingCoordinator.start()            │
                    │  1. CaptureRegistry.acquire(device_path)        │
                    │  2. HueStreamer.start(config_id)   ◄── DB       │
                    │  3. WledStreamer.start(enabled_devices)         │
                    │  4. Compute per-region N (max LED-range width)  │
                    │  5. Spawn _run_loop task                        │
                    └────────────────────┬───────────────────────────┘
                                         │
                                         ▼
      ┌──────────────────────────────────────────────────────────────┐
      │            StreamingCoordinator._frame_loop (60 Hz)            │
      │                                                                 │
      │   frame = await capture.wait_for_new_frame()                    │
      │   region_gradients = {                                           │
      │     region_id: sub_sample_along_longest_axis(frame, mask, N)    │
      │     for region_id, (mask, N) in region_plan.items()              │
      │   }                                                             │
      │                                                                 │
      │   await HueStreamer.render(region_gradients)     ─── DTLS (xy) │
      │   await WledStreamer.render(region_gradients)    ─── UDP (RGB) │
      │                                                                 │
      │   broadcaster.update_metrics({fps, latency, wled_devices})      │
      └──────────┬──────────────────────────────────┬──────────────────┘
                 │                                   │
                 ▼                                   ▼
     ┌──────────────────────┐           ┌─────────────────────────────┐
     │    HueStreamer       │           │      WledStreamer           │
     │                      │           │                             │
     │  streaming.set_input │           │  for device in enabled:     │
     │    (x, y, bri, ch)   │           │    pkt = build_drgb_or_     │
     │  for each channel    │           │      dnrgb(device, slices)  │
     │                      │           │    sock.sendto(pkt, (ip,    │
     │  Bridge reconnect    │           │      21324))                │
     │  on DTLS error       │           │  Per-device cooldown on     │
     │                      │           │  N consecutive failures     │
     └──────────┬───────────┘           └──────────┬──────────────────┘
                │                                    │
                ▼                                    ▼
     ┌──────────────────────┐           ┌─────────────────────────────┐
     │  Hue Bridge (UDP DTLS) │         │  WLED ESP32 devices (UDP 21324) │
     │  port 2100             │         │  DRGB (≤490 LEDs) or DNRGB      │
     │                        │         │    chunked (>490 LEDs)          │
     └────────────────────────┘         └─────────────────────────────────┘


Registration path (out-of-band, not per-frame):

  POST /api/wled/devices {ip}
         │
         ▼
  wled_client.fetch_info(ip) ──► GET http://{ip}/json/info (httpx)
         │                         └── returns {name, leds.count, ver, mac}
         ▼
  database: INSERT wled_devices + INSERT wled_channels (seed 'Strip')
         │
         ▼
  Return device record {id, ip, name, led_count, enabled=1}


Discovery path (on user click):

  POST /api/wled/scan
         │
         ▼
  zeroconf.AsyncServiceBrowser(_wled._tcp.local., timeout=3s)
         │
         ▼
  Return list of {ip, name} candidates (not yet registered)
```

### Recommended Project Structure (additions only)

```
Backend/
├── services/
│   ├── streaming_coordinator.py   # NEW (D-01, D-04, D-05, D-11)
│   ├── streaming_service.py       # refactor → HueStreamer (D-02)
│   ├── wled_streamer.py           # NEW (D-03, D-13, D-14, D-15)
│   ├── wled_client.py             # NEW — httpx /json/info wrapper
│   └── wled_discovery.py          # NEW — zeroconf one-shot scan (D-19)
├── routers/
│   ├── capture.py                 # modify — route through coordinator (D-11)
│   └── wled.py                    # NEW — CRUD + scan (D-18)
├── database.py                    # add 3 new tables (D-07)
└── main.py                        # lifespan: coordinator replaces streaming

Frontend/
├── src/
│   ├── api/
│   │   └── wled.ts                # NEW
│   ├── components/
│   │   ├── Settings/              # NEW directory
│   │   │   ├── SettingsPanel.tsx  # container (leaves room for Phase 19 paint)
│   │   │   └── WledDevicesPanel.tsx  # CRUD + scan (D-17)
│   │   └── EditorPage.tsx         # add Settings entry point
│   ├── store/
│   │   └── useStatusStore.ts      # extend with wledDevices field
│   └── hooks/
│       └── useStatusWS.ts         # parse wled_devices from WS
```

### Pattern 1: Per-Frame Coordinator-to-Sink Contract
**What:** Synchronous method signature on each sink, called once per frame from coordinator's `_run_loop`. Sinks wrap their own blocking work in `asyncio.to_thread`.
**When to use:** Every streaming tick.
**Example:**
```python
# services/streaming_coordinator.py
async def _run_loop(self) -> None:
    while self._run_event.is_set():
        frame = await self._capture.wait_for_new_frame()
        region_gradients: dict[str, np.ndarray] = {}
        for region_id, (region_mask, n) in self._region_plan.items():
            region_gradients[region_id] = sub_sample_gradient(frame, region_mask, n)
        # Fan out — each sink handles its own blocking work internally.
        await self._hue.render(region_gradients)
        await self._wled.render(region_gradients)
        self._broadcaster.update_metrics({
            "fps": self._fps,
            "latency_ms": self._latency_ms,
            "wled_devices": self._wled.health_snapshot(),
        })
```
[ASSUMED — inferred from current `streaming_service._frame_loop` structure; exact naming and signature is planner's call.]

### Pattern 2: DRGB Packet Builder
**What:** 2-byte header + sequential RGB triplets.
**When to use:** Any WLED device with `led_count <= 490`.
**Example:**
```python
# services/wled_streamer.py
DRGB_PROTOCOL = 0x02
DNRGB_PROTOCOL = 0x04
UDP_PORT = 21324
TIMEOUT_SECONDS = 2
DRGB_MAX_LEDS = 490
DNRGB_MAX_LEDS_PER_PACKET = 489  # 2-byte header + 2-byte start + 489*3 = 1471 bytes

def build_drgb_packet(colors: list[tuple[int, int, int]]) -> bytes:
    """Build a DRGB packet for a full strip (<= 490 LEDs)."""
    header = bytes([DRGB_PROTOCOL, TIMEOUT_SECONDS])
    body = bytes(c for rgb in colors for c in rgb)  # R, G, B, R, G, B, ...
    return header + body
```
[VERIFIED: kno.wled.ge/interfaces/udp-realtime/ + WLED wiki]

### Pattern 3: DNRGB Chunking for Long Strips
**What:** 4-byte header (`[0x04, timeout, start_hi, start_lo]`) followed by up to 489 RGB triplets. Send multiple packets for strips >490 LEDs.
**When to use:** Any WLED device with `led_count > 490`.
**Example:**
```python
def build_dnrgb_packets(colors: list[tuple[int, int, int]]) -> list[bytes]:
    """Chunk a long strip into DNRGB packets, each covering up to 489 LEDs."""
    packets: list[bytes] = []
    for chunk_start in range(0, len(colors), DNRGB_MAX_LEDS_PER_PACKET):
        chunk = colors[chunk_start : chunk_start + DNRGB_MAX_LEDS_PER_PACKET]
        header = bytes([
            DNRGB_PROTOCOL,
            TIMEOUT_SECONDS,
            (chunk_start >> 8) & 0xFF,   # start-index high byte
            chunk_start & 0xFF,          # start-index low byte
        ])
        body = bytes(c for rgb in chunk for c in rgb)
        packets.append(header + body)
    return packets
```
[VERIFIED: kno.wled.ge/interfaces/udp-realtime/ — start index is bytes 2-3, data starts at byte 4]

### Pattern 4: UDP Send via `asyncio.to_thread`
**What:** Wrap the blocking `sendto` in a thread pool call to match the codebase's existing pattern for blocking syscalls.
**When to use:** Every frame, per enabled device.
**Example:**
```python
async def _send_to_device(self, device_id: str, packets: list[bytes]) -> None:
    sock = self._sockets[device_id]
    ip = self._ips[device_id]
    try:
        def _send_all() -> None:
            for pkt in packets:
                sock.sendto(pkt, (ip, UDP_PORT))
        await asyncio.to_thread(_send_all)
        self._mark_success(device_id)
    except OSError as exc:
        self._mark_failure(device_id, exc)
```
[CITED: docs.python.org asyncio.to_thread; matches `capture_v4l2.py` ioctl pattern]

**Note on performance:** `socket.sendto` on a non-blocking UDP socket for a single ~1.5 KB packet completes in microseconds on localhost / LAN. `asyncio.to_thread` adds ~100 µs of overhead per call. At 60 Hz with 1–4 devices, this is well within frame budget (16.67 ms). For 10+ devices or very long strips (4+ DNRGB chunks each), the planner should consider batching all sends in one `to_thread` call (as shown) rather than one-call-per-packet. [ASSUMED — based on general asyncio guidance; perf measurement is a Validation Architecture invariant below.]

### Pattern 5: zeroconf One-Shot Timed Scan
**What:** Create `AsyncZeroconf` + `AsyncServiceBrowser`, sleep 3s, cancel both, return discovered candidates.
**When to use:** On `POST /api/wled/scan`.
**Example:**
```python
# services/wled_discovery.py
import asyncio
from zeroconf import ServiceStateChange
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

WLED_SERVICE_TYPE = "_wled._tcp.local."

async def scan_for_wled_devices(timeout_seconds: float = 3.0) -> list[dict]:
    discovered: dict[str, dict] = {}
    aiozc = AsyncZeroconf()

    async def _resolve_service(name: str) -> None:
        info = AsyncServiceInfo(WLED_SERVICE_TYPE, name)
        if await info.async_request(aiozc.zeroconf, timeout=1000):
            addrs = info.parsed_addresses()
            if addrs:
                discovered[name] = {"ip": addrs[0], "name": info.server or name}

    def on_state_change(zc, service_type, name, state_change):
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            asyncio.create_task(_resolve_service(name))

    browser = AsyncServiceBrowser(
        aiozc.zeroconf,
        [WLED_SERVICE_TYPE],
        handlers=[on_state_change],
    )
    try:
        await asyncio.sleep(timeout_seconds)
    finally:
        await browser.async_cancel()
        await aiozc.async_close()
    return list(discovered.values())
```
[VERIFIED: github.com/python-zeroconf/python-zeroconf examples/async_browser.py — `AsyncServiceBrowser(aiozc.zeroconf, [type], handlers=[...])`, cancel with `async_cancel()`, close `AsyncZeroconf` with `async_close()`]

### Pattern 6: Bounding-Box Longest-Axis Sub-Sampling (D-10)
**What:** For a region's `RegionMask` with pre-computed bbox, pick the longer of `(x2-x1)` and `(y2-y1)`, then sample N equidistant positions along it, extracting mean color in a perpendicular slab at each position.
**When to use:** Coordinator builds `region_gradients` dict per frame, one entry per region that has ≥1 WLED channel assigned.
**Example (sketch — planner will refine):**
```python
# services/color_math.py (new helper)
def sub_sample_gradient(
    frame: np.ndarray, region: RegionMask, n: int
) -> np.ndarray:
    """Return an (n, 3) array of RGB means, sampled along the region's longest axis.

    If n == 1, behaves like extract_region_color (one mean for the whole mask).
    """
    if n <= 1:
        r, g, b = extract_region_color(frame, region)
        return np.array([[r, g, b]], dtype=np.uint8)

    width = region.x2 - region.x1
    height = region.y2 - region.y1
    axis = "x" if width >= height else "y"
    roi_frame = frame[region.y1:region.y2, region.x1:region.x2]

    means = np.empty((n, 3), dtype=np.uint8)
    for i in range(n):
        t = i / (n - 1)
        if axis == "x":
            col_center = int(round(t * (width - 1)))
            # slab of +/- 1 column around col_center, respecting mask
            slab_x1 = max(col_center - 1, 0)
            slab_x2 = min(col_center + 2, width)
            slab_frame = roi_frame[:, slab_x1:slab_x2]
            slab_mask = region.roi_mask[:, slab_x1:slab_x2]
        else:
            row_center = int(round(t * (height - 1)))
            slab_y1 = max(row_center - 1, 0)
            slab_y2 = min(row_center + 2, height)
            slab_frame = roi_frame[slab_y1:slab_y2, :]
            slab_mask = region.roi_mask[slab_y1:slab_y2, :]
        mean_bgr = cv2.mean(slab_frame, mask=slab_mask)
        means[i] = [int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0])]
    return means
```
[ASSUMED — planner should tune slab width and sample method; this is a starting point consistent with existing `extract_region_color` using `cv2.mean`. Test with a horizontal gradient frame to verify left→right ordering.]

### Anti-Patterns to Avoid

- **One `to_thread` call per packet per device:** At 60 Hz × 5 devices × 2 DNRGB chunks = 600 thread context switches/sec. Batch per device: one `to_thread(_send_all)` call that loops packets internally.
- **Opening a fresh UDP socket per frame:** `socket()` + `close()` is expensive. Create one socket per device at stream start, reuse for the session, close on stop. [CITED: WLED UDP is stateless; socket reuse is free.]
- **Assuming `socket.sendto` always returns instantly:** [CITED: raspberrypi.org forum post] — if the network interface is down, `sendto` can block indefinitely. Set `sock.setblocking(False)` and catch `BlockingIOError`, OR keep blocking but rely on `asyncio.to_thread` + short failure rate window (D-15) to detect stalls. Recommend non-blocking mode for UDP — it never queues beyond kernel buffer anyway.
- **Re-masking polygons every frame:** `build_polygon_mask` is expensive (OpenCV fillPoly + bbox compute). Cache `RegionMask` per region at stream start, invalidate on region edit. Existing `StreamingService._load_channel_map` already does this — coordinator inherits the pattern.
- **Holding `asyncio.Lock` inside the frame loop:** Hot path; only use `threading.Lock` where mutation can actually happen from handler threads (e.g. enable toggle). Frame loop reads; handlers write; lock the write.
- **Calling `GET /json/info` per frame or per second:** It's an HTTP request. Only call at device registration or on explicit refresh.
- **Hand-rolling mDNS:** Use `zeroconf` library. Manual SSDP multicast is fragile and platform-specific.
- **Sending zero-length packets on stop:** `sendto(b"", ...)` is a no-op on some stacks. Send a fully-formed DRGB/DNRGB packet with all-zero RGB triplets (D-13) — this both explicitly blacks the strip and resets its timeout.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| mDNS service discovery | Raw multicast DNS over UDP | `zeroconf` library | Multicast queries, response parsing, TTL refresh, name conflicts. Weeks of work, platform-specific. |
| Hue Entertainment DTLS | Custom DTLS implementation | `hue-entertainment-pykit` (already present) | Python `ssl` has no DTLS support — this is why Hue pykit exists and why Python 3.12 is pinned. |
| HTTP client for `/json/info` | `urllib` / `http.client` | `httpx` (already present) | Async, connection pooling, proven in `hue_client.py`. |
| Polygon masking | Per-pixel point-in-polygon | `cv2.fillPoly` via `build_polygon_mask` | Already in `color_math.py` with pre-computed bbox. |
| Thread-safe device pool | New lock discipline | Extend `CaptureRegistry` pattern | v1.1 retrospective: `threading.Lock` + `asyncio.to_thread` is the right combo. |
| UDP realtime to WLED | Any existing Python WLED library | stdlib `socket` | `python-wled` wraps JSON API only (no realtime). Other libraries are not worth the dep; DRGB/DNRGB are trivial protocols. |
| WebSocket fan-out for device health | New broadcast channel | Extend `StatusBroadcaster._metrics` dict | Phase 16 proved this pattern works. |
| SQL migrations | Alembic | `CREATE TABLE IF NOT EXISTS` at startup | Existing project convention. |
| Per-region bbox computation | New per-frame bbox code | Reuse `RegionMask.x1/y1/x2/y2` | Already pre-computed in `build_polygon_mask`. |

**Key insight:** Every primitive needed by Phase 17 either already exists in the codebase (capture, color math, status broadcast, httpx client pattern) or is a trivial byte-twiddling exercise (DRGB/DNRGB packets). The only external primitive being added is `zeroconf` for mDNS — because writing a mDNS client from scratch is a losing proposition.

## Runtime State Inventory

> This phase mixes a refactor (`StreamingService` → `HueStreamer` + coordinator) with new capability. The refactor is purely a code restructure, not a rename of persisted IDs. This inventory checks for any persisted/cached state that could break.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None for rename.** New tables (`wled_devices`, `wled_channels`, `wled_light_assignments`) are additive; `CREATE TABLE IF NOT EXISTS` handles fresh + existing DBs. No column renames in existing tables. | None for existing; new tables created on next app startup. |
| Live service config | **None — no external service stores a reference to `StreamingService` by name.** The class is internal to the Python process. WLED devices themselves have no persistent state tied to this app — they accept UDP from anyone. | None. |
| OS-registered state | **None found.** No systemd units reference `StreamingService`. No pm2 configs. App is started by `uvicorn main:app` or `docker compose` — neither embeds the class name. | None. |
| Secrets / env vars | **None found.** No env var names change (`CAPTURE_DEVICE`, `DATABASE_PATH` unchanged). No new secrets (WLED has no auth). | None. |
| Build artifacts / installed packages | **None that would break.** `hue-entertainment-pykit` (0.9.4) is not changing. Adding `zeroconf>=0.148,<2` to requirements.txt — fresh install on next `pip install -r`. | `pip install -r Backend/requirements.txt` must run before first app start after this phase. |
| In-memory state across restart | **None — `app.state.streaming` becomes `app.state.coordinator`.** Any callers that reached into `app.state.streaming` must switch. Frontend `useStatusStore` already holds state from WS payload only (no reference to the Python class). | Grep for `app.state.streaming` references; currently limited to `routers/capture.py` per 17-CONTEXT.md §integration points. Migrate to `app.state.coordinator`. |

**Canonical question check:** After every file is updated, what runtime systems still have the old string cached, stored, or registered? **Answer: nothing persisted.** The rename is process-local and resets on every uvicorn start.

**Grep targets for planner:**
```bash
grep -rn "app.state.streaming" Backend/
grep -rn "StreamingService" Backend/ Frontend/
grep -rn "services.streaming_service" Backend/
```

## Common Pitfalls

### Pitfall 1: DNRGB per-packet max is 489, not 490
**What goes wrong:** Confusing DRGB's 490-LED maximum with DNRGB's 489-LED maximum — off-by-one index errors at chunk boundaries.
**Why it happens:** DRGB has a 2-byte header → room for 490 RGB triplets (1470 bytes body + 2 header = 1472). DNRGB has a 4-byte header (adds 2-byte start index) → room for only 489 triplets (1467 + 4 = 1471).
**How to avoid:** Use `DNRGB_MAX_LEDS_PER_PACKET = 489` constant. Unit-test a 490-LED strip and a 980-LED strip against the packet sizes.
**Warning signs:** `sendto` returns unexpectedly small byte counts, or WLED logs dropped packets.
[VERIFIED: kno.wled.ge + WLED wiki both state 489]

### Pitfall 2: UDP MTU on some LANs
**What goes wrong:** A max-size DNRGB packet (1471 bytes) is under standard Ethernet MTU (1500) but over Wi-Fi MTU minus headroom on some APs. Packets get silently dropped.
**Why it happens:** Fragmentation of UDP-over-Wi-Fi with DF bit unset.
**How to avoid:** 489 LEDs/packet keeps us under 1472 bytes total — same as DRGB and matches the WLED default. If users report odd flicker on specific devices, first check if their AP is fragmenting.
**Warning signs:** Strip updates arrive but in blocks (e.g., first 256 LEDs update, last 233 don't).
[ASSUMED — general UDP/WiFi knowledge]

### Pitfall 3: `sendto` blocks when interface is down
**What goes wrong:** If the WLED device goes offline (power-cycled, ARP cache stale, interface down), `sendto` can block for seconds on the syscall itself even for UDP.
**Why it happens:** Kernel tries to resolve the ARP entry. Uncommon but real. [CITED: Raspberry Pi forum thread on blocking sendto with interface down]
**How to avoid:** `sock.setblocking(False)` on every WLED socket. Wrap send in try/except `BlockingIOError` and count as a failure (tick D-15 fail counter). Alternatively, wrap in `asyncio.to_thread` with an outer timeout, but non-blocking mode is simpler.
**Warning signs:** Coordinator frame rate drops to <5 Hz when a WLED device unplugs; logs show long `sendto` calls.

### Pitfall 4: `AsyncServiceBrowser` requires an asyncio-style listener
**What goes wrong:** Passing a sync listener or not awaiting inside the handler causes silent misses.
**Why it happens:** `python-zeroconf` uses asyncio primitives; callbacks must schedule async work (e.g. `asyncio.create_task`) to resolve service details.
**How to avoid:** Use `asyncio.create_task(_resolve_service(name))` inside the `on_state_change` callback (see Pattern 5).
**Warning signs:** Scan returns 0 devices even though `avahi-browse -rt _wled._tcp` finds them.
[VERIFIED: python-zeroconf examples/async_browser.py]

### Pitfall 5: Coordinator vs snapshot endpoint capture ownership
**What goes wrong:** `routers/capture.py::get_snapshot` calls `registry.get_default()` — a non-ref-counted read. If the coordinator hasn't acquired the default device, snapshot returns 503. If the coordinator HAS acquired a non-default device, snapshot still returns from the default (wrong camera).
**Why it happens:** `get_default()` is hardcoded to `CAPTURE_DEVICE` env var.
**How to avoid:** Either (a) plumb the coordinator's currently-acquired device_path into `registry.get_snapshot()` helper, or (b) use the `active_device_path` already on `StatusBroadcaster._metrics` to pick the right backend. Snapshot is a convenience endpoint; consistency with the streaming device is the right call here. Existing behavior during Phase 16 did not address this — Phase 17 can optionally improve it, or leave it as-is (out of scope per 17-CONTEXT.md — snapshot is not mentioned).
**Warning signs:** Snapshot shows a black frame or stale image during streaming.
[VERIFIED: Backend/routers/capture.py lines 64-89]

### Pitfall 6: `enabled` toggle race with frame loop
**What goes wrong:** User toggles `enabled=false` on a device at the moment the frame loop is iterating the device list — per-frame send still happens, or iteration fails with "dict changed during iteration".
**Why it happens:** Frame loop reads `self._devices` from async context; PUT handler writes it from FastAPI thread.
**How to avoid:** `threading.Lock` on `WledStreamer._devices` (same pattern as `CaptureRegistry._lock`). Frame loop snapshots the list under the lock, then sends without the lock held.
**Warning signs:** Occasional "dictionary changed size during iteration" stack traces.

### Pitfall 7: Stop sequence order matters
**What goes wrong:** Sockets closed before blackout packet is sent → strip freezes on last color; or blackout sent after sockets closed → `OSError: Bad file descriptor`.
**Why it happens:** D-13 requires blackout THEN close; easy to reverse in teardown code.
**How to avoid:** `WledStreamer.stop()` always does: (1) build blackout packet per device, (2) `sendto` on each still-open socket (best-effort; swallow exceptions), (3) close each socket. Do NOT short-circuit to `socket.close()` in the exception path of send — blackout is best-effort, but close must still happen.
**Warning signs:** Strip stays on last color for 2s (D-14 timeout) instead of going dark immediately.

### Pitfall 8: Sub-sample when region is narrow in both axes
**What goes wrong:** For a region with bbox 5×5 pixels and N=100 LEDs, all samples collapse to roughly the same pixels — strip shows uniform color instead of gradient.
**Why it happens:** Sub-sample density exceeds pixel density.
**How to avoid:** Clamp N in the sub-sample helper to `max(1, min(N, longest_axis_length))`. Alternatively, accept uniform output — it's correct for tiny regions. Document the behavior; don't fight it.
**Warning signs:** User complains "my long strip isn't showing a gradient from my small region." Expected behavior.

### Pitfall 9: Forgetting to add `zeroconf` to requirements.txt
**What goes wrong:** Tests pass locally (zeroconf installed in dev venv from another project), CI fails, Docker image breaks.
**Why it happens:** `pip install zeroconf` during dev; forget to update requirements.
**How to avoid:** Add `zeroconf>=0.148,<2` to `Backend/requirements.txt` in the same commit that introduces `services/wled_discovery.py`.
**Warning signs:** `ModuleNotFoundError: zeroconf` in fresh env.

### Pitfall 10: Hue DTLS re-activation during coordinator lifecycle
**What goes wrong:** Coordinator stops; HueStreamer calls `deactivate_entertainment_config`. Coordinator restarts quickly; HueStreamer calls `activate_entertainment_config` before bridge has processed the deactivation. Bridge returns 409 or silently keeps the session.
**Why it happens:** Hue bridge takes ~200ms to process activation changes. `/api/capture/stop` immediately followed by `/api/capture/start` can race.
**How to avoid:** Not new in Phase 17 — already an issue in current code. If the planner moves the activation call into `HueStreamer.start`, it inherits the same behavior. Document but do not fix in this phase (out of scope).
**Warning signs:** Rapid stop/start sequence leaves Hue in a stuck state.

## Code Examples

### Pydantic models for `routers/wled.py` (follow `routers/cameras.py`)
```python
from pydantic import BaseModel, Field

class WledDeviceIn(BaseModel):
    ip: str = Field(..., pattern=r"^(\d{1,3}\.){3}\d{1,3}$")

class WledDeviceOut(BaseModel):
    id: str
    ip: str
    name: str
    led_count: int
    enabled: bool
    created_at: str
    connected: bool
    last_error: str | None = None

class WledDevicesResponse(BaseModel):
    devices: list[WledDeviceOut]

class WledEnabledRequest(BaseModel):
    enabled: bool

class WledScanCandidate(BaseModel):
    ip: str
    name: str

class WledScanResponse(BaseModel):
    candidates: list[WledScanCandidate]
```
[ASSUMED — mirrors `routers/cameras.py` CameraDevice / CamerasResponse conventions]

### Table DDL (add to `database.py::init_db`)
```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS wled_devices (
        id TEXT PRIMARY KEY,
        ip TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        led_count INTEGER NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
""")
await db.execute("""
    CREATE TABLE IF NOT EXISTS wled_channels (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        name TEXT NOT NULL,
        start_led INTEGER NOT NULL,
        end_led INTEGER NOT NULL,
        color TEXT NOT NULL DEFAULT '#ffffff',
        FOREIGN KEY (device_id) REFERENCES wled_devices(id) ON DELETE CASCADE
    )
""")
await db.execute("""
    CREATE TABLE IF NOT EXISTS wled_light_assignments (
        region_id TEXT NOT NULL,
        wled_channel_id TEXT NOT NULL,
        entertainment_config_id TEXT NOT NULL,
        PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id),
        FOREIGN KEY (wled_channel_id) REFERENCES wled_channels(id) ON DELETE CASCADE
    )
""")
```
**Note:** SQLite does NOT enforce `FOREIGN KEY` constraints by default. The project currently does not run `PRAGMA foreign_keys = ON`. Planner must implement cascade via explicit `DELETE` statements in the router handler, OR turn on the pragma at connection init. Recommend explicit cascades (simpler, matches existing pattern where `light_assignments` cleanup is done in `routers/regions.py` and `main.py` lifespan purge).
[VERIFIED: Backend/database.py lines 62-68 — no FK enforcement]

### `wled_client.fetch_info` skeleton
```python
# services/wled_client.py
import httpx

async def fetch_wled_info(ip: str, timeout: float = 5.0) -> dict:
    """GET http://{ip}/json/info and return {name, led_count, ver, mac}.

    Raises httpx.HTTPError on connection failure or non-2xx response.
    """
    url = f"http://{ip}/json/info"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return {
        "name": data.get("name", "WLED"),
        "led_count": int(data.get("leds", {}).get("count", 0)),
        "ver": data.get("ver", ""),
        "mac": data.get("mac", ""),
    }
```
[VERIFIED: kno.wled.ge/interfaces/json-api — `name`, `leds.count`, `ver`, `mac` fields documented]

### `WledStreamer` socket initialization
```python
# services/wled_streamer.py (sketch)
import socket
import threading
import time

class WledStreamer:
    def __init__(self):
        self._devices: dict[str, dict] = {}   # id -> {ip, led_count, enabled, socket, state}
        self._lock = threading.Lock()

    async def start(self, device_rows: list[dict]) -> None:
        with self._lock:
            for row in device_rows:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setblocking(False)
                self._devices[row["id"]] = {
                    "ip": row["ip"],
                    "led_count": row["led_count"],
                    "enabled": bool(row["enabled"]),
                    "socket": sock,
                    "last_error": None,
                    "last_success_at": None,
                    "consecutive_failures": 0,
                    "in_cooldown_until": 0.0,
                }

    async def stop(self) -> None:
        # D-13: blackout packet then close
        with self._lock:
            now = time.time()
            for dev_id, dev in self._devices.items():
                if dev["enabled"] and now >= dev["in_cooldown_until"]:
                    blackout = self._build_packets([(0, 0, 0)] * dev["led_count"], dev["led_count"])
                    try:
                        for pkt in blackout:
                            dev["socket"].sendto(pkt, (dev["ip"], 21324))
                    except OSError:
                        pass   # best-effort
                try:
                    dev["socket"].close()
                except OSError:
                    pass
            self._devices.clear()
```
[ASSUMED — skeleton; planner refines lifecycle integration with coordinator]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single Hue sink inside `StreamingService` | Coordinator + sink pattern | Phase 17 | Enables Phase 17 WLED and future sinks (Govee, Elgato, etc.) with no more big-bang refactors |
| DDP (tpm2.net port 4048) | DNRGB (WLED port 21324) | Locked at v1.3 discovery | Simpler header, same effect for this use case |
| WARLS for small strips | DRGB for all strips ≤490 LEDs | WLED wiki default since v0.10 (2020) | Higher max LED count (490 vs 255), simpler packet format |
| Polling `/json/state` for live color | UDP realtime only | Phase 17 design | REST calls are 10–50ms each; UDP is <1ms. Only registration uses HTTP. |
| `python-wled` for integrations | Direct socket / httpx | Locked at v1.3 discovery | Avoids a dep that covers only JSON API |
| Docker bridge network | Native Linux (user machine v1.2+) | v1.2 user memory note | Removes the mDNS-doesn't-work-in-bridge caveat; `zeroconf` scan works natively |

**Deprecated/outdated:**
- WARLS protocol: still supported by WLED, but superseded by DRGB for contiguous full-strip updates.
- `python-wled` library: fine for Home Assistant integration (JSON config), not viable for realtime streaming.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `asyncio.to_thread(sock.sendto, ...)` per device per frame is fast enough at 60 Hz × up to 4 devices | Pattern 4 note | If overhead exceeds budget, may need datagram transport or single-thread send loop. Measurable — see Validation Architecture. |
| A2 | 489 LEDs/packet keeps DNRGB under Wi-Fi MTU | Pitfall 2 | If specific APs fragment, users see partial strip updates. Measurable by user reports; mitigation is to shrink chunk size. |
| A3 | `zeroconf` `AsyncServiceBrowser` + 3s sleep + `async_cancel` is sufficient for one-shot scan | Pattern 5 | If discovery is flaky under 3s, planner can bump to 5s. Not critical — scan is a convenience. |
| A4 | Phase 17 leaves `routers/capture.py::get_snapshot` reading `registry.get_default()` — behavior unchanged from Phase 16 | Pitfall 5 | Snapshot may show wrong camera during streaming; pre-existing, not a regression. User acceptance check needed. |
| A5 | SQLite `FOREIGN KEY` cascade is NOT enabled in this project; cascade must be implemented in handler code | Code Examples section | If the planner assumes FKs cascade and omits explicit DELETE, orphan rows accumulate in `wled_channels` and `wled_light_assignments`. Verified against existing `database.py` — no `PRAGMA foreign_keys`. |
| A6 | Sub-sample helper (`sub_sample_gradient`) reads the same `RegionMask` instance the coordinator cached at stream start | Pattern 6 | If masks are rebuilt per frame, perf drops. Planner should verify cache lifetime. |
| A7 | WLED UDP is stateless; no hello/handshake required | Pattern 4 | If WLED firmware ≥ some version requires an auth step, this fails. No evidence of this in WLED docs as of Oct 2025. |
| A8 | ~30 consecutive send failures = 0.5s at 60 Hz is a sensible auto-disable threshold | User Constraints D-15 | Too low: transient network blips disable devices. Too high: slow failure detection. Planner's call; suggest exposing as constant. |
| A9 | `enabled` toggle mid-stream is safe with a `threading.Lock` on `WledStreamer._devices` | Pitfall 6 | If lock is forgotten or misused, intermittent crashes. Covered by a unit test that toggles enabled while frame loop iterates. |
| A10 | Frontend Settings panel as a drawer/modal satisfies WLED-04 ("dedicated tab") intent | phase_requirements note | If user reads WLED-04 strictly, the planner should re-verify via `/gsd-discuss-phase` escalation. 17-CONTEXT.md D-20 explicitly endorses this. |

## Open Questions

1. **Value of N in auto-disable threshold (D-15)**
   - What we know: 30 frames at 60 Hz = 0.5s — suggested by 17-CONTEXT.md.
   - What's unclear: Whether to expose this as an env var / config setting, or hardcode.
   - Recommendation: Hardcode at 30 with a named constant `WLED_FAILURE_COOLDOWN_THRESHOLD`. Expose only if a user reports it's wrong.

2. **Should GET `/api/wled/devices` actively probe each device, or return cached health from `WledStreamer._devices`?**
   - What we know: The coordinator has live state while streaming; stale/unknown when idle.
   - What's unclear: When idle, should GET trigger an ad-hoc `/json/info` call per device to update `connected: bool`?
   - Recommendation: GET returns persisted rows with `connected = (last_success_at within last 5s)` during streaming; when idle, `connected = False` for all. No HTTP probes from GET — it should be cheap. Manual refresh (if needed) can be a separate endpoint or just the scan button.

3. **Snapshot endpoint alignment with active streaming device**
   - What we know: `routers/capture.py::get_snapshot` uses `registry.get_default()` — may not match active camera.
   - What's unclear: Is this a Phase 17 concern?
   - Recommendation: Out of scope. Flag in RETROSPECTIVE for a later cleanup.

4. **Does the `WledStreamer.render` call path need to be concurrent across devices, or serial?**
   - What we know: Sending to 4 devices sequentially at ~1ms each = 4ms/frame, fine.
   - What's unclear: At 10+ devices, serial sends may exceed frame budget.
   - Recommendation: Start serial (simpler). Add `asyncio.gather` later if perf measurements show it matters.

5. **mDNS scan behavior if Docker returns (future)**
   - What we know: Native Linux per v1.2 memory — mDNS works.
   - What's unclear: If user later containerizes, `zeroconf` silently returns nothing in bridge network mode.
   - Recommendation: Document in code comment; add warning log if scan returns zero results within 3s.

## Environment Availability

> Phase 17 depends on external tools and devices.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Existing | ✓ | 3.12 (pinned) | — |
| FastAPI + uvicorn | Existing | ✓ | 0.115+ | — |
| aiosqlite | Existing | ✓ | 0.20+ | — |
| httpx | Existing | ✓ | 0.27+ | — |
| opencv-python-headless | Existing | ✓ | 4.10+ | — |
| hue-entertainment-pykit | Existing | ✓ | 0.9.4 | — |
| `zeroconf` | New for D-19 (scan) | ✗ — not yet in requirements.txt | Target `>=0.148,<2` | Manual IP entry works regardless |
| Hue Bridge (192.168.178.23) | Hue sink | ✓ (paired per CLAUDE.md) | v2 | — |
| Capture card `/dev/video0` | Coordinator | ✓ per CLAUDE.md | — | — |
| WLED device on LAN | Full E2E test of WSTR-01..04 | ✗ (not confirmed to exist on test bench) | — | Local UDP listener fixture for automated tests; manual smoke test deferred to HW availability |

**Missing dependencies with no fallback:**
- None — `zeroconf` is a simple pip install; manual IP entry covers discovery.

**Missing dependencies with fallback:**
- `zeroconf` library not yet installed — planner must include `pip install -r Backend/requirements.txt` step after editing the file.
- Physical WLED device not confirmed available — build the planner's integration tests with a local UDP listener (loopback, bind `127.0.0.1:21324`) to assert exact packet bytes. A final smoke test against a real device can be a manual QA step.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3+ / pytest-asyncio 0.24+ |
| Config file | `Backend/tests/conftest.py` (existing, with DB + capture fixtures) |
| Quick run command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_streamer.py -x` |
| Full suite command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |
| Frontend test | `cd Frontend && npx vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| WLED-01 | POST /api/wled/devices persists row | integration | `pytest tests/test_wled_router.py::test_add_device_persists -x` | ❌ Wave 0 |
| WLED-01 | POST failure on unreachable IP returns 502 | integration | `pytest tests/test_wled_router.py::test_add_device_unreachable -x` | ❌ Wave 0 |
| WLED-02 | DELETE /api/wled/devices/{id} cascades channels + assignments | integration | `pytest tests/test_wled_router.py::test_delete_cascades -x` | ❌ Wave 0 |
| WLED-03 | GET /api/wled/devices returns name/led_count/ver | integration | `pytest tests/test_wled_router.py::test_list_devices -x` | ❌ Wave 0 |
| WLED-03 | fetch_wled_info parses /json/info correctly | unit | `pytest tests/test_wled_client.py::test_fetch_info -x` | ❌ Wave 0 |
| WLED-04 | Frontend Settings panel renders WLED device list | vitest | `cd Frontend && npx vitest run WledDevicesPanel.test.tsx` | ❌ Wave 0 |
| WLED-05 | PUT .../{id}/enabled flips DB row and live gate | integration | `pytest tests/test_wled_router.py::test_enable_toggle -x` | ❌ Wave 0 |
| WSTR-01 | DRGB packet format: byte 0 = 0x02, byte 1 = 2 | unit | `pytest tests/test_wled_streamer.py::test_drgb_packet_bytes -x` | ❌ Wave 0 |
| WSTR-01 | 60 Hz send rate under load (loopback listener) | integration | `pytest tests/test_wled_streamer.py::test_send_rate_60hz -x` | ❌ Wave 0 |
| WSTR-02 | led_count > 490 triggers DNRGB chunked packets | unit | `pytest tests/test_wled_streamer.py::test_dnrgb_chunks -x` | ❌ Wave 0 |
| WSTR-02 | 980-LED strip produces exactly 3 packets (489+489+2) | unit | `pytest tests/test_wled_streamer.py::test_dnrgb_980_leds -x` | ❌ Wave 0 |
| WSTR-03 | Coordinator fans out one frame to both sinks | integration | `pytest tests/test_streaming_coordinator.py::test_fan_out -x` | ❌ Wave 0 |
| WSTR-03 | Hue FPS unaffected by WLED enabled (within 5%) | integration | `pytest tests/test_streaming_coordinator.py::test_no_interference -x` | ❌ Wave 0 |
| WSTR-04 | Timeout byte = 2 in every packet | unit | `pytest tests/test_wled_streamer.py::test_timeout_byte -x` | ❌ Wave 0 |
| WSTR-04 | Stop() sends blackout packet before close | unit | `pytest tests/test_wled_streamer.py::test_stop_blackout -x` | ❌ Wave 0 |

### Observable Invariants (runtime / integration tests)

These are the **measurable properties** the system must maintain. Each should map to a test OR a broadcaster metric.

| Invariant | Target | How to Measure | Test / Metric |
|-----------|--------|----------------|---------------|
| **Frame rate (Hue+WLED concurrent)** | ≥ 50 Hz sustained | `fps` metric via `/ws/status` heartbeat | Integration test: run coordinator 5s with 1 Hue zone + 1 WLED device; assert median fps ≥ 50 |
| **Frame rate (Hue-only baseline)** | ≥ 50 Hz | `fps` metric | Control test: run without WLED attached; compare fps |
| **WLED packet rate per device** | = coordinator fps (1 DRGB) or fps × ceil(led_count / 489) for DNRGB | Loopback listener counts packets in a 1s window | Integration: bind local listener, assert 50 ≤ packets/sec ≤ 60 per DRGB device |
| **DRGB packet size for 100-LED strip** | exactly 2 + 100×3 = 302 bytes | Packet length from loopback | Unit: `assert len(build_drgb_packet([(0,0,0)]*100)) == 302` |
| **DNRGB total bytes for 980-LED strip** | 3 packets, total 2×(4+489×3) + (4+2×3) = 2954 bytes | Packet list inspection | Unit |
| **Per-packet header byte 0** | 0x02 (DRGB) or 0x04 (DNRGB) | Inspect first byte | Unit |
| **Per-packet header byte 1** | 0x02 (2-second timeout per D-14) | Inspect second byte | Unit |
| **DNRGB chunk start-index encoding** | bytes 2-3 = big-endian uint16 | Parse header | Unit: for chunk starting at LED 489, bytes 2-3 = `[0x01, 0xE9]` |
| **Socket error rate (healthy device)** | 0 errors/sec | `_metrics.wled_devices[id].consecutive_failures` | Integration: attach listener, assert counter stays 0 after 1s |
| **Auto-disable triggers after N failures** | Device enters `in_cooldown = true` within N frames of unreachable target | Send to 127.0.0.1:21325 (wrong port) | Integration: assert cooldown after N frames |
| **Auto-re-probe after 30s cooldown** | Device leaves cooldown at +30s | Time-travel fixture | Integration |
| **Stop sequence sends blackout** | Loopback receives one all-zero packet per device per stop | Listener records last packet | Integration: call stop(), inspect last received buffer |
| **No stale frame masking** | `RegionMask` objects reused across frames | Mock `build_polygon_mask` and assert called-once-per-region-per-stream-start | Integration |
| **`enabled=false` device receives zero packets** | After PUT enabled=false, loopback receives 0 packets in next 1s | Listener + PUT call mid-stream | Integration |
| **`wled_devices` key present in WS payload** | Every `push_state` call includes `wled_devices` dict | Inspect `_metrics` after push_state calls | Unit |
| **`/json/info` HTTP timeout** | 5s max on POST /api/wled/devices | httpx mock; send that hangs | Integration: assert 504-or-502 returned within 6s |
| **mDNS scan returns within 3s ± 0.5s** | Timeout honored | Measure wall-clock of POST /api/wled/scan | Integration (mock zeroconf) |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_wled_streamer.py tests/test_wled_router.py -x`
- **Per wave merge:** `python -m pytest && cd Frontend && npx vitest run`
- **Phase gate:** Full suite green + manual smoke test against a real WLED device (or confirmed-green loopback listener run) before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `tests/test_wled_streamer.py` — packet format, chunking, stop-blackout, cooldown lifecycle
- [ ] `tests/test_wled_router.py` — CRUD endpoints, cascade delete, enable toggle
- [ ] `tests/test_wled_client.py` — `/json/info` parsing, httpx error paths
- [ ] `tests/test_wled_discovery.py` — mocked zeroconf scan, timeout, listener cancellation
- [ ] `tests/test_streaming_coordinator.py` — fan-out, independent reconnect, sub-sample correctness
- [ ] `tests/test_color_math.py` additions — `sub_sample_gradient` with known gradients
- [ ] Shared fixture: local UDP loopback listener context manager (`@contextmanager def udp_listener(port) -> Queue`)
- [ ] `Frontend/src/components/Settings/WledDevicesPanel.test.tsx` — add/remove/toggle/scan UI
- [ ] `Frontend/src/api/wled.test.ts` — typed API client
- [ ] Requirements update: `zeroconf>=0.148,<2` in `Backend/requirements.txt`

## Project Constraints (from CLAUDE.md)

- **Latency <100ms:** Hue end-to-end unchanged at ~20ms; WLED adds UDP send (~1ms). Phase 17 must not regress Hue latency.
- **Docker:** Per v1.2 user memory, project now runs natively on Linux (not Docker). `zeroconf` mDNS works natively. Host network caveats from CLAUDE.md no longer apply.
- **Hue API direct usage:** Unchanged — `hue-entertainment-pykit` retained for DTLS.
- **No auth:** `/api/wled/*` endpoints unauthenticated, consistent with rest of API.
- **Python 3.12 pinned:** `zeroconf>=0.148` supports 3.9–3.14, compatible. [VERIFIED: pypi.org/project/zeroconf]
- **GSD Workflow Enforcement:** Planner must use `/gsd-execute-phase` for this work per CLAUDE.md.
- **Skill integration:** `preflight` skill runs backend + frontend tests + health checks. Phase 17 tests must join the existing suite so `preflight` stays green.
- **CLAUDE.md "Context: What Already Exists":** Already commits to `socket` stdlib, DRGB/DNRGB protocols, httpx for `/json/info`, `zeroconf>=0.148,<2`, no `python-wled`, no DDP. **Research confirms all of these remain the correct choices.**

## Sources

### Primary (HIGH confidence)
- [WLED UDP Realtime / tpm2.net](https://kno.wled.ge/interfaces/udp-realtime/) — DRGB protocol byte 0x02 (max 490 LEDs), DNRGB protocol byte 0x04 (max 489 LEDs/packet, 2-byte start index), timeout byte, port 21324
- [WLED wiki UDP Realtime Control](https://github.com/Aircoookie/WLED/wiki/UDP-Realtime-Control) — byte-exact packet layouts; cross-verified with kno.wled.ge
- [WLED JSON API `/json/info`](https://kno.wled.ge/interfaces/json-api/) — fields `name`, `leds.count`, `ver`, `mac`, `vid`, `ip`, `arch`, `brand`, `product`
- [python-zeroconf on PyPI](https://pypi.org/project/zeroconf/) — v0.148.0 released 2025-10-05, 1.0.0 yanked, Python 3.9–3.14 support
- [python-zeroconf AsyncServiceBrowser example](https://github.com/python-zeroconf/python-zeroconf/blob/master/examples/async_browser.py) — canonical pattern for async scan + cancel
- `Backend/services/capture_service.py` — CaptureRegistry ref-count semantics (D-04/D-05 of Phase 8)
- `Backend/services/streaming_service.py` — current implementation to refactor into HueStreamer
- `Backend/services/status_broadcaster.py` — `_UNSET` sentinel and `push_state` extension pattern (Phase 16)
- `.planning/phases/17-wled-backend-and-streaming/17-CONTEXT.md` — locked decisions D-01 through D-20

### Secondary (MEDIUM confidence)
- [WLED Discourse forum thread: DNRGB >490 LEDs](https://wled.discourse.group/t/hyperion-udpraw-to-wled-more-then-490-leds/1258) — community confirms 489/packet for DNRGB
- [docs.python.org asyncio.to_thread](https://docs.python.org/3/library/asyncio-protocol.html) — UDP DatagramTransport overview (used to justify stdlib socket choice)

### Tertiary (LOW confidence)
- [Raspberry Pi forum: UDP sendto blocks when interface down](https://forums.raspberrypi.com/viewtopic.php?t=375341) — informs Pitfall 3; single source, flagged for watch but consistent with general UDP socket behavior

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — every library version verified against PyPI / docs; WLED packet format cross-verified from two WLED-owned sources
- Architecture patterns: **HIGH** — built on existing codebase patterns (CaptureRegistry, StatusBroadcaster, asyncio.to_thread)
- Pitfalls: **MEDIUM-HIGH** — Pitfalls 1-5 and 7 verified against docs; 6, 8, 9, 10 are defensive conjectures with clear test coverage in Validation Architecture
- Perf at 60 Hz: **MEDIUM** — first principles + existing 60 Hz Hue loop work fine; exact headroom with N WLED devices not measured yet — Validation Architecture invariants are the fallback
- Runtime state inventory: **HIGH** — internal refactor only; no OS-registered / external-service state depends on `StreamingService` class name

**Research date:** 2026-04-20
**Valid until:** 2026-05-20 for WLED protocol (stable since v0.10, 2020), 2026-05-20 for zeroconf (next minor release likely ~1 month). Refresh if starting this phase after 2026-06-01.
