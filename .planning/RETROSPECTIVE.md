# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.1 — Multi-Camera Support

**Shipped:** 2026-04-14
**Phases:** 5 | **Plans:** 10 | **Commits:** 79

### What Was Built
- V4L2 device enumeration with QUERYCAP capability filtering and stable sysfs identity
- CaptureRegistry — ref-counted, thread-safe pool for concurrent multi-camera capture
- Device-routed preview WebSocket with `?device=` parameter for per-zone camera routing
- Frontend camera selector — zone dropdown + per-zone camera dropdown with live preview switching
- Docker multi-device passthrough via `device_cgroup_rules` with comprehensive SETUP.md

### What Worked
- Wave-based plan execution kept phases focused and dependencies clear
- CaptureRegistry ref-counting pattern cleanly separated device lifecycle from streaming concerns
- Props-down state lifting in EditorPage gave a clean ownership model for zone/camera state
- TDD Wave 0 stubs (Phase 10) caught integration issues early before UI implementation
- `device_cgroup_rules` was a cleaner solution than explicit device lists for Docker passthrough

### What Was Inefficient
- 7 of 17 requirements left unchecked at close — traceability table wasn't updated as requirements were delivered, making it unclear which were actually satisfied vs. just unchecked
- v1.0 was never formally archived via `/gsd-complete-milestone`, so no milestone archive exists for it
- Phase 6 (Hardening) has "TBD" plans in the progress table — never formally tracked

### Patterns Established
- `CaptureRegistry.acquire()/release()` as the canonical pattern for device lifecycle — reuse for WLED and wireless in future milestones
- Props-down from EditorPage: zone/camera/device state owned at page level, passed to LightPanel and EditorCanvas
- `device_cgroup_rules` for Docker device passthrough (wildcard major number instead of explicit paths)
- Wave 0 test stubs before implementation for frontend phases with complex API integration

### Key Lessons
1. Keep requirements traceability table in sync during execution, not just at milestone close — 7 unchecked requirements may actually be satisfied but weren't tracked
2. Formally archive each milestone when it ships — skipping v1.0 left a gap in the historical record
3. `threading.Lock` (not `asyncio.Lock`) is correct when callers use `asyncio.to_thread` — methods run from thread-pool threads

### Cost Observations
- Model mix: primarily opus for planning/execution, sonnet for research/pattern-mapping
- Timeline: 22 days (2026-03-23 to 2026-04-14)
- Notable: Phase 11 (Docker infra) was a single-plan phase — lightweight phases for config/docs work well

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Commits | Phases | Key Change |
|-----------|---------|--------|------------|
| v1.0 | ~120 | 7 | Initial MVP — established GSD workflow, phase planning, hardware verification gates |
| v1.1 | 79 | 5 | Added Wave 0 TDD stubs, worktree isolation for parallel plans, CaptureRegistry pattern |

### Cumulative Quality

| Milestone | Backend Tests | Frontend Tests | Files Changed |
|-----------|--------------|----------------|---------------|
| v1.0 | 167+ | 30+ | ~200 |
| v1.1 | 167+ | 30+ | 103 |

### Top Lessons (Verified Across Milestones)

1. Hardware verification gates prevent wasted work — DTLS spike in v1.0, device passthrough in v1.1
2. Single-plan phases for infrastructure/docs work are efficient — don't over-plan simple deliverables
