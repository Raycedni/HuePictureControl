# Feature Research

**Domain:** Real-time ambient lighting — WLED ESP32 LED strip support, Home Assistant control, entertainment zone persistence
**Researched:** 2026-04-14
**Confidence:** HIGH (WLED protocols from official docs), MEDIUM (HA integration patterns from community), HIGH (persistence patterns from Zustand ecosystem)

## Context: What This Milestone Adds

This is a subsequent milestone on top of a working Hue Entertainment API system. The existing system has:
- Canvas-based freeform region editor (Konva.js + Zustand)
- Multi-camera per-zone support
- Live preview and streaming metrics WebSockets
- `POST /api/capture/start` and `POST /api/capture/stop` endpoints

New additions: WLED device support, Home Assistant control endpoints, entertainment zone persistence fix.

---

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Manual WLED device add by IP | Discovery fails on complex networks; power users always need manual fallback | LOW | `POST /api/wled/devices` with `{ip, name}` body; validate by hitting `/json/info` before saving |
| Fetch LED count from device | Without this, the paint-on-strip UI cannot render the strip at all | LOW | `GET /json/info` returns `leds.count` (1-1200); call on add and on refresh |
| Persist WLED device list | Devices disappear on restart otherwise | LOW | Add `wled_devices` table with `id, ip, name, led_count, created_at` |
| DDP UDP streaming to WLED | DDP is the dominant realtime protocol for WLED ambilight; users expect it by default | MEDIUM | Port 4048 UDP; one 1440-byte datagram = 480 RGB pixels; protocol ID 0x41 + data offset + RGB payload |
| Timeout/fallback behavior | Without a timeout byte, WLED freezes on last color when streaming stops | LOW | DDP header includes timeout; WLED reverts to effect mode after timeout |
| Stop streaming clears WLED | When the user stops streaming, lights should return to WLED's own effects | LOW | On stop(), rely on DDP timeout (1-2 seconds) OR send final all-zeros packet |
| Zone-to-LED-range assignment | Core purpose of WLED support; each canvas zone drives a contiguous LED range | HIGH | Paint-on-strip UI; store `{zone_id, wled_device_id, led_start, led_end}` per zone |
| HA start/stop streaming endpoints | HA users need unauthenticated HTTP calls to trigger ambilight from automations | LOW | `POST /api/ha/start` and `POST /api/ha/stop`; thin wrappers over existing capture service |
| HA select camera endpoint | HA automations switch input source (e.g., on HDMI input change event) | LOW | `PUT /api/ha/camera` with `{device_path}` — wraps existing camera assignment logic |
| HA select entertainment config | HA needs to switch Hue configs (e.g., room-specific presets) | LOW | `PUT /api/ha/config` with `{config_id}` — wraps existing Hue config selection |
| Persist selected entertainment config | Bug fix: config selection lost on page reload; users reconfigure every session | LOW | Zustand persist middleware writing to localStorage; key: selected-config-per-camera |
| Dropdown reflects streaming state on reload | Bug fix: dropdown shows wrong config when backend is already streaming | LOW | On mount, fetch streaming status to rehydrate; add `GET /api/capture/status` if needed |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Paint-on-strip visual editor | Hyperion uses numeric inputs (count per side, offsets); visual drag-on-strip is far more intuitive for irregular layouts | HIGH | Horizontal scrollable strip visualization; drag to define start/end of each zone's range; 300+ LEDs requires zoom/pan |
| Multi-device WLED streaming | Drive separate WLED strips independently from the same canvas (e.g., TV strip + bias light strip) | MEDIUM | Multiple wled_device_id per zone; streaming_service.py needs WLED send path alongside Hue DTLS path |
| Shared channel abstraction | Zones can drive Hue channels AND WLED LED ranges simultaneously | HIGH | Abstraction layer where a zone has N outputs: `{type: "hue", channel_id}` or `{type: "wled", device_id, led_start, led_end}` |
| mDNS auto-discovery | Users with WLED on simple networks see devices appear automatically | MEDIUM | zeroconf library; service type `_wled._tcp.local.`; populate suggestion list (not auto-add) |
| Per-device LED count validation | Warn if zone assignments exceed device LED count | LOW | Client-side + server-side check before save |
| WLED segment state restore on stop | On stop, restore WLED to its pre-streaming segment/effect state | MEDIUM | Before streaming: GET `/json/state`, cache; on stop: POST cached state back |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| WLED segment API control (POST `/json/state`) for streaming | Seems natural since WLED has a segment API | REST POST rate is limited and adds 10-30ms round-trip; DDP UDP is purpose-built for realtime at 40+ fps with single-datagram delivery | Use DDP UDP for streaming; only use JSON API for device config and state save/restore |
| Auto-add all discovered mDNS devices | Reduces clicks | Pollutes device list with neighbor ESP32s not intended for ambilight; `_wled._tcp` service name is generic | Show discovery suggestions in UI; require explicit user confirmation to add |
| HA webhook authentication tokens | Some users request token-based HA security | HuePictureControl is explicitly unauthenticated (local network tool); adding token validation creates inconsistency and maintenance surface | Document that HA integration assumes LAN-only and firewall isolation |
| WLED effect passthrough (trigger WLED effects from HPC) | Users ask for full WLED control from HPC UI | Duplicates WLED's own web UI and goes outside HPC's core value (color sync from video) | Link out to WLED device's own web UI from the device row |
| E1.31 / sACN streaming | Some ambilight setups use E1.31 | Adds significant protocol complexity for no gain vs DDP; DDP handles 480 LEDs/datagram with simpler framing | DDP only for v1.3; E1.31 deferred |
| DNRGB multi-packet spanning | DNRGB protocol supports >490 LEDs via start-index | Adds fragmentation logic for minimal gain; typical TV strip is 300 LEDs which fits in DRGB | Use DRGB (protocol 2) for <=490 LEDs; add DNRGB only if a user has >490 LED strip |

---

## Feature Dependencies

```
[WLED device table in DB]
    └──enables──> [Manual device add by IP]
    └──enables──> [mDNS discovery suggestions]
                       └──both enable──> [Zone-to-LED-range assignment]
                                             └──requires──> [Paint-on-strip editor]
                                             └──requires──> [DDP UDP streaming]

[DDP UDP streaming]
    └──requires──> [WLED device list with IP + LED count]
    └──integrates into──> [Existing streaming_service.py 50-60 Hz loop]

[Shared channel abstraction]
    └──requires──> [DDP UDP streaming]
    └──requires──> [Existing Hue DTLS streaming]

[HA start/stop endpoints]
    └──wraps──> [Existing POST /api/capture/start + stop]

[HA camera select]
    └──wraps──> [Existing PUT /api/cameras/assignments]

[Persist entertainment config]
    └──uses──> [Zustand persist middleware (already available in project)]
    └──fixes bug in──> [Existing EditorPage config dropdown]

[Dropdown reflects streaming state on reload]
    └──requires──> [Persist entertainment config]
    └──requires──> [Streaming state on mount — GET /api/capture/status or WS hydration]
```

### Dependency Notes

- **Zone-to-LED-range assignment requires device table first.** The paint editor needs to know which device to render (LED count determines strip length). Device CRUD must ship before the editor.
- **DDP streaming integrates into the existing loop.** `streaming_service.py` already runs a 50-60 Hz asyncio loop. WLED UDP sends can be appended to the same loop iteration with no second task needed.
- **HA endpoints are thin wrappers.** No new business logic. They exist purely so HA's `rest_command` integration can call them without knowing internal config IDs at call time.
- **Persist fix is independent of WLED.** Zustand `persist` middleware is already available. This is a 1-file change; no backend changes required.
- **Streaming state rehydration depends on a status endpoint.** The existing `/ws/status` WebSocket provides streaming state but requires active connection. A synchronous `GET /api/capture/status` returning current state simplifies on-mount rehydration.

---

## MVP Definition

### Launch With (v1.3)

- [ ] Manual WLED device add/delete by IP with LED count fetched from `/json/info` — without this, nothing else works
- [ ] WLED device list persisted in `wled_devices` DB table — required for survival across restarts
- [ ] Zone-to-LED-range assignments stored per zone — the core data model
- [ ] Paint-on-strip editor (scrollable strip with draggable zone handles) — users cannot map without visual feedback
- [ ] DDP UDP streaming (DRGB protocol, <=490 LEDs) — the delivery mechanism
- [ ] DDP integrated into existing 50-60 Hz streaming loop — same loop, parallel Hue + WLED sends
- [ ] HA endpoints: `POST /api/ha/start`, `POST /api/ha/stop`, `PUT /api/ha/camera`, `PUT /api/ha/config` — all thin wrappers, low cost
- [ ] Fix: entertainment config persisted to localStorage via Zustand persist — single store change
- [ ] Fix: streaming state rehydrated on reload via `GET /api/capture/status` — mount hook reads current state

### Add After Validation (v1.x)

- [ ] mDNS auto-discovery suggestions — useful but not blocking; manual IP entry is sufficient for v1.3
- [ ] Multi-device WLED (multiple strips from one zone) — complex data model change; validate single-device first
- [ ] Shared channel abstraction (zone drives Hue AND WLED simultaneously) — depends on multi-device validation
- [ ] WLED segment state save/restore on stop — polish; not correctness-critical

### Future Consideration (v2+)

- [ ] DNRGB multi-packet support for >490 LED strips
- [ ] E1.31/sACN protocol support
- [ ] WLED effect passthrough from HPC UI

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| WLED device add/persist | HIGH | LOW | P1 |
| DDP UDP streaming | HIGH | MEDIUM | P1 |
| Paint-on-strip editor | HIGH | HIGH | P1 |
| Zone-to-LED-range storage | HIGH | LOW | P1 |
| HA start/stop endpoints | MEDIUM | LOW | P1 |
| HA camera/config select | MEDIUM | LOW | P1 |
| Entertainment config persistence fix | HIGH | LOW | P1 |
| Streaming state on reload fix | MEDIUM | LOW | P1 |
| mDNS device discovery | MEDIUM | MEDIUM | P2 |
| Multi-device WLED | MEDIUM | HIGH | P2 |
| Shared Hue+WLED channel abstraction | HIGH | HIGH | P2 |
| WLED segment state restore on stop | LOW | MEDIUM | P3 |

---

## Competitor Feature Analysis

| Feature | Hyperion | HyperHDR | HuePictureControl Approach |
|---------|----------|----------|---------------------------|
| WLED streaming protocol | DDP (since Hyperion v2.0.13, requires WLED 0.13.3+) | DDP | DDP UDP (DRGB) — same as current best practice |
| LED layout editor | Numeric: count per side + offset; no visual strip editor | Numeric similar to Hyperion | Visual paint-on-strip — differentiator |
| WLED discovery | mDNS auto-add | mDNS auto-add | mDNS suggestions + manual IP — manual is MVP |
| Segment support | Yes, maps regions to segments | Yes | LED ranges (start/end) stored per zone — equivalent |
| Gradient Hue devices | Not supported | Not supported | Already supported — existing advantage |
| HA integration | External HA community component | External HA community component | Native REST endpoints — lower friction |
| Persistence | Config file on disk | Config file on disk | DB + localStorage — survives restart and reload |

---

## Protocol Technical Reference (for Implementation)

### DRGB (WLED port 21324 UDP) — HIGH confidence
Simpler, purpose-built WLED protocol for sequential RGB. Supports 490 LEDs max. Recommended for v1.3:
- Byte 0: `0x02` (DRGB protocol ID)
- Byte 1: timeout in seconds (1-2 recommended; 255 = no timeout)
- Bytes 2+: sequential RGB values (LED 0 R, G, B; LED 1 R, G, B; ...)

### DDP (WLED port 4048 UDP) — HIGH confidence
More general protocol. One datagram carries up to 480 RGB pixels (1440 bytes):
- Byte 0: flags `0x41` (standard push)
- Byte 1: sequence number (0 = no sequence)
- Bytes 2-3: data type (`0x0001` = RGB)
- Bytes 4-7: data offset (0 for strips <=480 LEDs)
- Bytes 8-9: data length (N * 3 bytes)
- Bytes 10+: RGB payload

**Recommendation:** Use DRGB for simplicity (native WLED timeout handling, fewer header bytes). Upgrade to DDP if user has >490 LEDs.

### WLED JSON API for device config — HIGH confidence
- `GET /json/info` returns `leds.count`, device name, firmware version
- `GET /json/state` returns current state (save before streaming for restore on stop)
- `POST /json/state` sets state — not for realtime use; only for config operations

### Home Assistant rest_command pattern — MEDIUM confidence
Example HA `configuration.yaml` entry for HPC control:
```yaml
rest_command:
  hpc_start:
    url: "http://192.168.x.y:8000/api/ha/start"
    method: POST
  hpc_stop:
    url: "http://192.168.x.y:8000/api/ha/stop"
    method: POST
  hpc_set_camera:
    url: "http://192.168.x.y:8000/api/ha/camera"
    method: PUT
    content_type: "application/json"
    payload: '{"device_path": "{{ device_path }}"}'
```
HA calls these as `rest_command.hpc_start` actions from automations. No auth token needed (LAN-only deployment).

---

## Sources

- [WLED UDP Realtime / DRGB docs](https://kno.wled.ge/interfaces/udp-realtime/) — protocol byte layout, port 21324, timeout behavior, HIGH confidence
- [WLED DDP protocol docs](https://kno.wled.ge/interfaces/ddp/) — DDP port 4048, packet structure, HIGH confidence
- [WLED JSON API](https://kno.wled.ge/interfaces/json-api/) — `/json/info`, `/json/state`, segment objects, HIGH confidence
- [WLED Home Automation guide](https://kno.wled.ge/advanced/home-automation/) — mDNS service type, HA integration patterns, HIGH confidence
- [Hyperion WLED device docs](https://docs.hyperion-project.org/user/leddevices/network/wled.html) — Hyperion uses DDP since v2.0.13; segment streaming requires WLED 0.13.3+, MEDIUM confidence
- [python-wled async client](https://github.com/frenck/python-wled) — async Python library, Python 3.11+, experimental status, MEDIUM confidence
- [wled-mdns-scanner](https://github.com/sanyvrbovec/wled-mdns-scanner) — mDNS discovery via zeroconf, `_wled._tcp.local.` service type, MEDIUM confidence
- [HA rest_command integration](https://www.home-assistant.io/integrations/rest_command/) — GET/POST/PUT/DELETE support, payload templating, HIGH confidence
- [Zustand persistence](https://react.alexey-dc.com/zustand_persistence) — persist middleware for localStorage, HIGH confidence

---
*Feature research for: HuePictureControl v1.3 — WLED + HA + persistence*
*Researched: 2026-04-14*
