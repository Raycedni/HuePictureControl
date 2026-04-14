---
phase: 9
slug: preview-routing-and-region-api
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-05
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend), vitest (frontend) |
| **Config file** | Backend/pytest.ini, Frontend/vitest.config.ts |
| **Quick run command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest -x -q` |
| **Full suite command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest && cd ../Frontend && npx vitest run` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest -x -q`
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 09-01-01 | 01 | 1 | MCAP-02 | unit | `pytest Backend/tests/test_capture_registry.py -q` | ❌ W0 | ⬜ pending |
| 09-01-02 | 01 | 1 | MCAP-02 | unit | `pytest Backend/tests/test_preview_ws.py -q` | ❌ W0 | ⬜ pending |
| 09-02-01 | 02 | 1 | CAMA-04 | unit | `pytest Backend/tests/test_cameras.py -q` | ✅ | ⬜ pending |
| 09-02-02 | 02 | 1 | CAMA-04 | unit | `pytest Backend/tests/test_regions.py -q` | ✅ | ⬜ pending |
| 09-03-01 | 03 | 2 | MCAP-02 | unit | `npx vitest run --reporter=verbose` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/test_preview_ws.py` — stubs for WebSocket device routing (MCAP-02)
- [ ] `Backend/tests/conftest.py` — update `db` fixture to include `entertainment_config_id` column in regions table
- [ ] Existing test infrastructure covers remaining requirements

*Existing pytest and vitest infrastructure covers most phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| WebSocket streams from physical device | MCAP-02 | Requires real capture card | Open preview with `?device=/dev/video0`, verify JPEG frames arrive |
| Camera health reflects actual hardware | CAMA-04 | Requires multiple cameras | Check `GET /api/cameras` zone_health with device plugged/unplugged |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
