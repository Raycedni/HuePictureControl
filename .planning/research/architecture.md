# Architecture Research

**Domain:** Real-time ambient lighting — WLED UDP streaming, Home Assistant control endpoints, entertainment zone persistence
**Researched:** 2026-04-14
**Confidence:** HIGH — based on direct code inspection of the existing implementation and verified WLED/HA protocol documentation

> This document covers v1.3 additions only. For the existing v1.0/v1.1 architecture see the sections preserved at the bottom.
> v1.3 adds three independent concerns: WLED streaming, HA control endpoints, zone persistence fix.

---

## What Already Exists (Do Not Re-Research)

The existing backend has a well-established layered architecture:

```
FastAPI main.py
  app.state: db, capture_registry, broadcaster, streaming (StreamingService)

Services:
  capture_service.py    CaptureRegistry + CaptureBackend ABC (V4L2/DirectShow)
  streaming_service.py  Hue-specific loop: CaptureRegistry -> color_math -> DTLS
  hue_client.py         REST + Entertainment config activation/deactivation
  color_math.py         RGB->CIE xy, build_polygon_mask, extract_region_color
  status_broadcaster.py WebSocket fan-out

Routers: capture.py, hue.py, regions.py, cameras.py
WebSockets: streaming_ws.py (/ws/status), preview_ws.py (/ws/preview)

Database tables: bridge_config, entertainment_configs, regions,
  light_assignments, known_cameras, camera_assignments
```

---

## System Overview (v1.3 additions)

```
+------------------------------------------------------------------+
|  Frontend (React 19)                                             |
|                                                                  |
|  App.tsx                                                         |
|  tabs: Setup | Preview | Editor | WLED (new)                     |
|                                                                  |
|  +------------+  +------------+  +---------------------------+   |
|  | EditorPage |  | WledPage   |  | PairingFlow / Setup       |   |
|  | (Konva.js  |  | (device    |  | entertainment config      |   |
|  |  canvas)   |  |  list +    |  | dropdown with persistence |   |
|  | unchanged  |  |  StripPainter) | fix (new)                |   |
|  +------------+  +------------+  +---------------------------+   |
|                                                                  |
|  Stores: useRegionStore  useStatusStore  useWledStore (new)      |
|  API:    regions.ts  hue.ts  cameras.ts  wled.ts (new)           |
+---------------------------+--------------------------------------+
                            | HTTP / WebSocket
+---------------------------v--------------------------------------+
|  FastAPI Backend                                                 |
|                                                                  |
|  Existing routers (unchanged):                                   |
|  /api/hue  /api/cameras  /api/regions  /ws/status  /ws/preview  |
|                                                                  |
|  New routers:                                                    |
|  +---------------+   +-------------------+                      |
|  | /api/wled     |   | /api/ha           |                      |
|  | (CRUD devices |   | (inbound control  |                      |
|  |  + segments)  |   |  from HA)         |                      |
|  +-------+-------+   +---------+---------+                      |
|          |                     |                                 |
|  Modified router:              |                                 |
|  +--------------------------------------------------+           |
|  | /api/capture (add selected-config GET/PUT)       |           |
|  +-------------------------------+------------------+           |
|                                  |                              |
|  New service:                    |                              |
|  +--------------------------------------------------+           |
|  | streaming_coordinator.py                         |           |
|  |  .start(config_id) -> fans out to both services  |           |
|  |  .stop() -> stops both services                  |           |
|  |  owns the one frame loop                         |           |
|  +----------------+-----------------+---------------+           |
|                   |                 |                            |
|  +----------------v---+  +----------v---------+                 |
|  | streaming_service  |  | wled_service (new) |                 |
|  | (Hue DTLS)         |  | (UDP socket send)  |                 |
|  | unchanged          |  |                    |                 |
|  +--------+-----------+  +----------+---------+                 |
|           |                         |                            |
|  +--------v-------------------------v---------+                  |
|  | color_math.py (shared, unchanged)          |                  |
|  | extract_region_color, build_polygon_mask   |                  |
|  +--------------------------------------------+                  |
|                                                                  |
|  Database (aiosqlite):                                           |
|  existing tables + wled_devices + wled_strip_assignments         |
|  + selected_configs (zone persistence fix)                       |
+------------------------------------------------------------------+
```

---

## New Component Boundaries

### Backend

| Component | File | Responsibility | Communicates With |
|-----------|------|----------------|-------------------|
| WledService | `services/wled_service.py` | Per-device UDP socket; builds DRGB/DNRGB packets; `process_frame(frame, segment_map)` | `color_math.extract_region_color`, DB (reads strip assignments at startup) |
| StreamingCoordinator | `services/streaming_coordinator.py` | Unified `start()/stop()` that owns the one frame loop and fans out to Hue and WLED sinks | `StreamingService`, `WledService`, `CaptureRegistry`, `StatusBroadcaster` |
| WledRouter | `routers/wled.py` | CRUD for WLED devices; read/write strip segment assignments | `wled_service.py`, DB |
| HaRouter | `routers/ha.py` | Inbound REST endpoints for HA automations (`start`, `stop`, `camera`, `zone`) | `app.state.coordinator` (the StreamingCoordinator) |

### Frontend

| Component | File | Responsibility | Communicates With |
|-----------|------|----------------|-------------------|
| WledPage | `components/WledPage.tsx` | WLED tab: device list, add/remove, open StripPainter | `useWledStore`, `api/wled.ts` |
| StripPainter | `components/StripPainter.tsx` | 1D LED strip canvas — drag to select LED range, click zone to assign | `useWledStore`, `useRegionStore` |
| useWledStore | `store/useWledStore.ts` | Devices list, segment assignments, selected device state | `api/wled.ts` |
| api/wled.ts | `api/wled.ts` | HTTP client for `/api/wled/*` | WledRouter |

---

## Data Flow

### Frame to WLED Strip (new parallel path)

```
CaptureBackend.wait_for_new_frame()
  |
  v (frame: BGR ndarray, shared reference — no copy)
StreamingCoordinator._frame_loop()
  |
  +---> StreamingService.process_frame(frame)
  |       for each channel_id, mask in hue_channel_map:
  |         r,g,b = extract_region_color(frame, mask)
  |         x,y = rgb_to_xy(r,g,b)
  |         streaming.set_input((x, y, bri, channel_id))
  |
  +---> WledService.process_frame(frame)
          for each wled_device in active_devices:
            rgb_values = []
            for segment in device.segments:
              r,g,b = color_cache.get(segment.region_id)
                      or extract_region_color(frame, segment.mask)
              fill rgb_values[segment.led_start : segment.led_end+1]
            packet = _build_packet(device.led_count, rgb_values)
            device.socket.sendto(packet, (device.ip, device.port))
```

**Color cache:** The coordinator maintains a `dict[region_id, (r,g,b)]` populated once per frame. Both Hue and WLED sinks look up this cache before calling `extract_region_color`, so a region shared between Hue and WLED is extracted exactly once per frame.

**WLED packet sizes:**
- DRGB (byte 0 = 0x02): 2-byte header + 3 bytes/LED, max 490 LEDs per packet
- DNRGB (byte 0 = 0x04): 4-byte header (includes 2-byte start index) + 3 bytes/LED, no pixel limit across multiple packets
- For a 300-LED strip: one DRGB packet = 902 bytes (well under LAN UDP MTU ~1472 bytes)
- For a 600-LED strip: two DNRGB packets, start_index 0 and 300
- Byte 1 in both protocols: timeout seconds before WLED reverts to normal mode — use 2

```python
def _build_drgb_packet(timeout_s: int, rgb: list[tuple[int,int,int]]) -> bytes:
    return bytes([0x02, timeout_s]) + bytes(v for r,g,b in rgb for v in (r,g,b))

def _build_dnrgb_packet(timeout_s: int, start: int,
                        rgb: list[tuple[int,int,int]]) -> bytes:
    return bytes([0x04, timeout_s, (start >> 8) & 0xFF, start & 0xFF]) \
           + bytes(v for r,g,b in rgb for v in (r,g,b))
```

### WLED Device Discovery and Configuration

```
Frontend WledPage mounts
  -> GET /api/wled/devices
  <- [{id, name, ip, port, led_count, mac, segments: [...]}]

User adds device (types IP):
  -> POST /api/wled/devices {ip: "192.168.1.x"}
  Backend: GET http://{ip}/json/info
    extracts: name (device "name" field), led_count ("leds.count"), mac ("mac")
  <- 201 {id, name, ip, port:21324, led_count, mac}

User opens StripPainter for a device:
  -> GET /api/wled/devices/{id}/segments
  <- [{id, region_id, led_start, led_end, region_name}]
  StripPainter renders horizontal bar (2-4px per LED, scrollable)
  User drags to select LED range, clicks region name to assign
  -> PUT /api/wled/devices/{id}/segments [{led_start, led_end, region_id}, ...]
  <- 200 [{id, ...}]
```

### Home Assistant Control

```
HA automation fires:
  POST /api/ha/start
  body: {"config_id": "...", "target_hz": 25}
  -> app.state.coordinator.start(config_id, target_hz)
  <- 200 {"status": "starting"}

  POST /api/ha/stop
  -> app.state.coordinator.stop()
  <- 200 {"status": "stopping"}

  POST /api/ha/camera
  body: {"entertainment_config_id": "...", "camera_stable_id": "..."}
  -> DB UPSERT camera_assignments
  <- 200 {"status": "ok"}

  POST /api/ha/zone
  body: {"config_id": "..."}
  -> DB UPSERT selected_configs (id=1, config_id=?)
  <- 200 {"status": "ok"}
```

HA uses `rest_command` in `configuration.yaml`. No auth header required (this API has no auth). All four endpoints are write-only — HA does not need to read state back, it drives state changes.

### Zone Persistence Fix

The bug: entertainment config selection lives only in React local state, lost on page reload; the Start/Stop button does not reflect actual streaming state on first render.

```
Current (broken):
  user selects config -> useState('') in component -> lost on reload
  streaming state unknown until WS connects

Fixed:
  Config selection:
    user selects config
    -> PUT /api/capture/selected-config {"config_id": "..."}
    -> DB UPSERT selected_configs SET config_id=? WHERE id=1

  Page load:
    -> GET /api/capture/selected-config
    <- {"config_id": "..." | null}
    -> GET /ws/status (existing) -> {state: "streaming"|"idle"|...}
    dropdown pre-populated, button state correct before any user action
```

New DB table (single-row pattern, same as `bridge_config`):
```sql
CREATE TABLE IF NOT EXISTS selected_configs (
    id INTEGER PRIMARY KEY,
    config_id TEXT NOT NULL
);
```

---

## Recommended File Structure (New Files Only)

```
Backend/
+-- routers/
|   +-- wled.py              GET/POST/DELETE /api/wled/devices + segments
|   +-- ha.py                POST /api/ha/start|stop|camera|zone
|   +-- capture.py           ADD: GET/PUT /api/capture/selected-config
+-- services/
|   +-- wled_service.py      WledService: UDP sockets, DRGB builder, process_frame()
|   +-- streaming_coordinator.py  Thin fan-out: StreamingService + WledService
+-- models/
    +-- wled.py              Pydantic: WledDevice, WledSegment, WledSegmentAssignment

Frontend/src/
+-- components/
|   +-- WledPage.tsx         WLED tab: device list, add/remove
|   +-- StripPainter.tsx     1D LED range assignment canvas
+-- store/
|   +-- useWledStore.ts      devices, segments, selected device
+-- api/
    +-- wled.ts              HTTP client for /api/wled/*
```

**main.py changes:** Replace `app.state.streaming` (StreamingService) with `app.state.coordinator` (StreamingCoordinator). The coordinator owns the StreamingService instance. Update `routers/capture.py` to call `app.state.coordinator.start/stop` instead of `app.state.streaming.start/stop`.

---

## Architectural Patterns

### Pattern 1: Coordinator as Thin Fan-out, Services as Pure Sinks

**What:** `StreamingCoordinator` owns the single frame loop (moved out of `StreamingService`). On each iteration it builds the per-region color cache once, then calls `hue_service.send(color_cache)` and `wled_service.send(frame, color_cache)`. Neither sub-service runs its own loop.

**Why:** Avoids two competing `wait_for_new_frame()` callers on the same CaptureBackend (the threading model does not support concurrent waiters — the event is cleared before waiting). Single loop also ensures Hue and WLED updates are always in sync within one frame.

**Tradeoff:** `StreamingService` must be refactored to expose a `send(color_cache)` method rather than running its own loop. This is a moderate change to an existing service with 167+ tests — plan for test updates.

**Alternative if refactor is too risky:** Keep `StreamingService._frame_loop` intact and add a callback hook (`on_frame: Callable[[frame, color_cache], None]`) that the coordinator sets. WLED processing runs inside this callback. Looser coupling, no test changes, but slightly less clean.

### Pattern 2: WledService as Stateless Packet Builder with Persistent Sockets

**What:** `WledService.__init__` opens one `socket.AF_INET, socket.SOCK_DGRAM` socket per WLED device and stores them in `_sockets: dict[str, socket.socket]`. `process_frame()` builds packets and calls `socket.sendto()` synchronously — no thread, no asyncio. Sockets are closed in `WledService.stop()`.

**Why persistent sockets:** Socket creation is ~10µs on Linux. At 50 Hz with 3 devices that is 1.5ms/s of pure overhead. More importantly, the OS can optimize the send buffer for a long-lived socket.

**Why synchronous sendto:** UDP `sendto()` for a ~900 byte packet to a LAN address returns in under 50µs. The asyncio overhead of `loop.sock_sendto()` or `asyncio.to_thread()` exceeds the send time. Synchronous is correct here.

### Pattern 3: StripPainter as a Plain Canvas (Not Konva)

**What:** `StripPainter` renders a horizontal scrollable `<canvas>` element. Each LED is a 2-4px wide column. Pointer events handle drag-to-select a range. A sidebar lists all canvas regions — clicking assigns the selected LED range to that region and colors the strip segment accordingly.

**Why not Konva:** StripPainter is a 1D range selector, not a 2D polygon editor. Konva's scene graph and event model are designed for 2D — the overhead (hit detection, layers, transformers) is entirely wasted on a linear strip. A plain canvas is 10x simpler to implement and performs better for 300-600 LED columns.

**Scrolling:** 600 LEDs at 3px each = 1800px — render the full strip in a horizontally scrollable div. At 1200 LEDs (WLED max) = 3600px, still tractable. No virtualization needed.

### Pattern 4: HA Router as a Thin Adapter

**What:** `routers/ha.py` translates HA-friendly endpoint shapes into calls on `app.state.coordinator` and the DB. Zero business logic. Each handler is 5-10 lines.

**Why a separate router:** HA's `rest_command` configuration needs stable, descriptive URLs (`/api/ha/start` vs `/api/capture/start`). Keeping HA endpoints in a dedicated file also makes them easy to find, document, and eventually add HA-specific auth if needed. The existing `capture.py` router is not modified.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Embedding WLED Logic in StreamingService

**What people do:** Add UDP send calls inside `streaming_service.py`'s `_frame_loop`.

**Why it's wrong:** `streaming_service.py` is Hue-specific — it imports `hue_entertainment_pykit`, manages DTLS reconnect, and handles Hue entertainment config activation. Mixing WLED logic couples two completely independent output devices. The 167+ existing tests would need WLED mocks.

**Do this instead:** Introduce `StreamingCoordinator`. `streaming_service.py` stays unchanged (or gains only a `send()` method).

### Anti-Pattern 2: Two Separate Frame Loops for Hue and WLED

**What people do:** Give WLED its own `asyncio.Task` that calls `wait_for_new_frame()` independently.

**Why it's wrong:** `CaptureBackend.wait_for_new_frame()` clears the internal `threading.Event` before waiting. Two concurrent callers will race: one will see no event and time out, creating frame drops. The existing backend threading model is explicitly single-consumer.

**Do this instead:** One frame loop in the coordinator; pass the decoded frame reference to both sinks.

### Anti-Pattern 3: Per-Frame UDP Socket Creation

**What people do:** `socket.socket(AF_INET, SOCK_DGRAM).sendto(...)` inside `process_frame()`.

**Why it's wrong:** See Pattern 2 rationale — ~10µs overhead per call, no OS send-buffer optimization.

**Do this instead:** Persistent sockets keyed by device IP in `WledService._sockets`.

### Anti-Pattern 4: WLED Data Columns in the `regions` Table

**What people do:** Add `wled_device_id`, `led_start`, `led_end` columns to `regions`.

**Why it's wrong:** A canvas region is abstract. One region can map to a Hue channel AND a WLED LED range simultaneously. Embedding device-specific columns in `regions` makes this many-to-many relationship impossible and conflates the canvas model with output device models.

**Do this instead:** The `wled_strip_assignments` join table with explicit foreign keys to both `wled_devices` and `regions`.

### Anti-Pattern 5: Polling for Zone Persistence

**What people do:** Frontend polls `GET /ws/status` every second to check if the selected config is still valid.

**Why it's wrong:** The WebSocket connection already delivers state changes. Polling is redundant. The persistence fix needs only one additional REST call at page load (`GET /api/capture/selected-config`), not ongoing polling.

**Do this instead:** `GET /api/capture/selected-config` on mount (once), then rely on the existing `/ws/status` WebSocket for live streaming state.

---

## Database Schema Additions

```sql
-- WLED device registry
CREATE TABLE IF NOT EXISTS wled_devices (
    id TEXT PRIMARY KEY,           -- UUID generated by backend
    name TEXT NOT NULL,            -- from /json/info "name"
    ip TEXT NOT NULL UNIQUE,
    port INTEGER NOT NULL DEFAULT 21324,
    led_count INTEGER NOT NULL,    -- from /json/info "leds.count"
    mac TEXT,                      -- from /json/info "mac"
    added_at TEXT NOT NULL         -- ISO8601 timestamp
);

-- LED range -> canvas region mappings (join table)
CREATE TABLE IF NOT EXISTS wled_strip_assignments (
    id TEXT PRIMARY KEY,
    wled_device_id TEXT NOT NULL REFERENCES wled_devices(id) ON DELETE CASCADE,
    region_id TEXT NOT NULL REFERENCES regions(id) ON DELETE CASCADE,
    led_start INTEGER NOT NULL,
    led_end INTEGER NOT NULL       -- inclusive
);

-- Persisted entertainment config selection (zone persistence fix)
-- Single-row pattern, same as bridge_config (id always = 1)
CREATE TABLE IF NOT EXISTS selected_configs (
    id INTEGER PRIMARY KEY,
    config_id TEXT NOT NULL
);
```

All three tables are additive — no existing tables are modified.

---

## New API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/wled/devices` | List all WLED devices with led_count and segment assignments |
| POST | `/api/wled/devices` | Add device by IP (probes `/json/info` for name, led_count, mac) |
| DELETE | `/api/wled/devices/{id}` | Remove device and all its strip assignments (CASCADE) |
| GET | `/api/wled/devices/{id}/segments` | Get strip assignments for one device |
| PUT | `/api/wled/devices/{id}/segments` | Replace all strip assignments for one device |
| POST | `/api/ha/start` | Start streaming — body: `{config_id, target_hz?}` |
| POST | `/api/ha/stop` | Stop streaming |
| POST | `/api/ha/camera` | Assign camera — body: `{entertainment_config_id, camera_stable_id}` |
| POST | `/api/ha/zone` | Set selected config — body: `{config_id}` |
| GET | `/api/capture/selected-config` | Get persisted selected `config_id` |
| PUT | `/api/capture/selected-config` | Persist selected `config_id` — body: `{config_id}` |

---

## Build Order (Phase Dependencies)

Three independent tracks with one cross-track dependency:

```
Track A — Zone persistence fix (no dependencies, lowest risk, build first)
  Step A1: DB migration — selected_configs table (database.py)
  Step A2: GET/PUT /api/capture/selected-config (capture.py)
  Step A3: Frontend — load on mount, pre-populate dropdown, reflect WS state

Track B — WLED streaming
  Step B1: DB migrations — wled_devices + wled_strip_assignments tables
  Step B2: services/wled_service.py — UDP socket, DRGB builder, process_frame()
  Step B3: routers/wled.py — device CRUD + segment endpoints
  Step B4: services/streaming_coordinator.py
           Wire into main.py: app.state.coordinator (replaces app.state.streaming)
           Update routers/capture.py to call coordinator
  Step B5: Frontend — api/wled.ts, useWledStore, WledPage, StripPainter

Track C — HA router (depends on B4: coordinator must exist)
  Step C1: routers/ha.py — 4 thin adapter endpoints
```

Recommended order: A1-A3 → B1-B3 → B4 → C1 → B5

**Why Track A first:** It is a self-contained bug fix with zero risk of breaking existing streaming. Completing it first provides a working persistence layer before the streaming refactor.

**Why B4 before C1:** `ha.py` calls `app.state.coordinator` — the coordinator must be wired in before HA routes can be tested.

**Why B5 last:** The StripPainter UI is the most novel component with no existing UI pattern in the codebase. Keeping it last allows the backend API to stabilize before the frontend is built against it.

---

## Integration Points with Existing Modules

| New Component | Existing Module | Integration |
|---------------|----------------|-------------|
| `StreamingCoordinator` | `streaming_service.py` | Owns a `StreamingService` instance; delegates Hue-specific logic entirely to it |
| `StreamingCoordinator` | `capture_service.CaptureRegistry` | Receives registry in constructor; acquires/releases via the same pattern as current `StreamingService` |
| `StreamingCoordinator` | `status_broadcaster.py` | Passes broadcaster to sub-services; coordinator emits unified state via same push_state interface |
| `WledService` | `color_math.py` | Calls `extract_region_color(frame, mask)` — no changes to color_math needed |
| `WledService` | `database.py` | Reads `wled_strip_assignments` at stream start to build segment-to-mask map |
| `routers/ha.py` | `routers/capture.py` | Both call the coordinator; `capture.py` is modified only to swap `app.state.streaming` to `app.state.coordinator` |
| `routers/wled.py` | `database.py` | Reads/writes `wled_devices` and `wled_strip_assignments` |
| `WledPage.tsx` | `App.tsx` | Add `'wled'` to `Page` type union; add nav tab button |
| `StripPainter.tsx` | `useRegionStore` | Reads `regions` (existing store, no changes) to render zone name list |

---

## Confidence Assessment

| Area | Confidence | Source |
|------|------------|--------|
| WLED DRGB/DNRGB packet format | HIGH | kno.wled.ge/interfaces/udp-realtime/ (verified 2026-04) |
| WLED port 21324 default | HIGH | Official WLED docs |
| WLED DRGB 490 LED limit per packet | HIGH | Official WLED docs — DNRGB required for >490 LEDs |
| WLED /json/info field names | HIGH | kno.wled.ge/interfaces/json-api/ (verified 2026-04) |
| WLED DDP port 4048 | HIGH | kno.wled.ge/interfaces/ddp/ (verified 2026-04) — but DRGB recommended for this use case |
| HA REST /api/services/{domain}/{service} | HIGH | developers.home-assistant.io (verified 2026-04) |
| HA auth requirement | HIGH | Bearer token required — but this project has no auth, so HA must store no-auth URLs |
| StreamingCoordinator fan-out pattern | MEDIUM | Derived from codebase structure; no direct prior art |
| StripPainter canvas approach | MEDIUM | Standard 1D range selector pattern; WLED-specific UI varies across projects |

---

## Preserved: v1.1 Architecture (for reference)

The v1.1 multi-camera architecture document covers:
- `CaptureRegistry` (already shipped)
- Per-zone camera dispatch in `streaming_service.py` (already shipped)
- `camera_assignments` DB table (already shipped)
- `known_cameras` DB table (already shipped)

These are not repeated here. The v1.3 architecture builds on top of v1.1 without modifying any of its components.

---

## Sources

- Direct code inspection: `Backend/services/streaming_service.py` — frame loop, channel map, coordinator integration point
- Direct code inspection: `Backend/services/capture_service.py` — CaptureRegistry, CaptureBackend, wait_for_new_frame threading model
- Direct code inspection: `Backend/services/color_math.py` — extract_region_color, build_polygon_mask (shared abstraction)
- Direct code inspection: `Backend/main.py` — app.state layout, lifespan pattern
- Direct code inspection: `Backend/database.py` — existing schema, ALTER TABLE migration pattern
- Direct code inspection: `Frontend/src/App.tsx` — Page type, tab structure
- Direct code inspection: `Frontend/src/store/useRegionStore.ts` — Region model
- [WLED UDP Realtime docs](https://kno.wled.ge/interfaces/udp-realtime/) — DRGB/DNRGB packet format, port 21324, 490 LED limit — HIGH confidence
- [WLED DDP docs](https://kno.wled.ge/interfaces/ddp/) — port 4048, no timecode support — HIGH confidence
- [WLED JSON API docs](https://kno.wled.ge/interfaces/json-api/) — /json/info fields: name, leds.count, ip, mac — HIGH confidence
- [HA REST API developer docs](https://developers.home-assistant.io/docs/api/rest/) — /api/services endpoint format, auth — HIGH confidence

---

*Architecture research for: HuePictureControl v1.3 WLED Support, HA Control, Zone Persistence Fix*
*Researched: 2026-04-14*
