---
phase: 1
slug: infrastructure-and-dtls-spike
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-23
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio (backend), Vitest + React Testing Library (frontend) |
| **Config file** | `Backend/pytest.ini` (Wave 0 creates), `Frontend/vitest.config.ts` (Wave 0 creates) |
| **Quick run command** | `cd Backend && python -m pytest tests/ -x -q` |
| **Full suite command** | `cd Backend && python -m pytest tests/ -v && cd ../Frontend && npm run test` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd Backend && python -m pytest tests/ -x -q`
- **After every plan wave:** Run `cd Backend && python -m pytest tests/ -v && cd ../Frontend && npm run test`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | INFR-01 | smoke | `docker compose up --wait && curl http://localhost/api/health` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | INFR-02 | smoke | manual — requires capture card hardware | manual | ⬜ pending |
| 01-01-03 | 01 | 1 | INFR-03 | smoke | manual — requires bridge on LAN | manual | ⬜ pending |
| 01-01-04 | 01 | 1 | INFR-05 | integration | `pytest tests/test_database.py::test_db_file_created -x` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | BRDG-01 | unit | `pytest tests/test_hue_router.py::test_pair_success -x` | ❌ W0 | ⬜ pending |
| 01-02-02 | 02 | 1 | BRDG-01 | unit | `pytest tests/test_hue_router.py::test_pair_link_button_not_pressed -x` | ❌ W0 | ⬜ pending |
| 01-02-03 | 02 | 1 | BRDG-02 | integration | `pytest tests/test_database.py::test_credentials_persist -x` | ❌ W0 | ⬜ pending |
| 01-02-04 | 02 | 1 | BRDG-03 | unit | `pytest tests/test_hue_router.py::test_list_configs -x` | ❌ W0 | ⬜ pending |
| 01-02-05 | 02 | 1 | BRDG-05 | integration | manual — requires physical bridge | manual | ⬜ pending |
| 01-03-01 | 03 | 2 | UI-02 | unit | `cd Frontend && npm run test -- PairingFlow` | ❌ W0 | ⬜ pending |
| 01-04-01 | 04 | 2 | BRDG-05 | spike | manual — DTLS test script with real bridge | manual | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/__init__.py` — package marker
- [ ] `Backend/tests/conftest.py` — shared fixtures (in-memory aiosqlite, mock httpx)
- [ ] `Backend/tests/test_hue_router.py` — covers BRDG-01, BRDG-03
- [ ] `Backend/tests/test_database.py` — covers BRDG-02, INFR-05
- [ ] `Backend/pytest.ini` — pytest-asyncio mode = auto
- [ ] `Frontend/src/components/PairingFlow.test.tsx` — covers UI-02
- [ ] `Frontend/vitest.config.ts` — Vitest configuration
- [ ] Framework install: `pip install pytest pytest-asyncio httpx` (backend) + `npm install -D vitest @testing-library/react @testing-library/jest-dom` (frontend)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| USB device accessible inside container | INFR-02 | Requires physical capture card | Run `docker compose exec backend ls /dev/video0` |
| Bridge reachable from host network | INFR-03 | Requires bridge on LAN | Run `docker compose exec backend curl -sk https://<bridge-ip>/api` |
| Entertainment configs list from real bridge | BRDG-05 | Requires paired bridge | Check UI shows entertainment configurations after pairing |
| DTLS spike changes real light color | Phase gate | Requires physical bridge + light | Run `python spike/dtls_test.py` and observe light |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
