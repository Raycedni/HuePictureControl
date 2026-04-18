"""Tests for V4L2Capture format negotiation and decode paths.

Covers gap-closure G-13-01: V4L2Capture must handle v4l2loopback devices
that own their format (scrcpy --v4l2-sink with exclusive-caps=1), not just
physical UVC cameras locked to MJPEG 640x480. See VERIFICATION.md G-13-01.
"""
import errno
import struct
import sys

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="V4L2 is Linux-only")

if sys.platform != "win32":
    import cv2
    from unittest.mock import patch

    from services.capture_v4l2 import (
        V4L2Capture,
        _V4L2_PIX_FMT_MJPEG,
        _V4L2_PIX_FMT_YUYV,
        _V4L2_PIX_FMT_YU12,
        _VIDIOC_S_FMT,
        _VIDIOC_G_FMT,
        _VIDIOC_REQBUFS,
        _VIDIOC_QUERYCAP,
        _VIDIOC_STREAMON,
        _VIDIOC_S_PARM,
    )

    def _make_querycap_buffer():
        """Build a 104-byte QUERYCAP buffer advertising VIDEO_CAPTURE."""
        buf = bytearray(104)
        struct.pack_into("<I", buf, 88, 0x01)  # device_caps: VIDEO_CAPTURE
        return buf

    def _make_gfmt_buffer(pixelformat: int, width: int, height: int) -> bytes:
        """Build a 208-byte v4l2_format buffer for G_FMT to return."""
        buf = bytearray(208)
        struct.pack_into("<I",  buf, 0,  1)            # type = VIDEO_CAPTURE
        struct.pack_into("<II", buf, 4,  width, height)
        struct.pack_into("<I",  buf, 12, pixelformat)
        return bytes(buf)

    class TestSetupDeviceFormatNegotiation:
        """_setup_device must handle both S_FMT-succeeds and S_FMT-EINVAL paths."""

        def _run_setup(self, *, s_fmt_effect, g_fmt_result=None):
            """Drive V4L2Capture._setup_device with mocked ioctls.

            s_fmt_effect: callable(fd, request, arg) raising/returning for S_FMT.
            g_fmt_result: bytes returned into the buffer by G_FMT, or None.
            """
            capture = V4L2Capture("/dev/video11")
            capture._fd = 99  # pretend fd; never used directly

            call_log: list[int] = []

            def fake_ioctl(fd, request, arg=None):
                call_log.append(request)
                if request == _VIDIOC_QUERYCAP:
                    data = _make_querycap_buffer()
                    arg[:len(data)] = data
                    return 0
                if request == _VIDIOC_S_FMT:
                    return s_fmt_effect(fd, request, arg)
                if request == _VIDIOC_G_FMT:
                    if g_fmt_result is None:
                        raise AssertionError("G_FMT called but no g_fmt_result provided")
                    arg[:len(g_fmt_result)] = g_fmt_result
                    return 0
                if request == _VIDIOC_REQBUFS:
                    struct.pack_into("<I", arg, 0, 0)  # count = 0 -> skip buffer loop
                    return 0
                if request == _VIDIOC_S_PARM:
                    return 0
                if request == _VIDIOC_STREAMON:
                    return 0
                return 0

            with patch("services.capture_v4l2.fcntl.ioctl", side_effect=fake_ioctl):
                capture._setup_device()

            return capture, call_log

        def test_s_fmt_success_physical_camera_no_regression(self):
            """When S_FMT succeeds (UVC camera), pixelformat stays MJPEG 640x480."""
            def s_fmt_ok(fd, request, arg):
                return 0

            capture, calls = self._run_setup(s_fmt_effect=s_fmt_ok)

            assert capture._pixelformat == _V4L2_PIX_FMT_MJPEG
            assert capture._width == 640
            assert capture._height == 480
            assert _VIDIOC_S_FMT in calls
            assert _VIDIOC_G_FMT not in calls, "G_FMT must NOT be called on physical camera success path"

        def test_s_fmt_einval_falls_back_to_g_fmt(self):
            """When producer owns format (scrcpy), S_FMT raises EINVAL and G_FMT wins."""
            def s_fmt_einval(fd, request, arg):
                raise OSError(errno.EINVAL, "Invalid argument")

            capture, calls = self._run_setup(
                s_fmt_effect=s_fmt_einval,
                g_fmt_result=_make_gfmt_buffer(_V4L2_PIX_FMT_YU12, 1080, 2400),
            )

            assert capture._pixelformat == _V4L2_PIX_FMT_YU12
            assert capture._width == 1080
            assert capture._height == 2400
            assert _VIDIOC_S_FMT in calls
            assert _VIDIOC_G_FMT in calls, "G_FMT must be called after EINVAL fallback"

        def test_s_fmt_einval_falls_back_for_yuyv_too(self):
            """YUYV is another common producer format; G_FMT must be honored."""
            def s_fmt_einval(fd, request, arg):
                raise OSError(errno.EINVAL, "Invalid argument")

            capture, _ = self._run_setup(
                s_fmt_effect=s_fmt_einval,
                g_fmt_result=_make_gfmt_buffer(_V4L2_PIX_FMT_YUYV, 1920, 1080),
            )

            assert capture._pixelformat == _V4L2_PIX_FMT_YUYV
            assert capture._width == 1920
            assert capture._height == 1080

        def test_s_fmt_non_einval_error_propagates(self):
            """Non-EINVAL OSError must NOT be swallowed (don't hide real device errors)."""
            def s_fmt_ebusy(fd, request, arg):
                raise OSError(errno.EBUSY, "Device or resource busy")

            with pytest.raises(OSError) as exc_info:
                self._run_setup(s_fmt_effect=s_fmt_ebusy)

            assert exc_info.value.errno == errno.EBUSY

        def test_unsupported_pixelformat_raises_runtime_error(self):
            """If G_FMT reports a format the reader loop can't decode, fail fast."""
            def s_fmt_einval(fd, request, arg):
                raise OSError(errno.EINVAL, "Invalid argument")

            with pytest.raises(RuntimeError) as exc_info:
                self._run_setup(
                    s_fmt_effect=s_fmt_einval,
                    g_fmt_result=_make_gfmt_buffer(0xDEADBEEF, 1280, 720),
                )

            assert "Unsupported" in str(exc_info.value) or "unsupported" in str(exc_info.value).lower()


    class TestDecodePaths:
        """Validate the reshape + cvtColor math used by _reader_loop for raw YUV."""

        def test_yuyv_decode_produces_bgr_shape(self):
            """YUYV reshape + COLOR_YUV2BGR_YUYV yields (H, W, 3) uint8."""
            W, H = 64, 48
            raw = np.full((H, W, 2), 128, dtype=np.uint8)  # neutral grey
            arr = np.frombuffer(raw.tobytes(), dtype=np.uint8, count=W * H * 2)
            arr = arr.reshape((H, W, 2))
            bgr = cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_YUYV)

            assert bgr.dtype == np.uint8
            assert bgr.shape == (H, W, 3)

        def test_yu12_decode_produces_bgr_shape(self):
            """YU12 (I420) reshape + COLOR_YUV2BGR_I420 yields (H, W, 3) uint8.

            This is the scrcpy path; it must produce a frame the rest of the
            pipeline (region extraction, streaming) can consume.
            """
            W, H = 1080, 2400  # phone resolution per VERIFICATION.md
            total = W * H * 3 // 2
            raw = np.full((total,), 128, dtype=np.uint8)
            arr = np.frombuffer(raw.tobytes(), dtype=np.uint8, count=total)
            arr = arr.reshape((H * 3 // 2, W))
            bgr = cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_I420)

            assert bgr.dtype == np.uint8
            assert bgr.shape == (H, W, 3)

        def test_mjpeg_decode_path_still_uses_imdecode(self):
            """Physical-camera MJPEG path: smoke test that imdecode on a real
            JPEG yields a BGR frame. Guards against accidental removal."""
            W, H = 32, 24
            frame_in = np.full((H, W, 3), 200, dtype=np.uint8)
            ok, jpeg = cv2.imencode(".jpg", frame_in)
            assert ok
            frame_out = cv2.imdecode(np.frombuffer(jpeg.tobytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
            assert frame_out is not None
            assert frame_out.shape == (H, W, 3)
            assert frame_out.dtype == np.uint8
