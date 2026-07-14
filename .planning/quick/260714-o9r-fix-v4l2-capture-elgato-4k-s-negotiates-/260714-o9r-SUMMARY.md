---
phase: quick-260714-o9r
plan: 01
subsystem: capture
tags: [v4l2, opencv, yuyv, mjpeg, elgato, capture-card]

requires: []
provides:
  - Format-aware V4L2 frame decode that content-sniffs YUYV vs MJPEG instead of trusting the negotiated fourcc
  - _decode_frame helper on V4L2Capture, cached decode-mode resolution (self._decode_yuyv)
  - Negotiated width/height readback from VIDIOC_S_FMT (used for YUYV buffer sizing only)
affects: [capture, preview-ws]

tech-stack:
  added: []
  patterns:
    - "Content-sniff wire format instead of trusting driver-reported negotiated format when hardware lies about VIDIOC_S_FMT results"

key-files:
  created: []
  modified:
    - Backend/services/capture_v4l2.py
    - Backend/tests/test_capture_service.py

key-decisions:
  - "Decode path selection is content-based (FFD8 SOI marker vs exact width*height*2 byte length), not based on the VIDIOC_S_FMT readback, because the Elgato 4K S driver reports MJPG success while still streaming raw YUYV"
  - "Format readback after VIDIOC_S_FMT is retained but repurposed: it only sizes the YUYV reshape buffer (self._width/self._height), never chooses the decode branch"
  - "YUYV frames are re-encoded to JPEG via cv2.imencode (mirrors capture_dshow.py's DirectShow backend) so the preview WebSocket keeps receiving real JPEG bytes; MJPEG frames pass the original jpeg bytes through unchanged (zero re-encode cost for real-MJPEG devices)"

requirements-completed: [BFIX-V4L2-YUYV]

duration: ~15min
completed: 2026-07-14
---

# Quick Task 260714-o9r: Fix V4L2 capture for Elgato 4K S (YUYV-over-MJPEG) Summary

**Format-aware `_decode_frame` helper added to `V4L2Capture` that content-sniffs YUYV vs MJPEG payload (cached after first frame) instead of trusting the driver's negotiated fourcc, fixing silent `cv2.imdecode` failure on the Elgato 4K S.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2/2 completed
- **Files modified:** 2

## Accomplishments
- `V4L2Capture._decode_frame` resolves decode mode once by sniffing frame content (FFD8 SOI marker -> MJPEG; exact `width*height*2` byte length -> YUYV) and caches the result in `self._decode_yuyv`, so `_reader_loop` no longer calls `cv2.imdecode` unconditionally and silently drops every frame from devices that lie about their negotiated format.
- YUYV branch reshapes the raw buffer to `(height, width, 2)`, converts via `cv2.COLOR_YUV2BGR_YUYV`, and re-encodes to JPEG (quality 85) for the preview WebSocket — same pattern as `capture_dshow.py`'s DirectShow backend.
- MJPEG branch is unchanged in behavior: `cv2.imdecode` + original jpeg bytes passed through byte-for-byte (no regression, no extra re-encode for real-MJPEG hardware).
- `_setup_device()` now reads back the negotiated width/height/pixelformat from the `VIDIOC_S_FMT` buffer and logs the (possibly lying) fourcc at info level; the readback sizes the YUYV reshape but does NOT select the decode path (content sniffing does that, since the driver's reported format can't be trusted).
- `release()` resets `self._decode_yuyv = None` so a reconnect re-detects the format from scratch.
- Added `TestV4L2Decode` unit test class covering: YUYV buffer -> valid `(480,640,3)` BGR frame + JPEG bytes starting `\xff\xd8`; MJPEG bytes -> `imdecode` + byte-identical jpeg passthrough; garbage bytes -> `None` with decode mode staying unresolved; and cached-mode reuse on a second YUYV frame (no re-sniff).

## Task Commits

Each task was committed atomically:

1. **Task 1: Add format-aware decode to V4L2Capture** - `6b659ef` (fix)
2. **Task 2: Unit-test the YUYV decode path** - `75c6fea` (test)

_Both tasks were plan-designated `tdd="true"`, but since `_decode_frame` did not exist before this plan, Task 1 (implementation) and Task 2 (tests) were executed and committed as a fix-then-test pair rather than a strict RED/GREEN cycle — matching the plan's own task ordering (implementation task first, test task second), which the plan author explicitly structured this way._

## Files Created/Modified
- `Backend/services/capture_v4l2.py` - Added `_V4L2_PIX_FMT_YUYV` constant, `self._width`/`self._height`/`self._decode_yuyv` instance state, negotiated-format readback in `_setup_device`, the `_decode_frame` helper, and rewired `_reader_loop` to call it.
- `Backend/tests/test_capture_service.py` - Added `cv2` import and `TestV4L2Decode` class (4 tests) inside the existing `if sys.platform != "win32":` Linux-guarded block.

## Decisions Made
- Root cause confirmed per plan context: Elgato 4K S negotiates/reports MJPEG success via `VIDIOC_S_FMT` but streams raw YUYV over the wire (bytesused always exactly `640*480*2`, no FFD8 marker). Decode-path selection is therefore content-based, never format-readback-based.
- Kept the negotiated-format readback (width/height/fourcc) per the plan's explicit instruction — it's used only to size the YUYV reshape, logged for diagnostics, not trusted for path selection.
- Did not touch `Backend/services/color_math.py` or the `hdr=True` path, per plan constraint — both operate downstream of `get_frame()`'s decoded BGR output and are unaffected by wire-format detection.

## Deviations from Plan

None - plan executed exactly as written. One process correction (not a deviation from the plan's technical content): the worktree branch had drifted one commit behind the required base (missing the `7825d56` pre-dispatch commit that added `PLAN.md`) at the start of execution. This was caught mid-task, corrected via `git rebase --onto 7825d5689ee5c38d7f5c6365714f0410d9be40f0 4680510` (clean, no conflicts — my two commits only touch `capture_v4l2.py`/`test_capture_service.py`, no overlap with the plan doc), and verified post-rebase that `git merge-base HEAD 7825d56...` now equals the expected hash and both task commits are intact.

## Issues Encountered

**Test execution environment (Windows dev machine, Linux-only code path):** `Backend/tests/test_capture_service.py` guards all `V4L2Capture` tests (including the new `TestV4L2Decode` class) behind `if sys.platform != "win32":`, and `capture_v4l2.py` does an unconditional `import fcntl` (POSIX-only, no Windows equivalent). Since this dev machine reports `sys.platform == "win32"`, the new `TestV4L2Decode` tests are silently skipped (not run, not failed) when `pytest` executes on this machine — they will only actually execute in CI/production on Linux.

To verify the new `_decode_frame` logic without ioctls (the method is pure — no device I/O), I wrote a standalone verification script (`scratchpad/verify_decode.py`) that stubs `sys.modules["fcntl"]` with a no-op module (only `ioctl` is referenced at import time by other methods, never called by `_decode_frame`), imports `V4L2Capture` directly, and runs the same 4 assertions as the real `TestV4L2Decode` class (YUYV decode shape/dtype/JPEG-SOI, MJPEG passthrough, garbage->None, cached-mode reuse). All 19 individual assertions passed.

**What ran successfully in this environment:**
- `python -c "import ast; ast.parse(...)"` syntax check on `capture_v4l2.py` — passed.
- `python -m pytest tests/test_capture_service.py -q` — 3 passed (the non-guarded `TestFactory` tests; `TestV4L2Decode` and all other V4L2 test classes are skipped on win32, not run).
- `python -m pytest -q` (full backend suite) — 409 passed, 21 skipped, 12 failed. The 12 failures are all in `tests/test_cameras_router.py` and confirmed pre-existing: I stashed my changes and re-ran `tests/test_cameras_router.py` in isolation, getting the identical 12 failures (same test names, same assertion messages) with zero code changes applied. This matches the prior quick task's STATE.md note: "Pre-existing 12 test_cameras_router.py failures logged to deferred-items.md as out-of-scope (verified pre-existing via git-stash diff)." Out of scope for this task per the deviation rules' scope boundary (unrelated file, pre-existing before this plan's changes).

**What could NOT run in this environment:**
- The actual `TestV4L2Decode` pytest class (skipped due to `sys.platform == "win32"` guard) — logic instead verified via the standalone stub-import script described above, with all 19 assertions passing.
- Any real V4L2 ioctl path (`_setup_device`, `_reader_loop`, `open`, mmap) — these require actual Linux `/dev/video*` nodes and are inherently untestable on Windows; they were already excluded from unit coverage before this plan (pre-existing test design, mocked ioctls where exercised at all).
- Real hardware verification against the Elgato 4K S itself — this plan is code-only per its `<output>` spec; hardware verification is a manual step for the user/deploy process, not part of this quick task's scope.

## User Setup Required

None - no external service configuration required. This is a backend-only code fix; no deployment or manual verification step was requested by the plan (deploying to the Linux host with the actual Elgato 4K S hardware and confirming HDMI capture, if desired, would be the user's follow-up manual step, per `.claude/vm-exec.sh` deploy pattern noted in project memory).

## Next Phase Readiness

Code change is complete and committed (`6b659ef`, `75c6fea`). Ready to be deployed to the Linux host running the actual V4L2 hardware for real-world confirmation that the Elgato 4K S now streams correctly. No blockers.

---
*Phase: quick-260714-o9r*
*Completed: 2026-07-14*

## Self-Check: PASSED

- FOUND: Backend/services/capture_v4l2.py
- FOUND: Backend/tests/test_capture_service.py
- FOUND: .planning/quick/260714-o9r-fix-v4l2-capture-elgato-4k-s-negotiates-/260714-o9r-SUMMARY.md
- FOUND commit: 6b659ef (fix task)
- FOUND commit: 75c6fea (test task)
