# Phase 18: Home Assistant Control Endpoints - Context

**Gathered:** 2026-05-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Backend adds a thin Home Assistant control surface on top of the existing `StreamingCoordinator`:

1. **Control endpoints** — start, stop, status of the streaming pipeline, callable from Home Assistant's `rest_command:` integration.
2. **Selection endpoints** — let HA pick the entertainment zone and camera that the next `/api/ha/start` will use, persisted across backend restarts.
3. **Discovery endpoints** — HA-stable lists of available zones and cameras, decoupled from the internal `/api/cameras` and `/api/hue/configs` payload shapes.
4. **Status payload** — curated, machine-readable JSON with friendly names resolved server-side, plus both currently-active and HA-pending selections.

Explicitly out of scope:
- Web UI for HA settings (HA is API-only; the web UI is unchanged).
- Outbound calls from HuePictureControl to Home Assistant (HA → HPC direction only; no HA token storage — per `CLAUDE.md`).
- Authentication or per-caller authorization on HA endpoints (consistent with rest of API; LAN is trust boundary).
- Documentation / HA YAML snippets (potential follow-up; not in this phase).

</domain>

<decisions>
## Implementation Decisions

### Endpoint shape

- **D-01:** Five separate verb endpoints in a new `routers/ha.py` (prefix `/api/ha`, tag `ha`):
  - `POST /api/ha/start` — empty body
  - `POST /api/ha/stop` — empty body
  - `GET  /api/ha/status` — curated JSON (see D-09)
  - `PUT  /api/ha/zone` — body `{zone_id: string}`
  - `PUT  /api/ha/camera` — body `{stable_id: string}`
  - `GET  /api/ha/zones` — discovery wrapper (D-11)
  - `GET  /api/ha/cameras` — discovery wrapper (D-11)
  Each verb gets its own URL — cleanest fit for HA's `rest_command` (one URL per command) and mirrors the existing `/api/capture/start` convention.

- **D-02:** Selectors use **PUT with JSON body**. Idempotent, matches the existing `PUT /api/cameras/assignments/{config_id}` convention, body-first uniform with the rest of the API.

- **D-03:** `POST /api/ha/start` is **strict** — accepts an empty body and uses whatever is currently in `ha_state` (D-04). HA performs `PUT /api/ha/zone` (and optionally `PUT /api/ha/camera`) before calling `/start`. Two-call pattern; each endpoint has one job. No inline `target_hz` override in this phase — coordinator default (60 Hz) applies.

### Selection persistence

- **D-04:** New single-row table:
  ```sql
  CREATE TABLE IF NOT EXISTS ha_state (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      active_config_id TEXT,
      active_camera_stable_id TEXT,
      updated_at TEXT
  );
  ```
  Added in `database.py` next to the existing `CREATE TABLE IF NOT EXISTS` blocks. Single-row constraint enforced via `CHECK (id = 1)` per existing conventions; all writes are `INSERT OR REPLACE` against `id = 1`.

- **D-05:** Row creation is **lazy** — no eager seed insert at schema creation. The first `PUT /api/ha/zone` or `PUT /api/ha/camera` does `INSERT OR REPLACE`. `GET /api/ha/status` and `POST /api/ha/start` tolerate the missing row (treat as NULL fields).

- **D-06:** `PUT /api/ha/zone {zone_id}` semantics:
  1. Validate `zone_id` exists in `entertainment_configs` → 404 otherwise.
  2. `INSERT OR REPLACE` into `ha_state`, setting `active_config_id = zone_id`, preserving `active_camera_stable_id` if already set, updating `updated_at`.
  3. **If** `ha_state.active_camera_stable_id` is non-null after the write, **also** write `camera_last_zone[active_camera_stable_id] = zone_id` in the same transaction so the web UI sees HA's zone pre-selected on next reload (per Phase 16 D-04 + Phase 17 D-10 "most-recently-touched camera" pattern).
  4. If `active_camera_stable_id` is NULL, **skip** the `camera_last_zone` write — UI sync only happens when HA has picked both zone and camera.

- **D-07:** `PUT /api/ha/camera {stable_id}` semantics:
  1. Validate `stable_id` exists in `known_cameras` → 404 otherwise.
  2. `INSERT OR REPLACE` into `ha_state`, setting `active_camera_stable_id = stable_id`, preserving `active_config_id`, updating `updated_at`.
  3. **Does NOT touch `camera_assignments`.** HA's camera choice is global-to-HA, decoupled from the per-zone UI assignment. The web UI's per-zone camera dropdown is unaffected.

- **D-08:** `POST /api/ha/start` preconditions and resolution order:
  1. **Precondition:** `ha_state.active_config_id` must be non-null → `400 "no zone selected"` otherwise.
  2. **Zone validation:** `active_config_id` must still exist in `entertainment_configs` → `404 "zone not found"` (zone may have been deleted on the Bridge after HA's last PUT).
  3. **Camera resolution chain** (existing coordinator behavior preserved):
     a. If `ha_state.active_camera_stable_id` is set → resolve `device_path` via `known_cameras.last_device_path`.
     b. Else fall back to `camera_assignments[active_config_id]` (existing `StreamingCoordinator._resolve_device_path` path).
     c. Else fall back to the default `CAPTURE_DEVICE` env var.
  4. Call `coordinator.start(active_config_id)`.
  5. **Idempotency** (Claude's Discretion below): if already streaming, return `200` no-op (coordinator already no-ops in non-idle states).

### Status & discovery

- **D-09:** `GET /api/ha/status` returns a **curated HA-friendly flat JSON subset** with friendly names resolved server-side so HA template sensors don't need joins:
  ```json
  {
    "state": "idle|starting|streaming|stopping|error|reconnecting",
    "active_config_id": "..." | null,
    "active_config_name": "TV-Bereich" | null,
    "active_camera_stable_id": "..." | null,
    "active_camera_name": "..." | null,
    "active_device_path": "/dev/video0" | null,
    "fps": 60,
    "latency_ms": 12.3,
    "ha_selected_config_id": "..." | null,
    "ha_selected_config_name": "..." | null,
    "ha_selected_camera_stable_id": "..." | null,
    "ha_selected_camera_name": "..." | null,
    "bridge_paired": true
  }
  ```
  Stable contract — does NOT leak internal `StatusBroadcaster._metrics` shape changes (e.g. `packets_sent`, `seq`, `wled_devices`). Friendly names resolved by joining: `active_config_*` from a `/api/hue/configs` lookup keyed by the active config id; `active_camera_*` from `known_cameras` keyed by reverse lookup of `active_device_path` (or the cached resolution from D-08).

- **D-10:** Both currently-active and HA-pending fields exposed in status:
  - `active_*` mirrors the broadcaster's `_metrics` (what is actually streaming right now). NULL when idle.
  - `ha_selected_*` always reads from `ha_state` (what the next `/api/ha/start` will use). NULL when row absent.
  HA dashboards can show "will start with X" before `/start` fires; ops dashboards can show "currently streaming Y".

- **D-11:** Two dedicated discovery wrappers, decoupled from internal API shape:
  - `GET /api/ha/cameras` → `[{stable_id, name, connected}]`. Reuses `routers/cameras.py::_scan_devices` + `known_cameras` query; emits only the three fields HA needs (no `last_seen_at`, `last_entertainment_config_id`, `identity_mode`, `zone_health`).
  - `GET /api/ha/zones` → `[{id, name}]`. Reuses `services/hue_client.py::list_entertainment_configs` and projects only `{id, name}`.
  Lets us evolve `/api/cameras` and `/api/hue/configs` freely without breaking HA scripts.

### Claude's Discretion

- **Idempotency:** `POST /api/ha/start` when state is not `idle`/`error` → `200` no-op (coordinator already no-ops). `POST /api/ha/stop` when state is `idle` → `200` no-op (coordinator already no-ops). Both return the current `status` payload (D-09) in the response body so HA gets immediate post-action state.
- **HTTP status map:**
  - `400` — precondition missing (`/start` with no zone in `ha_state`)
  - `404` — unknown zone (not in `entertainment_configs`), unknown camera (not in `known_cameras`)
  - `502` — Hue bridge HTTP error during `/api/ha/zones` resolution
  - `503` — Hue bridge unpaired or unreachable during `/start` or `/api/ha/zones`
- **Coordinator access pattern:** Follow Phase 17 `routers/wled.py` convention — `getattr(request.app.state, "coordinator", None)` so tests can omit the coordinator wiring and exercise CRUD/status paths only.
- **Pydantic model naming:** Follow `routers/cameras.py` and `routers/wled.py` style — `HaZoneRequest`, `HaCameraRequest`, `HaStatusResponse`, `HaCameraListResponse`, `HaZoneListResponse`. All in `routers/ha.py`; no separate `models/ha.py` unless cross-router reuse emerges.
- **Friendly-name resolution caching:** For each `/api/ha/status` call we hit the Hue Bridge once for `list_entertainment_configs` (already cached at the bridge for short windows). If this proves expensive under HA polling, add a 5s in-memory cache in a follow-up — not for this phase.
- **Status payload error field:** If broadcaster `_metrics["error"]` is set, surface it as `status.error: string` (additive field — HA template sensors can ignore it). Otherwise omit.
- **Test strategy:** Unit tests per endpoint (mock coordinator + mock DB). One integration test that wires a real `StreamingCoordinator` with mocked sinks and walks `PUT zone → PUT camera → POST start → GET status → POST stop`. Follow Phase 17 Plan 09 E2E pattern.
- **OpenAPI:** `tags=["ha"]` on the router. No special documentation generation in this phase.

### Folded Todos

None — STATE.md lists no pending todos.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & Project
- `.planning/ROADMAP.md` §Phase 18 — five success criteria for HA control endpoints (HASS-01..05)
- `.planning/PROJECT.md` §Active (v1.3) — HA REST endpoints bullet
- `.planning/PROJECT.md` §Constraints — "No auth: Web UI is unauthenticated — local network tool only" (applies to HA endpoints too)
- `.planning/STATE.md` §Accumulated Context → Decisions — `[v1.3 roadmap]: HA endpoints are unauthenticated thin adapters over the existing StreamingCoordinator — no new auth layer`

### Prior Phase Contexts (must-read)
- `.planning/phases/17-wled-backend-and-streaming/17-CONTEXT.md` — `StreamingCoordinator` API surface (state property, start/stop signatures), `StatusBroadcaster._metrics` extensions, "coordinator exposes the same `state` property and `start(config_id, target_hz)` / `stop()` signatures so downstream consumers (status WS, HA endpoints in Phase 18) don't change" (17-CONTEXT.md §Integration Points)
- `.planning/phases/16-zone-persistence-bug-fixes/16-CONTEXT.md` — `active_config_id`/`active_device_path` payload convention, `push_state` `_UNSET` kwarg semantics, `camera_last_zone` schema (D-02/D-04), "most-recently-touched camera" heuristic (D-10)

### Project Convention / Research
- `CLAUDE.md` §"Integration Points with Existing Code" — confirms `routers/ha.py` is a new file; HA control endpoints under `/api/ha/...`
- `CLAUDE.md` §"Home Assistant REST API (Inbound)" — HA → HPC direction only; no HA token stored; user configures `rest_command:` in their `configuration.yaml`
- `CLAUDE.md` §"Alternatives Considered" — `HA calls HuePictureControl (rest_command)` over `HuePictureControl calls HA REST API`; reason: no secret management burden
- `CLAUDE.md` §"What NOT to Use" — "Storing HA long-lived access token in HuePictureControl"; reason: violates no-auth local tool design

### Backend Files (modify)
- `Backend/database.py` — add `CREATE TABLE IF NOT EXISTS ha_state` block (D-04) alongside the existing tables
- `Backend/main.py` — append `app.include_router(ha.router)` in the router includes block

### Backend Files (new)
- `Backend/routers/ha.py` — new router with the seven endpoints (D-01, D-09, D-11). Reuses `services/hue_client.list_entertainment_configs` and `routers/cameras._scan_devices` patterns.

### Backend Files (read-only reference)
- `Backend/services/streaming_coordinator.py` — entry point for `/start` and `/stop` calls; `_resolve_device_path` is the existing camera-resolution chain D-08 extends
- `Backend/services/status_broadcaster.py` — source for `active_*` fields in status payload (`_metrics` dict)
- `Backend/services/hue_client.py` — `list_entertainment_configs(bridge_ip, username)` used by `/api/ha/zones`
- `Backend/routers/cameras.py` — `_scan_devices`, `known_cameras` query pattern, `camera_last_zone` write pattern (PUT /api/cameras/last-zone)
- `Backend/routers/wled.py` — `getattr(request.app.state, "coordinator", None)` test-tolerance pattern, Pydantic model conventions
- `Backend/routers/capture.py` — `coordinator.start`/`coordinator.stop` wiring template

### External Docs
- [Home Assistant REST API developer docs](https://developers.home-assistant.io/docs/api/rest/) — bearer-token format (used by HA-as-server, not us); confirms `rest_command:` is the right HA-side integration
- Home Assistant `rest_command:` integration docs — confirms HA can POST/PUT/GET with JSON bodies and capture responses (no payload-shape constraints from HA side)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app.state.coordinator` — `StreamingCoordinator` instance. Has `.start(config_id, target_hz)`, `.stop()`, `.state` (string: `idle|starting|streaming|stopping|error|reconnecting`). HA `/start` and `/stop` delegate here.
- `app.state.broadcaster._metrics` — source of truth for `active_*` fields in HA status (already populated by coordinator per Phase 16/17 D-05/D-06).
- `services.hue_client.list_entertainment_configs(bridge_ip, username)` — returns the list HA's `/api/ha/zones` projects to `[{id, name}]`. Already used by `/api/hue/configs`.
- `routers.cameras._scan_devices()` + `known_cameras` table — fresh device scan + persisted identity. HA's `/api/ha/cameras` reuses this without duplicating logic; consider extracting a helper if the projection differs enough.
- `database.py` `CREATE TABLE IF NOT EXISTS` pattern — D-04's `ha_state` table follows the established schema-on-startup convention.
- `routers.wled.py` `_coord_health` helper pattern — `getattr(request.app.state, "coordinator", None)` for test tolerance. Reuse the pattern (not the helper).
- Pydantic request/response models per router (see `routers/cameras.py`, `routers/wled.py`) — same style.

### Established Patterns
- `INSERT OR REPLACE` upserts for single-row config tables (mirrors `bridge_config` in `routers/hue.py`).
- 503 for "Bridge not paired" — already returned by `/api/hue/configs` (`HTTPException(400, "Bridge not paired")` today; planner should align — possibly bump to 503 for consistency with HA-friendly semantics, but keep `/api/hue/configs` unchanged).
- `asyncio.to_thread` for blocking syscalls (device scans, ioctl) — `/api/ha/cameras` inherits this from `_scan_devices`.
- Router prefix pattern `/api/<domain>` and `tags=["<domain>"]` — `/api/ha`, `tags=["ha"]`.
- Per-router file under `Backend/routers/<name>.py`, wired in `main.py`'s router-include block.

### Integration Points
- `Backend/main.py` lifespan: no new app.state attributes — HA endpoints use the existing `coordinator`, `broadcaster`, and `db`.
- `Backend/main.py` router includes: append `app.include_router(ha.router)`.
- `Backend/database.py`: add `CREATE TABLE IF NOT EXISTS ha_state` next to existing table creates.
- No frontend changes. The web UI is unaware of HA. The "Synced" sub-decision (D-06) means HA's zone choice surfaces in the UI via the existing `camera_last_zone` → frontend 3-tier cascade — no new frontend code needed.
- No changes to `StreamingCoordinator`, `HueStreamer`, `WledStreamer`, `StatusBroadcaster` internals — Phase 17 deliberately shaped these for HA consumption.

</code_context>

<specifics>
## Specific Ideas

- HA's `rest_command:` example (illustrative, NOT shipped this phase):
  ```yaml
  rest_command:
    hpc_start:
      url: "http://hpc.local:8000/api/ha/start"
      method: POST
    hpc_stop:
      url: "http://hpc.local:8000/api/ha/stop"
      method: POST
    hpc_select_zone:
      url: "http://hpc.local:8000/api/ha/zone"
      method: PUT
      content_type: "application/json"
      payload: '{"zone_id": "{{ zone }}"}'
  ```
- HA can keep zone & camera as `input_select` helpers, mapped to the IDs returned by `/api/ha/zones` and `/api/ha/cameras`.
- "Synced" zone sub-decision (D-06) lets a single HA automation drive the system AND have the web UI reflect HA's choice when the user opens it next — important if the user uses HA as primary control surface and the web UI for occasional reconfiguration.
- Status response includes `error` only when present (D-09 Claude's Discretion) — keeps the happy-path payload compact for HA template sensors.

</specifics>

<deferred>
## Deferred Ideas

- **HA YAML snippet documentation** — full `configuration.yaml` examples, `input_select` mappings, template sensor recipes. Belongs in a docs phase, not Phase 18 backend.
- **`/api/ha/restart` convenience endpoint** — HA can chain `/stop` then `/start` easily; no value in a combined verb.
- **Inline body on `/start`** (zone/camera overrides) — explicitly rejected (D-03). Revisit only if HA users report friction with the two-call pattern.
- **`target_hz` tuning via `/start` body** — explicitly out of this phase. Add a separate `PUT /api/ha/target_hz` later if anyone asks.
- **HA WebSocket push for status changes** — HA's REST polling (10–30s) is sufficient for ambient lighting telemetry. Adding HA WS surface multiplies test complexity for marginal latency win.
- **Per-device WLED health in `/api/ha/status`** — `broadcaster._metrics["wled_devices"]` exists (Phase 17 D-16) but HA exposure deferred to Phase 19 or a follow-up; HA status stays Hue-coordinator-centric.
- **Live device probing in `/api/ha/cameras`** — current `_scan_devices` is on-demand (matches `/api/cameras`); HA users opt into cost by calling the endpoint.
- **Friendly-name caching layer** for `/api/ha/status` — only add if HA polling overwhelms the Hue Bridge's `list_entertainment_configs` cache.
- **HA long-lived access token storage in HPC** — explicitly rejected per `CLAUDE.md`. Direction stays HA → HPC.
- **Authentication on HA endpoints** — out of scope; LAN trust boundary per PROJECT.md.

### Reviewed Todos (not folded)

None — STATE.md lists no pending todos.

</deferred>

---

*Phase: 18-home-assistant-control-endpoints*
*Context gathered: 2026-05-11*
