"""Asyncio-compatible frame capture service backed by OpenCV/V4L2.

Exports:
    CAPTURE_DEVICE     -- Module-level device path from env (or /dev/video0)
    LatestFrameCapture -- Pull-based capture class; use open()/release()/get_frame()
"""
import asyncio
import logging
import os
import struct
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Module-level constant — read once at import time
CAPTURE_DEVICE: str = os.getenv("CAPTURE_DEVICE", "/dev/video0")


class LatestFrameCapture:
    """Pull-based, asyncio-compatible wrapper around cv2.VideoCapture.

    Usage::

        capture = LatestFrameCapture("/dev/video0")
        capture.open()
        frame = await capture.get_frame()   # non-blocking; delegates to thread pool
        capture.release()

    ``open()`` can be called again with a new path to switch devices at runtime
    without restarting.  ``get_frame()`` acquires an asyncio.Lock so that
    concurrent callers serialize reads without racing.
    """

    def __init__(self, device_path: str = "/dev/video0") -> None:
        self._device_path: str = device_path
        self._cap: Optional[cv2.VideoCapture] = None
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def open(self, device_path: Optional[str] = None) -> None:
        """Open (or reopen) the V4L2 capture device.

        Closes any currently open device first.  Configures MJPEG format at
        640x480.  Discards the first 3 frames to avoid black/garbage warmup
        frames (Pitfall 5 in research).

        Args:
            device_path: Override device path. When None, uses the path stored
                         at construction time (or the most recent open() call).

        Raises:
            RuntimeError: If the device cannot be opened.
        """
        # Close existing device before reopening
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        path = device_path if device_path is not None else self._device_path
        self._device_path = path

        self._cap = cv2.VideoCapture(path, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open capture device: {path}")

        # Request MJPEG at 640x480 — device may silently refuse; log actual fourcc
        fourcc_mjpg = cv2.VideoWriter_fourcc(*"MJPG")
        self._cap.set(cv2.CAP_PROP_FOURCC, fourcc_mjpg)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        actual_fourcc = int(self._cap.get(cv2.CAP_PROP_FOURCC))
        try:
            fourcc_str = struct.pack("<I", actual_fourcc).decode("ascii", errors="replace")
        except Exception:
            fourcc_str = str(actual_fourcc)
        logger.info("Opened %s — actual fourcc: %s", path, fourcc_str)

        # Discard first 3 frames to let AGC/AEC stabilize (Pitfall 5)
        for _ in range(3):
            self._cap.read()

    def release(self) -> None:
        """Release the capture device.  Safe to call when already released."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _read_frame(self) -> np.ndarray:
        """Synchronous blocking read — must only be called via asyncio.to_thread.

        Returns:
            BGR uint8 numpy array of shape (height, width, 3).

        Raises:
            RuntimeError: If the device is not open or cap.read() fails.
        """
        if self._cap is None or not self._cap.isOpened():
            raise RuntimeError("Capture device is not open")
        ret, frame = self._cap.read()
        if not ret:
            raise RuntimeError(
                "cap.read() returned False — device may be disconnected"
            )
        return frame

    async def get_frame(self) -> np.ndarray:
        """Non-blocking async frame read; delegates blocking cap.read() to thread pool.

        Acquires an asyncio.Lock to prevent concurrent reads from racing.

        Returns:
            BGR uint8 numpy array of shape (height, width, 3).

        Raises:
            RuntimeError: If the device is not open.
        """
        if self._cap is None:
            raise RuntimeError("Capture device is not open")
        async with self._lock:
            return await asyncio.to_thread(self._read_frame)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def device_path(self) -> str:
        """The current (or most recently configured) device path."""
        return self._device_path
