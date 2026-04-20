# Phase 17: WLED Backend and Streaming - Context

**Gathered:** 2026-04-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Backend adds WLED ESP32 support alongside the existing Hue pipeline:

1. **Device management** — register WLED devices by IP, fetch name + LED count via `/json/info`, persist across restarts, enable/disable, remove.
2. **UDP streaming** — stream per-frame color data to enabled WLED devices at 50–60 Hz using DRGB (≤490 LEDs) or DNRGB (>490 LEDs), auto-selected per device.
3. **Coordinator refactor** — extract a `StreamingCoordinator` that owns the capture loop and fans out to a Hue sink and a WLED sink, so Hue and WLED both run from a single captured frame without double-decoding or double-masking.
4. **Channel abstraction** — WLED LED ranges become assignable "channels" under the existing region-assignment workflow, per-entertainment-config scoped, so Phase 19's paint UI can drop into this model cleanly.
5. **Minimal Settings-panel UI** — register/list/enable/disable devices and trigger a zeroconf scan. No painting in this phase (Phase 19 owns that).

Explicitly out of scope: paint-on-strip UI (Phase 19), HA control endpoints (Phase 18), per-device UI health rendering (payload only, no visual component).

</domain>

<decisions>
## Implementation Decisions

### Coordinator architecture
- **D-01:** Extract a new `StreamingCoordinator` class that owns `CaptureRegistry.acquire()`, the 60 Hz frame loop, `StatusBroadcaster` orchestration, and reconnect coordination. It is the new entry point called by `/api/capture/start` and `/api/capture/stop`.
- **D-02:** Refactor existing `StreamingService` into a `HueStreamer` sink — full extraction. Capture lifecycle moves out of this class. `HueStreamer` accepts per-frame input from the coordinator (see D-05) and owns bridge create/activate, DTLS socket, `set_input` calls, and Hue-only reconnect.
- **D-03:** Add a new `WledStreamer` sink as a sibling to `HueStreamer`. Owns one `socket.SOCK_DGRAM` per enabled WLED device (created on stream start, reused for the session, closed on stop) and the DRGB/DNRGB protocol choice per device. Runs in the same frame loop the coordinator drives — no independent loop.
- **D-04:** Color extraction runs **once** in the coordinator per frame. Region polygons are masked once; both sinks receive the result. No duplicate `extract_region_color` calls when a region feeds both Hue and WLED.
- **D-05:** Coordinator passes `{region_id: gradient_array}` to sinks per frame, where `gradient_array` is `N` sub-sampled RGBs along the region's bounding-box longest axis. `N` is the max LED-range width among WLED channels referencing that region (floor 1 for Hue-only regions). Hue sink averages the array back to a single RGB for `set_input`; WLED sink maps array slices to LED ranges.
- **D-06:** Per-sink reconnect policies are independent. Hue bridge disconnect uses the existing Hue backoff pattern inside `HueStreamer`. WLED device send failures are handled inside `WledStreamer` per-device; they never block Hue and never halt the coordinator loop.

### WLED channel data model
- **D-07:** Three new tables, separate from Hue's `light_assignments`:
  - `wled_devices(id TEXT PRIMARY KEY, ip TEXT NOT NULL UNIQUE, name TEXT NOT NULL, led_count INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)`
  - `wled_channels(id TEXT PRIMARY KEY, device_id TEXT NOT NULL, name TEXT NOT NULL, start_led INTEGER NOT NULL, end_led INTEGER NOT NULL, color TEXT NOT NULL DEFAULT '#ffffff')` (color is a UI display color for the channel chip, not the streaming color)
  - `wled_light_assignments(region_id TEXT NOT NULL, wled_channel_id TEXT NOT NULL, entertainment_config_id TEXT NOT NULL, PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id))`
- **D-08:** WLED channel assignments are **per `entertainment_config_id`**, mirroring Hue `light_assignments`. Switching Hue zones can yield different WLED-region mappings — same mental model users built in v1.0–v1.1.
- **D-09:** On WLED device registration, auto-seed **one channel** covering the full strip: `start_led=0, end_led=led_count-1, name='Strip'`. Phase 17 is fully usable end-to-end without painting — user assigns the seed channel to a region via existing drag-drop. Phase 19 paint UI replaces/splits/resizes this seed channel.
- **D-10:** Per-LED color = **linear sub-sample across the region's bounding box along its longest axis**. LED `i` of a range [start, end] of width `W` samples position `i/(W-1)` along the bounding box. Matches user's intent that LEDs along a strip map spatially across a region.

### Streaming lifecycle
- **D-11:** Global `/api/capture/start` triggers the coordinator, which starts Hue **and** attaches all `wled_devices WHERE enabled = 1` as UDP sinks in the same call. `/api/capture/stop` stops everything. One toggle, not two — consistent with the existing global on/off UX.
- **D-12:** The `enabled` column is a **per-frame UDP-send gate**, not an attachment gate. Devices always live in the coordinator's device list once added; `enabled=false` simply skips that device in the per-frame send loop. Mid-stream toggle requires no restart.
- **D-13:** Stop sequence: coordinator (a) emits one final DRGB/DNRGB packet with all-zero RGB to every enabled device (explicit blackout), then (b) closes sockets. WLED's timeout byte (D-14) is a belt-and-suspenders — explicit off covers the normal stop path; timeout covers coordinator crash or network drop.
- **D-14:** DRGB/DNRGB timeout byte = **2 seconds**. Strip reverts within 2s of packets stopping. Fast enough that users see immediate stop confirmation; long enough to absorb single-frame network hiccups.
- **D-15:** Per-device error handling: UDP `sendto` exceptions (OSError: unreachable, etc.) are logged at a rate limit (e.g. once per 5s per device). After N consecutive send failures (planner to pick N — 30 frames at 60 Hz = 0.5s is a reasonable starting point), the device is **auto-disabled for 30s** in-memory (DB `enabled` flag unchanged). After 30s it auto-re-probes. Per-device health surfaces in `StatusBroadcaster` payload (D-16), not logs alone.
- **D-16:** `StatusBroadcaster._metrics` gains a `wled_devices` key: `{device_id: {last_error: str|None, last_success_at: iso8601|None, in_cooldown: bool}}`. Included in every WS broadcast. Phase 17 does not render this in the UI — it is wire-ready for Phase 18 (HA status) and Phase 19 (paint UI device status).

### Phase 17 UI scope
- **D-17:** Minimal WLED device CRUD UI in a **Settings panel** (drawer/modal). Fields: IP input + Add button, device list showing name / IP / LED count / connected state / enabled toggle / Remove button, and a "Scan network" button for zeroconf discovery.
- **D-18:** Device CRUD API (new router `routers/wled.py`):
  - `GET /api/wled/devices` — list registered devices with live connection state
  - `POST /api/wled/devices` — body `{ip: string}`; backend fetches `/json/info` via httpx, persists `name`, `led_count`; auto-seeds one channel per D-09; returns full device record
  - `DELETE /api/wled/devices/{id}` — removes device and cascades its channels/assignments
  - `PUT /api/wled/devices/{id}/enabled` — body `{enabled: bool}`; toggles gate per D-12
  - `POST /api/wled/scan` — triggers zeroconf `_wled._tcp.local.` discovery with a 3s timeout; returns list of `{ip, name}` candidates (not yet registered)
- **D-19:** Scan uses the **`zeroconf` library** (`>=0.148,<2`). Add to `Backend/requirements.txt`. `AsyncServiceBrowser` runs inside an `asyncio.to_thread`-compatible wrapper as needed. Backend runs natively on Linux (no Docker from v1.2) per user memory, so mDNS works without the Docker-bridge caveat.
- **D-20:** **Phase 19 paint UI lives in the same Settings panel** as the WLED device CRUD (user decision — keeps WLED-everything in one place). Phase 17 must leave room in the panel layout for a canvas-heavy paint area to slot in later.

### Claude's Discretion
- Exact class naming of coordinator and sinks. `StreamingCoordinator`, `HueStreamer`, `WledStreamer` are proposed — planner may refine if existing imports suggest better names.
- Exponential backoff curve for per-device WLED probe after auto-disable (30s hold is anchored in D-15; re-probe delay after resume is open).
- Rate-limit window for per-device error logs (suggested 5s, planner can tune).
- SQL upsert form for the new tables (INSERT OR REPLACE vs explicit UPSERT — follow existing `database.py` conventions).
- How the `/api/wled/devices` GET response merges persisted device rows with live connection state (probe on GET vs cache last successful send timestamp).
- Sub-sample implementation for D-10: whether bounding-box longest axis is computed once per region mask and cached, or recomputed per frame (recompute at 60 Hz × 8–16 regions is likely fine).
- Test strategy for WLED sink: whether to stand up a local UDP listener in integration tests or rely on mocked `socket.sendto`.
- UI visual language of the Settings panel (Phase 19 will refine).

### Folded Todos
None — STATE.md lists no pending todos.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & Project
- `.planning/ROADMAP.md` §Phase 17 — six success criteria for WLED backend and streaming
- `.planning/ROADMAP.md` §Phase 19 — paint UI scope, for ensuring Phase 17 data model supports it cleanly
- `.planning/ROADMAP.md` §Phase 18 — HA endpoints, for ensuring status payload extension serves that phase too
- `.planning/PROJECT.md` §Active (v1.3) — WLED / HA bullets
- `.planning/STATE.md` §Accumulated Context → Decisions — v1.3 roadmap pre-decisions (stdlib socket, DRGB/DNRGB auto-select, httpx for /json/info, shared channel abstraction)

### Prior Phase Contexts (must-read)
- `.planning/phases/16-zone-persistence-bug-fixes/16-CONTEXT.md` — `active_config_id`/`active_device_path` payload convention, `push_state` kwarg semantics, "per-dropdown autosave" pattern
- `.planning/milestones/v1.1-phases/08-capture-registry/08-CONTEXT.md` — `CaptureRegistry.acquire/release` ref-counted pool semantics (coordinator will be the sole acquirer)
- `.planning/milestones/v1.1-phases/10-frontend-camera-selector/10-CONTEXT.md` — auto-save-on-change UX convention for dropdowns (applies to the Settings panel toggles)
- `.planning/phases/03-entertainment-api-streaming-integration/03-CONTEXT.md` — DTLS streaming lifecycle, `set_input` color-space semantics
- `.planning/phases/05-gradient-device-support-and-polish/05-CONTEXT.md` — per-channel gradient semantics for Hue, reference point for WLED per-LED semantics

### Project Convention / Research
- `CLAUDE.md` "Context: What Already Exists" and "Recommended Stack Additions" — WLED packet formats, DRGB vs DNRGB thresholds, httpx usage, zeroconf Docker caveat (no longer applies — native Linux per user memory)
- `CLAUDE.md` "Alternatives Considered" / "What NOT to Use" — `python-wled` rejected, DDP rejected in favor of DNRGB, etc. Planner must not reintroduce these.
- `.planning/research/STACK.md` — existing stack context
- `.planning/research/PITFALLS.md` — accumulated project pitfalls to avoid

### Backend Files (modify)
- `Backend/database.py` — add three `CREATE TABLE IF NOT EXISTS` blocks for `wled_devices`, `wled_channels`, `wled_light_assignments` (D-07)
- `Backend/services/streaming_service.py` — refactor into `HueStreamer` sink per D-02; capture loop and StatusBroadcaster orchestration move out
- `Backend/services/status_broadcaster.py` — add `wled_devices` key to `_metrics` (D-16); extend `update_metrics`/`push_state` as needed to carry per-device health
- `Backend/routers/capture.py` — `/api/capture/start` and `/api/capture/stop` now go through `StreamingCoordinator` (D-11)
- `Backend/main.py` — lifespan creates `StreamingCoordinator` (replaces `StreamingService` in `app.state`); still holds the capture registry and broadcaster

### Backend Files (new)
- `Backend/services/streaming_coordinator.py` — new `StreamingCoordinator` class (D-01, D-04, D-05, D-11)
- `Backend/services/wled_streamer.py` — new `WledStreamer` sink with DRGB/DNRGB packet builders and per-device UDP socket lifecycle (D-03, D-13, D-14, D-15)
- `Backend/services/wled_client.py` — thin httpx wrapper for `GET /json/info`, used at device registration
- `Backend/services/wled_discovery.py` — zeroconf `_wled._tcp.local.` scan with 3s timeout (D-19)
- `Backend/routers/wled.py` — device CRUD + scan endpoints (D-18)

### Frontend Files (new/modify)
- `Frontend/src/api/wled.ts` — new API client for `/api/wled/*` endpoints
- `Frontend/src/components/Settings/WledDevicesPanel.tsx` — new component implementing D-17 (list, add, remove, enable toggle, scan)
- `Frontend/src/components/Settings/SettingsPanel.tsx` — new container (or extended existing settings entry point) hosting the WLED panel and leaving room for Phase 19 paint UI per D-20
- `Frontend/src/components/EditorPage.tsx` — add Settings entry point (button/drawer trigger)
- `Frontend/src/store/useStatusStore.ts` — add `wledDevices` field mirroring D-16 payload (stored but not rendered in Phase 17)
- `Frontend/src/hooks/useStatusWS.ts` — parse `wled_devices` from WS payload into the store

### External Docs
- [WLED UDP Realtime docs](https://kno.wled.ge/interfaces/udp-realtime/) — DRGB (byte 2), DNRGB (byte 4) packet formats, port 21324, LED-count thresholds, timeout byte semantics
- [WLED JSON API `/json/info`](https://kno.wled.ge/interfaces/json-api/) — fields `name`, `leds.count` fetched at registration
- [WLED mDNS service type](https://github.com/Aircoookie/WLED/issues/103) — `_wled._tcp.local.`
- [zeroconf PyPI](https://pypi.org/project/zeroconf/) — `AsyncServiceBrowser` usage, version 0.148+

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CaptureRegistry.acquire/release` — coordinator is the sole acquirer; ref-counting semantics unchanged
- `StatusBroadcaster.push_state` + `_UNSET` sentinel — extend with new kwargs for WLED payload (follows Phase 16 D-05/D-06 pattern)
- `color_math.extract_region_color` + `build_polygon_mask` — reuse per-region masking; add a sub-sample helper that produces N sub-colors along the mask's bounding-box longest axis (D-10)
- `httpx` (already in requirements) — used for WLED `/json/info` registration fetch, same pattern as `hue_client.py`
- `hue_client.activate_entertainment_config` / `deactivate_entertainment_config` — keep, move calls inside `HueStreamer`
- `resolve_light_to_channel_map`, `_load_channel_map` logic — move into `HueStreamer`; extend channel-map loading to also emit per-region "required sample count" max(N) for the coordinator
- Settings drawer/modal pattern — if one exists in ui/ already, reuse; otherwise a new component

### Established Patterns
- `CREATE TABLE IF NOT EXISTS` at startup in `database.py` — follow for all three new WLED tables
- Auto-save on dropdown/toggle change (Phase 10 D-05, Phase 16 D-03) — extend to WLED enabled toggle
- `asyncio.to_thread` for blocking syscalls (capture ioctls, DTLS start) — use same for `socket.sendto` batch sends and for zeroconf blocking APIs
- Router prefix pattern `/api/<domain>` — follow with `/api/wled`
- Pydantic request/response models per router (see `routers/cameras.py`) — follow for `routers/wled.py`
- Zustand store extension (not new store) for shared frontend state

### Integration Points
- `main.py` lifespan: replace `app.state.streaming = StreamingService(...)` with `app.state.coordinator = StreamingCoordinator(db, capture_registry, broadcaster)`; coordinator holds `HueStreamer` and `WledStreamer` internally
- `routers/capture.py` `start`/`stop` handlers switch from `request.app.state.streaming` to `request.app.state.coordinator`
- `StreamingCoordinator` exposes the same `state` property and `start(config_id, target_hz)` / `stop()` signatures so downstream consumers (status WS, HA endpoints in Phase 18) don't change
- `routers/wled.py` appended to `main.py` router includes
- Frontend Settings entry point sits alongside the camera selector / light panel on the Editor page

</code_context>

<specifics>
## Specific Ideas

- Class names proposed: `StreamingCoordinator`, `HueStreamer` (was `StreamingService`), `WledStreamer`. Matches the "sibling services" guidance already captured in `CLAUDE.md`.
- Coordinator-to-sink contract per frame: `sink.render(frame_gradients: dict[region_id, list[RGB]]) -> None`. Synchronous call from the coordinator's 60 Hz loop; sinks do any `asyncio.to_thread` internally.
- Per-region gradient sample count `N_region = max(wled_range_width for every wled_channel assigned to region, else 1)` — computed once at stream start, refreshed if assignments change.
- `wled_channels.color` is a **UI display chip color** (like a zone-color swatch in Phase 19), not a streaming color. Streaming color comes from the per-frame region gradient.
- Settings panel houses WLED device CRUD now and WLED paint UI in Phase 19 — one place for everything WLED.
- Zeroconf scan UX: click "Scan network" → 3s spinner → list of discovered devices with an "Add" button next to each; manual IP entry remains the primary path.
- Explicit blackout-then-close on stop (D-13): `WledStreamer.stop()` sends one zeroed DRGB/DNRGB packet per device before closing the socket.

</specifics>

<deferred>
## Deferred Ideas

- **Polygon-path LED mapping** — mapping LEDs to positions along a polygon's perimeter/centerline instead of the bounding-box axis. Future refinement if bounding-box sampling looks wrong on curved regions.
- **User-picks-axis per region** — letting user override the sampling direction per region. Would need a schema column and UI affordance; revisit only if bounding-box heuristic fails.
- **Per-device configurable timeout byte** — currently fixed 2s (D-14). Add a `timeout_seconds` column + UI control only if users report the default is wrong.
- **Rendering per-device WLED health in the UI** — payload shipped in Phase 17 (D-16), visual rendering deferred to Phase 18 or 19.
- **Startup auto-reconnect of WLED devices** — beyond the 30s in-flight auto-disable/resume cycle, no explicit "try on app startup" probe is planned. Devices are discovered as idle rows; first stream start probes them.
- **Per-device start/stop endpoints** — rejected in favor of global start + enabled gate (D-11, D-12). Can revisit if HA use cases in Phase 18 demand fine-grained control.
- **python-wled library** — explicitly rejected per `CLAUDE.md`. Planner must not reintroduce.
- **DDP protocol** — rejected in favor of DNRGB per `CLAUDE.md`. Do not add.

### Reviewed Todos (not folded)
None — STATE.md lists no pending todos.

</deferred>

---

*Phase: 17-wled-backend-and-streaming*
*Context gathered: 2026-04-20*
