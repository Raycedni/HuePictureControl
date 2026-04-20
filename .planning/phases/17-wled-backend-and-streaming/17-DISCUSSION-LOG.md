# Phase 17: WLED Backend and Streaming - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in 17-CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-20
**Phase:** 17-wled-backend-and-streaming
**Areas discussed:** Coordinator architecture, WLED channel data model, Streaming lifecycle, Phase 17 UI scope

---

## Coordinator architecture

### Q: Where does the capture → per-frame fan-out to Hue and WLED live?

| Option | Description | Selected |
|--------|-------------|----------|
| Extract Coordinator | New StreamingCoordinator owns the 60 Hz capture loop. HueStreamer and WledStreamer are sinks receiving per-region RGB dict. | ✓ |
| Two sibling services | Keep StreamingService as-is; add parallel WledStreamingService with its own capture loop. | |
| Extend StreamingService | Add WLED code paths inside existing StreamingService. | |

**User's choice:** Extract Coordinator.

### Q: Where is per-region color extraction done?

| Option | Description | Selected |
|--------|-------------|----------|
| Once in Coordinator | Extract region → rgb once per frame, pass {region_id: rgb} to both sinks. | ✓ |
| Twice (once per sink) | Each sink iterates its own channel map and runs extract_region_color independently. | |

**User's choice:** Once in Coordinator.

### Q: How much of StreamingService's Hue logic moves into a new HueStreamer sink?

| Option | Description | Selected |
|--------|-------------|----------|
| Full extraction | Coordinator owns capture, frame loop, reconnect, broadcaster. HueStreamer is a pure sink. | ✓ |
| Coordinator wraps Service | Thin layer that calls existing StreamingService.start() and new WledStreamingService.start(). | |
| Claude's discretion | Let planner decide the split during implementation. | |

**User's choice:** Full extraction.

### Q: Per-sink failure handling during streaming?

| Option | Description | Selected |
|--------|-------------|----------|
| Independent sinks | Hue bridge disconnect → Hue-only reconnect. WLED device unreachable → per-device backoff within WledStreamer. | ✓ |
| Coordinator-managed | Coordinator owns reconnect policy for all sinks. | |
| Fire-and-forget WLED | WLED UDP errors ignored silently. | |

**User's choice:** Independent sinks.

---

## WLED channel data model

### Q: How are WLED LED ranges modeled in the DB relative to existing light_assignments?

| Option | Description | Selected |
|--------|-------------|----------|
| Separate WLED tables | New wled_devices, wled_channels, wled_light_assignments tables. | ✓ |
| Unified channel table | One channels table with source_type discriminator + one channel_assignments table. | |
| Strip-as-channel | Phase 17 treats entire strip as one channel; defer range modeling to Phase 19. | |

**User's choice:** Separate WLED tables.

### Q: Are WLED channels scoped to an entertainment_config_id (like Hue channels), or globally available?

| Option | Description | Selected |
|--------|-------------|----------|
| Per-config | WLED channel assignments key on entertainment_config_id, mirroring Hue. | ✓ |
| Global | WLED channels and assignments not tied to a Hue entertainment config. | |

**User's choice:** Per-config.

### Q: At device registration, how is the initial wled_channels content populated before Phase 19 paint UI exists?

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-seed one channel | On device add, auto-create one channel spanning the full strip named 'Strip'. | ✓ |
| Empty until painted | wled_channels rows only exist once Phase 19 paints them. | |
| POST channels endpoint | Expose POST /api/wled/devices/{id}/channels for manual channel creation. | |

**User's choice:** Auto-seed one channel.

### Q: When a WLED channel spans LEDs 10-30 and is assigned to region X, what color does each LED get?

| Option | Description | Selected |
|--------|-------------|----------|
| Uniform across range | All LEDs in range get the single averaged color of region X (Hue gradient semantics). | |
| Per-LED region split | Region subdivided spatially; each LED samples its own slice. | ✓ |
| Claude's discretion | Let implementer pick. | |

**User's choice:** Per-LED region split.

### Q: Per-LED split — how should LEDs along a range map to spatial positions in the region?

| Option | Description | Selected |
|--------|-------------|----------|
| Linear across bounding box | Split region's bounding box into N equal slices along its longest axis, each LED samples one slice. | ✓ |
| Along polygon path | Map LEDs to positions along the polygon's perimeter or centerline. | |
| User picks axis per region | User specifies direction per region (adds UI + schema column). | |

**User's choice:** Linear across bounding box.

### Q: What does the Coordinator pass to the WLED sink per frame?

| Option | Description | Selected |
|--------|-------------|----------|
| Region → gradient array | Coordinator extracts region colors as an array of N sub-samples per region; both sinks consume. | ✓ |
| Sink-specific extraction | Hue gets averaged RGB; WLED re-extracts per-LED sub-colors independently. | |
| Claude's discretion | Planner picks the shape. | |

**User's choice:** Region → gradient array.

---

## Streaming lifecycle

### Q: How does WLED streaming start/stop relate to /api/capture/start?

| Option | Description | Selected |
|--------|-------------|----------|
| Tied to global start | One /api/capture/start — coordinator starts capture, Hue, and all enabled WLED devices. | ✓ |
| Independent toggles | Separate POST /api/wled/start and /stop endpoints, independent of Hue. | |
| Global start + per-device opt-out | Global start attaches enabled devices; also expose per-device start/stop endpoints. | |

**User's choice:** Tied to global start.

### Q: What does the per-device `enabled` column actually gate?

| Option | Description | Selected |
|--------|-------------|----------|
| UDP-send gate only | Device always in coordinator list; enabled=false skips that device per-frame. | ✓ |
| Full attachment gate | enabled=false prevents inclusion at start time; mid-stream toggle requires restart. | |

**User's choice:** UDP-send gate only.

### Q: When streaming stops, what does the coordinator do regarding the final packet?

| Option | Description | Selected |
|--------|-------------|----------|
| Rely on WLED timeout | Stop sending; rely on firmware timeout to revert. | |
| Explicit off packet | Send all-zero DRGB packet, then rely on timeout. | ✓ |
| Send off, no timeout byte | Set timeout to 255 (infinite) and send explicit blackout. | |

**User's choice:** Explicit off packet.

### Q: UDP timeout byte value — how long WLED holds the last color after packets stop?

| Option | Description | Selected |
|--------|-------------|----------|
| 2 seconds (fast revert) | Strip releases within 2s of stream stop. | ✓ |
| 5 seconds (tolerant) | Absorbs brief stalls; slower release on stop. | |
| Per-device configurable | Add timeout_seconds column per device. | |
| Claude's discretion | Default 2s, tune later. | |

**User's choice:** 2 seconds (fast revert).

### Q: When a WLED device stops responding mid-stream, how aggressively should the coordinator recover?

| Option | Description | Selected |
|--------|-------------|----------|
| Silent + backoff probe | Log at rate-limit; after N failures auto-disable 30s then retry; no UI surfacing. | |
| Surface to status | Extend StatusBroadcaster with per-device health; UI eventually renders. | ✓ |
| Fire-and-forget only | Ignore all UDP errors. | |

**User's choice:** Surface to status.

---

## Phase 17 UI scope

### Q: How much frontend work lives in Phase 17?

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal device CRUD tab | WLED tab: IP input, device list (name/IP/LED count/enabled toggle/remove). No painting. | ✓ |
| Backend + REST only | Zero frontend. All testing via curl. | |
| Read-only status strip | No device CRUD in UI; compact StatusBar strip. | |

**User's choice:** Minimal device CRUD tab.

### Q: Should the StatusBroadcaster per-device WLED health surface in the UI this phase?

| Option | Description | Selected |
|--------|-------------|----------|
| Payload only, no UI render | Backend emits; frontend parses/stores; no visual component. | ✓ |
| Render in device list | WLED tab shows per-device last_error and last_success_at inline. | |
| Skip until Phase 19 | Don't extend WS payload in Phase 17. | |

**User's choice:** Payload only, no UI render.

### Q: Where does the new WLED tab live?

| Option | Description | Selected |
|--------|-------------|----------|
| New top-level tab | WLED tab alongside Editor/Preview. | |
| Settings panel | Nest WLED CRUD inside Settings drawer/modal. | ✓ |
| Claude's discretion | Frontend planner decides. | |

**User's choice:** Settings panel.

### Q: Should the WLED tab include any device auto-discovery, or IP-only manual add?

| Option | Description | Selected |
|--------|-------------|----------|
| IP-only manual | Just an IP field + Add button. No mDNS. | |
| IP + optional scan button | IP field plus a "Scan network" button triggering backend zeroconf query. | ✓ |

**User's choice:** IP + optional scan button.

### Q: Phase 19 paint UI — where does it go if Phase 17's WLED device CRUD lives in Settings?

| Option | Description | Selected |
|--------|-------------|----------|
| Paint UI becomes top-level tab | Settings for registration, top-level tab for painting. | |
| Paint UI inside same settings panel | Settings panel expands to include paint canvas. | ✓ |
| Defer decision to Phase 19 | Phase 19 discuss-phase decides fresh. | |

**User's choice:** Paint UI inside same settings panel.

### Q: Scan button implementation — stdlib-only or add zeroconf dependency?

| Option | Description | Selected |
|--------|-------------|----------|
| zeroconf library | Add zeroconf>=0.148,<2; AsyncServiceBrowser with 3s timeout on _wled._tcp.local. | ✓ |
| stdlib UDP probe | Manually craft mDNS query packets with stdlib socket. | |
| Defer scan to Phase 19 | Ship Phase 17 with IP-only manual add. | |

**User's choice:** zeroconf library.

---

## Claude's Discretion

Areas where user deferred explicit decision or left headroom for planner:

- Exact class naming of coordinator and sinks (`StreamingCoordinator`, `HueStreamer`, `WledStreamer` proposed).
- Exponential backoff curve for per-device WLED probe after auto-disable 30s hold.
- Rate-limit window for per-device error logs (suggested 5s).
- SQL upsert form for the new tables (INSERT OR REPLACE vs explicit UPSERT).
- Probe strategy in GET /api/wled/devices (live probe vs cached last-success timestamp).
- Whether bounding-box axis is cached per region mask or recomputed per frame.
- Test strategy for WLED sink (local UDP listener vs mocked socket.sendto).
- Visual language of the Settings panel (Phase 19 will refine).

## Deferred Ideas

- Polygon-path LED mapping (refinement of linear bounding-box sampling).
- User-picks-axis per region (schema + UI additions, not justified yet).
- Per-device configurable timeout byte (default 2s fixed for now).
- Rendering per-device WLED health in the UI (payload only in Phase 17).
- Startup auto-reconnect probe of WLED devices (beyond the in-flight 30s cycle).
- Per-device start/stop endpoints (rejected in favor of global start + enabled gate).
- `python-wled` library and DDP protocol — explicitly rejected, planner must not reintroduce.
