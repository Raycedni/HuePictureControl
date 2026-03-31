---
phase: 5
slug: gradient-device-support-and-polish
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-31
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (Backend), vitest (Frontend) |
| **Config file** | Backend/pytest.ini, Frontend/vite.config.ts |
| **Quick run command** | `cd Backend && python -m pytest tests/ -x -q` |
| **Full suite command** | `cd Backend && python -m pytest tests/ && cd ../Frontend && npx vitest run` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd Backend && python -m pytest tests/ -x -q`
- **After every plan wave:** Run `cd Backend && python -m pytest tests/ && cd ../Frontend && npx vitest run`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | BRDG-04 | unit | `pytest tests/test_hue_client.py -x -k channel` | ✅ (extend) | ⬜ pending |
| 05-01-02 | 01 | 1 | BRDG-04 | unit | `pytest tests/test_hue_client.py -x -k segment_map` | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 1 | BRDG-04 | unit | `pytest tests/test_hue_client.py -x -k gradient` | ✅ (extend) | ⬜ pending |
| 05-02-01 | 02 | 1 | GRAD-01/02/03 | manual | visual inspection with physical device | N/A | ⬜ pending |
| 05-02-02 | 02 | 1 | GRAD-04 | unit | `npx vitest run src/components/LightPanel.test.tsx` | ❌ W0 | ⬜ pending |
| 05-02-03 | 02 | 1 | GRAD-04 | unit | `npx vitest run src/store/useRegionStore.test.ts` | ✅ (extend) | ⬜ pending |
| 05-03-01 | 03 | 2 | — | unit | `pytest tests/test_streaming_service.py -x -k reconnect` | ✅ (extend) | ⬜ pending |
| 05-03-02 | 03 | 2 | — | unit | `pytest tests/test_streaming_service.py -x -k capture_reconnect` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/test_hue_client.py` — add tests for extended channel fields (service_rid, segment_index) and `build_light_segment_map`
- [ ] `Frontend/src/components/LightPanel.test.tsx` — covers GRAD-04 warning banner and channel counter display
- [ ] `Backend/tests/test_streaming_service.py` — add test for `_capture_reconnect_loop` with mock capture.open() retry behavior

*Existing infrastructure covers framework installation — pytest and vitest already configured.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Gradient segments appear as individual rows in LightPanel | GRAD-01/02/03 | Requires physical gradient device on bridge | Connect gradient light, verify segment rows match entertainment config channel count |
| Per-segment colors match assigned screen regions | GRAD-01/02/03 | Requires physical device + capture card | Assign different regions to different segments, verify distinct colors |
| Festavia actual channel count | BRDG-04 | Underdocumented, hardware-only | Connect Festavia, count channels in entertainment config vs UI display |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
