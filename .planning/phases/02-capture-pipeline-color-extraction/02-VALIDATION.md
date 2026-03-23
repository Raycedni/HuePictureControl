---
phase: 2
slug: capture-pipeline-color-extraction
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-23
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.x + pytest-asyncio 0.24.x (already installed) |
| **Config file** | `Backend/pytest.ini` (already exists: `asyncio_mode = auto`) |
| **Quick run command** | `cd Backend && python -m pytest tests/ -x -q` |
| **Full suite command** | `cd Backend && python -m pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd Backend && python -m pytest tests/ -x -q`
- **After every plan wave:** Run `cd Backend && python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | CAPT-01 | unit (mock cv2) | `pytest tests/test_capture_service.py::test_open_sets_mjpg_640_480 -x` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | CAPT-01 | unit (mock cap.read) | `pytest tests/test_capture_service.py::test_get_frame_returns_array -x` | ❌ W0 | ⬜ pending |
| 02-01-03 | 01 | 1 | CAPT-01 | unit | `pytest tests/test_capture_service.py::test_get_frame_no_device -x` | ❌ W0 | ⬜ pending |
| 02-01-04 | 01 | 1 | CAPT-02 | unit (mock LatestFrameCapture) | `pytest tests/test_capture_router.py::test_set_device_reopens -x` | ❌ W0 | ⬜ pending |
| 02-01-05 | 01 | 1 | CAPT-02 | unit (mock env + cap) | `pytest tests/test_capture_service.py::test_env_device_path -x` | ❌ W0 | ⬜ pending |
| 02-01-06 | 01 | 1 | CAPT-05 | unit (mock get_frame + imencode) | `pytest tests/test_capture_router.py::test_snapshot_returns_jpeg -x` | ❌ W0 | ⬜ pending |
| 02-01-07 | 01 | 1 | CAPT-05 | unit | `pytest tests/test_capture_router.py::test_snapshot_no_device_503 -x` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | color math | unit | `pytest tests/test_color_math.py::test_red_in_gamut -x` | ❌ W0 | ⬜ pending |
| 02-02-02 | 02 | 1 | color math | unit | `pytest tests/test_color_math.py::test_black_no_divide_by_zero -x` | ❌ W0 | ⬜ pending |
| 02-02-03 | 02 | 1 | color math | unit | `pytest tests/test_color_math.py::test_out_of_gamut_clamped -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/test_capture_service.py` — stubs for CAPT-01, CAPT-02
- [ ] `Backend/tests/test_capture_router.py` — stubs for CAPT-05
- [ ] `Backend/tests/test_color_math.py` — stubs for color math correctness
- [ ] `pip install opencv-python-headless>=4.10,<5` — add to `Backend/requirements.txt`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Snapshot on real hardware returns JPEG within 200ms | CAPT-05 | Requires physical capture card | `curl -o /dev/null -w '%{time_total}' http://localhost:8000/api/capture/snapshot` — verify < 0.2s |
| MJPEG mode applied on specific capture card | CAPT-01 | Hardware-dependent format negotiation | Check debug log for actual FOURCC after device open |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
