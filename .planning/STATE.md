---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Home Assistant Integration Polish
status: defining_requirements
stopped_at: Milestone v1.3 opened — gathering requirements
last_updated: "2026-05-12T18:00:00.000Z"
last_activity: 2026-05-12
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-12)

**Core value:** Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.
**Current focus:** v1.3 milestone — Home Assistant Integration Polish (defining requirements)

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-05-12 — Milestone v1.3 (HA Integration Polish) started

## Performance Metrics

**Velocity:**

- Total plans completed: 15 (Phase 16 full)
- Average duration: ~30 min / plan
- Total execution time: ~1.5 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 16 | 3 | ~1.5h | ~30 min |
| 17 | 9 | - | - |
| 18 | 3 | - | - |

**Recent Trend:**

- Last 5 plans: 16-01 (backend DB + router), 16-02 (broadcaster + streaming service), 16-03 (frontend store + LightPanel)
- Trend: steady; Phase 16 executed cleanly across both backend and frontend

*Updated after each plan completion*
| Phase 18-02 P18-02 | 4 min | 2 tasks | 2 files |
| Phase Phase 18-03 PP18-03 | 7 min | 3 tasks tasks | 4 files files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [16-03]: LightPanel uses a 3-tier zone selection cascade (streaming > camera-persisted > configs[0]) with guard-clause early returns inside a single useEffect
- [16-03]: Stale-persisted configs fall back silently AND overwrite the dangling row via putLastZone (Claude's Discretion per 16-CONTEXT.md)
- [16-03]: W2 closure — pre-selection is read-only; verified by explicit `not.toHaveBeenCalled()` negative assertion
- [16-03]: W3 closure — zone `<select>` carries data-testid="zone-select"; tests use findByTestId/getByTestId instead of index-based querySelectorAll
- [v1.3 roadmap]: WLED streaming uses stdlib socket (UDP) — no new library; DRGB for <=490 LEDs, DNRGB for >490 (auto-selected by WledService)
- [v1.3 roadmap]: WLED device registration uses existing httpx to fetch /json/info from device IP before persisting
- [v1.3 roadmap]: WLED channels use shared channel abstraction — painted ranges appear in light panel alongside Hue segments, same drag-drop assignment
- [v1.3 roadmap]: HA endpoints are unauthenticated thin adapters over the existing StreamingCoordinator — no new auth layer
- [v1.3 roadmap]: Phase 16 (bug fixes) runs first as warm-up — independent of WLED, unblocks clean state for WLED testing
- [18-01]: ha_state is a single-row table with CHECK (id = 1); created lazily (no INSERT OR IGNORE seed) — first PUT /api/ha/zone or /camera writes via ON CONFLICT DO UPDATE
- [18-01]: StreamingCoordinator.start now takes optional device_path_override: str | None = None (Option C per RESEARCH.md A1); when None, existing camera_assignments resolution chain runs unchanged so D-07 (HA never touches camera_assignments) stays clean
- Phase 18 Plan 02: HA REST router exposes 7 unauthenticated endpoints under /api/ha/* — LAN trust boundary per PROJECT.md; zero Depends, zero auth tokens, zero camera_assignments writes (D-07 negative)
- Phase 18 Plan 02: HaStatusResponse uses response_model_exclude_none=True at the route boundary so the optional 'error' field stays out of happy-path payloads while the model itself remains declarative (D-09 sealed contract — no leakage of packets_sent / packets_dropped / wled_devices)
- Phase 18 Plan 02: ha_router imported alphabetically in main.py (between capture and health) to preserve the existing alphabetical convention; app.include_router(ha_router) placed after wled_router per plan spec — preserves both convention and intent
- Phase 18 Plan 03 closed: 26 unit tests + 1 e2e test cover HASS-01..05 with named D-06/D-07/D-09 enforcement; modernised 4 asyncio.get_event_loop().run_until_complete calls in test_hue_router.py to asyncio.run (Rule 1 deviation — Python 3.12 latent bug exposed by alphabetical test-file collection order)
- Phase 18 Plan 03: D-09 sealed-contract test relaxed from response-key exact-equality to a subset assertion because response_model_exclude_none=True drops null optional fields; subset check still rejects forbidden internal _metrics keys (packets_sent / seq / wled_devices) and requires the four non-nullable D-09 keys

### Pending Todos

None yet.

### Roadmap Evolution

- Phase 3.1 inserted after Phase 3: Auto-Mapping from Entertainment Config — auto-generate screen regions from channel positions before building manual canvas editor (user decision 2026-03-24)
- v1.3 Phases 16-19 added 2026-04-14: Zone persistence fixes, WLED backend+streaming, HA control endpoints, WLED strip paint UI
- v1.1 archived 2026-04-14: 5 phases, 10 plans, 7 requirements left unchecked (known gaps)
- Phase 16 closed 2026-04-20: 3 plans, BFIX-01 + BFIX-02 shipped
- Phase 18 Plan 01 closed 2026-05-11: ha_state DDL + StreamingCoordinator.start device_path_override (8 min, 2 tasks, 2 files modified)

### Blockers/Concerns

(None — Phase 16 clean close; ready for Phase 17 kickoff)

## Session Continuity

Last session: 2026-05-12T17:37:41.269Z
Stopped at: Completed 18-03-PLAN.md (Phase 18 closed)
Resume file: None

**Planned Phase:** 18 (Home Assistant Control Endpoints) — 3 plans, 1 complete — next: 18-02 (routers/ha.py)
