---
phase: 13
slug: scrcpy-android-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-16
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | Backend/pytest.ini |
| **Quick run command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest -x -q` |
| **Full suite command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest -x -q`
- **After every plan wave:** Run `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | SCPY-01 | T-13-01 / — | IP validation prevents injection | unit | `pytest tests/test_pipeline_manager.py -k scrcpy` | ❌ W0 | ⬜ pending |
| 13-01-02 | 01 | 1 | SCPY-03 | — | ADB disconnect on stop | unit | `pytest tests/test_pipeline_manager.py -k stop` | ❌ W0 | ⬜ pending |
| 13-01-03 | 01 | 1 | SCPY-04 | — | Stale-frame reconnect | unit | `pytest tests/test_pipeline_manager.py -k reconnect` | ❌ W0 | ⬜ pending |
| 13-02-01 | 02 | 1 | WAPI-03 | T-13-02 / — | POST validates IP before ADB | integration | `pytest tests/test_wireless_router.py -k scrcpy` | ❌ W0 | ⬜ pending |
| 13-02-02 | 02 | 1 | SCPY-02 | — | Camera tagged as wireless | integration | `pytest tests/test_cameras_router.py -k wireless` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/test_pipeline_manager.py` — extend existing tests for scrcpy ADB/reconnect
- [ ] `Backend/tests/test_wireless_router.py` — extend existing tests for scrcpy POST/DELETE endpoints
- [ ] `Backend/tests/test_cameras_router.py` — add wireless camera tagging test

*Existing test infrastructure covers framework and fixtures.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Android device mirror to lights | SCPY-01 | Requires physical Android device on same WiFi | POST device IP, verify lights respond |
| WiFi interruption recovery | SCPY-04 | Requires toggling WiFi on physical device | Start session, toggle airplane mode briefly, verify auto-reconnect |
| Same latency as physical | SC3 | Requires visual comparison with USB capture | Compare light response time side-by-side |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
