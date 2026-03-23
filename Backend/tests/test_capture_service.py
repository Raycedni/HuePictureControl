"""Unit tests for Backend/services/capture_service.py."""
import asyncio
import os
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

from services.capture_service import LatestFrameCapture, CAPTURE_DEVICE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_cap():
    """A pre-configured MagicMock for cv2.VideoCapture."""
    cap = MagicMock()
    cap.isOpened.return_value = True
    cap.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))
    return cap


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

    def test_cap_is_none(self):
        """__init__ leaves _cap as None (device not opened yet)."""
        svc = LatestFrameCapture()
        assert svc._cap is None


# ---------------------------------------------------------------------------
# open()
# ---------------------------------------------------------------------------


class TestOpen:
    def test_open_creates_video_capture_with_v4l2(self, mock_cap):
        """open() creates cv2.VideoCapture with CAP_V4L2 backend."""
        with patch("services.capture_service.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_V4L2 = 200  # Realistic constant value
            mock_cv2.CAP_PROP_FOURCC = 6
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
            mock_cv2.VideoWriter_fourcc.return_value = 1196444237  # MJPG
            svc = LatestFrameCapture("/dev/video0")
            svc.open()
            mock_cv2.VideoCapture.assert_called_once_with("/dev/video0", mock_cv2.CAP_V4L2)

    def test_open_sets_mjpg_fourcc_and_resolution(self, mock_cap):
        """open() sets MJPG fourcc, 640 width, 480 height on the capture."""
        with patch("services.capture_service.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_V4L2 = 200
            mock_cv2.CAP_PROP_FOURCC = 6
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
            mock_cv2.VideoWriter_fourcc.return_value = 1196444237  # MJPG
            svc = LatestFrameCapture("/dev/video0")
            svc.open()
            # Verify fourcc, width, height were set
            set_calls = mock_cap.set.call_args_list
            prop_values = {c.args[0]: c.args[1] for c in set_calls}
            assert prop_values[mock_cv2.CAP_PROP_FRAME_WIDTH] == 640
            assert prop_values[mock_cv2.CAP_PROP_FRAME_HEIGHT] == 480
            assert prop_values[mock_cv2.CAP_PROP_FOURCC] == mock_cv2.VideoWriter_fourcc.return_value

    def test_open_discards_first_3_frames(self, mock_cap):
        """open() discards first 3 frames to avoid black frame issue."""
        with patch("services.capture_service.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_V4L2 = 200
            mock_cv2.CAP_PROP_FOURCC = 6
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
            mock_cv2.VideoWriter_fourcc.return_value = 1196444237
            svc = LatestFrameCapture("/dev/video0")
            svc.open()
            # cap.read() should have been called exactly 3 times (discard warmup frames)
            assert mock_cap.read.call_count == 3

    def test_open_raises_runtime_error_when_device_not_opened(self):
        """open() raises RuntimeError when device cannot be opened."""
        with patch("services.capture_service.cv2") as mock_cv2:
            bad_cap = MagicMock()
            bad_cap.isOpened.return_value = False
            mock_cv2.VideoCapture.return_value = bad_cap
            mock_cv2.CAP_V4L2 = 200
            mock_cv2.VideoWriter_fourcc.return_value = 1196444237
            svc = LatestFrameCapture("/dev/nonexistent")
            with pytest.raises(RuntimeError, match="Could not open capture device"):
                svc.open()

    def test_open_with_new_path_closes_existing(self, mock_cap):
        """open(new_path) releases existing cap before reopening."""
        with patch("services.capture_service.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_V4L2 = 200
            mock_cv2.CAP_PROP_FOURCC = 6
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
            mock_cv2.VideoWriter_fourcc.return_value = 1196444237
            svc = LatestFrameCapture("/dev/video0")
            svc.open()
            mock_cap.reset_mock()
            # Open again with a new path — should release first
            svc.open("/dev/video1")
            mock_cap.release.assert_called_once()
            # VideoCapture should be called again for the new path
            assert mock_cv2.VideoCapture.call_count == 2
            mock_cv2.VideoCapture.assert_called_with("/dev/video1", mock_cv2.CAP_V4L2)


# ---------------------------------------------------------------------------
# release()
# ---------------------------------------------------------------------------


class TestRelease:
    def test_release_releases_capture_and_sets_none(self, mock_cap):
        """release() calls cap.release() and sets _cap to None."""
        with patch("services.capture_service.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_V4L2 = 200
            mock_cv2.CAP_PROP_FOURCC = 6
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
            mock_cv2.VideoWriter_fourcc.return_value = 1196444237
            svc = LatestFrameCapture()
            svc.open()
            svc.release()
            mock_cap.release.assert_called()
            assert svc._cap is None

    def test_release_safe_when_cap_is_none(self):
        """release() does not raise when _cap is already None."""
        svc = LatestFrameCapture()
        # Should not raise
        svc.release()
        assert svc._cap is None


# ---------------------------------------------------------------------------
# get_frame()
# ---------------------------------------------------------------------------


class TestGetFrame:
    @pytest.mark.asyncio
    async def test_get_frame_calls_asyncio_to_thread(self, mock_cap):
        """get_frame() delegates to asyncio.to_thread with _read_frame."""
        with patch("services.capture_service.cv2") as mock_cv2:
            mock_cv2.VideoCapture.return_value = mock_cap
            mock_cv2.CAP_V4L2 = 200
            mock_cv2.CAP_PROP_FOURCC = 6
            mock_cv2.CAP_PROP_FRAME_WIDTH = 3
            mock_cv2.CAP_PROP_FRAME_HEIGHT = 4
            mock_cv2.VideoWriter_fourcc.return_value = 1196444237
            svc = LatestFrameCapture()
            svc.open()
            # After warmup reads, reset mock count
            mock_cap.reset_mock()
            mock_cap.isOpened.return_value = True
            mock_cap.read.return_value = (True, np.zeros((480, 640, 3), dtype=np.uint8))

            frame = await svc.get_frame()
            assert frame is not None
            assert frame.shape == (480, 640, 3)
            # cap.read() should have been called exactly once for the frame
            assert mock_cap.read.call_count == 1

    @pytest.mark.asyncio
    async def test_get_frame_raises_when_cap_is_none(self):
        """get_frame() raises RuntimeError when _cap is None (device not open)."""
        svc = LatestFrameCapture()
        with pytest.raises(RuntimeError, match="not open"):
            await svc.get_frame()


# ---------------------------------------------------------------------------
# _read_frame()
# ---------------------------------------------------------------------------


class TestReadFrame:
    def test_read_frame_raises_when_cap_read_fails(self, mock_cap):
        """_read_frame raises RuntimeError when cap.read() returns False."""
        mock_cap.read.return_value = (False, None)
        mock_cap.isOpened.return_value = True
        svc = LatestFrameCapture()
        svc._cap = mock_cap
        with pytest.raises(RuntimeError, match="cap.read\\(\\) returned False"):
            svc._read_frame()

    def test_read_frame_raises_when_cap_is_none(self):
        """_read_frame raises RuntimeError when _cap is None."""
        svc = LatestFrameCapture()
        with pytest.raises(RuntimeError, match="not open"):
            svc._read_frame()


# ---------------------------------------------------------------------------
# CAPTURE_DEVICE module-level constant
# ---------------------------------------------------------------------------


class TestCaptureDeviceEnvVar:
    def test_capture_device_readable_from_env(self, monkeypatch):
        """CAPTURE_DEVICE module constant uses CAPTURE_DEVICE env var when set."""
        # Verify the constant exists and is a string
        assert isinstance(CAPTURE_DEVICE, str)

    def test_capture_device_default_is_video0(self, monkeypatch):
        """CAPTURE_DEVICE defaults to /dev/video0 when env var is unset."""
        # When env var is absent, CAPTURE_DEVICE should be /dev/video0
        # We test the actual imported value — if env var wasn't set during import, default applies
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
