---
phase: quick-260714-ong
plan: 01
subsystem: capture
tags: [v4l2, ioctl, struct-offset, capture, elgato]

requires:
  - phase: quick-260704-o9r
    provides: Format-aware _decode_frame YUYV/MJPEG content-sniffing that depends on self._width/self._height being correct
provides:
  - Corrected v4l2_format struct offsets (8/12/16) in _setup_device(), accounting for 64-bit alignment padding after the `type` field
  - Named offset constants (_FMT_OFF_WIDTH, _FMT_OFF_HEIGHT, _FMT_OFF_PIXELFORMAT) documenting the padding rationale
  - Regression test exercising the previously-untested _setup_device() ioctl readback path
affects: [capture, preview-ws]

tech-stack:
  added: []
  patterns:
    - "Named byte-offset constants with an explanatory comment instead of magic numbers when packing/unpacking C structs via ctypes/struct, to prevent silent alignment-padding regressions"

key-files:
  created: []
  modified:
    - Backend/services/capture_v4l2.py
    - Backend/tests/test_capture_service.py

key-decisions:
  - "Offsets 8/12/16 confirmed via the plan's proven hex-dump layout (VIDIOC_G_FMT on the live target): 4 bytes of padding exist between `type` (offset 0-3) and the `fmt` union (offset 8) because the union's v4l2_window variant contains a pointer member forcing 8-byte alignment"
  - "Fix scoped strictly to v4l2_format in _setup_device() per plan scope_notes — _v4l2_buffer (ctypes.Structure, used for REQBUFS/QUERYBUF/QBUF/DQBUF) and v4l2_streamparm (S_PARM) were left untouched since neither has a pointer member forcing extra alignment"
  - "_decode_frame's YUYV reshape (self._height, self._width, 2) required no changes — it was already correct once self._width/self._height hold real values"

patterns-established: []

requirements-completed: [BFIX-v4l2-fmt-offset]

duration: ~20min
completed: 2026-07-14
---

# Quick Task 260714-ong: Fix v4l2_format struct offset bug in capture_v4l2.py Summary

**Corrected `_setup_device()`'s VIDIOC_S_FMT pack/unpack offsets from 4/8/12 to 8/12/16, fixing `self._width` resolving to 0 and `self._height` to 640 (the struct's 4-byte alignment padding after `type` was never accounted for), which had silently broken the YUYV decode fallback shipped in quick task 260704-o9r.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-07-14T15:30:00Z (approx)
- **Completed:** 2026-07-14T15:50:39Z
- **Tasks:** 2/2 completed
- **Files modified:** 2

## Accomplishments
- Added three named offset constants (`_FMT_OFF_WIDTH = 8`, `_FMT_OFF_HEIGHT = 12`, `_FMT_OFF_PIXELFORMAT = 16`) with a comment explaining the 8-byte union alignment padding, replacing the previous unlabeled magic-number offsets (4/8/12) in `_setup_device()`.
- Both the `pack_into` calls (request construction) and `unpack_from` calls (readback) in `_setup_device()` now use the corrected offsets, so `self._width`/`self._height` resolve to the driver's real negotiated values (640/480) instead of (0/640).
- Confirmed the fix is scoped only to `v4l2_format` — `_v4l2_buffer` (ctypes.Structure for REQBUFS/QUERYBUF/QBUF/DQBUF) and `v4l2_streamparm` (S_PARM) were left untouched, since neither struct variant has the pointer-member alignment issue.
- Added `TestV4L2SetupDeviceOffsets` regression test class that mocks `fcntl.ioctl`/`mmap.mmap` and simulates the driver writing the empirically-proven byte layout (`width@8`, `height@12`, `YUYV@16`) into the S_FMT buffer, then asserts `self._width == 640` and `self._height == 480` — a path the prior quick task's tests never exercised (they only tested `_decode_frame` directly with width/height already set).
- Verified via a standalone script (fcntl-stub import, since this dev machine is Windows) that the OLD offsets (4/8) against the real proven byte layout would read `width=0, height=640` — exactly matching the bug description in the plan — while the NEW offsets (8/12) correctly read `width=640, height=480`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix v4l2_format field offsets in _setup_device()** - `927f61d` (fix)
2. **Task 2: Add regression test for the S_FMT readback offset path** - `37f9bf5` (test)

## Files Created/Modified
- `Backend/services/capture_v4l2.py` - Added `_FMT_OFF_WIDTH`/`_FMT_OFF_HEIGHT`/`_FMT_OFF_PIXELFORMAT` constants with padding-rationale comment; updated `_setup_device()`'s S_FMT pack_into/unpack_from calls to use them.
- `Backend/tests/test_capture_service.py` - Added `TestV4L2SetupDeviceOffsets` class (1 test) inside the existing `if sys.platform != "win32":` Linux-guarded block, alongside `TestV4L2Decode`.

## Decisions Made
- Offsets 8/12/16 taken verbatim from the plan's proven hex-dump table (empirically captured via `VIDIOC_G_FMT` on the live target: Ubuntu 24.04, kernel 6.8.0, x86_64) — not re-derived.
- Left `_decode_frame`'s YUYV reshape unchanged per plan's scope_notes — it already reads `self._height`/`self._width`, which are now correct.
- Fix strictly scoped to `v4l2_format`; no other ioctl struct in the file was touched, matching the plan's explicit scope boundary.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**Test execution environment (Windows dev machine, Linux-only code path):** Same constraint as the prior quick task (260704-o9r) — `Backend/tests/test_capture_service.py` guards all `V4L2Capture` test classes (including the new `TestV4L2SetupDeviceOffsets`) behind `if sys.platform != "win32":`, and `capture_v4l2.py` unconditionally `import fcntl` (POSIX-only). This dev machine reports `sys.platform == "win32"`, so the new test is silently skipped (not run, not failed) by pytest here.

To verify the offset logic without a real device, I wrote a standalone script that stubs `sys.modules["fcntl"]` with a no-op module, imports `capture_v4l2` directly, and runs the exact same mocked-ioctl scenario as `TestV4L2SetupDeviceOffsets.test_setup_device_resolves_real_width_height`. It asserted `self._width == 640` and `self._height == 480` — both passed. I additionally confirmed (via a separate one-off snippet, not part of the test suite) that applying the OLD offsets (4/8) to the same proven byte layout reads `width=0, height=640`, exactly reproducing the bug symptom described in the plan.

**What ran successfully in this environment:**
- `python -c "import ast; ast.parse(...)"` syntax check on `capture_v4l2.py` — passed.
- `cd Backend && python -m pytest tests/test_capture_service.py -x -q` — 3 passed (the non-guarded `TestFactory` tests; all V4L2 test classes, including the new one, are skipped on win32).
- `cd Backend && python -m pytest -q` (full backend suite) — 409 passed, 21 skipped, 12 failed. The 12 failures are all in `tests/test_cameras_router.py`, identical test names to the ones documented as pre-existing in the prior quick task's SUMMARY (260704-o9r) and STATE.md ("Pre-existing 12 test_cameras_router.py failures logged to deferred-items.md as out-of-scope"). Confirmed out of scope — unrelated file, unrelated to this plan's changes, unchanged failure count/names before and after this plan's edits.
- Standalone fcntl-stub verification script — all assertions passed, confirming both the fix and the bug it corrects.

**What could NOT run in this environment:**
- The actual `TestV4L2SetupDeviceOffsets` pytest class (skipped due to `sys.platform == "win32"` guard) — logic instead verified via the standalone stub-import script described above.
- Any real V4L2 ioctl path against actual hardware — inherently untestable on Windows; unchanged from before this plan.

## User Setup Required

None - no external service configuration required. This is a backend-only code fix; deploying to the Linux host running the actual capture hardware (per `.claude/vm-exec.sh` deploy pattern) is the user's follow-up manual step if they want to confirm the fix against the live Elgato 4K S device.

## Next Phase Readiness

Code change is complete and committed (`927f61d`, `37f9bf5`). This closes the loop on the YUYV fallback introduced in quick task 260704-o9r/260714-o9r — `self._width`/`self._height` now resolve to real driver-negotiated values, so the `len(data) == self._width * self._height * 2` check in `_decode_frame` can actually match a real 614400-byte YUYV frame instead of comparing against 0 forever. Ready to be deployed to the Linux host for real-world confirmation. No blockers.

---
*Phase: quick-260714-ong*
*Completed: 2026-07-14*

## Self-Check: PASSED

- FOUND: Backend/services/capture_v4l2.py
- FOUND: Backend/tests/test_capture_service.py
- FOUND: .planning/quick/260714-ong-fix-v4l2-format-struct-offset-bug-in-cap/260714-ong-SUMMARY.md
- FOUND commit: 927f61d (fix task)
- FOUND commit: 37f9bf5 (test task)
