---
phase: 7
slug: device-enumeration-and-camera-assignment-schema
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-03
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3 + pytest-asyncio 0.24 |
| **Config file** | `Backend/pytest.ini` |
| **Quick run command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_cameras_router.py tests/test_device_enum.py tests/test_device_identity.py tests/test_database.py -x` |
| **Full suite command** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_cameras_router.py tests/test_device_enum.py tests/test_device_identity.py tests/test_database.py -x`
- **After every plan wave:** Run `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 0 | DEVC-01 | unit | `pytest tests/test_device_enum.py::test_metadata_node_excluded -x` | ❌ W0 | ⬜ pending |
| 07-01-02 | 01 | 0 | DEVC-01 | unit | `pytest tests/test_device_enum.py::test_only_capture_nodes_returned -x` | ❌ W0 | ⬜ pending |
| 07-02-01 | 02 | 1 | DEVC-02 | unit | `pytest tests/test_cameras_router.py::TestListCameras::test_returns_200 -x` | ❌ W0 | ⬜ pending |
| 07-02-02 | 02 | 1 | DEVC-02 | unit | `pytest tests/test_cameras_router.py::TestListCameras::test_device_fields -x` | ❌ W0 | ⬜ pending |
| 07-02-03 | 02 | 1 | DEVC-03 | unit | `pytest tests/test_cameras_router.py::TestListCameras::test_no_cache -x` | ❌ W0 | ⬜ pending |
| 07-02-04 | 02 | 1 | DEVC-04 | unit | `pytest tests/test_device_identity.py::test_sysfs_stable_id -x` | ❌ W0 | ⬜ pending |
| 07-02-05 | 02 | 1 | DEVC-04 | unit | `pytest tests/test_device_identity.py::test_degraded_stable_id -x` | ❌ W0 | ⬜ pending |
| 07-02-06 | 02 | 1 | DEVC-04 | unit | `pytest tests/test_cameras_router.py::TestListCameras::test_degraded_identity_mode -x` | ❌ W0 | ⬜ pending |
| 07-03-01 | 03 | 1 | DEVC-05 | unit | `pytest tests/test_cameras_router.py::TestReconnect::test_reconnect_found -x` | ❌ W0 | ⬜ pending |
| 07-03-02 | 03 | 1 | DEVC-05 | unit | `pytest tests/test_cameras_router.py::TestReconnect::test_reconnect_not_found -x` | ❌ W0 | ⬜ pending |
| 07-04-01 | 04 | 1 | CAMA-01 | unit | `pytest tests/test_database.py::test_camera_assignments_table_created -x` | ❌ W0 | ⬜ pending |
| 07-04-02 | 04 | 1 | CAMA-02 | unit | `pytest tests/test_database.py::test_camera_assignment_persists -x` | ❌ W0 | ⬜ pending |
| 07-04-03 | 04 | 1 | CAMA-03 | unit | `pytest tests/test_cameras_router.py::TestAssignment::test_no_assignment_returns_404 -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/test_cameras_router.py` — stubs for DEVC-02, DEVC-03, DEVC-04, DEVC-05, CAMA-03
- [ ] `Backend/tests/test_device_enum.py` — stubs for DEVC-01; mock `glob.glob` + `fcntl.ioctl`
- [ ] `Backend/tests/test_device_identity.py` — stubs for DEVC-04 sysfs path; mock `builtins.open` for sysfs reads
- [ ] `Backend/services/device_identity.py` — new module (must exist before tests)
- [ ] `Backend/routers/cameras.py` — new router (must exist before router tests)

*Note: `conftest.py` already has the `db` fixture and `app_client` pattern needed. No new conftest additions required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Hot-plug detection (second card) | DEVC-03 | Requires physical USB hardware | Plug second capture card, call `GET /api/cameras`, verify new device appears |
| sysfs identity in real Docker | DEVC-04 | Requires USB passthrough to container | Attach USB capture card via `usbipd`, verify `identity_mode: "full"` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
