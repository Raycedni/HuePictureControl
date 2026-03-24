---
phase: 3
slug: entertainment-api-streaming-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.x + pytest-asyncio 0.24.x (already installed) |
| **Config file** | `Backend/pytest.ini` (exists: `asyncio_mode = auto`) |
| **Quick run command** | `cd Backend && python -m pytest tests/test_streaming_service.py tests/test_streaming_ws.py tests/test_capture_router.py -x -q` |
| **Full suite command** | `cd Backend && python -m pytest tests/ -v` |
| **Estimated runtime** | ~8 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd Backend && python -m pytest tests/ -x -q`
- **After every plan wave:** Run `cd Backend && python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 8 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | STRM-03 | unit (mock hue-entertainment-pykit) | `pytest tests/test_streaming_service.py::TestStreamStart -x` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | STRM-01, STRM-02, STRM-04 | unit (mock capture + streaming) | `pytest tests/test_streaming_service.py::TestFrameLoop -x` | ❌ W0 | ⬜ pending |
| 03-01-03 | 01 | 1 | STRM-06 | unit (16-channel map) | `pytest tests/test_streaming_service.py::TestMultiChannel -x` | ❌ W0 | ⬜ pending |
| 03-01-04 | 01 | 1 | GRAD-05 | unit (single-channel target) | `pytest tests/test_streaming_service.py::TestSingleChannel -x` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 1 | CAPT-03 | unit (mock streaming_service) | `pytest tests/test_capture_router.py::TestStartStop -x` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 1 | CAPT-04 | unit (verify release called) | `pytest tests/test_capture_router.py::TestStopRelease -x` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 2 | status ws | unit (WebSocket connect/broadcast) | `pytest tests/test_streaming_ws.py -x` | ❌ W0 | ⬜ pending |
| 03-04-01 | 04 | 3 | STRM-05 | smoke (physical hardware) | manual — requires capture card + bridge | manual-only | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/test_streaming_service.py` — covers STRM-01..STRM-06, GRAD-05
- [ ] `Backend/tests/test_streaming_ws.py` — covers /ws/status WebSocket
- [ ] Update `Backend/tests/test_capture_router.py` — covers CAPT-03, CAPT-04 (start/stop)
- [ ] Update `Backend/tests/conftest.py` — streaming mock fixtures

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end latency under 100ms | STRM-05 | Requires physical capture card + Hue Bridge | Start streaming, check `/ws/status` latency field < 100ms |
| Lights return to pre-streaming state on Stop | CAPT-04 | Requires physical Hue Bridge | Note light state, start streaming, stop, verify lights return |
| 25-50 Hz frame rate on real hardware | STRM-03 | Hardware-dependent timing | Check `/ws/status` FPS field during streaming |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 8s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
