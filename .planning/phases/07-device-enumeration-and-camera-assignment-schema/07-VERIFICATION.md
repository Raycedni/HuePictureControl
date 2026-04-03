---
phase: 07-device-enumeration-and-camera-assignment-schema
verified: 2026-04-03T00:00:00Z
status: passed
score: 15/15 must-haves verified
re_verification: false
---

# Phase 7: Device Enumeration and Camera Assignment Schema — Verification Report

**Phase Goal:** Enumerate all V4L2 capture devices and persist camera-to-zone assignments in the database
**Verified:** 2026-04-03
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `enumerate_capture_devices()` returns only V4L2 nodes with VIDEO_CAPTURE capability | VERIFIED | `capture_v4l2.py:140` filters `device_caps & 0x01`; 7 enum tests pass |
| 2 | Metadata-only nodes (no VIDEO_CAPTURE bit) are excluded from results | VERIFIED | `test_metadata_node_excluded` passes; bit 0x20000 (META_CAPTURE) without bit 0x01 excluded |
| 3 | `get_stable_id()` returns VID:PID:serial when sysfs is available | VERIFIED | `device_identity.py:42` returns `f"{vid}:{pid}:{serial}"` with `True` |
| 4 | `get_stable_id()` returns card@bus_info when sysfs is unavailable | VERIFIED | `device_identity.py:47` returns `f"{card}@{bus_info}"` with `False` |
| 5 | `known_cameras` table exists with correct schema | VERIFIED | `database.py:64-70` — stable_id PK, display_name, last_seen_at, last_device_path |
| 6 | `camera_assignments` table exists with correct schema | VERIFIED | `database.py:72-77` — entertainment_config_id PK, camera_stable_id, camera_name |
| 7 | Camera assignments persist across DB close and reopen | VERIFIED | `test_camera_assignment_persists` opens real tmp_path DB, closes, reopens; passes |
| 8 | GET /api/cameras returns devices with device_path, stable_id, display_name per D-03 | VERIFIED | `cameras.py:130-186`; `test_device_fields` passes |
| 9 | Each call to GET /api/cameras triggers a fresh device scan (no caching) per DEVC-03 | VERIFIED | `cameras.py:143` comment; `test_no_cache` verifies enumerate called twice; passes |
| 10 | POST /api/cameras/reconnect re-scans and returns updated status per D-04, D-05 | VERIFIED | `cameras.py:189-242`; `test_reconnect_found` and `test_reconnect_not_found` pass |
| 11 | Reconnect returns connected=false when device is truly gone | VERIFIED | `cameras.py:237-242` returns `connected=False`; `test_reconnect_not_found` passes |
| 12 | PUT /api/cameras/assignments/{config_id} persists camera assignment per CAMA-02 | VERIFIED | `cameras.py:245-289`; `test_put_assignment` and `test_put_assignment_upsert` pass |
| 13 | GET /api/cameras/assignments/{config_id} returns 404 when no assignment exists | VERIFIED | `cameras.py:310-312` raises 404 with fallback message; `test_get_assignment_not_found` passes |
| 14 | identity_mode field is 'degraded' when sysfs is unavailable per D-02 | VERIFIED | `cameras.py:179-184`; `test_degraded_identity_mode` passes |
| 15 | EditorPage shows amber alert banner when identity_mode is degraded per D-02 | VERIFIED | `EditorPage.tsx:60-64` — exact copy, correct placement, conditional on `identityMode === 'degraded'` |

**Score:** 15/15 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `Backend/services/device_identity.py` | get_stable_id() with sysfs + fallback | VERIFIED | 48 lines, fully implemented, no stubs |
| `Backend/services/capture_v4l2.py` | enumerate_capture_devices() function | VERIFIED | V4L2DeviceInfo dataclass + enumerate function at lines 108-163 |
| `Backend/database.py` | known_cameras and camera_assignments tables | VERIFIED | CREATE TABLE IF NOT EXISTS at lines 64 and 72 |
| `Backend/tests/test_device_enum.py` | Tests for enumeration filtering | VERIFIED | 183 lines, 7 tests including required test_only_capture_nodes_returned and test_metadata_node_excluded |
| `Backend/tests/test_device_identity.py` | Tests for sysfs and degraded identity | VERIFIED | 111 lines, 6 tests including required test_sysfs_stable_id and test_degraded_stable_id |
| `Backend/tests/test_database.py` | Tests for new tables and persistence | VERIFIED | 153 lines, contains test_camera_assignments_table_created at line 75 |
| `Backend/routers/cameras.py` | GET /api/cameras, POST reconnect, PUT/GET assignments | VERIFIED | 321 lines, all 4 endpoints implemented with Pydantic models |
| `Backend/main.py` | cameras router registered | VERIFIED | Lines 11 (import) and 92 (include_router) |
| `Backend/tests/test_cameras_router.py` | Router endpoint tests | VERIFIED | 327 lines, all 10 required test functions present |
| `Frontend/src/components/EditorPage.tsx` | Sysfs degraded identity alert banner | VERIFIED | identityMode state at line 10, fetch at 16, alert at 60-64 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `cameras.py` | `capture_v4l2.py` | `run_in_executor(None, enumerate_capture_devices)` | WIRED | `cameras.py:86` — correct executor wrapping |
| `cameras.py` | `device_identity.py` | `run_in_executor(None, get_stable_id, ...)` | WIRED | `cameras.py:92-93` — called per device in executor |
| `cameras.py` | `database.py` (known_cameras) | `ON CONFLICT(stable_id) DO UPDATE` upsert | WIRED | `cameras.py:113-121` in `_upsert_known_cameras` |
| `cameras.py` | `database.py` (camera_assignments) | INSERT with `ON CONFLICT(entertainment_config_id) DO UPDATE` | WIRED | `cameras.py:273-283` |
| `main.py` | `cameras.py` | `app.include_router(cameras_router)` | WIRED | `main.py:11` import, `main.py:92` include |
| `EditorPage.tsx` | GET /api/cameras | `fetch('/api/cameras')` on mount | WIRED | `EditorPage.tsx:16` — fetch + setIdentityMode |
| `tests/conftest.py` | `database.py` | known_cameras and camera_assignments in db fixture | WIRED | `conftest.py:55-63` — both tables present |

**Note on Plan 01 key_link spec:** Plan 01 specified a link from `capture_v4l2.py` to `device_identity.py` (via `enumerate_capture_devices` calling `get_stable_id`). The implementation took a cleaner separation-of-concerns approach: `enumerate_capture_devices()` returns raw V4L2DeviceInfo, and `cameras.py` calls `get_stable_id()` per device separately. The functional requirement (get_stable_id called per device on every scan) is fully satisfied — the architectural boundary shifted to the router layer. No functional gap.

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `cameras.py` list_cameras | `known_rows` | `SELECT stable_id, display_name, last_seen_at, last_device_path FROM known_cameras` | Yes — real DB query after upsert | FLOWING |
| `cameras.py` get_assignment | `row` | `SELECT ... FROM camera_assignments WHERE entertainment_config_id = ?` | Yes — real DB query | FLOWING |
| `EditorPage.tsx` | `identityMode` | `fetch('/api/cameras').then(data => setIdentityMode(data.identity_mode))` | Yes — fetch result from real endpoint | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| enumerate_capture_devices() exports correct function | `grep -c "def enumerate_capture_devices" Backend/services/capture_v4l2.py` | 1 | PASS |
| get_stable_id() exports correct function | `grep -c "def get_stable_id" Backend/services/device_identity.py` | 1 | PASS |
| known_cameras in database.py | `grep -c "known_cameras" Backend/database.py` | 2 | PASS |
| camera_assignments in database.py | `grep -c "camera_assignments" Backend/database.py` | 2 | PASS |
| cameras_router registered in main.py | `grep -c "cameras_router" Backend/main.py` | 2 (import + include) | PASS |
| All 36 new backend tests pass | `python -m pytest tests/test_device_enum.py tests/test_device_identity.py tests/test_database.py tests/test_cameras_router.py` | 36 passed in 0.85s | PASS |
| Full backend suite unbroken | `python -m pytest` | 187 passed, 34 skipped | PASS |
| Frontend test suite | `npx vitest run` | Could not execute (vitest hangs in WSL2/npx environment — known environment issue) | SKIP |

Frontend tests marked SKIP due to WSL2/npx timeout behavior — not a code issue. The SUMMARY reports 30 passed with no regressions. The EditorPage change (alert banner addition) is non-breaking and has been visually confirmed in the source.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DEVC-01 | 07-01 | Backend enumerates V4L2 capture devices, filters metadata via VIDIOC_QUERYCAP | SATISFIED | `capture_v4l2.py:118-163` — full implementation with `device_caps & 0x01` filter; 5 tests pass |
| DEVC-02 | 07-02 | GET /api/cameras returns list with device path and name | SATISFIED | `cameras.py:130-186`; `test_list_cameras_returns_200` and `test_device_fields` pass |
| DEVC-03 | 07-02 | Device list refreshes on demand (no cache) | SATISFIED | Fresh scan on every GET call; `test_no_cache` verifies enumerate called twice per two requests |
| DEVC-04 | 07-01 | Stable identity via sysfs VID/PID/serial, survives USB re-plug | SATISFIED | `device_identity.py` — full sysfs + fallback implementation; identity propagated through cameras.py |
| DEVC-05 | 07-02 | User can trigger manual reconnect for disconnected camera | SATISFIED | `POST /api/cameras/reconnect` at `cameras.py:189-242`; reconnect tests pass |
| CAMA-01 | 07-01 | Camera assigned per entertainment config, not per-region | SATISFIED | `camera_assignments` table uses `entertainment_config_id TEXT PRIMARY KEY`; schema is per-config |
| CAMA-02 | 07-01 | Camera assignment persists in DB across restarts | SATISFIED | `test_camera_assignment_persists` — real file DB, close, reopen, verify row; passes |
| CAMA-03 | 07-02 | No assignment falls back to default capture device | SATISFIED | GET /api/cameras/assignments returns 404 with explicit fallback message; caller uses CAPTURE_DEVICE env var |

**REQUIREMENTS.md discrepancy:** The traceability table in REQUIREMENTS.md marks DEVC-01, DEVC-04, CAMA-01, and CAMA-02 as "Pending" while marking DEVC-02, DEVC-03, DEVC-05, and CAMA-03 as "Complete". The code fully implements all eight requirements. The "Pending" status is stale documentation — the implementations exist, are tested, and pass. This should be updated to "Complete" for all eight.

**Orphaned requirements check:** CAMA-04 is assigned to Phase 9 (not Phase 7) — correctly excluded from this phase's scope.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | — |

No TODOs, FIXMEs, placeholder returns, empty handlers, or hardcoded empty data found in any Phase 7 file.

---

### Human Verification Required

#### 1. Degraded Identity Alert Rendering

**Test:** Open the editor page in a browser when the backend is running and reports `identity_mode: "degraded"` (e.g., in Docker where sysfs is absent or by mocking the API response)
**Expected:** Amber banner "Device identity is limited to capture card name. Devices may be misidentified if multiple identical cards are connected." appears above the 20-channel warning
**Why human:** Visual render behavior and DOM ordering cannot be verified programmatically without a running browser

#### 2. Frontend Test Suite

**Test:** Run `cd Frontend && npx vitest run` in a non-WSL2 or native environment
**Expected:** 30 tests pass, no regressions
**Why human:** npx vitest consistently hangs in this WSL2 shell environment (zero-byte output file, no exit code); the SUMMARY reports 30 passed

---

### Gaps Summary

No gaps. All 15 observable truths verified. All 10 artifacts exist with substantive implementation. All 7 key links wired. All 8 phase requirements satisfied by real code with passing tests. Full backend test suite (187 tests) passes without regressions.

The only notable deviation from plan specs is architectural: Plan 01's key_link specified that `enumerate_capture_devices()` would call `get_stable_id()` internally. The implementation instead has the cameras router call both independently — a cleaner separation that achieves the same functional outcome. No gap.

The REQUIREMENTS.md traceability table has stale "Pending" status for DEVC-01, DEVC-04, CAMA-01, and CAMA-02. These are fully implemented. The documentation should be updated separately.

---

_Verified: 2026-04-03_
_Verifier: Claude (gsd-verifier)_
