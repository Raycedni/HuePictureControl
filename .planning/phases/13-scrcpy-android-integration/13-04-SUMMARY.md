---
phase: 13-scrcpy-android-integration
plan: "04"
subsystem: backend-capture
tags: [v4l2, v4l2loopback, scrcpy, gap-closure, G-13-01, yuyv, yu12, mjpeg, format-negotiation, ioctl]

# Dependency graph
requires:
  - phase: 13-01
    provides: ADB lifecycle, stale-frame watchdog, error codes
  - phase: 13-02
    provides: POST/DELETE /api/wireless/scrcpy endpoints, is_wireless camera tagging
  - phase: 13-03
    provides: 18 PipelineManager unit tests pinning scrcpy integration
provides:
  - format-agnostic V4L2Capture (MJPEG, YUYV, YU12)
  - VIDIOC_G_FMT fallback on EINVAL for producer-owned formats
  - scrcpy -> V4L2Capture integration unblocked
affects:
  - Phase 14 (Miracast) — same v4l2loopback consumer path now works for any producer-owned format
  - SC-3 verification — Hue lights now drivable from Android screen via scrcpy

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "V4L2 S_FMT with G_FMT fallback on errno.EINVAL (producer-owned format negotiation)"
    - "Reader-loop pixel-format dispatch: self._pixelformat branch -> cv2.imdecode / cv2.cvtColor"
    - "Short-frame defensive skip (used < expected) before np.frombuffer + reshape"
    - "Module-level pytest.mark.skipif gate for Linux-only V4L2 tests"
    - "fcntl.ioctl mocking via unittest.mock.patch at services.capture_v4l2.fcntl.ioctl"

key-files:
  created:
    - Backend/tests/test_capture_v4l2.py
  modified:
    - Backend/services/capture_v4l2.py

key-decisions:
  - "Only errno.EINVAL is caught in the S_FMT fallback path — every other OSError propagates so real device errors surface to the caller (T-13-06 mitigation)."
  - "Unsupported pixel formats raise RuntimeError at _setup_device before buffer allocation — fail-fast rather than silently accept a format the reader thread cannot decode (T-13-04 mitigation)."
  - "Raw-YUV paths leave self._latest_jpeg = None; existing get_jpeg() callers fall back to re-encoding the BGR frame. Avoids paying JPEG encode cost on every raw-YUV frame when no one asks for JPEG."
  - "Reshape math reads self._width/self._height (resolved values) not module-level _WIDTH/_HEIGHT so scrcpy's phone resolution (typically 1080x2400) is honored."
  - "cv2.imdecode is kept exclusively in the MJPEG branch; no shared decode helper. Keeps the three format paths independently auditable."

patterns-established:
  - "Producer-owned format negotiation: try S_FMT -> on EINVAL call G_FMT -> reject unsupported pixelformat. Reusable for any v4l2loopback consumer."
  - "Linux-only V4L2 tests module-gated with pytest.mark.skipif(sys.platform == 'win32') and a top-level 'if sys.platform != \"win32\":' block guarding all imports."

requirements-completed: [SCPY-01, SCPY-02, SCPY-03, SCPY-04, WAPI-03]

# Metrics
duration: 35min
completed: 2026-04-18
---

# Phase 13 Plan 04: Format-Agnostic V4L2Capture Summary

**V4L2Capture now negotiates MJPEG/YUYV/YU12 via VIDIOC_S_FMT with VIDIOC_G_FMT fallback on EINVAL, unblocking scrcpy's raw-YUV output to the existing Hue streaming pipeline without regressing the physical UVC camera path.**

## Performance

- **Duration:** ~35 min (elapsed executor time; human UAT checkpoint pending)
- **Started:** 2026-04-18T10:50:00Z (approx, worktree agent start)
- **Completed (code):** 2026-04-18T11:23:36Z
- **Tasks:** 2 of 3 auto-tasks complete; Task 3 is a blocking human-UAT checkpoint (pending)
- **Files modified:** 1 source file + 1 new test file

## Accomplishments

- Closed code-level root cause of gap **G-13-01** in `Backend/services/capture_v4l2.py`:
  - Added `errno` import, YUYV/YU12 FourCC constants, `_VIDIOC_G_FMT` ioctl number
  - `V4L2Capture.__init__` now seeds `_pixelformat`, `_width`, `_height` with MJPEG 640x480 defaults
  - `_setup_device` attempts `VIDIOC_S_FMT` at the legacy MJPEG 640x480 and, on `OSError(errno.EINVAL)` only, falls back to `VIDIOC_G_FMT` to adopt the producer's pixel format and resolution
  - Non-`EINVAL` `OSError` propagates unchanged (real device errors still surface)
  - Unsupported pixel formats raise `RuntimeError` before buffer allocation
  - `_reader_loop` decodes based on resolved `self._pixelformat`:
    - `MJPEG` -> `cv2.imdecode(np.frombuffer(raw, uint8), IMREAD_COLOR)` (existing path, unchanged)
    - `YUYV` -> `np.frombuffer(raw, uint8, count=W*H*2).reshape((H, W, 2))` + `cv2.cvtColor(..., COLOR_YUV2BGR_YUYV)`
    - `YU12` -> `np.frombuffer(raw, uint8, count=W*H*3//2).reshape((H*3//2, W))` + `cv2.cvtColor(..., COLOR_YUV2BGR_I420)`
  - Short-frame defensive skip (`used < expected`) protects the reshape from out-of-bounds reads on a misbehaving producer (T-13-05 mitigation)
  - `open()` log line now reports the resolved pixelformat (hex) and resolution
- Added `Backend/tests/test_capture_v4l2.py` with 6 Linux-gated tests covering:
  - S_FMT success path (physical-camera MJPEG 640x480 regression guard)
  - S_FMT EINVAL -> G_FMT fallback for YU12 1080x2400 (scrcpy case)
  - S_FMT EINVAL -> G_FMT fallback for YUYV 1920x1080 (other common producers)
  - Non-EINVAL OSError propagation (EBUSY is not swallowed)
  - Unsupported pixelformat (`0xDEADBEEF`) raising `RuntimeError`
  - YUYV reshape + `COLOR_YUV2BGR_YUYV` produces `(H, W, 3)` uint8
  - YU12 reshape + `COLOR_YUV2BGR_I420` produces `(H, W, 3)` uint8 at 1080x2400
  - MJPEG imdecode round-trip smoke test

## Task Commits

Each task was committed atomically on the worktree branch `worktree-agent-a79537fd`:

1. **Task 1: Make V4L2Capture format-agnostic (S_FMT with G_FMT fallback, MJPEG/YUYV/YU12 decode)** - `2037f39` (feat)
2. **Task 2: Add test_capture_v4l2.py covering G_FMT fallback, regression, and YUV decode paths** - `59c9c81` (test)
3. **Task 3: Human UAT re-run for SC-3 and HUMAN-UAT items 2 and 3** - PENDING (blocking human-verify checkpoint)

**Plan metadata commit:** pending (will be made with SUMMARY.md after orchestrator merges this worktree).

## Pixel Format Reference (Load-Bearing Constants)

| Format     | FourCC bytes (LE)   | Hex literal    | OpenCV decode                                 | Buffer size      | Reshape target              |
|------------|---------------------|----------------|-----------------------------------------------|------------------|-----------------------------|
| MJPEG      | 'MJPG' 4D 4A 50 47  | `0x47504A4D`   | `cv2.imdecode(arr, IMREAD_COLOR)`             | variable (JPEG)  | n/a (decoder handles)       |
| YUYV       | 'YUYV' 59 55 59 56  | `0x56595559`   | `cv2.cvtColor(arr, COLOR_YUV2BGR_YUYV)`       | `W * H * 2`      | `(H, W, 2)`                 |
| YU12 (I420)| 'YU12' 59 55 31 32  | `0x32315559`   | `cv2.cvtColor(arr, COLOR_YUV2BGR_I420)`       | `W * H * 3 // 2` | `(H * 3 // 2, W)`           |

`_VIDIOC_G_FMT = 0xC0D05604` — same struct layout as `_VIDIOC_S_FMT = 0xC0D05605`, different ioctl nr (4 vs 5).

## Files Created/Modified

- `Backend/services/capture_v4l2.py` — MODIFIED. 93 insertions, 15 deletions. Format negotiation + YUV decode branches. **`Backend/services/capture_service.py`, `Backend/services/pipeline_manager.py`, and all routers UNTOUCHED** (confirmed by git status after Task 1 commit; `git diff Backend/services/capture_service.py` is empty).
- `Backend/tests/test_capture_v4l2.py` — CREATED. 195 lines. 6 tests across 2 classes (`TestSetupDeviceFormatNegotiation`, `TestDecodePaths`).

## Decisions Made

1. **errno.EINVAL exclusivity.** Only `errno.EINVAL` is caught in the S_FMT fallback. This is deliberate: the plan's threat model treats any other `OSError` as a real device failure (T-13-06). `errno.EBUSY` (device held) must propagate so `CaptureRegistry.acquire()` fails fast rather than hang on a broken device.
2. **Pixelformat allowlist at setup.** `_setup_device` rejects any pixelformat outside `{MJPEG, YUYV, YU12}` with `RuntimeError` before allocating mmap buffers. Guards against a producer reporting a format the reader thread cannot decode (T-13-04).
3. **Hardcoded `_VIDIOC_G_FMT = 0xC0D05604` literal.** Consistent with `_VIDIOC_S_FMT = 0xC0D05605` style already in the file. The `_iowr` helper in this module uses `_v4l2_buf_size` (88 bytes, sizeof `v4l2_buffer`), not the 204-byte `v4l2_format` struct size, so computing G_FMT via `_iowr` would require passing a size override. Literal is clearer.
4. **Short-frame skip, not crash.** When `dqbuf.bytesused < expected`, the frame is logged at DEBUG and skipped via `continue`. Protects `np.frombuffer(..., count=expected).reshape(...)` from out-of-bounds reads if a producer lies about resolution (T-13-05).
5. **`jpeg_bytes = None` for raw-YUV paths.** The existing `_latest_jpeg` slot is left `None` for YUYV/YU12; `CaptureBackend.get_jpeg()` can fall back to re-encoding the BGR frame on demand. Avoids per-frame JPEG encoding cost for clients that only consume `_latest_frame`.

## Deviations from Plan

None — Tasks 1 and 2 executed exactly as written. No bugs discovered, no missing critical functionality, no blocking issues, no architectural changes required.

Reshape math, ioctl numbers, FourCC constants, `_VIDIOC_G_FMT` literal, and EINVAL-exclusive `except` clause all match the plan's `<pixel_format_reference>`, `<ioctl_reference>`, and `<action>` steps verbatim.

**Total deviations:** 0
**Impact on plan:** Plan was prescriptive enough that no interpretation was needed.

## Issues Encountered

- Worktree's initial `ACTUAL_BASE` did not match the orchestrator's expected commit `b4983ec`. Followed the `<worktree_branch_check>` protocol and `git reset --hard b4983ec` succeeded, bringing the worktree to the correct pre-Task-1 state. HEAD verified before proceeding.
- Windows host cannot run the Backend pytest suite (`fcntl`, `cv2`, `linuxpy` unavailable). Per project CLAUDE.md, tests run in `/tmp/hpc-venv` on Linux. Syntax-checked both modified files with `python -c "import ast; ast.parse(...)"` and `py_compile.compile(..., doraise=True)` on Windows — both pass. The six new tests in `test_capture_v4l2.py` collect as 0 on Windows (`pytest.mark.skipif` at module level) and will collect + run on Linux. Full pytest verification (167+ backend tests still green) must be executed on the HueControl VM by the human UAT step (Task 3) or on a Linux developer host before merge.

## Automated Verification Performed (within executor's reach)

- `python -c "import ast; ast.parse(open('Backend/services/capture_v4l2.py').read())"` -> syntax OK
- `py_compile.compile('Backend/services/capture_v4l2.py', doraise=True)` -> compile OK
- `python -c "import ast; ast.parse(open('Backend/tests/test_capture_v4l2.py').read())"` -> syntax OK
- `python -m pytest tests/test_capture_v4l2.py --collect-only` -> 0 tests collected on Windows (expected, skipif gate); will collect 8 test methods (2 classes) on Linux
- `git diff Backend/services/capture_service.py` -> empty (no regression on the base class)

## Automated Verification Deferred to Linux

The plan's `<verify>` block requires `python -m pytest` in `/tmp/hpc-venv`:

1. `source /tmp/hpc-venv/bin/activate && cd Backend && python -c "import services.capture_v4l2"` — module loads
2. `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_capture_v4l2.py -x -q` — 6 new tests pass
3. `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest -x -q` — 167+ full suite still green

These are prerequisites for the human UAT (Task 3). The executor agent ran on Windows and cannot execute them directly. The human tester on the HueControl VM will run them as part of the UAT procedure.

## Pending Human UAT (Task 3 — blocking checkpoint)

Task 3 is a `checkpoint:human-verify` gate that the executor agent CANNOT auto-approve. The plan's `<how-to-verify>` procedure must be run on the HueControl VM against a real Samsung Android device + real Hue Bridge + real Hue lights:

1. Restart backend to pick up new `capture_v4l2.py`
2. `POST /api/wireless/scrcpy` with the Android device's IP — expect HTTP 200 within 15s (previously 422 `producer_timeout`)
3. Backend log should show `S_FMT rejected (EINVAL) -- producer owns format; G_FMT reports pixelformat=0x32315559 1080x2400` (or similar, depending on device)
4. `GET /api/cameras` shows `/dev/video11` with `is_wireless=true, connected=true`
5. Assign `/dev/video11` to an entertainment zone and `POST /api/capture/start` — Hue lights should track Android screen color within ~100ms
6. Swap back to physical `/dev/video0` with HDMI — existing MJPEG behavior unchanged (regression check)
7. `DELETE /api/wireless/scrcpy/{session_id}` — clean teardown

On **UAT passed**, a follow-up executor must:
- Flip `13-HUMAN-UAT.md` tests 2 and 3 from `pending` to `passed`, update Summary counts (passed += 2, pending -= 2)
- Update `13-VERIFICATION.md` frontmatter: `status: gaps_found` -> `status: verified`; set `gaps: []` (or mark G-13-01 `resolved: true` with resolution date)

On failure, the failure mode (backend log excerpt, pixelformat observed, lights-behavior symptom) is recorded in `13-HUMAN-UAT.md` under the failing test's `result:` field and G-13-01 is re-opened.

## Next Phase Readiness

**Code-level G-13-01 is closed.** Once the human UAT step confirms SC-3 end-to-end on real hardware:

- Phase 13 goal (Android screen -> Hue lights via scrcpy) is satisfied end-to-end
- Phase 14 (Miracast) can proceed on the same v4l2loopback consumer path — any producer-owned format (YUYV from FFmpeg's RTSP transcode, for example) is now transparently handled by `V4L2Capture`
- No blockers for v1.2 milestone completion (assuming Phase 14 hardware NIC check passes)

**Threat surface:** The new producer-owned-format path crosses a trust boundary (v4l2loopback producer -> V4L2Capture consumer). Mitigations for T-13-04 (unsupported format), T-13-05 (short frame), and T-13-06 (non-EINVAL errors) are all implemented and covered by the new tests.

## Self-Check

**Created files:**
- `Backend/tests/test_capture_v4l2.py` — present at expected path (195 lines)

**Modified files:**
- `Backend/services/capture_v4l2.py` — format-negotiation and YUV decode paths present (lines 38-39, 97, 187-189, 237-276, 370-399)

**Commits (verified via `git log --oneline -3` on worktree branch):**
- `2037f39` — Task 1 feat commit (capture_v4l2.py implementation) — FOUND
- `59c9c81` — Task 2 test commit (test_capture_v4l2.py) — FOUND
- `b4983ec` — plan commit (pre-existing, base of worktree) — FOUND

**Threat surface scan:** No new network endpoints, auth paths, file access patterns, or schema changes introduced. All modifications are in the local V4L2 ioctl layer; the threat model explicitly enumerated in the plan's `<threat_model>` (T-13-04, T-13-05, T-13-06, T-13-07) is fully covered.

**Known stubs:** None. The implementation is complete for all three supported pixel formats.

## Self-Check: PASSED

---
*Phase: 13-scrcpy-android-integration*
*Plan: 04 (gap-closure for G-13-01)*
*Completed (code): 2026-04-18*
*Status: BLOCKED — awaiting human UAT checkpoint (Task 3)*
