"""Asyncio-compatible frame capture service with platform-specific backends.

On Linux: uses direct V4L2 ioctls + mmap for low-latency MJPEG capture.
On Windows: uses OpenCV's DirectShow backend (cv2.VideoCapture).

The factory function ``create_capture()`` returns the correct backend
for the current platform. Both backends expose the same public interface.

Exports:
    CAPTURE_DEVICE   -- Module-level device path from env
    CaptureBackend   -- Abstract base class defining the capture interface
    create_capture   -- Factory that returns the right backend for the OS
    CaptureRegistry  -- Thread-safe ref-counted pool of CaptureBackend instances
"""
import abc
import logging
import os
import sys
import threading
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_DEFAULT_DEVICE = "0" if sys.platform == "win32" else "/dev/video0"
CAPTURE_DEVICE: str = os.getenv("CAPTURE_DEVICE", _DEFAULT_DEVICE)

# If no new frame arrives within this many seconds, consider the device dead.
_STALE_FRAME_TIMEOUT = 3.0


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
        self._last_frame_time: float = 0.0
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._reader_error = threading.Event()

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
        self._check_health()
        with self._frame_lock:
            if self._latest_frame is None:
                raise RuntimeError("No frame available from capture device")
            return self._latest_frame

    async def get_jpeg(self) -> bytes:
        """Return the most recent JPEG bytes. Non-blocking."""
        self._check_health()
        with self._frame_lock:
            if self._latest_jpeg is None:
                raise RuntimeError("No frame available from capture device")
            return self._latest_jpeg

    def _check_health(self) -> None:
        """Raise RuntimeError if capture is unhealthy (reader dead or frames stale)."""
        if not self.is_open:
            raise RuntimeError("Capture device is not open")
        if self._reader_error.is_set():
            raise RuntimeError("Capture reader thread died — device disconnected")
        if (
            self._last_frame_time > 0
            and (time.monotonic() - self._last_frame_time) > _STALE_FRAME_TIMEOUT
        ):
            raise RuntimeError(
                "No new frame for %.1fs — device may be disconnected"
                % (time.monotonic() - self._last_frame_time)
            )

    def _start_reader(self) -> None:
        """Start the background reader thread."""
        self._stop_event.clear()
        self._reader_error.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_wrapper, daemon=True, name="capture-reader"
        )
        self._reader_thread.start()

    def _reader_wrapper(self) -> None:
        """Wrapper that sets _reader_error if the loop exits unexpectedly."""
        try:
            self._reader_loop()
        finally:
            if not self._stop_event.is_set():
                logger.warning("Capture reader exited unexpectedly — flagging error")
                self._reader_error.set()

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


class CaptureRegistry:
    """Thread-safe, reference-counted pool of CaptureBackend instances.

    Backends are keyed by device path.  Multiple callers (zones) may acquire
    the same device path — they share one backend and each increment the
    reference count.  The backend is only released (closed + destroyed) when
    the last holder calls release().

    Methods use a threading.Lock (not asyncio.Lock) because callers run from
    asyncio.to_thread() worker threads, not the event loop.

    Usage::

        registry = CaptureRegistry()
        backend = registry.acquire("/dev/video0")   # creates or reuses
        ...
        registry.release("/dev/video0")             # decrements ref; destroys at 0
        registry.shutdown()                         # force-release all
    """

    def __init__(self) -> None:
        self._backends: dict[str, CaptureBackend] = {}
        self._ref_counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def acquire(self, device_path: str) -> CaptureBackend:
        """Return a backend for *device_path*, creating it on first acquisition.

        Increments the reference count.  The backend's ``open()`` is called
        only on the first acquisition.
        """
        with self._lock:
            if device_path not in self._backends:
                backend = create_capture(device_path)
                backend.open()
                self._backends[device_path] = backend
                self._ref_counts[device_path] = 0
            self._ref_counts[device_path] += 1
            return self._backends[device_path]

    def release(self, device_path: str) -> None:
        """Decrement the reference count for *device_path*.

        When the count reaches zero the backend is removed from the pool and
        its ``release()`` method is called.  Releasing a path that was never
        acquired is a no-op.
        """
        with self._lock:
            if device_path not in self._ref_counts:
                return
            self._ref_counts[device_path] -= 1
            if self._ref_counts[device_path] <= 0:
                backend = self._backends.pop(device_path)
                self._ref_counts.pop(device_path)
                backend.release()

    def get_default(self) -> Optional[CaptureBackend]:
        """Return the backend for the default CAPTURE_DEVICE, or None."""
        with self._lock:
            return self._backends.get(CAPTURE_DEVICE)

    def shutdown(self) -> None:
        """Force-release all backends regardless of reference count.

        Exceptions raised by individual ``backend.release()`` calls are caught
        and logged so that all backends are released even if one fails.
        """
        with self._lock:
            for device_path, backend in list(self._backends.items()):
                try:
                    backend.release()
                except Exception:
                    logger.exception(
                        "Error releasing capture backend for %s during shutdown",
                        device_path,
                    )
            self._backends.clear()
            self._ref_counts.clear()
