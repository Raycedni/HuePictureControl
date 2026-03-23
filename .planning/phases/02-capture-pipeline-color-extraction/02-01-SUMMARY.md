---
phase: 02-capture-pipeline-color-extraction
plan: "01"
subsystem: backend-capture
tags: [opencv, color-math, async, tdd, services]
dependency_graph:
  requires: []
  provides:
    - LatestFrameCapture class (Backend/services/capture_service.py)
    - rgb_to_xy, build_polygon_mask, extract_region_color (Backend/services/color_math.py)
  affects:
    - Phase 2 Plan 02 (capture REST endpoints will import these services)
    - Phase 3 (streaming loop will use LatestFrameCapture.get_frame)
tech_stack:
  added:
    - opencv-python-headless>=4.10,<5 (headless variant for Docker; brings numpy)
  patterns:
    - asyncio.to_thread wrapping blocking cap.read() call
    - asyncio.Lock on get_frame() to serialize concurrent reads
    - Gamut C barycentric in-gamut test + segment-projection clamping (Philips SDK algorithm)
    - Pitfall 4 coordinate clamping: min(1.0, max(0.0, v)) * (dim - 1) before int()
    - Warmup frame discard: 3 frames on open() to clear AGC/AEC black frames
key_files:
  created:
    - Backend/services/color_math.py
    - Backend/services/capture_service.py
    - Backend/tests/test_color_math.py
    - Backend/tests/test_capture_service.py
  modified:
    - Backend/requirements.txt
decisions:
  - inline-gamut-c-math: Inlined the 20-line Gamut C algorithm rather than taking rgbxy dependency (last released 2020, unmaintained)
  - asyncio-lock-on-get-frame: Added asyncio.Lock per Open Question 3 in research to prevent concurrent read races
  - opencv-headless-installed-at-task1: opencv-python-headless installed during Task 1 (Rule 3 deviation) because test_color_math.py requires cv2/numpy; plan ordering had install at Task 2 but tests needed it earlier
metrics:
  duration: "3m 24s"
  completed_date: "2026-03-23"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 1
  tests_added: 41
  tests_total_suite: 59
---

# Phase 02 Plan 01: Capture Service and Color Math Summary

**One-liner:** LatestFrameCapture (V4L2/MJPEG/asyncio.to_thread) and inline Gamut C color math (rgb_to_xy, build_polygon_mask, extract_region_color) with 41 new TDD tests.

## What Was Built

### Backend/services/color_math.py

Pure math module for the Hue Entertainment API color pipeline:

- `GAMUT_C` — Gamut C triangle vertices (all Gen 3+ Hue lights)
- `rgb_to_xy(r, g, b)` — sRGB gamma expansion, Wide RGB D65 matrix to XYZ, XYZ to xy chromaticity, barycentric in-gamut test, segment-projection clamp to Gamut C triangle. Returns D65 white point for black input.
- `build_polygon_mask(normalized_points, width, height)` — converts normalized [0..1] polygon to pixel coordinates with boundary clamping, rasterizes via `cv2.fillPoly` to uint8 mask.
- `extract_region_color(frame, mask)` — `cv2.mean` over mask region, BGR-to-RGB channel swap, returns `(r, g, b)` int tuple.
- Internal helpers: `_cross_product`, `_closest_point_on_segment`, `_in_gamut`, `_clamp_to_gamut`.

### Backend/services/capture_service.py

Pull-based, asyncio-safe OpenCV V4L2 wrapper:

- `CAPTURE_DEVICE` — module constant from `os.getenv("CAPTURE_DEVICE", "/dev/video0")`
- `LatestFrameCapture.__init__` — stores device path, `_cap = None`, creates `asyncio.Lock`
- `open(device_path?)` — closes any existing cap, opens V4L2 with MJPG fourcc at 640x480, logs actual fourcc, discards first 3 warmup frames. Raises `RuntimeError` if device unavailable.
- `release()` — releases cap and sets to None; safe when already None.
- `_read_frame()` — synchronous blocking read; guards against None/closed cap; raises on False return.
- `get_frame()` — async; raises early if `_cap` is None (fast path), then acquires Lock and delegates to `asyncio.to_thread(_read_frame)`.
- `device_path` property — returns current device path.

### Backend/requirements.txt

Added `opencv-python-headless>=4.10,<5` after pydantic, before test deps.

## Test Coverage

| Test file | Tests | Coverage |
|-----------|-------|----------|
| test_color_math.py | 24 | rgb_to_xy primaries/black/white, _in_gamut, _clamp_to_gamut, build_polygon_mask shape/clamping/dimensions, extract_region_color solid colors/region masking/types |
| test_capture_service.py | 17 | __init__ defaults/path/None cap, open() V4L2/MJPG/warmup-frames/RuntimeError/reopen, release() cap+None/safe, get_frame() threading/RuntimeError, _read_frame() False/None, CAPTURE_DEVICE env, device_path property |

Full suite: **59 tests, 0 failures**.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking Issue] opencv-python-headless installed during Task 1 rather than Task 2**

- **Found during:** Task 1 RED phase
- **Issue:** `test_color_math.py` imports `cv2` and `numpy` which are both bundled via `opencv-python-headless`. The plan ordered the pip install at Task 2, but Task 1 tests needed it to even collect (import error on `numpy`).
- **Fix:** Installed `opencv-python-headless>=4.10,<5 --break-system-packages` immediately during Task 1 before the RED run. Also added to requirements.txt in Task 2 as planned.
- **Files modified:** None (install only; requirements.txt updated in Task 2 as planned)
- **Impact:** Zero — same package, same version, just installed one task earlier.

## Self-Check: PASSED

All files confirmed on disk. Both task commits verified in git log.

| Item | Status |
|------|--------|
| Backend/services/color_math.py | FOUND |
| Backend/services/capture_service.py | FOUND |
| Backend/tests/test_color_math.py | FOUND |
| Backend/tests/test_capture_service.py | FOUND |
| Commit cc1df02 (color_math) | FOUND |
| Commit a4392bf (capture_service) | FOUND |
