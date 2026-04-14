# Stack Research

**Domain:** Real-time ambient lighting — WLED UDP streaming, Home Assistant REST control, LED strip paint UI (v1.3)
**Researched:** 2026-04-14
**Confidence:** HIGH for WLED protocols (official docs verified); HIGH for HA REST API; MEDIUM for zeroconf/mDNS in Docker bridge; HIGH for frontend (Konva.js already in use)

---

## Context: What Already Exists (Do Not Re-Research)

| Layer | Technology | Version |
|-------|-----------|---------|
| Backend framework | FastAPI | >=0.115 |
| Async DB | aiosqlite | >=0.20 |
| HTTP client | httpx | >=0.27 |
| Frame capture (Linux) | Custom V4L2 ctypes/ioctl + mmap | in `capture_v4l2.py` |
| Frame decode | opencv-python-headless | >=4.10 |
| Hue streaming | hue-entertainment-pykit | 0.9.4 |
| Python | 3.12 (pinned) | 3.12 |
| Frontend | React 19 + TypeScript + Konva.js + Zustand | — |
| Device enumeration | linuxpy | >=0.24 (added in v1.1) |

---

## Recommended Stack Additions

### Core Technologies (Backend — New)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python `socket` stdlib (UDP) | stdlib (3.12) | WLED DRGB/DNRGB realtime packet sending | No library needed. WLED UDP realtime is a 2-byte header + raw RGB bytes over `SOCK_DGRAM`. This codebase already builds protocols from scratch (see `capture_v4l2.py`, `hue_client.py`). One `WledStreamer` class with `socket.socket(AF_INET, SOCK_DGRAM)` is the complete implementation — ~30 lines of Python. |
| `zeroconf` | `>=0.148,<2` | WLED device discovery via mDNS (`_wled._tcp.local.`) | Pure Python, no system Bonjour/Avahi/D-Bus dependency. WLED devices advertise as `_wled._tcp.local.`; `AsyncServiceBrowser` integrates with the existing asyncio event loop. Version 0.148.0 released Oct 2025. Python 3.9+ compatible, no conflict with existing requirements. See Docker caveat below — only useful if backend uses `network_mode: host`. |
| `httpx` (already present) | `>=0.27` | WLED JSON API queries + Home Assistant REST API | Already a dependency. WLED's `GET /json/info` returns `leds.count` (needed at device registration for strip UI). HA REST API uses the same bearer-token HTTP pattern. Zero new libraries needed for either integration. |

### Core Technologies (Frontend — New)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `react-konva` (already in use) | current | Paint-on-strip LED range selector UI | Already the established canvas primitive. The strip UI is a horizontal canvas showing one cell per LED (or one rect per zone range). Click-drag paints a zone color assignment. Same pointer event model as the existing freeform region editor — no new library needed. |

---

## Protocol Specifications (Build-Not-Buy)

### WLED UDP Realtime — Packet Formats

**Port:** 21324 (default, user-configurable per device; read from `/json/info` or let user override when adding device)

**DRGB (protocol byte = 2) — up to 490 LEDs:**
```
Byte 0:   0x02            protocol = DRGB
Byte 1:   0x02            timeout seconds before WLED returns to normal mode (use 2)
Bytes 2+: R G B R G B ... 3 bytes per LED, from LED 0 upward
```
Use DRGB for strips with <= 490 LEDs. One packet per frame. Max UDP payload = 490 * 3 + 2 = 1472 bytes (fits in one Ethernet MTU).

**DNRGB (protocol byte = 4) — unlimited LEDs via chunked packets:**
```
Byte 0:   0x04            protocol = DNRGB
Byte 1:   0x02            timeout seconds
Byte 2:   start >> 8      high byte of 16-bit starting LED index
Byte 3:   start & 0xFF    low byte of starting LED index
Bytes 4+: R G B R G B ... 3 bytes per LED from start_index
```
Use DNRGB for strips > 490 LEDs. Send multiple packets per frame: packet 0 starts at 0, packet 1 starts at 490, etc. A 300-LED strip needs one DRGB packet; a 1200-LED strip needs three DNRGB packets.

**Decision rule for implementation:**
```python
if led_count <= 490:
    use DRGB (single packet)
else:
    use DNRGB (chunked, 490 LEDs per packet)
```

**Timeout semantics:** byte 1 = seconds WLED waits after last packet before reverting to its own effects. Use `2` during streaming. Send at ~25–50 Hz to keep WLED in realtime mode. WLED handles up to 15ms delivery intervals on ESP32 without issue.

### WLED JSON API (Device Registration)

```
GET  http://[WLED_IP]/json/info
     → {"leds": {"count": 300}, "name": "TV Strip", "ver": "0.14.x", ...}

POST http://[WLED_IP]/json/state
     Body: {"on": true}
     → confirmation of state
```

Called once at device add time to read `leds.count` and `name`. Not called per-frame. Reachable via existing `httpx.AsyncClient` already used in `hue_client.py`.

### Home Assistant REST API (Inbound — HA Calls HuePictureControl)

The HA integration goes in one direction: **HA calls HuePictureControl via its `rest_command` integration**. HuePictureControl does NOT call HA outbound. This means:

- No HA token stored in HuePictureControl config
- No outbound firewall rules needed
- HA user configures `rest_command:` in their `configuration.yaml` pointing at `http://[HPC_HOST]:8001/api/ha/...`
- HuePictureControl exposes new unauthenticated REST endpoints (consistent with existing no-auth design)

Example HA `configuration.yaml`:
```yaml
rest_command:
  hpc_start:
    url: "http://192.168.178.x:8001/api/ha/start"
    method: POST
    content_type: "application/json"
    payload: '{"config_id": "{{ config_id }}"}'
  hpc_stop:
    url: "http://192.168.178.x:8001/api/ha/stop"
    method: POST
```

New HuePictureControl endpoints:
```
POST /api/ha/start         Body: {"config_id": "..."}  — start streaming
POST /api/ha/stop          Body: {}                    — stop streaming
PUT  /api/ha/camera        Body: {"stable_id": "..."}  — switch active camera
PUT  /api/ha/zone          Body: {"config_id": "..."}  — switch entertainment zone
```

---

## Integration Points with Existing Code

### New `WledStreamingService` (sibling to `StreamingService`)

Do NOT extend the existing `StreamingService`. The protocols are fundamentally different:

| Aspect | Hue (existing) | WLED (new) |
|--------|---------------|------------|
| Transport | DTLS/UDP via `hue-entertainment-pykit` | Raw UDP `socket.SOCK_DGRAM` |
| Color space | xyb (CIE 1931) | Raw RGB bytes |
| Activation | REST call to Bridge required | None — UDP is stateless |
| Reconnect | Bridge socket re-activate | Reconnect UDP socket (trivial) |
| Config | Entertainment config UUID | WLED device IP + LED count |

`WledStreamingService` shares the same lifecycle contract as `StreamingService` (`start()`/`stop()`/state machine) but is independent. Both services run concurrently on the same frame from `CaptureRegistry.acquire()`.

Shared logic (color extraction, polygon masks) should move to a utility module both call.

### `database.py` — Three New Tables

```sql
-- WLED device registry
CREATE TABLE IF NOT EXISTS wled_devices (
    id       TEXT PRIMARY KEY,   -- UUID generated at add time
    name     TEXT NOT NULL,      -- from /json/info "name"
    ip       TEXT NOT NULL UNIQUE,
    port     INTEGER NOT NULL DEFAULT 21324,
    led_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);

-- LED range → canvas region mapping for each WLED device
CREATE TABLE IF NOT EXISTS wled_assignments (
    wled_device_id TEXT NOT NULL,  -- FK → wled_devices.id
    region_id      TEXT NOT NULL,  -- FK → regions.id
    led_start      INTEGER NOT NULL,  -- 0-indexed, inclusive
    led_end        INTEGER NOT NULL,  -- 0-indexed, inclusive
    PRIMARY KEY (wled_device_id, region_id)
);

-- Persist selected entertainment config per camera (bug fix)
CREATE TABLE IF NOT EXISTS entertainment_config_selections (
    camera_stable_id       TEXT PRIMARY KEY,
    entertainment_config_id TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
```

All use the existing `ALTER TABLE ... ADD COLUMN` migration pattern for additive schema changes.

### `main.py` — App State Addition

```python
from services.wled_streaming_service import WledStreamingService

wled_streaming = WledStreamingService(db=db, capture_registry=registry, broadcaster=broadcaster)
app.state.wled_streaming = wled_streaming
```

Follows the exact `app.state.streaming` pattern already established.

### New Router Files

- `routers/wled.py` — CRUD for WLED devices, start/stop WLED streaming, paint assignments (`/api/wled/...`)
- `routers/ha.py` — HA control endpoints (`/api/ha/start`, `/api/ha/stop`, `/api/ha/camera`, `/api/ha/zone`)
- No changes to `routers/capture.py`, `routers/hue.py`, or `routers/regions.py`

---

## Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `zeroconf` | `>=0.148,<2` | WLED auto-discovery on LAN via `_wled._tcp.local.` | Only during user-initiated device scan in the WLED tab. `AsyncServiceBrowser` with 3-second timeout. Not continuous background browsing. Only useful with `network_mode: host` in Docker — see caveat. |
| Python `socket` stdlib | stdlib | WLED UDP DRGB/DNRGB packet send | Per-frame during streaming. One `SOCK_DGRAM` socket per WLED device created at stream start, reused for the session, closed on stop. |
| `httpx` (existing) | `>=0.27` | WLED `/json/info` fetch, HA REST calls | At device registration and on-demand refresh. Not per-frame. |

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| Raw `socket` stdlib for WLED UDP | `python-wled` (PyPI v0.21.0) | `python-wled` wraps the JSON API only — no UDP realtime protocol support. Confirmed from source. Adding a 3+ dependency library for HTTP calls already covered by `httpx` is unjustified. |
| DNRGB for strips > 490 LEDs | DDP protocol (port 4048) | DDP has a 10-byte header with push IDs, flags, and offset fields. WLED explicitly states it ignores optional timecodes in DDP headers. DNRGB achieves the same segmented addressing with a 4-byte header. Lower complexity, same result for this use case. |
| DRGB for strips <= 490 LEDs | WARLS (protocol byte = 1) | WARLS has a 255 LED limit and requires per-LED index bytes. DRGB covers 490 LEDs, has a simpler packet format (no indices), and is the recommended WLED realtime protocol for full-strip updates. |
| HA calls HuePictureControl (`rest_command`) | HuePictureControl calls HA REST API | Storing an HA long-lived access token in HuePictureControl adds a configuration burden and an outbound dependency. `rest_command` is purpose-built for HA→external service control. Simpler, no secrets stored in HPC. |
| Sibling `WledStreamingService` class | Extend `StreamingService` with WLED support | Extending entangles DTLS and UDP codepaths, making each harder to test. `StreamingService` has Hue-specific activation/deactivation; WLED has none. Same lifecycle interface, separate classes. |
| `react-konva` (existing) for strip paint UI | Dedicated LED strip React component | No suitable package exists for this specific interaction pattern. The Konva canvas already handles pointer drag events and zone coloring in this project. A custom component using `Rect` nodes per LED range is ~150 lines of TSX. |
| Manual IP entry as primary discovery | mDNS-only discovery | mDNS multicast does not propagate through Docker bridge networks. Manual IP entry works reliably regardless of Docker network mode. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `python-wled` (PyPI) | JSON API only, no UDP realtime streaming. Adds indirect dependencies for functionality `httpx` already covers. | `httpx` for JSON API; raw `socket` for UDP |
| DDP over DNRGB | More complex header, no benefit for this use case. WLED ignores optional DDP timecodes anyway. | DNRGB chunked packets for > 490 LEDs |
| WARLS protocol (byte 0 = 1) | 255 LED limit. Superseded by DRGB/DNRGB. Most WS2812B strips are 300–1200 LEDs. | DRGB or DNRGB |
| Polling `/json/state` per frame | HTTP polling destroys latency. WLED does not confirm UDP receipt. | Fire-and-forget UDP only during streaming |
| `zeroconf` with Docker bridge network mode | Multicast does not propagate through Docker bridge. `AsyncServiceBrowser` will find zero devices. | Manual IP entry; mDNS only if backend switches to `network_mode: host` |
| Storing HA long-lived access token in HuePictureControl | Adds secret management burden; violates no-auth local tool design. | HA calls HPC via `rest_command`; HPC exposes unauthenticated control endpoints |
| New camera manager service / process for WLED camera | The existing `CaptureRegistry` pattern is sufficient. WLED streaming uses the same frame as Hue streaming — no second capture needed for the same device. | Extend `app.state` with `wled_streaming` that calls `registry.acquire()` on the same device path |

---

## Docker / Network Considerations

**mDNS in Docker bridge mode (current `docker-compose.yaml`):** Multicast does NOT propagate through Docker bridge networks. `zeroconf.AsyncServiceBrowser` will find zero WLED devices. Options:

1. **Switch backend to `network_mode: host`** — mDNS works immediately. Removes port mapping syntax (must use `expose:` instead). The Hue DTLS connection and WLED UDP both benefit from host network.
2. **Manual IP entry only** — Ship v1.3 without mDNS. User enters WLED IP + optional port. `/json/info` verifies the device. Sufficient for home use with static DHCP leases.

**Recommendation:** Ship v1.3 with manual IP entry as the only discovery path. Add mDNS as an optional v1.4 enhancement conditioned on `network_mode: host` migration. Do not block the milestone on network topology changes.

**UDP to WLED from Docker bridge:** Standard outbound UDP from Docker bridge to LAN works without `network_mode: host`. The streaming packets reach WLED devices on the LAN without any changes to `docker-compose.yaml`.

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `zeroconf>=0.148,<2` | Python 3.9–3.14, asyncio | Pure Python, no C extension required. Optional Cython for performance (not needed). No conflict with any existing requirement. |
| `zeroconf>=0.148,<2` | `fastapi>=0.115`, `uvicorn[standard]` | No interaction. Used only in a FastAPI route handler via `asyncio.to_thread` or `AsyncServiceBrowser`. |
| Python `socket` stdlib | Python 3.12, asyncio | Use `asyncio.to_thread(sock.sendto, data, addr)` for non-blocking sends — same pattern as `capture_v4l2.py` uses `asyncio.to_thread` for blocking ioctl calls. Consistent with existing codebase. |

---

## Installation

```bash
# Add to Backend/requirements.txt:
zeroconf>=0.148,<2

# Install in venv:
source /tmp/hpc-venv/bin/activate
pip install "zeroconf>=0.148,<2"
```

No frontend packages needed. `react-konva` and `zustand` (both already present) cover all UI requirements for the strip editor and WLED device management tab.

---

## Sources

- [WLED UDP Realtime docs](https://kno.wled.ge/interfaces/udp-realtime/) — WARLS/DRGB/DNRGB/DRGBW packet formats, port 21324, LED count limits, HIGH confidence
- [WLED Wiki UDP Realtime Control](https://github.com/Aircoookie/WLED/wiki/UDP-Realtime-Control) — Protocol byte values (1=WARLS, 2=DRGB, 3=DRGBW, 4=DNRGB), timeout semantics, exact byte offsets, HIGH confidence
- [WLED DDP docs](https://kno.wled.ge/interfaces/ddp/) — DDP port 4048, WLED does not read optional timecodes, HIGH confidence
- [WLED JSON API docs](https://kno.wled.ge/interfaces/json-api/) — `/json/info` endpoint, `leds.count` field structure, HIGH confidence
- [python-wled GitHub](https://github.com/frenck/python-wled) — v0.21.0, JSON API only, no UDP realtime, confirmed via README, HIGH confidence
- [zeroconf PyPI](https://pypi.org/project/zeroconf/) — v0.148.0 (Oct 2025), Python 3.9+, pure Python with optional Cython, HIGH confidence
- [WLED mDNS service type issue #103](https://github.com/Aircoookie/WLED/issues/103) — `_wled._tcp.local.` service type confirmed, HIGH confidence
- [Home Assistant REST API developer docs](https://developers.home-assistant.io/docs/api/rest/) — Bearer token auth, `/api/services/` endpoint format, HIGH confidence
- [wledcast reference implementation](https://github.com/ppamment/wledcast) — DDP streaming from Python, MEDIUM confidence (reference only, uses wxPython GUI not relevant here)

---
*Stack research for: HuePictureControl v1.3 — WLED UDP streaming, HA control endpoints, strip paint UI*
*Researched: 2026-04-14*
