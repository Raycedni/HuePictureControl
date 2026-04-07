---
phase: 10
slug: frontend-camera-selector
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-07
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Vitest + @testing-library/react |
| **Config file** | `Frontend/vitest.config.ts` |
| **Quick run command** | `cd Frontend && npx vitest run` |
| **Full suite command** | `cd Frontend && npx vitest run` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd Frontend && npx vitest run`
- **After every plan wave:** Run `cd Frontend && npx vitest run`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 10-01-01 | 01 | 1 | CMUI-01 | unit | `cd Frontend && npx vitest run --reporter=verbose src/components/LightPanel.test.tsx` | ❌ W0 | ⬜ pending |
| 10-01-02 | 01 | 1 | CMUI-02 | unit | `cd Frontend && npx vitest run --reporter=verbose src/components/LightPanel.test.tsx` | ❌ W0 | ⬜ pending |
| 10-01-03 | 01 | 1 | CMUI-03 | unit | `cd Frontend && npx vitest run --reporter=verbose src/hooks/usePreviewWS.test.ts` | ✅ (needs update) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Frontend/src/components/LightPanel.test.tsx` — stubs for CMUI-01, CMUI-02 (zone and camera dropdown rendering, option format)
- [ ] `Frontend/src/api/cameras.test.ts` — covers `getCameras()` and `putCameraAssignment()` fetch wrappers
- [ ] Update `Frontend/src/hooks/usePreviewWS.test.ts` — pass `device` arg to fix baseline failure

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live preview switches within 2s | CMUI-03 | Real WebSocket + camera hardware needed | 1. Open editor 2. Select different camera 3. Verify preview updates within 2s |
| Camera assignment persists after restart | CMUI-03 | Requires full Docker restart cycle | 1. Assign camera 2. docker compose restart 3. Verify correct camera pre-selected |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
