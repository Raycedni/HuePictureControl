"""Unit tests for capture service: base class + V4L2 backend."""
import asyncio
import os
import sys
import threading
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from services.capture_service import CaptureBackend, create_capture, CAPTURE_DEVICE


# ---------------------------------------------------------------------------
# Factory / module-level
# ---------------------------------------------------------------------------


class TestFactory:
    def test_create_capture_returns_backend(self):
        """create_capture() returns a CaptureBackend subclass."""
        svc = create_capture("/dev/nonexistent")
        assert isinstance(svc, CaptureBackend)

    def test_capture_device_readable_from_env(self):
        """CAPTURE_DEVICE module constant uses CAPTURE_DEVICE env var when set."""
        assert isinstance(CAPTURE_DEVICE, str)

    def test_capture_device_default(self):
        """CAPTURE_DEVICE defaults based on platform when env var is unset."""
        if os.getenv("CAPTURE_DEVICE") is None:
            if sys.platform == "win32":
                assert CAPTURE_DEVICE == "0"
            else:
                assert CAPTURE_DEVICE == "/dev/video0"


# ---------------------------------------------------------------------------
# V4L2 backend tests (Linux only)
# ---------------------------------------------------------------------------

if sys.platform != "win32":
    from services.capture_v4l2 import V4L2Capture

    class TestV4L2Init:
        def test_stores_device_path(self):
            svc = V4L2Capture("/dev/video1")
            assert svc._device_path == "/dev/video1"

        def test_default_device_path(self):
            svc = V4L2Capture()
            assert svc._device_path == "/dev/video0"

        def test_fd_is_none(self):
            svc = V4L2Capture()
            assert svc._fd is None

        def test_is_open_false_initially(self):
            svc = V4L2Capture()
            assert svc.is_open is False

        def test_latest_frame_is_none(self):
            svc = V4L2Capture()
            assert svc._latest_frame is None

        def test_buffers_empty(self):
            svc = V4L2Capture()
            assert svc._buffers == []

    class TestV4L2Open:
        def test_open_raises_when_device_not_found(self):
            svc = V4L2Capture("/dev/nonexistent")
            with pytest.raises(RuntimeError, match="Capture device not found"):
                svc.open()

        def test_open_raises_when_os_open_fails(self, tmp_path):
            fake_dev = tmp_path / "video99"
            fake_dev.touch()
            svc = V4L2Capture(str(fake_dev))
            with patch("services.capture_v4l2.os.open", side_effect=OSError("Permission denied")):
                with pytest.raises(RuntimeError, match="Cannot open"):
                    svc.open()

        def test_open_stores_device_path_override(self):
            svc = V4L2Capture("/dev/video0")
            svc.open = lambda path=None: setattr(svc, '_device_path', path or svc._device_path)
            svc.open("/dev/video1")
            assert svc._device_path == "/dev/video1"

        def test_open_calls_release_first(self):
            svc = V4L2Capture("/dev/nonexistent")
            svc.release = MagicMock()
            with pytest.raises(RuntimeError):
                svc.open()
            svc.release.assert_called_once()

        def test_open_closes_fd_on_setup_failure(self, tmp_path):
            fake_dev = tmp_path / "video99"
            fake_dev.touch()
            svc = V4L2Capture(str(fake_dev))
            mock_fd = 42
            with patch("services.capture_v4l2.os.open", return_value=mock_fd), \
                 patch.object(svc, "_setup_device", side_effect=RuntimeError("setup failed")), \
                 patch("services.capture_v4l2.os.close") as mock_close:
                with pytest.raises(RuntimeError, match="setup failed"):
                    svc.open()
                mock_close.assert_called_once_with(mock_fd)
                assert svc._fd is None

    class TestV4L2Release:
        def test_release_safe_when_not_opened(self):
            svc = V4L2Capture()
            svc.release()
            assert svc._fd is None

        def test_release_closes_fd(self):
            svc = V4L2Capture()
            svc._fd = 42
            svc._buffers = []
            svc._reader_thread = None
            with patch("services.capture_v4l2.fcntl.ioctl"), \
                 patch("services.capture_v4l2.os.close") as mock_close:
                svc.release()
            mock_close.assert_called_once_with(42)
            assert svc._fd is None

        def test_release_closes_mmap_buffers(self):
            svc = V4L2Capture()
            svc._fd = 42
            buf1 = MagicMock()
            buf2 = MagicMock()
            svc._buffers = [buf1, buf2]
            svc._reader_thread = None
            with patch("services.capture_v4l2.fcntl.ioctl"), \
                 patch("services.capture_v4l2.os.close"):
                svc.release()
            buf1.close.assert_called_once()
            buf2.close.assert_called_once()
            assert svc._buffers == []

        def test_release_sets_stop_event(self):
            svc = V4L2Capture()
            svc.release()
            assert svc._stop_event.is_set()

        def test_release_clears_latest_frame(self):
            svc = V4L2Capture()
            svc._latest_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            svc.release()
            assert svc._latest_frame is None

        def test_release_joins_reader_thread(self):
            svc = V4L2Capture()
            mock_thread = MagicMock()
            svc._reader_thread = mock_thread
            svc.release()
            mock_thread.join.assert_called_once_with(timeout=3)
            assert svc._reader_thread is None

    class TestV4L2GetFrame:
        @pytest.mark.asyncio
        async def test_get_frame_raises_when_not_open(self):
            svc = V4L2Capture()
            with pytest.raises(RuntimeError, match="not open"):
                await svc.get_frame()

        @pytest.mark.asyncio
        async def test_get_frame_raises_when_no_frame_available(self):
            svc = V4L2Capture()
            svc._fd = 42  # pretend device is open
            svc._latest_frame = None
            with pytest.raises(RuntimeError, match="No frame available"):
                await svc.get_frame()

        @pytest.mark.asyncio
        async def test_get_frame_returns_latest_frame(self):
            svc = V4L2Capture()
            svc._fd = 42
            expected = np.zeros((480, 640, 3), dtype=np.uint8)
            svc._latest_frame = expected
            frame = await svc.get_frame()
            assert frame is expected

    class TestV4L2GetJpeg:
        @pytest.mark.asyncio
        async def test_get_jpeg_raises_when_not_open(self):
            svc = V4L2Capture()
            with pytest.raises(RuntimeError, match="not open"):
                await svc.get_jpeg()

        @pytest.mark.asyncio
        async def test_get_jpeg_raises_when_no_frame_available(self):
            svc = V4L2Capture()
            svc._fd = 42
            svc._latest_jpeg = None
            with pytest.raises(RuntimeError, match="No frame available"):
                await svc.get_jpeg()

        @pytest.mark.asyncio
        async def test_get_jpeg_returns_latest_jpeg(self):
            svc = V4L2Capture()
            svc._fd = 42
            expected = b"\xff\xd8\xff\xe0fake-jpeg"
            svc._latest_jpeg = expected
            result = await svc.get_jpeg()
            assert result is expected

    class TestV4L2DevicePathProperty:
        def test_device_path_property_returns_path(self):
            svc = V4L2Capture("/dev/video2")
            assert svc.device_path == "/dev/video2"
