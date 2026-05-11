---
phase: 18
slug: home-assistant-control-endpoints
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-11
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio (already in Backend/requirements.txt) |
| **Config file** | Backend/pytest.ini / Backend/conftest.py |
| **Quick run command** | `python -m pytest Backend/tests/test_ha_router.py -x -q` |
| **Full suite command** | `python -m pytest Backend/` |
| **Estimated runtime** | ~15 seconds (per-router unit tests); ~45 seconds full backend suite |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest Backend/tests/test_ha_router.py -x -q`
- **After every plan wave:** Run `python -m pytest Backend/`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

> Planner will populate this table with one row per generated task. Each row MUST cite a HASS-XX requirement or be explicitly marked "infrastructure" with rationale.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 18-01-XX | 01 | 1 | HASS-XX | — | N/A (no auth, LAN trust boundary) | unit | `python -m pytest Backend/tests/test_ha_router.py::test_X -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/test_ha_router.py` — unit test file for all 7 HA endpoints (Wave 0 creates skeleton with `pytest.fixture` for mocked coordinator + sqlite-in-memory db)
- [ ] `Backend/tests/test_ha_e2e.py` — integration test that walks `PUT zone → PUT camera → POST start → GET status → POST stop` against a real `StreamingCoordinator` with mocked sinks (follows Phase 17 `test_phase17_e2e.py` pattern)
- [ ] Confirm `Backend/tests/conftest.py::_make_coordinator_mock` is reused (no new fixture file needed — RESEARCH.md verified this helper exists)

*If existing infrastructure suffices for any task: cite the file:line from RESEARCH.md.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end HA `rest_command:` round-trip on real network | HASS-01..05 | Requires a real Home Assistant instance and live Hue Bridge; only meaningful as smoke test before milestone close | 1) Add the four `rest_command:` snippets from CONTEXT.md §Specific Ideas to a HA `configuration.yaml`, 2) `curl -X PUT -H 'Content-Type: application/json' -d '{"zone_id":"…"}' http://hpc.local:8000/api/ha/zone`, 3) call `hpc_start` service from HA, 4) verify lights respond, 5) call `hpc_stop`. |

*Automated tests cover all D-01..D-11 contractual behavior; the manual run only confirms HA's own rest_command parser interoperates.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (test_ha_router.py + test_ha_e2e.py)
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
