"""Asyncio-compatible frame capture service with platform-specific backends.

On Linux: uses direct V4L2 ioctls + mmap for low-latency MJPEG capture.
On Windows: uses OpenCV's DirectShow backend (cv2.VideoCapture).

The factory function ``create_capture()`` returns the correct backend
for the current platform. Both backends expose the same public interface.

Exports:
    CAPTURE_DEVICE   -- Module-level device path from env
    CaptureBackend   -- Abstract base class defining the capture interface
    create_capture   -- Factory that returns the right backend for the OS
"""
import abc
import logging
import os
import sys
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_DEVICE = "0" if sys.platform == "win32" else "/dev/video0"
CAPTURE_DEVICE: str = os.getenv("CAPTURE_DEVICE", _DEFAULT_DEVICE)


class CaptureBackend(abc.ABC):
    """Abstract base class for platform-specific video capture backends.

    Subclasses must implement open(), release(), and _reader_loop().
    get_frame() / get_jpeg() / is_open are provided by this base class.
    """

    def __init__(self, device_path: str) -> None:
        self._device_path = device_path
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_jpeg: Optional[bytes] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def device_path(self) -> str:
        return self._device_path

    @property
    @abc.abstractmethod
    def is_open(self) -> bool:
        """Return True if the capture device is currently open."""

    @abc.abstractmethod
    def open(self, device_path: Optional[str] = None) -> None:
        """Open the capture device and start the background reader thread."""

    @abc.abstractmethod
    def release(self) -> None:
        """Stop capture and release all resources."""

    async def get_frame(self) -> np.ndarray:
        """Return the most recent decoded BGR frame. Non-blocking."""
        if not self.is_open:
            raise RuntimeError("Capture device is not open")
        with self._frame_lock:
            if self._latest_frame is None:
                raise RuntimeError("No frame available from capture device")
            return self._latest_frame

    async def get_jpeg(self) -> bytes:
        """Return the most recent JPEG bytes. Non-blocking."""
        if not self.is_open:
            raise RuntimeError("Capture device is not open")
        with self._frame_lock:
            if self._latest_jpeg is None:
                raise RuntimeError("No frame available from capture device")
            return self._latest_jpeg

    def _start_reader(self) -> None:
        """Start the background reader thread."""
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="capture-reader"
        )
        self._reader_thread.start()

    def _stop_reader(self) -> None:
        """Signal and join the background reader thread."""
        self._stop_event.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=3)
            self._reader_thread = None

    @abc.abstractmethod
    def _reader_loop(self) -> None:
        """Background thread: continuously capture frames and store the latest."""


def create_capture(device_path: str = CAPTURE_DEVICE) -> CaptureBackend:
    """Factory: return the appropriate capture backend for the current OS."""
    if sys.platform == "win32":
        from services.capture_dshow import DirectShowCapture
        return DirectShowCapture(device_path)
    else:
        from services.capture_v4l2 import V4L2Capture
        return V4L2Capture(device_path)
