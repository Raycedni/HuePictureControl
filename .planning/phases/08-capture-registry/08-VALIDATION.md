---
phase: 08
slug: capture-registry
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-03
---

# Phase 08 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (async via pytest-asyncio) |
| **Config file** | existing pytest config |
| **Quick run command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_capture_registry.py tests/test_streaming_service.py -x -q` |
| **Full suite command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest --tb=short -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_capture_registry.py tests/test_streaming_service.py -x -q`
- **After every plan wave:** Run `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest --tb=short -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 08-01-01 | 01 | 1 | MCAP-03 | unit | `pytest tests/test_capture_registry.py -x` | ❌ W0 | ⬜ pending |
| 08-01-02 | 01 | 1 | MCAP-01 | unit | `pytest tests/test_streaming_service.py -x` | ✅ extends | ⬜ pending |
| 08-02-01 | 02 | 2 | MCAP-01 | unit | `pytest tests/test_capture_router.py -x` | ✅ extends | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/test_capture_registry.py` — new file for CaptureRegistry unit tests (acquire, release, ref counting, shutdown)
- [ ] `Backend/tests/test_streaming_service.py` — extend with registry-aware tests (start uses assigned camera, stop releases, fallback to default)

*Existing infrastructure covers framework and fixture requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Two physical cameras stream simultaneously | MCAP-03 | Requires two USB capture cards | Plug two cards, assign to different zones, start both, verify both produce frames |
| Mid-stream camera switch on real hardware | Success criterion 3 | Requires physical device swap | Stop zone, reassign camera, start zone, verify new device active |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
