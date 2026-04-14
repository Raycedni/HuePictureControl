---
phase: 11
slug: docker-multi-device-infrastructure
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-09
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (Backend), vitest (Frontend) |
| **Config file** | `Backend/pytest.ini` |
| **Quick run command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |
| **Full suite command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest && cd ../Frontend && npx vitest run` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest`
- **After every plan wave:** Run `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest && cd ../Frontend && npx vitest run`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | DOCK-01 | — | cgroup rules scoped to major 81 only (not privileged) | manual | `docker compose exec backend ls /dev/video*` | N/A | ⬜ pending |
| 11-01-02 | 01 | 1 | DOCK-01 | — | group_add: [video] retained | manual | `grep -q 'group_add' docker-compose.yaml` | ✅ | ⬜ pending |
| 11-01-03 | 01 | 1 | DOCK-02 | — | N/A | manual | `test -f SETUP.md` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- No new test files required (config + docs only phase)
- Verify existing tests pass after docker-compose.yaml changes: `python -m pytest && npx vitest run`

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Multiple video devices visible in container | DOCK-01 | Requires physical hardware (USB capture cards) attached via usbipd | 1. Attach 2+ capture cards via `usbipd attach --wsl --busid <id>` 2. Run `docker compose exec backend ls /dev/video*` 3. Verify all attached devices appear |
| SETUP.md covers required topics | DOCK-02 | Documentation review | Verify SETUP.md contains: usbipd walkthrough, cgroup rules explanation, explicit devices fallback, device path shift gotcha |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending