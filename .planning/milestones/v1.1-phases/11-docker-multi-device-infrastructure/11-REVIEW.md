---
phase: 11-docker-multi-device-infrastructure
reviewed: 2026-04-14T12:00:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - docker-compose.yaml
  - SETUP.md
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 11: Code Review Report

**Reviewed:** 2026-04-14T12:00:00Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Reviewed `docker-compose.yaml` (modified) and `SETUP.md` (created) for the Docker multi-device infrastructure phase. The docker-compose.yaml change is clean: it correctly replaces an explicit (commented-out) devices block with `device_cgroup_rules: 'c 81:* rw'` for V4L2 hot-plug support, uses `group_add: [video]` for filesystem permissions, and avoids `privileged: true`. YAML structure is valid, no regressions to existing service config.

SETUP.md is well-written and technically accurate overall. Two findings: one incorrect API endpoint reference (Warning) and one minor accuracy note about GID portability (Info).

## Warnings

### WR-01: Non-existent API endpoint in verification instructions

**File:** `SETUP.md:186`
**Issue:** The "Verifying the Full Stack" section references `curl http://localhost:8001/api/capture/devices`, but this endpoint does not exist. The actual endpoint for listing capture devices is `GET /api/cameras` (defined in `Backend/routers/cameras.py` with prefix `/api/cameras`). Users following this guide will receive a 404 error, which may cause confusion about whether the stack is working.
**Fix:**
```bash
# List detected capture devices
curl http://localhost:8001/api/cameras
```

## Info

### IN-01: GID 44 claim is distro-specific

**File:** `SETUP.md:165`
**Issue:** States "The `video` group (GID 44 on standard Linux)" -- GID 44 is correct for Debian/Ubuntu-based distributions (which the project's Docker image likely uses), but differs on other distros (e.g., Arch Linux uses GID 985). Since `group_add: [video]` in docker-compose.yaml resolves by group name (not GID), the compose config itself works correctly regardless. The documentation claim is slightly misleading but unlikely to cause real issues since the Docker container is Debian-based.
**Fix:** Optionally clarify: "The `video` group (GID 44 on Debian/Ubuntu-based Linux, including the project's Docker image)" or simply remove the GID reference since it is not actionable.

---

_Reviewed: 2026-04-14T12:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
