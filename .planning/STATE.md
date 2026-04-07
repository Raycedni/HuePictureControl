---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Multi-Camera Support
status: verifying
stopped_at: Phase 10 context gathered
last_updated: "2026-04-07T19:04:11.370Z"
last_activity: 2026-04-07
progress:
  total_phases: 5
  completed_phases: 3
  total_plans: 6
  completed_plans: 6
  percent: 20
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-03)

**Core value:** Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.
**Current focus:** Phase 09 — preview-routing-and-region-api

## Current Position

Phase: 10
Plan: Not started
Status: Phase complete — ready for verification
Last activity: 2026-04-07

Progress: [██░░░░░░░░] 20% (v1.1) — Phase 7 complete

## Performance Metrics

**Velocity (v1.0 reference):**

- Total plans completed (v1.0): 17
- Average duration: ~8 min/plan
- Total execution time: ~2.5 hours

**v1.1 By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 7. Device Enumeration + Schema | 2 | ✓ Complete | ~7 min/plan |
| 8. Capture Registry | TBD | - | - |
| 9. Preview Routing + Region API | TBD | - | - |
| 10. Frontend Camera Selector | TBD | - | - |
| 11. Docker Multi-Device | TBD | - | - |

*Updated after each plan completion*
| Phase 07 P02 | 750 | 2 tasks | 4 files |
| Phase 08 P01 | 8 | 1 tasks | 2 files |
| Phase 09-preview-routing-and-region-api P01 | 15 | 2 tasks | 5 files |
| Phase 09-preview-routing-and-region-api P02 | 18 | 2 tasks | 7 files |

## Accumulated Context

### Decisions

- [v1.1 design]: Camera assignment scoped to entertainment config (zone), not per-region — matches existing streaming model (one session per config)
- [v1.1 design]: CaptureBackend singleton → CaptureRegistry (dict keyed by device path, ref-counted)
- [v1.1 design]: Device identity stored as USB VID/PID/serial (not raw /dev/videoN path) — verify sysfs accessibility inside Docker/WSL2 before finalizing schema; fallback to VIDIOC_QUERYCAP card name
- [v1.1 design]: linuxpy>=0.24 for V4L2 enumeration (pure Python, zero C-extension conflicts with Python 3.12 pin)
- [v1.1 design]: Preview WebSocket gains optional ?device= query param for per-zone routing
- [Phase 07]: enumerate_capture_devices + get_stable_id wrapped in run_in_executor for async FastAPI context
- [Phase 07]: GET /api/cameras always returns known_cameras rows to preserve disconnected device history per D-06
- [Phase 07]: PUT /api/cameras/assignments validates camera_stable_id exists in known_cameras before upsert
- [Phase 08-01]: Used threading.Lock (not asyncio.Lock) in CaptureRegistry — callers use asyncio.to_thread so methods run from thread-pool threads
- [Phase 08-01]: CaptureRegistry.shutdown() catches per-backend exceptions to ensure all backends released even if one fails
- [Phase 09-01]: Preview WebSocket is a passive observer — uses registry.get() not acquire() to avoid holding ref count that would prevent streaming zones from releasing backends
- [Phase 09-01]: Close code 1008 (Policy Violation) enforced before WebSocket accept when ?device= param missing
- [Phase 09-preview-routing-and-region-api]: camera_device is read-only derived field — computed via LEFT JOIN, not stored; write path uses entertainment_config_id column
- [Phase 09-preview-routing-and-region-api]: update_region now writes entertainment_config_id to regions table (previously only wrote to light_assignments)
- [Phase 09-preview-routing-and-region-api]: usePreviewWS stays disconnected when device param is undefined — Phase 10 call sites will wire device

### Pending Todos

None yet.

### Blockers/Concerns

- ~~[Phase 7]: sysfs accessibility~~ — Resolved: get_stable_id() implements fallback to card@bus_info when sysfs unavailable
- [Phase 8]: Reference counting edge cases during mid-stream camera switches need explicit test scenarios before CaptureRegistry is finalized

## Session Continuity

Last session: 2026-04-07T19:04:11.351Z
Stopped at: Phase 10 context gathered
Resume file: .planning/phases/10-frontend-camera-selector/10-CONTEXT.md
