# Phase 11: Docker Multi-Device Infrastructure - Context

**Gathered:** 2026-04-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Docker Compose configuration for passing multiple video capture devices into the backend container, plus a standalone SETUP.md documenting the full multi-device and WSL2/usbipd workflow. This phase does NOT change backend code — the CaptureRegistry (Phase 8) and camera APIs (Phase 7) already handle multiple devices. This is purely infrastructure config and documentation.

</domain>

<decisions>
## Implementation Decisions

### Device Passthrough Strategy
- **D-01:** Default approach uses `device_cgroup_rules: 'c 81:* rw'` in docker-compose.yaml to enable hot-plug support — new capture cards become accessible inside the container without restarting Docker.
- **D-02:** Explicit `devices` list is documented as a fallback in SETUP.md for users who encounter cgroup rules instability on specific Docker/Compose versions.
- **D-03:** `group_add: [video]` remains (already present) — required for device access regardless of passthrough approach.

### Documentation
- **D-04:** Multi-device documentation lives in a separate `SETUP.md` file at the project root. Docker-compose.yaml gets brief inline comments pointing to SETUP.md.
- **D-05:** SETUP.md includes a full WSL2/usbipd walkthrough with step-by-step commands (`usbipd list`, `usbipd bind`, `usbipd attach`), example output, and common gotchas (device path shifts on re-attach, need to re-attach after WSL restart).
- **D-06:** SETUP.md documents both passthrough approaches (cgroup rules default + explicit devices fallback) with guidance on when to switch.

### Claude's Discretion
- Docker-compose.yaml comment style and level of detail (brief pointers to SETUP.md)
- SETUP.md structure and section ordering
- Whether to include a troubleshooting section in SETUP.md

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Configuration
- `docker-compose.yaml` — Current Compose config with commented-out devices, group_add, and usbipd notes
- `Backend/Dockerfile` — Backend container build (python:3.12-slim base)

### Project Docs
- `.planning/REQUIREMENTS.md` §DOCK-01, §DOCK-02 — Multi-device passthrough and documentation requirements
- `CLAUDE.md` §Docker Compose — Multiple Device Passthrough — Recommended approach and alternatives

### Prior Phase Context
- `.planning/phases/08-capture-registry/08-CONTEXT.md` — CaptureRegistry design (backend is already multi-camera-ready)
- `.planning/phases/07-device-enumeration-and-camera-assignment-schema/07-CONTEXT.md` — Device enumeration and camera assignment schema

### External References
- [Docker Compose `services` reference](https://docs.docker.com/reference/compose-file/services/) — `devices` list and `device_cgroup_rules` syntax
- [docker/compose #9059](https://github.com/docker/compose/issues/9059) — `device_cgroup_rules` instability history

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `docker-compose.yaml` already has `group_add: [video]` and commented usbipd notes — extend rather than rewrite
- `Backend/services/capture_v4l2.py` has `enumerate_capture_devices()` — verifies devices are accessible inside container

### Established Patterns
- Docker Compose uses bridge networking with port mapping (not host network on WSL2)
- Backend healthcheck already configured

### Integration Points
- `docker-compose.yaml` backend service `devices` / `device_cgroup_rules` section
- SETUP.md (new file) referenced from docker-compose.yaml comments

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 11-docker-multi-device-infrastructure*
*Context gathered: 2026-04-09*
