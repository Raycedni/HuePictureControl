---
phase: 11-docker-multi-device-infrastructure
plan: 01
subsystem: infrastructure
tags: [docker, v4l2, device-passthrough, documentation, wsl2, usbipd]
dependency_graph:
  requires: []
  provides: [multi-device-docker-passthrough, setup-documentation]
  affects: [docker-compose.yaml, SETUP.md]
tech_stack:
  added: []
  patterns: [device_cgroup_rules for V4L2 wildcard access]
key_files:
  created:
    - SETUP.md
  modified:
    - docker-compose.yaml
decisions:
  - "device_cgroup_rules 'c 81:* rw' as default passthrough (hot-plug, no restart) with explicit devices list as documented fallback"
  - "SETUP.md at project root for all multi-device and WSL2/usbipd documentation, referenced from docker-compose.yaml inline comment"
  - "group_add video retained alongside cgroup rules for filesystem-level permissions"
metrics:
  duration: "3min"
  completed: "2026-04-14"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
---

# Phase 11 Plan 01: Docker Multi-Device Infrastructure Summary

**One-liner:** cgroup rules for V4L2 wildcard device passthrough with comprehensive SETUP.md covering WSL2/usbipd workflows and fallback approaches

## What Was Done

### Task 1: Update docker-compose.yaml with device_cgroup_rules
- Replaced commented-out `devices` block with active `device_cgroup_rules: 'c 81:* rw'` granting container access to all V4L2 video devices (Linux major 81)
- Removed stale commented-out usbipd commands
- Updated `group_add: [video]` comment to reference plural devices
- Added inline comment pointing to SETUP.md for multi-device details
- All existing configuration preserved: ports 8001:8000 and 2100:2100/udp, hue_data volume, healthcheck, frontend service
- Commit: `8f66a6e`

### Task 2: Create SETUP.md with multi-device and WSL2/usbipd documentation
- Created 188-line SETUP.md at project root with practical, copy-paste-ready documentation
- Sections: Prerequisites, Quick Start, Multi-Device Passthrough (cgroup default + explicit devices fallback), WSL2/usbipd Walkthrough (step-by-step with example output), Common Gotchas
- Documented both passthrough approaches with guidance on when to switch (per D-02, D-06)
- Included verification commands: `docker compose exec backend ls /dev/video*` and Python `enumerate_capture_devices()` check
- Covered gotchas: device path shifts on re-attach, WSL restart drops attachments, Docker Desktop vs native Docker Engine, permission denied, empty device list troubleshooting
- No `privileged: true` anywhere (security constraint satisfied)
- Commit: `babe459`

## Deviations from Plan

None - plan executed exactly as written. Both tasks completed with all acceptance criteria met.

## Decisions Made

1. **cgroup rules as default, explicit devices as fallback** - `device_cgroup_rules: 'c 81:* rw'` enables hot-plug support without container restart. Explicit `devices` list documented in SETUP.md for environments where cgroup rules don't auto-mount device nodes.
2. **SETUP.md as standalone documentation** - Multi-device setup and WSL2/usbipd walkthrough live in SETUP.md at project root, with docker-compose.yaml containing a brief inline comment reference.
3. **group_add video retained** - Required for filesystem-level permissions on /dev/video* regardless of passthrough approach.

## Threat Model Compliance

- T-11-01 (Elevation of Privilege): MITIGATED - `device_cgroup_rules: 'c 81:* rw'` scoped to V4L2 major 81 only, no `privileged: true`
- T-11-02 (Tampering via wildcard): ACCEPTED - `c 81:*` grants all V4L2 minor numbers intentionally for multi-device support
- T-11-03 (Information Disclosure in SETUP.md): ACCEPTED - Only generic commands and device paths, no secrets

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| DOCK-01 | Complete | `device_cgroup_rules: 'c 81:* rw'` in docker-compose.yaml enables all V4L2 devices |
| DOCK-02 | Complete | SETUP.md (188 lines) covers usbipd workflow, both passthrough approaches, verification commands, and troubleshooting |

## Verification Results

- docker-compose.yaml: valid YAML, contains device_cgroup_rules with c 81:* rw
- docker-compose.yaml: group_add video present
- docker-compose.yaml: SETUP.md referenced in inline comment
- docker-compose.yaml: no commented-out devices or usbipd blocks
- docker-compose.yaml: no privileged: true
- docker-compose.yaml: all existing config preserved (ports, volumes, healthcheck, frontend)
- SETUP.md: exists at project root (188 lines)
- SETUP.md: contains usbipd list, bind, attach --wsl commands
- SETUP.md: documents both cgroup rules and explicit devices approaches
- SETUP.md: includes verification commands and enumerate_capture_devices
- SETUP.md: covers device path shifts, WSL restart, Docker Desktop, permissions gotchas
- SETUP.md: no privileged: true

## Self-Check: PASSED

All files exist (docker-compose.yaml, SETUP.md, 11-01-SUMMARY.md). All commits found (8f66a6e, babe459).
