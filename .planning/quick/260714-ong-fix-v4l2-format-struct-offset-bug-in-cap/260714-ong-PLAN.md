---
phase: quick-260714-ong
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - Backend/services/capture_v4l2.py
  - Backend/tests/test_capture_service.py
autonomous: true
requirements: [BFIX-v4l2-fmt-offset]

must_haves:
  truths:
    - "_setup_device() sets self._width to the driver-negotiated width (640), not 0"
    - "_setup_device() sets self._height to the driver-negotiated height (480), not 640"
    - "The YUYV length check in _decode_frame matches a real 614400-byte YUYV frame"
    - "A regression test fails on the old offsets and passes on the corrected ones"
  artifacts:
    - path: "Backend/services/capture_v4l2.py"
      provides: "v4l2_format offset constants + corrected pack_into/unpack_from"
      contains: "_FMT_OFF_WIDTH"
    - path: "Backend/tests/test_capture_service.py"
      provides: "Regression test for the S_FMT readback offset path"
      contains: "def test_setup_device"
  key_links:
    - from: "_setup_device pack_into"
      to: "VIDIOC_S_FMT ioctl buffer"
      via: "byte offsets 8/12/16 (width/height/pixelformat)"
      pattern: "_FMT_OFF_(WIDTH|HEIGHT|PIXELFORMAT)"
    - from: "_setup_device unpack_from readback"
      to: "self._width / self._height"
      via: "same offsets 8/12"
      pattern: "unpack_from.*_FMT_OFF_WIDTH"
---

<objective>
Fix a pre-existing struct-offset bug in `V4L2Capture._setup_device()` where `v4l2_format`'s width/height/pixelformat fields are packed/unpacked 4 bytes too early, ignoring the 4-byte alignment padding the compiler inserts between `type` (offset 0-3) and the `fmt` union (offset 8) on 64-bit Linux.

The wrong offsets cause `self._width` to resolve to 0 and `self._height` to 640, which breaks the YUYV decode fallback shipped in quick task 260714-o9r (the `len(data) == self._width * self._height * 2` check becomes `== 0` and never matches, so `_decode_frame` returns None forever — the "Device opened but no frames produced" symptom).

Purpose: Make the just-shipped YUYV fallback actually work in production by feeding it correct frame dimensions.
Output: Corrected offsets (with named constants + explanatory comment) in `capture_v4l2.py`, plus a regression test that exercises the previously-untested `_setup_device()` readback path.
</objective>

<execution_context>
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/STATE.md
@Backend/services/capture_v4l2.py
@Backend/tests/test_capture_service.py

<proven_layout>
Empirically proven on the live target (Ubuntu 24.04, kernel 6.8.0, x86_64) by
setting a known format with `v4l2-ctl --set-fmt-video=width=640,height=480,pixelformat=YUYV`
then reading it back via raw VIDIOC_G_FMT. Raw hex from offset 0:

  01000000 00000000 80020000 e0010000 59555956 01000000

  offset 0-3   = 01000000  -> type = 1 (V4L2_BUF_TYPE_VIDEO_CAPTURE)
  offset 4-7   = 00000000  -> PADDING (always zero, 8-byte union alignment)
  offset 8-11  = 80020000  -> 0x280 = 640 = width
  offset 12-15 = e0010000  -> 0x1e0 = 480 = height
  offset 16-19 = 59555956  -> "YUYV" = pixelformat
  offset 20-23 = 01000000  -> field = 1 (V4L2_FIELD_NONE)

Canonical offset table (do not re-derive):
  type        -> 0
  (padding)   -> 4
  width       -> 8
  height      -> 12
  pixelformat -> 16
  field       -> 20

The padding exists because the `fmt` union contains a `v4l2_window` variant with
a pointer member (`v4l2_clip*`), forcing 8-byte alignment on the whole union.
</proven_layout>

<scope_notes>
- Fix is scoped ONLY to the `v4l2_format` struct used by VIDIOC_S_FMT in `_setup_device()`.
- Do NOT touch VIDIOC_REQBUFS, VIDIOC_QUERYBUF/QBUF/DQBUF (`_v4l2_buffer` ctypes.Structure),
  or VIDIOC_S_PARM (`v4l2_streamparm`) offsets — those variants have no pointer member
  forcing 8-byte alignment and are already correct.
- The `_decode_frame` YUYV reshape `reshape((self._height, self._width, 2))` is already
  correct once self._width/self._height hold real values (640, 480) — confirm, don't change.
</scope_notes>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix v4l2_format field offsets in _setup_device()</name>
  <files>Backend/services/capture_v4l2.py</files>
  <action>
Add three module-level constants near the other `_V4L2_*` constants (around line 37), documenting the padding:

```python
# v4l2_format field offsets. On 64-bit Linux the fmt union contains a
# v4l2_window variant with a pointer member (v4l2_clip*), forcing 8-byte
# alignment of the whole union. Since `type` is only 4 bytes, the compiler
# inserts 4 bytes of padding at offset 4-7 before the union starts at offset 8.
# Empirically verified via VIDIOC_G_FMT hex dump on the live target device.
_FMT_OFF_WIDTH = 8
_FMT_OFF_HEIGHT = 12
_FMT_OFF_PIXELFORMAT = 16
```

Then update `_setup_device()` (lines ~228-243) to use these offsets instead of the wrong 4/8/12 values.

Request construction (was `pack_into("<II", fmt, 4, ...)` at line 230 and `pack_into("<I", fmt, 12, ...)` at line 231):

```python
fmt = bytearray(208)
struct.pack_into("<I", fmt, 0, _V4L2_BUF_TYPE_VIDEO_CAPTURE)
struct.pack_into("<I", fmt, _FMT_OFF_WIDTH, _WIDTH)
struct.pack_into("<I", fmt, _FMT_OFF_HEIGHT, _HEIGHT)
struct.pack_into("<I", fmt, _FMT_OFF_PIXELFORMAT, _V4L2_PIX_FMT_MJPEG)
fcntl.ioctl(fd, _VIDIOC_S_FMT, fmt)
```

Readback (was `unpack_from("<II", fmt, 4)` at line 239 and `unpack_from("<I", fmt, 12)` at line 240):

```python
negotiated_width = struct.unpack_from("<I", fmt, _FMT_OFF_WIDTH)[0]
negotiated_height = struct.unpack_from("<I", fmt, _FMT_OFF_HEIGHT)[0]
negotiated_fourcc = struct.unpack_from("<I", fmt, _FMT_OFF_PIXELFORMAT)[0]
self._width = negotiated_width
self._height = negotiated_height
```

Keep the existing explanatory NOTE comment about content-sniffed decode selection and the fourcc logging line intact. Leave everything else in the function (QUERYCAP, REQBUFS, QUERYBUF/QBUF, S_PARM, STREAMON) untouched. Confirm the `_decode_frame` YUYV reshape needs no change (it doesn't — it reads self._height/self._width which are now correct).
  </action>
  <verify>
    <automated>cd Backend && python -c "import ast; ast.parse(open('services/capture_v4l2.py').read()); print('parse OK')"</automated>
  </verify>
  <done>Offsets are 8/12/16 via named constants with a padding comment; no other struct in the file is modified.</done>
</task>

<task type="auto">
  <name>Task 2: Add regression test for the S_FMT readback offset path</name>
  <files>Backend/tests/test_capture_service.py</files>
  <action>
Add a new test class inside the existing `if sys.platform != "win32":` block (alongside `TestV4L2Decode`) that exercises `_setup_device()`'s offset logic — the path 260714-o9r's tests never touched (they fed `_decode_frame` with width/height already set correctly).

The test must call `_setup_device()` with `fcntl.ioctl` and `mmap.mmap` mocked so no real device is needed, and a mock `fcntl.ioctl` side_effect that simulates the driver writing the empirically-proven byte layout into the fmt buffer on VIDIOC_S_FMT. Verify `self._width == 640` and `self._height == 480` afterward. This test would fail on the old offsets (self._width would be 0).

Sketch (adapt to how ioctl args are passed — the buffer is the 3rd positional arg to `fcntl.ioctl`):

```python
class TestV4L2SetupDeviceOffsets:
    """Regression: _setup_device must read width/height from the padded
    v4l2_format offsets (8/12), not the pre-padding offsets (4/8)."""

    def test_setup_device_resolves_real_width_height(self):
        import struct
        from services import capture_v4l2 as v

        svc = V4L2Capture()
        svc._fd = 99

        def fake_ioctl(fd, request, arg=0):
            if request == v._VIDIOC_QUERYCAP:
                # set device_caps VIDEO_CAPTURE bit at offset 88
                struct.pack_into("<I", arg, 88, 0x01)
            elif request == v._VIDIOC_S_FMT:
                # Driver writes the proven layout: width@8, height@12, YUYV@16
                struct.pack_into("<I", arg, 0, v._V4L2_BUF_TYPE_VIDEO_CAPTURE)
                struct.pack_into("<I", arg, 8, 640)
                struct.pack_into("<I", arg, 12, 480)
                struct.pack_into("<I", arg, 16, v._V4L2_PIX_FMT_YUYV)
            elif request == v._VIDIOC_REQBUFS:
                struct.pack_into("<I", arg, 0, 0)  # 0 buffers -> skip mmap loop
            # QUERYBUF/QBUF/S_PARM/STREAMON: no-op
            return 0

        with patch("services.capture_v4l2.fcntl.ioctl", side_effect=fake_ioctl), \
             patch("services.capture_v4l2.mmap.mmap"):
            svc._setup_device()

        assert svc._width == 640
        assert svc._height == 480
```

Notes for the executor:
- Returning 0 buffers from REQBUFS makes the `for i in range(count)` mmap/QUERYBUF loop a no-op, so `mmap.mmap` patching is defensive but the loop won't execute. Keep it simple.
- `fcntl.ioctl` may be called with 2 or 3 args across the function (STREAMON passes a bytes buffer). The `arg=0` default in `fake_ioctl` handles the ctypes `_v4l2_buffer` and bytes cases without needing to write into them.
- If `struct.pack_into` on a ctypes structure arg (QUERYBUF path) is a problem, guard those branches by request number as shown — only QUERYCAP/S_FMT/REQBUFS need writes and all three receive bytearrays.
- Confirm the existing `TestV4L2Decode` tests still pass unchanged.
  </action>
  <verify>
    <automated>cd Backend && python -m pytest tests/test_capture_service.py -x -q</automated>
  </verify>
  <done>New test passes on corrected offsets; all pre-existing tests in test_capture_service.py still pass.</done>
</task>

</tasks>

<verification>
- Backend suite green: `cd Backend && python -m pytest` (per CLAUDE.md; run in the Linux venv).
- The new offset regression test asserts self._width == 640 and self._height == 480.
- No changes to _v4l2_buffer / v4l2_streamparm structs.
- Note: live V4L2 ioctl code is guarded by platform and only runs on Linux; on the
  Windows dev machine the V4L2 test block is skipped by the `if sys.platform != "win32"`
  guard — the regression test runs in the backend Linux venv.
</verification>

<success_criteria>
- `_setup_device()` uses named offset constants 8/12/16 with a padding comment.
- After a simulated S_FMT round-trip with the proven byte layout, self._width == 640 and self._height == 480.
- The YUYV `_decode_frame` length check `len(data) == self._width * self._height * 2` equals 614400 for a real frame (not 0).
- Regression test in place; full backend test suite passes.
</success_criteria>

<output>
After completion, create `.planning/quick/260714-ong-fix-v4l2-format-struct-offset-bug-in-cap/260714-ong-SUMMARY.md`
</output>
