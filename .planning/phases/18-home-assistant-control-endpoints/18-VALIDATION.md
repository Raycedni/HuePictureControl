---
phase: 18
slug: home-assistant-control-endpoints
status: draft
nyquist_compliant: true
wave_0_complete: true
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
| 18-01-01 | 01 | 1 | HASS-01,03,04 (infra: schema) | T-18-01 | parameterised DDL, single-row CHECK(id=1) | unit (DB) | `cd Backend && python -m pytest tests/ -x -q -k "not test_ha" --tb=short` | exists (regression check) | pending |
| 18-01-02 | 01 | 1 | HASS-01 (infra: coordinator override) | T-18-03 | typed optional kwarg, in-process | unit | `cd Backend && python -m pytest tests/test_streaming_coordinator.py -x -q` | exists (regression check) | pending |
| 18-02-01 | 02 | 2 | HASS-01,02,03,04,05 | T-18-06,07,08,10,12 | parameterised SQL, Field(min_length=1), no Depends, ON CONFLICT DO UPDATE, response_model_exclude_none, try/except httpx.HTTPError | unit + manual import | `cd Backend && python -c "from routers.ha import router; assert len([r for r in router.routes]) == 7"` | created by Plan 03 (test_ha_router.py) | pending |
| 18-02-02 | 02 | 2 | HASS-01,02,03,04,05 (wiring) | T-18-05 | LAN trust boundary, no middleware change | unit + manual import | `cd Backend && python -c "from main import app; paths = {r.path for r in app.routes}; assert '/api/ha/start' in paths"` | implicit (importability) | pending |
| 18-03-01 | 03 | 3 | HASS-01,02,03,04,05 | T-18-06,07,08,10,12,13 | 24 named unit tests (incl. status_handles_partial_bridge_config_row), direct-DB-poke for D-06/D-07, schema-key set check for D-09 | unit | `cd Backend && python -m pytest tests/test_ha_router.py -x -q --tb=short` | created by this task | pending |
| 18-03-02 | 03 | 3 | HASS-01..05 (cross-cut) | T-18-13,14 | real StreamingCoordinator with mocked sinks, state warm-up loops | integration | `cd Backend && python -m pytest tests/test_ha_e2e.py -x -q --tb=short` | created by this task | pending |
| 18-03-03 | 03 | 3 | infrastructure (validation map maintenance) | — | doc-only | doc | `grep -c "^| 18-0" .planning/phases/18-home-assistant-control-endpoints/18-VALIDATION.md` returns >= 7 | created by this task | pending |

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
