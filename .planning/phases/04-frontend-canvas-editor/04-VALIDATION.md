---
phase: 4
slug: frontend-canvas-editor
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Vitest 4.x + @testing-library/react 16.x (frontend), pytest 7.x (backend) |
| **Config file** | `Frontend/vitest.config.ts` (exists), `Backend/pytest.ini` |
| **Quick run command** | `cd Frontend && npm test` |
| **Full suite command** | `cd Frontend && npm test && cd ../Backend && pytest` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd Frontend && npm test`
- **After every plan wave:** Run `cd Frontend && npm test && cd ../Backend && pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | REGN-01 | unit | `npm test -- useRegionStore` | ❌ W0 | ⬜ pending |
| 04-01-02 | 01 | 1 | REGN-02 | unit | `npm test -- useRegionStore` | ❌ W0 | ⬜ pending |
| 04-01-03 | 01 | 1 | REGN-03 | unit | `npm test -- useRegionStore` | ❌ W0 | ⬜ pending |
| 04-01-04 | 01 | 1 | REGN-04 | unit | `npm test -- geometry` | ❌ W0 | ⬜ pending |
| 04-01-05 | 01 | 1 | REGN-06 | unit | `npm test -- usePreviewWS` | ❌ W0 | ⬜ pending |
| 04-02-01 | 02 | 1 | UI-03 | unit | `npm test -- EditorPage` | ❌ W0 | ⬜ pending |
| 04-02-02 | 02 | 1 | UI-04 | unit | `npm test -- useStatusStore` | ❌ W0 | ⬜ pending |
| 04-02-03 | 02 | 1 | UI-05 | unit | `npm test -- LightPanel` | ❌ W0 | ⬜ pending |
| 04-BE-01 | BE | 1 | REGN-05 | unit | `pytest tests/test_regions_router.py` | ❌ W0 | ⬜ pending |
| 04-BE-02 | BE | 1 | REGN-06 | unit | `pytest tests/test_preview_ws.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Frontend/src/store/useRegionStore.test.ts` — stubs for REGN-01, REGN-02, REGN-03
- [ ] `Frontend/src/store/useStatusStore.test.ts` — stubs for UI-04
- [ ] `Frontend/src/hooks/usePreviewWS.test.ts` — stubs for REGN-06
- [ ] `Frontend/src/utils/geometry.test.ts` — stubs for REGN-04
- [ ] `Backend/tests/test_preview_ws.py` — stubs for /ws/preview binary streaming
- [ ] `Backend/tests/test_regions_router.py` — extend for PUT, DELETE, POST
- [ ] `cd Frontend && npm install zustand konva react-konva use-image` — if not yet installed

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live camera preview at ≥10 fps | REGN-06, UI-01 | Requires physical camera + WebSocket streaming | Start capture, open browser, verify preview updates smoothly |
| Polygon draw + drag interaction | REGN-01, REGN-02 | Canvas interaction requires visual verification | Draw polygon, drag vertices, verify shape updates |
| Light color updates in real-time | UI-06 | Requires Hue bridge hardware | Assign region to light, start capture, verify light color matches |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
