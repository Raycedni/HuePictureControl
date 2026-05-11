# Phase 18: Home Assistant Control Endpoints - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-11
**Phase:** 18-home-assistant-control-endpoints
**Areas discussed:** Endpoint shape, Selection persistence, Status & discovery

---

## Endpoint shape

### Q1 — How should HA endpoints be organized?

| Option | Description | Selected |
|--------|-------------|----------|
| Separate verb endpoints | POST /api/ha/start, POST /api/ha/stop, GET /api/ha/status, PUT /api/ha/zone, PUT /api/ha/camera. One URL per HA `rest_command`. | ✓ |
| Unified control endpoint | POST /api/ha/control with body `{action, zone?, camera?}`. One URL, action discriminator. | |
| RESTful resources | POST /api/ha/streaming `{state: 'running'\|'stopped'}`, PATCH /api/ha/streaming `{zone, camera}`, GET /api/ha/streaming. | |

**User's choice:** Separate verb endpoints (Recommended)
**Notes:** Maps cleanly to HA's `rest_command` integration and mirrors the existing `/api/capture/start` convention.

### Q2 — How should zone and camera be selected via HA?

| Option | Description | Selected |
|--------|-------------|----------|
| PUT with JSON body | `PUT /api/ha/zone {zone_id}`; `PUT /api/ha/camera {stable_id}`. Matches `PUT /api/cameras/assignments/{config_id}` convention. | ✓ |
| Path parameter | `PUT /api/ha/zone/{zone_id}` and `PUT /api/ha/camera/{stable_id}`. Encoding risk for Windows `stable_id`. | |
| Query parameter on POST | `POST /api/ha/zone?zone_id=...`. Simpler YAML but breaks body-first convention. | |

**User's choice:** PUT with JSON body (Recommended)

### Q3 — Should `POST /api/ha/start` accept an inline zone/camera body to set-and-start in one call?

| Option | Description | Selected |
|--------|-------------|----------|
| Strict — empty body | `/start` uses whatever's in `ha_state`. HA must PUT zone (and optionally camera) first. Two-call pattern. | ✓ |
| Inline override | Body `{zone_id?, camera_stable_id?, target_hz?}` — provided fields override and persist. One-call pattern. | |
| Only target_hz | Body `{target_hz?: int}`. Selection still requires PUT. Middle ground. | |

**User's choice:** Strict — empty body (Recommended)
**Notes:** Clean separation of concerns; each endpoint has one job. No `target_hz` plumbing in this phase.

---

## Selection persistence

### Q1 — Where does HA's currently selected zone live?

| Option | Description | Selected |
|--------|-------------|----------|
| New `ha_state` table | Single-row table `ha_state(id=1, active_config_id, active_camera_stable_id, updated_at)`. Persists across restart. | ✓ |
| In-memory only | `app.state.ha_state = {...}`. No schema change. Lost on backend restart. | |
| Reuse `camera_last_zone` heuristic | Derive HA-active zone from `camera_last_zone[ha_active_camera]`. No new table; ambiguous when no camera picked. | |

**User's choice:** New `ha_state` table (Recommended)

### Q2 — Should HA's selection affect what the web UI shows pre-selected on reload?

| Option | Description | Selected |
|--------|-------------|----------|
| Independent | HA state and UI state are separate. PUT /api/ha/zone does NOT change UI pre-selection. | |
| Synced | PUT /api/ha/zone also updates `camera_last_zone` so the UI sees HA's choice on next reload. | ✓ |

**User's choice:** Synced
**Notes:** User wants HA's zone choice visible in the UI on next load — single source of truth for the operator. Introduces an ambiguity (which `camera_stable_id` to update) resolved in the follow-up below.

### Q3 — Camera selection scope: per-zone like UI, or global?

| Option | Description | Selected |
|--------|-------------|----------|
| Global to HA | `PUT /api/ha/camera` writes only `ha_state.active_camera_stable_id`. Doesn't touch `camera_assignments`. UI unaffected. | ✓ |
| Per-zone like UI | `PUT /api/ha/camera` writes to `camera_assignments` for the HA-active zone. Reuses existing schema; HA mutates UI. | |

**User's choice:** Global to HA (Recommended)
**Notes:** HA's camera choice is decoupled from the per-zone UI assignment. Asymmetric with the "Synced" zone behavior — intentional: zone sync gives the operator UI visibility; camera stays HA-internal to avoid stomping on per-zone UI configuration the user may have set deliberately.

### Q4 — Sync rule: when HA hasn't picked a camera yet, which row gets the `camera_last_zone` update?

| Option | Description | Selected |
|--------|-------------|----------|
| Only sync when HA camera set | Update `camera_last_zone[ha_state.active_camera_stable_id]` only when both zone and camera are set. | ✓ |
| Most-recently-touched camera | Use the Phase 17 D-10 heuristic (MAX(`last_seen_at`) in `known_cameras`). | |
| Sync to every known camera | Write `camera_last_zone` for every row. Maximum UI visibility, overwrites per-camera history. | |

**User's choice:** Only sync when HA camera set (Recommended)

### Q5 — Start precondition: what does `POST /api/ha/start` do when `ha_state.active_config_id` is NULL?

| Option | Description | Selected |
|--------|-------------|----------|
| 400 "no zone selected" | Strict. HA must PUT `/api/ha/zone` first. Surfaces broken HA scripts immediately. | ✓ |
| Fall back to first `/api/hue/configs` entry | Best-effort. Opaque default. | |
| Fall back to most-recent `camera_last_zone` | Inherits UI's most recent zone. | |

**User's choice:** 400 "no zone selected" (Recommended)

### Q6 — When does the single `ha_state` row get created?

| Option | Description | Selected |
|--------|-------------|----------|
| Lazy on first write | INSERT OR REPLACE on first PUT. No seed at CREATE TABLE. Status tolerates absent row. | ✓ |
| Eager at schema creation | INSERT OR IGNORE seed row at CREATE TABLE. Always exists with NULLs. | |

**User's choice:** Lazy on first write (Recommended)

---

## Status & discovery

### Q1 — What does `GET /api/ha/status` return?

| Option | Description | Selected |
|--------|-------------|----------|
| Curated HA-friendly subset | Flat JSON with friendly names resolved server-side. Stable contract. | ✓ |
| Full `_metrics` passthrough | StatusBroadcaster `_metrics` verbatim + `ha_state` appended. Less code, leaks internal shape. | |
| Tiered (`?verbose=true` expands) | Curated by default, full on opt-in. Two contracts to maintain. | |

**User's choice:** Curated HA-friendly subset (Recommended)

### Q2 — Should HA-specific discovery endpoints (cameras list, zones list) be exposed?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — dedicated `/api/ha/cameras` and `/api/ha/zones` | Thin wrappers projecting minimal fields. Decouple HA from internal API evolution. | ✓ |
| No — HA users call existing endpoints | Zero new code; couples HA to internal payload shapes. | |

**User's choice:** Yes — dedicated `/api/ha/cameras` and `/api/ha/zones` (Recommended)

### Q3 — How should status reflect HA's pending selection vs what's currently streaming?

| Option | Description | Selected |
|--------|-------------|----------|
| Both fields exposed | `active_*` (broadcaster) AND `ha_selected_*` (ha_state). HA dashboards can show "will start with X". | ✓ |
| Only currently-active | Only broadcaster's `active_*` fields. Pending selection requires inference. | |

**User's choice:** Both fields exposed (Recommended)

---

## Claude's Discretion

Areas the user did not select for explicit discussion; handled by Claude using existing project conventions:

- **Edge behavior** (not selected as a gray area) — idempotency, fallbacks, error response shapes:
  - POST `/start` when not idle → 200 no-op (coordinator already no-ops)
  - POST `/stop` when idle → 200 no-op (coordinator already no-ops)
  - Bridge not paired → 503 on `/start` and `/api/ha/zones`
  - Camera unavailable at start → fall back to default `CAPTURE_DEVICE` (existing coordinator behavior)
  - HTTP status map: 400 (missing precondition), 404 (unknown zone/camera id), 502 (bridge HTTP error), 503 (bridge unreachable/unpaired)
- Pydantic model naming and field shapes
- Friendly-name resolution: per-call lookup against `list_entertainment_configs` and `known_cameras` (no caching layer added in this phase)
- Test wiring: follow Phase 17 `routers/wled.py` `getattr(..., "coordinator", None)` tolerance pattern
- OpenAPI tagging: `tags=["ha"]` consistent with other routers

## Deferred Ideas

- HA YAML snippet documentation (separate docs phase)
- `/api/ha/restart` convenience verb
- Inline zone/camera body on `/start` (rejected per D-03)
- `target_hz` tuning endpoint
- HA WebSocket push for status
- Per-device WLED health in `/api/ha/status`
- Friendly-name caching layer in `/api/ha/status`
- HA long-lived access token storage (rejected per CLAUDE.md)
- Authentication on HA endpoints (out of scope; LAN trust boundary)
