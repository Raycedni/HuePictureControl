# Phase 9: Preview Routing and Region API - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Route the preview WebSocket to serve frames from a specific device (not just the global default), expose per-zone camera health status in the existing cameras API, derive `camera_device` as a read-only field on region responses via a join through `entertainment_config_id`, and update frontend TypeScript types/API functions to match the new backend responses.

This phase does NOT add the camera dropdown UI or any new components (Phase 10), nor Docker multi-device config (Phase 11).

</domain>

<decisions>
## Implementation Decisions

### Preview WebSocket Routing
- **D-01:** Preview WebSocket uses read-only peek — calls `registry.get(device_path)` to read frames but does NOT acquire/release (no ref counting). Preview is a passive observer; only streaming sessions own device lifecycle.
- **D-02:** When the requested device is unavailable, the WebSocket stays open and retries every 1 second (same as current behavior). No close-with-error or fallback to a different device.
- **D-03:** The `?device=` param accepts both device paths (`/dev/video0`) and stable IDs (`vid:pid:serial`). If the param looks like a path (starts with `/dev/`), use directly. Otherwise, treat as stable_id and resolve to current device path via `known_cameras` lookup.
- **D-04:** Opening the preview WebSocket WITHOUT `?device=` param returns an error (close the connection). The param is required — no fallback to default device. This is a breaking change for the existing frontend, which Phase 9's frontend type updates will account for.

### Camera Health Endpoint
- **D-05:** Per-zone camera health (CAMA-04) is exposed by extending the existing `GET /api/cameras` response with a `zone_health` section. Each entry is keyed by `entertainment_config_id` and includes `camera_name`, `camera_stable_id`, `connected` boolean, and `device_path`.
- **D-06:** `GET /api/cameras` response adds a top-level `cameras_available: bool` field. When `devices` is empty, this is `false`. Frontend can use this to show a "No cameras detected" banner.

### Region camera_device Field
- **D-07:** `camera_device` is a read-only derived field on `GET /api/regions` responses. It is NOT stored in the `regions` table. The join path is: region -> `entertainment_config_id` (stored on region) -> `camera_assignments` -> `known_cameras.last_device_path`.
- **D-08:** Add `entertainment_config_id` column to the `regions` table (schema migration). This provides a direct link from region to zone, simplifying the join. Keeps it in sync via the existing region creation/update flow.
- **D-09:** `PUT /api/regions/{id}` does NOT accept `camera_device`. Camera assignment is managed exclusively via `PUT /api/cameras/assignments/{config_id}` (Phase 7).

### Frontend API Changes
- **D-10:** Phase 9 updates TypeScript types and API functions only — no new UI components. `Region` interface gains `camera_device: string | null`. `usePreviewWS` hook gains optional `device` parameter for the WebSocket URL.
- **D-11:** No camera dropdown, no new components. Phase 10 handles all UI work.

### Claude's Discretion
- How to handle the `entertainment_config_id` migration for existing regions (nullable column, backfill strategy)
- The exact WebSocket close code when `?device=` is missing
- Whether `zone_health` includes zones with no camera assignment (with a default camera fallback indicator)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Codebase
- `Backend/routers/preview_ws.py` — Current WebSocket using `registry.get_default()`; needs `?device=` routing
- `Backend/routers/regions.py` — Region CRUD; needs `camera_device` derived field in GET, `entertainment_config_id` in schema
- `Backend/routers/cameras.py` — GET /api/cameras response; needs `zone_health` and `cameras_available` extensions
- `Backend/database.py` — Schema definitions; needs `entertainment_config_id` migration on `regions` table
- `Backend/services/capture_registry.py` — CaptureRegistry with `get()`, `acquire()`, `release()` (Phase 8)
- `Backend/services/device_identity.py` — `get_stable_id()` for resolving stable_id to device_path
- `Frontend/src/api/regions.ts` — Region interface and API functions; needs `camera_device` field
- `Frontend/src/hooks/usePreviewWS.ts` — Preview WebSocket hook; needs optional `device` parameter

### Project Docs
- `.planning/REQUIREMENTS.md` — MCAP-02, CAMA-04 requirements
- `.planning/ROADMAP.md` — Phase 9 success criteria
- `.planning/phases/07-device-enumeration-and-camera-assignment-schema/07-CONTEXT.md` — DB schema decisions (D-07 through D-09)
- `.planning/phases/08-capture-registry/08-CONTEXT.md` — Registry lifecycle decisions (D-01 through D-11)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CamerasResponse` Pydantic model in `cameras.py` — extend with `zone_health` and `cameras_available` fields
- `_scan_devices()` helper in `cameras.py` — already returns connected/disconnected info per device
- `camera_assignments` and `known_cameras` tables — Phase 7 schema provides the join path for derived `camera_device`
- `light_assignments` table — maps region_id to channel_id and entertainment_config_id (alternative join path, but D-08 adds direct column)

### Established Patterns
- `app.state.capture_registry` for registry access (Phase 8)
- `db.row_factory = aiosqlite.Row` for dict-like row access
- ALTER TABLE migration with try/except in `database.py` for backward-compatible schema changes
- Pydantic `BaseModel` for request/response models in routers

### Integration Points
- `preview_ws.py` — add query param parsing, device resolution, registry.get() call
- `regions.py` — modify list_regions SQL to JOIN camera_assignments + known_cameras
- `cameras.py` — extend CamerasResponse model, add zone_health query in list_cameras
- `database.py` — add entertainment_config_id column to regions table
- `Frontend/src/api/regions.ts` — update Region interface
- `Frontend/src/hooks/usePreviewWS.ts` — add device URL param

</code_context>

<specifics>
## Specific Ideas

- Preview WebSocket `?device=` must accept both `/dev/videoN` paths and stable IDs — check prefix to determine which, then resolve stable_id via known_cameras lookup
- `cameras_available: false` flag enables a "No cameras detected" banner in the frontend
- `entertainment_config_id` on regions table is a direct foreign key to simplify the join, replacing the indirect path through light_assignments
- Preview WebSocket without `?device=` is an error (breaking change) — frontend type updates in this phase prepare for Phase 10's component wiring

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 09-preview-routing-and-region-api*
*Context gathered: 2026-04-05*
