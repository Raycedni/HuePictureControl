"""Unit tests for the DirectShow (Windows) capture backend.

Entire module is skipped when not running on Windows.
"""
import sys

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DirectShow backend requires Windows")

from services.capture_dshow import DirectShowCapture  # noqa: E402


class TestDirectShowInit:
    def test_stores_device_path(self):
        svc = DirectShowCapture("1")
        assert svc._device_path == "1"

    def test_default_device_path(self):
        svc = DirectShowCapture()
        assert svc._device_path == "0"

    def test_is_open_false_initially(self):
        svc = DirectShowCapture()
        assert svc.is_open is False

    def test_latest_frame_is_none(self):
        svc = DirectShowCapture()
        assert svc._latest_frame is None


class TestDirectShowRelease:
    def test_release_safe_when_not_opened(self):
        svc = DirectShowCapture()
        svc.release()
        assert svc.is_open is False

    def test_release_sets_stop_event(self):
        svc = DirectShowCapture()
        svc.release()
        assert svc._stop_event.is_set()

    def test_release_clears_latest_frame(self):
        svc = DirectShowCapture()
        svc._latest_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        svc.release()
        assert svc._latest_frame is None


class TestDirectShowGetFrame:
    @pytest.mark.asyncio
    async def test_get_frame_raises_when_not_open(self):
        svc = DirectShowCapture()
        with pytest.raises(RuntimeError, match="not open"):
            await svc.get_frame()

    @pytest.mark.asyncio
    async def test_get_jpeg_raises_when_not_open(self):
        svc = DirectShowCapture()
        with pytest.raises(RuntimeError, match="not open"):
            await svc.get_jpeg()


class TestDirectShowDevicePath:
    def test_device_path_property(self):
        svc = DirectShowCapture("2")
        assert svc.device_path == "2"
