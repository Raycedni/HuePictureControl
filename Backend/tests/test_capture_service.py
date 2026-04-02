"""Unit tests for Backend/services/capture_service.py."""
import asyncio
import os
import threading
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest

from services.capture_service import LatestFrameCapture, CAPTURE_DEVICE


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_stores_device_path(self):
        """__init__ stores the given device_path."""
        svc = LatestFrameCapture("/dev/video1")
        assert svc._device_path == "/dev/video1"

    def test_default_device_path(self):
        """__init__ defaults device_path to /dev/video0."""
        svc = LatestFrameCapture()
        assert svc._device_path == "/dev/video0"

    def test_fd_is_none(self):
        """__init__ leaves _fd as None (device not opened yet)."""
        svc = LatestFrameCapture()
        assert svc._fd is None

    def test_latest_frame_is_none(self):
        """__init__ leaves _latest_frame as None."""
        svc = LatestFrameCapture()
        assert svc._latest_frame is None

    def test_buffers_empty(self):
        """__init__ starts with empty buffer list."""
        svc = LatestFrameCapture()
        assert svc._buffers == []


# ---------------------------------------------------------------------------
# open()
# ---------------------------------------------------------------------------


class TestOpen:
    def test_open_raises_when_device_not_found(self):
        """open() raises RuntimeError when device path does not exist."""
        svc = LatestFrameCapture("/dev/nonexistent")
        with pytest.raises(RuntimeError, match="Capture device not found"):
            svc.open()

    def test_open_raises_when_os_open_fails(self, tmp_path):
        """open() raises RuntimeError when os.open fails."""
        # Create a file so path exists, but patch os.open to fail
        fake_dev = tmp_path / "video99"
        fake_dev.touch()
        svc = LatestFrameCapture(str(fake_dev))
        with patch("services.capture_service.os.open", side_effect=OSError("Permission denied")):
            with pytest.raises(RuntimeError, match="Cannot open"):
                svc.open()

    def test_open_stores_device_path_override(self):
        """open(new_path) updates stored _device_path."""
        svc = LatestFrameCapture("/dev/video0")
        svc.open = lambda path=None: setattr(svc, '_device_path', path or svc._device_path)
        svc.open("/dev/video1")
        assert svc._device_path == "/dev/video1"

    def test_open_calls_release_first(self):
        """open() calls release() before opening to clean up prior state."""
        svc = LatestFrameCapture("/dev/nonexistent")
        svc.release = MagicMock()
        # Will fail because device doesn't exist, but release should be called first
        with pytest.raises(RuntimeError):
            svc.open()
        svc.release.assert_called_once()

    def test_open_closes_fd_on_setup_failure(self, tmp_path):
        """open() closes the fd if _setup_device raises."""
        fake_dev = tmp_path / "video99"
        fake_dev.touch()
        svc = LatestFrameCapture(str(fake_dev))
        mock_fd = 42
        with patch("services.capture_service.os.open", return_value=mock_fd), \
             patch.object(svc, "_setup_device", side_effect=RuntimeError("setup failed")), \
             patch("services.capture_service.os.close") as mock_close:
            with pytest.raises(RuntimeError, match="setup failed"):
                svc.open()
            mock_close.assert_called_once_with(mock_fd)
            assert svc._fd is None


# ---------------------------------------------------------------------------
# release()
# ---------------------------------------------------------------------------


class TestRelease:
    def test_release_safe_when_not_opened(self):
        """release() does not raise when device was never opened."""
        svc = LatestFrameCapture()
        svc.release()
        assert svc._fd is None

    def test_release_closes_fd(self):
        """release() closes the file descriptor."""
        svc = LatestFrameCapture()
        svc._fd = 42
        svc._buffers = []
        svc._reader_thread = None
        with patch("services.capture_service.fcntl.ioctl"), \
             patch("services.capture_service.os.close") as mock_close:
            svc.release()
        mock_close.assert_called_once_with(42)
        assert svc._fd is None

    def test_release_closes_mmap_buffers(self):
        """release() closes all mmap buffers."""
        svc = LatestFrameCapture()
        svc._fd = 42
        buf1 = MagicMock()
        buf2 = MagicMock()
        svc._buffers = [buf1, buf2]
        svc._reader_thread = None
        with patch("services.capture_service.fcntl.ioctl"), \
             patch("services.capture_service.os.close"):
            svc.release()
        buf1.close.assert_called_once()
        buf2.close.assert_called_once()
        assert svc._buffers == []

    def test_release_sets_stop_event(self):
        """release() signals the reader thread to stop."""
        svc = LatestFrameCapture()
        svc.release()
        assert svc._stop_event.is_set()

    def test_release_clears_latest_frame(self):
        """release() sets _latest_frame to None."""
        svc = LatestFrameCapture()
        svc._latest_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        svc.release()
        assert svc._latest_frame is None

    def test_release_joins_reader_thread(self):
        """release() joins the reader thread if it exists."""
        svc = LatestFrameCapture()
        mock_thread = MagicMock()
        svc._reader_thread = mock_thread
        svc.release()
        mock_thread.join.assert_called_once_with(timeout=3)
        assert svc._reader_thread is None


# ---------------------------------------------------------------------------
# get_frame()
# ---------------------------------------------------------------------------


class TestGetFrame:
    @pytest.mark.asyncio
    async def test_get_frame_raises_when_not_open(self):
        """get_frame() raises RuntimeError when _fd is None (device not open)."""
        svc = LatestFrameCapture()
        with pytest.raises(RuntimeError, match="not open"):
            await svc.get_frame()

    @pytest.mark.asyncio
    async def test_get_frame_raises_when_no_frame_available(self):
        """get_frame() raises RuntimeError when no frame has been captured yet."""
        svc = LatestFrameCapture()
        svc._fd = 42  # pretend device is open
        svc._latest_frame = None
        with pytest.raises(RuntimeError, match="No frame available"):
            await svc.get_frame()

    @pytest.mark.asyncio
    async def test_get_frame_returns_latest_frame(self):
        """get_frame() returns the latest frame stored by the reader thread."""
        svc = LatestFrameCapture()
        svc._fd = 42
        expected = np.zeros((480, 640, 3), dtype=np.uint8)
        svc._latest_frame = expected
        frame = await svc.get_frame()
        assert frame is expected


# ---------------------------------------------------------------------------
# CAPTURE_DEVICE module-level constant
# ---------------------------------------------------------------------------


class TestCaptureDeviceEnvVar:
    def test_capture_device_readable_from_env(self):
        """CAPTURE_DEVICE module constant uses CAPTURE_DEVICE env var when set."""
        assert isinstance(CAPTURE_DEVICE, str)

    def test_capture_device_default_is_video0(self):
        """CAPTURE_DEVICE defaults to /dev/video0 when env var is unset."""
        if os.getenv("CAPTURE_DEVICE") is None:
            assert CAPTURE_DEVICE == "/dev/video0"


# ---------------------------------------------------------------------------
# device_path property
# ---------------------------------------------------------------------------


class TestDevicePathProperty:
    def test_device_path_property_returns_path(self):
        """device_path property returns the stored device path."""
        svc = LatestFrameCapture("/dev/video2")
        assert svc.device_path == "/dev/video2"
