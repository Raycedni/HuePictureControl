# Phase 11: Docker Multi-Device Infrastructure - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-09
**Phase:** 11-docker-multi-device-infrastructure
**Areas discussed:** Documentation scope & location, Dynamic device handling

---

## Documentation Scope & Location

### Q1: Where should the multi-device setup documentation live?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline comments only | Detailed comments in docker-compose.yaml. No separate doc file. | |
| README section | Add a 'Multi-Camera Setup' section to the project README. | |
| Separate SETUP.md | Dedicated setup guide covering device passthrough, usbipd workflow, troubleshooting. | ✓ |

**User's choice:** Separate SETUP.md
**Notes:** Docker-compose gets brief comments pointing to SETUP.md.

### Q2: How detailed should the WSL2/usbipd workflow documentation be?

| Option | Description | Selected |
|--------|-------------|----------|
| Full walkthrough | Step-by-step: usbipd commands with example output, common gotchas. | ✓ |
| Brief reference | Just the 3 key commands with a note about device path changes. | |
| Link only | Link to Microsoft's usbipd docs. Minimal inline instructions. | |

**User's choice:** Full walkthrough
**Notes:** None

---

## Dynamic Device Handling

### Q1: Should Docker support hot-plugging new capture devices without restarting?

| Option | Description | Selected |
|--------|-------------|----------|
| Plug then start | All cards must be plugged in before docker compose up. Simple and reliable. | |
| Hot-plug via cgroup rules | Use device_cgroup_rules: 'c 81:* rw' for automatic access to new devices. | ✓ |
| You decide | Claude picks based on architecture and WSL2 constraints. | |

**User's choice:** Hot-plug via cgroup rules
**Notes:** None

### Q2: Should explicit devices list be documented as fallback?

| Option | Description | Selected |
|--------|-------------|----------|
| Both approaches documented | Default to cgroup rules. SETUP.md includes explicit devices list as fallback. | ✓ |
| Cgroup rules only | Commit to cgroup rules only. | |
| You decide | Claude picks based on Docker version compatibility research. | |

**User's choice:** Both approaches documented
**Notes:** Fallback for when cgroup rules misbehave on specific Docker versions.

---

## Claude's Discretion

- Docker-compose.yaml comment style and level of detail
- SETUP.md structure and section ordering
- Whether to include a troubleshooting section

## Deferred Ideas

None — discussion stayed within phase scope
