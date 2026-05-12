---
phase: 18-home-assistant-control-endpoints
verified: 2026-05-12T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 18: Home Assistant Control Endpoints Verification Report

**Phase Goal:** Home Assistant can start and stop streaming, select the active camera and entertainment zone, and query current streaming status via REST endpoints — without requiring access to the web UI.

**Verified:** 2026-05-12
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| #   | Truth                                                                                                                                                       | Status     | Evidence                                                                                                                                                              |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | POST /api/ha/start starts streaming from HA with the currently configured zone and camera; POST /api/ha/stop stops it cleanly                              | VERIFIED   | `Backend/routers/ha.py:185-241` (ha_start delegates to `coordinator.start(active_config_id, device_path_override=...)`), `:244-254` (ha_stop calls coordinator.stop). e2e test `test_ha_e2e_full_flow` proves coordinator transitions idle → streaming → idle. |
| 2   | GET /api/ha/status returns current streaming state, active zone, and active camera in a machine-readable format                                            | VERIFIED   | `Backend/routers/ha.py:257-263` returns `HaStatusResponse` with 14 fields including `state`, `active_config_id`, `active_config_name`, `active_camera_stable_id`, `active_camera_name`. Curated payload locked by `test_status_curated_payload_shape`. |
| 3   | HA can select a specific camera via REST and a subsequent start uses that camera                                                                            | VERIFIED   | `Backend/routers/ha.py:323-363` (PUT /camera persists to `ha_state.active_camera_stable_id`); `:224-233` (start resolves `device_path_override` from camera's `last_device_path`). Asserted by `test_start_calls_coordinator_with_resolved_path` — `coord.start.assert_awaited_once_with("cfg1", device_path_override="/dev/video10")`. |
| 4   | HA can select a specific entertainment zone via REST and a subsequent start activates that zone                                                            | VERIFIED   | `Backend/routers/ha.py:266-320` (PUT /zone validates against entertainment_configs and persists to `ha_state.active_config_id`); `ha_start` consumes the persisted value. Covered by e2e flow and `test_put_zone_persists_lazy`, `test_put_zone_preserves_camera`. |
| 5   | All HA endpoints are unauthenticated and accessible from within the local network, consistent with the rest of the API                                     | VERIFIED   | `grep -n "Depends" Backend/routers/ha.py` returns ZERO matches. Router declares only `APIRouter(prefix="/api/ha", tags=["ha"])` — same auth posture as `/api/hue/*`, `/api/cameras/*`, `/api/capture/*`. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact                                       | Expected                                                                                                      | Status     | Details                                                                                                                                                                                     |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Backend/database.py`                          | `CREATE TABLE IF NOT EXISTS ha_state` with `CHECK (id=1)`, four columns, no eager seed                        | VERIFIED   | Lines 96-100 contain the exact DDL block; no `INSERT OR IGNORE INTO ha_state` in any Backend file (lazy creation per D-05).                                                                  |
| `Backend/services/streaming_coordinator.py`    | `start()` extended with `device_path_override: str \| None = None` parameter that bypasses `_resolve_device_path` when supplied | VERIFIED   | Lines 97-115 (signature + docstring), line 125 contains `device_path = device_path_override or await self._resolve_device_path(config_id)`. `_resolve_device_path` body unchanged.            |
| `Backend/routers/ha.py`                        | 409-line router with 7 endpoints, 6 Pydantic models, `_build_status_response` helper                          | VERIFIED   | File is 409 lines (≥ 250 minimum). Has 7 `@router.*` decorators (2 POST, 2 PUT, 3 GET). All 6 models exported. Helper at lines 88-177.                                                       |
| `Backend/main.py`                              | Import + `app.include_router(ha_router)`                                                                       | VERIFIED   | Line 12: `from routers.ha import router as ha_router`. Line 85: `app.include_router(ha_router)`. Lifespan unchanged.                                                                         |
| `Backend/tests/test_ha_router.py`              | ≥ 24 unit tests covering HASS-01..05 plus D-06/D-07/D-09                                                       | VERIFIED   | 26 test functions present (24 mandated + 2 zones error tests). All run green in 0.29s.                                                                                                       |
| `Backend/tests/test_ha_e2e.py`                 | Single integration test driving PUT zone → PUT camera → POST start → GET status → POST stop                    | VERIFIED   | `test_ha_e2e_full_flow` at line 140 wires a real `StreamingCoordinator(db, _MockRegistry(make_mock_capture()), broadcaster, mock_hue, mock_wled)` and proves state transitions to streaming and back to idle. Passes in 0.23s. |

### Key Link Verification

| From                                              | To                                                                          | Via                                                                       | Status | Details                                                                                                                                                                    |
| ------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Backend/database.py::init_db`                    | `ha_state` table                                                            | `await db.execute(CREATE TABLE IF NOT EXISTS ha_state ...)`               | WIRED  | Schema test in 18-01 plan executed at init time; `ha_state` row check in `test_ha_router.py` (`SELECT FROM ha_state WHERE id = 1`) passes against the runtime schema.       |
| `Backend/services/streaming_coordinator.py::start`| device path resolution                                                      | `device_path = device_path_override or await self._resolve_device_path(config_id)` | WIRED  | Line 125. Verified by `test_start_calls_coordinator_with_resolved_path`: e2e test confirms the path actually drives the coordinator into streaming state.                   |
| `Backend/routers/ha.py::ha_start`                 | `StreamingCoordinator.start`                                                | `coordinator.start(active_config_id, device_path_override=device_path_override)` | WIRED  | Line 239. Test `test_start_calls_coordinator_with_resolved_path` asserts the exact call shape with `assert_awaited_once_with("cfg1", device_path_override="/dev/video10")`.|
| `Backend/routers/ha.py::ha_put_zone`              | `ha_state + camera_last_zone` tables                                        | `INSERT ... ON CONFLICT(id) DO UPDATE` + conditional second INSERT        | WIRED  | Lines 295-317. D-06 dual-write verified by `test_put_zone_dual_writes_camera_last_zone` and `test_put_zone_skips_dual_write_when_no_camera`.                                |
| `Backend/routers/ha.py::_build_status_response`   | `broadcaster._metrics + ha_state + entertainment_configs + bridge_config + known_cameras` | 5 joined reads producing `HaStatusResponse`                          | WIRED  | Lines 88-177. Verified by `test_status_schema_when_streaming`, `test_status_includes_ha_selected`, `test_status_resolves_friendly_names`.                                   |
| `Backend/main.py`                                 | `routers.ha.router`                                                          | `app.include_router(ha_router)`                                            | WIRED  | Line 85. Confirmed via `from main import app; ...` introspection: all 7 `/api/ha/*` paths registered.                                                                       |

### Data-Flow Trace (Level 4)

| Artifact          | Data Variable                                          | Source                                                                                                                  | Produces Real Data | Status     |
| ----------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | ------------------ | ---------- |
| `ha.py:ha_start`  | `active_config_id`, `active_camera_stable_id`          | Real `SELECT ... FROM ha_state WHERE id = 1` after PUT writes                                                            | Yes                | FLOWING    |
| `ha.py:ha_put_zone` | `body.zone_id` validated against `entertainment_configs` | Live `SELECT id FROM entertainment_configs` (real schema populated by Hue Bridge sync)                                 | Yes                | FLOWING    |
| `ha.py:ha_status` | `metrics`, `bridge_row`, `ha_row`, `cam_row`           | Live reads from `broadcaster._metrics`, `bridge_config`, `ha_state`, `known_cameras` + httpx call to `list_entertainment_configs` | Yes                | FLOWING    |
| `ha.py:ha_zones`  | `raw`                                                  | Real `await list_entertainment_configs(ip, username)` against Hue bridge                                                 | Yes                | FLOWING    |
| `ha.py:ha_cameras`| `scan_results, rows`                                   | Live `_scan_devices()` (V4L2 enumeration) + `SELECT ... FROM known_cameras`                                              | Yes                | FLOWING    |

No hollow components — every endpoint's data flow is verified to reach real DB tables or live services.

### Behavioral Spot-Checks

| Behavior                                              | Command                                                                                                                                                | Result                            | Status |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------- | ------ |
| All 7 HA endpoints registered on the FastAPI app      | `python -c "from main import app; ..."`                                                                                                                  | 7 paths (`/api/ha/{camera,cameras,start,status,stop,zone,zones}`) | PASS   |
| Router file imports without errors                    | `python -c "from routers.ha import router, HaStatusResponse, ..."`                                                                                       | Import succeeded                  | PASS   |
| Zero auth dependencies in router                      | `grep -n "Depends" Backend/routers/ha.py`                                                                                                              | 0 matches                          | PASS   |
| D-07 negative: no `camera_assignments` writes         | `grep "camera_assignments\|INSERT OR REPLACE" Backend/routers/ha.py`                                                                                    | 0 matches                          | PASS   |
| D-09 sealed payload: no internal metrics leak in code | `grep "packets_sent\|packets_dropped\|wled_devices" Backend/routers/ha.py`                                                                              | 0 matches                          | PASS   |
| HA unit tests pass                                    | `python -m pytest tests/test_ha_router.py -v --tb=short`                                                                                                 | 26 passed                          | PASS   |
| HA e2e integration test passes                        | `python -m pytest tests/test_ha_e2e.py -v --tb=short`                                                                                                    | 1 passed                           | PASS   |
| Full backend suite (excluding pre-existing failures)  | `python -m pytest --ignore=tests/test_cameras_router.py -q`                                                                                              | 300 passed, 21 skipped             | PASS   |

### Requirements Coverage

| Requirement | Source Plan | Description                                                              | Status     | Evidence                                                                                                                                                                |
| ----------- | ----------- | ------------------------------------------------------------------------ | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| HASS-01     | 18-01, 18-02, 18-03 | HA can start streaming via REST endpoint (POST /api/ha/start)            | SATISFIED  | `ha.py:185-241` + `test_start_400_when_no_zone_selected`, `test_start_404_when_zone_deleted`, `test_start_calls_coordinator_with_resolved_path`, `test_start_idempotent_when_streaming`, `test_ha_e2e_full_flow` |
| HASS-02     | 18-02, 18-03        | HA can stop streaming via REST endpoint (POST /api/ha/stop)              | SATISFIED  | `ha.py:244-254` + `test_stop_calls_coordinator`, `test_stop_idempotent_when_idle`, `test_ha_e2e_full_flow`                                                                |
| HASS-03     | 18-01, 18-02, 18-03 | HA can select the active camera via REST endpoint                        | SATISFIED  | `ha.py:323-363` (PUT /camera) + `streaming_coordinator.py:97-125` (`device_path_override`) + `test_put_camera_persists_lazy`, `test_put_camera_does_not_touch_assignments`, `test_start_calls_coordinator_with_resolved_path` |
| HASS-04     | 18-01, 18-02, 18-03 | HA can select the entertainment zone via REST endpoint                   | SATISFIED  | `ha.py:266-320` (PUT /zone) + 5 PUT-zone tests covering happy path, 404, D-06 dual-write conditional, and Pitfall 1 preservation                                          |
| HASS-05     | 18-02, 18-03        | HA can query current streaming status via GET endpoint                   | SATISFIED  | `ha.py:88-177` (`_build_status_response`) + 8 status tests covering schema, friendly names, unpaired bridge, HTTP error, sealed payload, error field, partial bridge row  |

No orphaned requirements — every HASS-XX from `.planning/milestones/v1.1-REQUIREMENTS.md` lines 174-178 maps to at least one plan in this phase and to a named test.

### Anti-Patterns Found

| File                             | Line | Pattern                                | Severity | Impact                                                                                                                          |
| -------------------------------- | ---- | -------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------- |
| (none)                           | —    | —                                      | —        | Phase 18's modified files contain no TODO/FIXME/PLACEHOLDER markers, no empty handlers, no hardcoded empty data, and no console-only stubs. |

`grep -n -E "TODO|FIXME|XXX|HACK|PLACEHOLDER|placeholder|not implemented" Backend/routers/ha.py Backend/database.py Backend/services/streaming_coordinator.py Backend/main.py Backend/tests/test_ha_router.py Backend/tests/test_ha_e2e.py` returns zero matches.

### Human Verification Required

None for goal achievement. The roadmap's success criteria are all verifiable from the codebase and existing tests. The `18-VALIDATION.md` "Manual-Only Verifications" section already documents that a future live-HA smoke test (`rest_command:` integration with real Home Assistant + live Hue Bridge) is the only manual check, and it is explicitly deferred per CONTEXT.md (HA integration docs / configuration.yaml snippet is a separate future docs phase). This is consistent with the phase goal — the goal is "HA can start/stop/select/query via REST endpoints," and that is verified by automated tests + endpoint introspection.

### Gaps Summary

No gaps. All five roadmap success criteria are satisfied by code that exists, is wired into the FastAPI app, is exercised by 27 green tests, and is properly traced to all five HASS-XX requirements. The pre-existing 12 `test_cameras_router.py` failures predate Phase 18 (confirmed via git-stash baseline in Plan 01) and are tracked in `deferred-items.md` — they are not Phase 18's responsibility.

---

## Verification Notes

- **Re-verification mode:** No — first verification of this phase.
- **Override usage:** None.
- **Deferred items:** None — Phase 18 is the last phase covering HASS-01..05 in milestone v1.1.
- **Test execution:** All 27 HA tests pass locally (0.41s combined). Full backend suite green (300 passed, 21 skipped) when excluding the 12 pre-existing `test_cameras_router.py` failures documented in `deferred-items.md`.
- **Trust boundary:** Unauthenticated `/api/ha/*` endpoints match the established LAN-only trust model per `CLAUDE.md` § Constraints ("No auth: Web UI is unauthenticated — local network tool only").

---

_Verified: 2026-05-12_
_Verifier: Claude (gsd-verifier)_
