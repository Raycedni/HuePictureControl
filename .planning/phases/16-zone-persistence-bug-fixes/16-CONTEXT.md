# Phase 16: Zone Persistence Bug Fixes - Context

**Gathered:** 2026-04-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix two reload-time defects in the zone/camera dropdowns:

1. **BFIX-01** — After page reload, the entertainment config selection persists per camera. Switching cameras pre-selects the last zone that camera was used with.
2. **BFIX-02** — When another tab is already streaming, the dropdown on a freshly opened tab reflects the actual streaming state instead of a stale default.

This phase does **not** add new capabilities: no new UI affordances, no HA control, no WLED support. It extends existing schemas, endpoints, and components minimally to eliminate the two defects. Phase 17+ (WLED, HA) depend on a clean streaming-state surface, which this phase incidentally provides.

</domain>

<decisions>
## Implementation Decisions

### Persistence (Area 1)
- **D-01:** Persistence lives in the backend DB — authoritative across tabs/devices. No `localStorage` usage. Keeps the project's "zero client-side state" convention.
- **D-02:** A **new `camera_last_zone` table** holds the mapping. Schema: `(camera_stable_id TEXT PRIMARY KEY, entertainment_config_id TEXT NOT NULL, updated_at TEXT NOT NULL)`. Kept separate from `camera_assignments` (which encodes zone→camera); this one encodes camera→zone. Two tables, two concerns, no conflation.
- **D-03:** Auto-save on every zone-dropdown change — consistent with Phase 10 D-05 (camera auto-save). No explicit save button, no debounce needed for this rate.
- **D-04:** Write endpoint: `PUT /api/cameras/last-zone/{stable_id}` with body `{ "entertainment_config_id": "..." }`. Read piggybacks on `GET /api/cameras`: each device in the response gets a `last_entertainment_config_id: string | null` field (null when never set).

### Streaming State Surface (Area 2)
- **D-05:** Extend `/ws/status` to include the active streaming config. Both the initial snapshot on `connect()` and every `push_state()` carry it. No new REST endpoint in this phase (HA Phase 18 will add one if needed).
- **D-06:** Payload additions: `active_config_id: string | null` and `active_device_path: string | null`. Values populated during `starting`, `streaming`, `reconnecting`; `null` when state is `idle` or `error`.
- **D-07:** When `active_config_id` is non-null on page load, the zone dropdown pre-selects that value. Selector is **disabled** while `isStreaming` (existing LightPanel pattern — no scope creep into live zone switching).

### Camera ↔ Zone Direction (Area 3)
- **D-08:** Bidirectional association with "last touched wins":
  - Zone change → look up `camera_assignments[zone]` to derive camera (existing Phase 10 D-06).
  - Camera change → look up `camera_last_zone[camera]` to derive zone (new in this phase).
- **D-09:** On initial page load (not streaming):
  1. Pick the **most-recently-touched camera** (see D-10).
  2. Look up that camera's last zone via `camera_last_zone`.
  3. If no record exists, fall back to the first available config (preserves Phase 10 behavior for fresh installs).
- **D-10:** "Most-recently-touched camera" is tracked by an app-level last-used marker. **Reuse `known_cameras.last_seen_at`** (already exists) — update it on every camera-dropdown change in addition to the current update-on-enumeration. No new table needed.
- **D-11:** Active streaming (D-07) **overrides** both D-09 defaults on load. If the system is streaming on mount, the dropdowns reflect that, not persisted preferences.

### Claude's Discretion (Reconciliation edge cases)
- If the stored `entertainment_config_id` no longer exists on the bridge (config deleted), silently fall back to the first available config on load and clear the stale row.
- If the stored `camera_stable_id` is not in `known_cameras`, ignore the row.
- Debounce/rate-limit considerations: a single write per zone-change event is fine — no need to throttle.
- Exact SQL upsert form for `camera_last_zone` (INSERT OR REPLACE vs explicit UPSERT).
- Whether to add a migration step or rely on `CREATE TABLE IF NOT EXISTS` at startup (existing pattern in `database.py`).
- Whether the frontend reads `last_entertainment_config_id` from `useCameras` directly or via a new derived selector.

### Folded Todos
None — no matching todos in backlog.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & Project
- `.planning/ROADMAP.md` §Phase 16 — success criteria for BFIX-01/BFIX-02
- `.planning/PROJECT.md` §Active (v1.3) — the two bullets on zone persistence
- `.planning/RETROSPECTIVE.md` — v1.1 lesson: keep requirements traceability in sync during execution

### Prior Phase Contexts (must-read)
- `.planning/milestones/v1.1-phases/10-frontend-camera-selector/10-CONTEXT.md` — Phase 10 D-05 (auto-save), D-06 (zone→camera), D-07 (no auto-select), D-10 (disconnected state). This phase **extends** D-06 with the inverse direction.
- `.planning/milestones/v1.1-phases/09-preview-routing-and-region-api/09-CONTEXT.md` — `zone_health`, `usePreviewWS` device param
- `.planning/milestones/v1.1-phases/07-device-enumeration-and-camera-assignment-schema/07-CONTEXT.md` — `camera_stable_id` identity model, `known_cameras` schema
- `.planning/milestones/v1.1-phases/08-capture-registry/08-CONTEXT.md` — capture lifecycle (unchanged here)

### Backend Files (modify)
- `Backend/database.py` §60-86 — add `camera_last_zone` `CREATE TABLE IF NOT EXISTS` block alongside existing tables
- `Backend/routers/cameras.py` — add `PUT /api/cameras/last-zone/{stable_id}`; extend `GET /api/cameras` response to include `last_entertainment_config_id` per device and update `last_seen_at` on PUT of last-zone
- `Backend/services/status_broadcaster.py` — extend `_metrics` dict with `active_config_id`/`active_device_path`; accept them in `update_metrics`/`push_state`
- `Backend/services/streaming_service.py` §87-121, 228-230 — pass `active_config_id` and `active_device_path` into `push_state` calls during starting/streaming/reconnecting; clear on stop/error
- `Backend/routers/streaming_ws.py` — no changes needed (endpoint unchanged; payload shape changes)

### Frontend Files (modify)
- `Frontend/src/components/LightPanel.tsx` §47-77 — replace "pick `cfgs[0].id` if empty" with: (a) if streaming, use active_config_id; else (b) derive from selected camera's last-zone; else (c) fallback to first config
- `Frontend/src/components/LightPanel.tsx` §79-96 — `handleCameraChange` must also PUT the new last-zone pairing when changing camera AND persist current zone, or leave zone as-is and let the camera→zone auto-switch fire
- `Frontend/src/components/EditorPage.tsx` §12-13 — keep state lifting; initial state must account for async cameras/status loading (no more `''` default trigger)
- `Frontend/src/store/useStatusStore.ts` — add `activeConfigId: string | null` field
- `Frontend/src/hooks/useStatusWS.ts` §17-25 — parse new fields into `setMetrics`
- `Frontend/src/api/cameras.ts` — add `lastEntertainmentConfigId` to `CameraDevice` type; add `putLastZone(stableId, configId)` API
- `Frontend/src/api/cameras.test.ts` — extend mock responses
- `Frontend/src/components/LightPanel.test.tsx` — cover: reload with persisted zone, reload during streaming, camera switch restores last zone, missing stored config falls back cleanly

### External Docs
No external specs — the two requirements fully define behavior.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `StatusBroadcaster._metrics` dict and `push_state`/`update_metrics` methods — extensible; just add keys
- `StreamingService._config_id` / `_device_path` — already tracked internally; just need to route through to broadcaster
- `camera_assignments` PUT endpoint (Phase 10) — template for the new `PUT /api/cameras/last-zone/{stable_id}`
- `known_cameras.last_seen_at` — reuse for "most-recently-touched" tracking rather than a new column
- `useStatusStore` + `useStatusWS` — trivial extension for `activeConfigId`
- `CamerasResponse.devices[]` pattern — add one field, frontend consumes it

### Established Patterns
- `CREATE TABLE IF NOT EXISTS` at startup for all schema (not Alembic); follow this for `camera_last_zone`
- Auto-save on dropdown change via PUT (Phase 10 D-05); extend to zone dropdown
- `push_state` for instant broadcast on state transitions; `update_metrics` for rate-limited heartbeat — keep both semantics
- Zustand for shared frontend state; don't add a new store — extend `useStatusStore`
- `disabled={isStreaming}` on the Zone `<select>` already exists — keep it; it enforces D-07

### Integration Points
- `LightPanel` receives `activeConfigId` from status store, uses it to override initial selection
- `EditorPage` continues to own `selectedConfigId`/`selectedDevice`; initial values derive async from `camerasData` + status snapshot
- `StreamingService.start()` must call `broadcaster.push_state("starting", active_config_id=config_id, active_device_path=device_path)` — new optional kwargs on push_state
- `_run_loop` cleanup must `push_state("idle", active_config_id=None, active_device_path=None)`

</code_context>

<specifics>
## Specific Ideas

- New DB table name: `camera_last_zone` (not `camera_zone_history` — no history semantics needed; just last)
- API path shape: `/api/cameras/last-zone/{stable_id}` (hyphenated; mirrors `/api/cameras/assignments/{config_id}`)
- Status payload field names: `active_config_id`, `active_device_path` (snake_case, consistent with existing `latency_ms`, `packets_sent`)
- Frontend field on `CameraDevice`: `last_entertainment_config_id: string | null`
- Zustand field: `activeConfigId: string | null` (camelCase, matches existing store fields)
- Load-time dropdown resolution order (most to least authoritative): streaming state > camera's last_zone > first config
- Bidirectional rule phrased simply: "whichever dropdown the user just touched wins; the other follows."

</specifics>

<deferred>
## Deferred Ideas

- **Live zone-switch while streaming** — user can already stop+restart manually; live switch is a UX improvement, out of bug-fix scope. Candidate for a future polish phase.
- **REST `GET /api/capture/status`** — not needed for the UI fix (WS is enough). Phase 18 (HA endpoints) will add it as part of that phase's status endpoint.
- **Camera `last_selected_at` on `camera_assignments`** — considered but rejected in favor of the dedicated `camera_last_zone` table. If later we need to query "all zones a camera was ever used with", we can revisit.
- **`localStorage` write-through cache** — not implemented. Revisit only if reload-flicker proves visible; measure first.
- **Tracking per-user last-active pair as a single unit** — rejected; per-camera memory is what the roadmap crit calls for.

### Reviewed Todos (not folded)
None — `STATE.md` lists no pending todos.

</deferred>

---

*Phase: 16-zone-persistence-bug-fixes*
*Context gathered: 2026-04-18*
