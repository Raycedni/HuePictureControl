"""DirectShow capture backend for Windows.

Uses cv2.VideoCapture with the DirectShow backend (CAP_DSHOW) for
low-latency MJPEG capture on Windows. Falls back to default backend
if DirectShow is unavailable.
"""
import logging
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from services.capture_service import CaptureBackend

logger = logging.getLogger(__name__)

_WIDTH = 640
_HEIGHT = 480

_MAX_PROBE_INDEX = 10


@dataclass
class DShowDeviceInfo:
    """Metadata for a DirectShow capture device."""

    device_path: str
    card: str


def enumerate_capture_devices() -> list[DShowDeviceInfo]:
    """Probe DirectShow device indices 0.._MAX_PROBE_INDEX and return those that open successfully.

    Each probe opens and immediately releases the device, so it does not
    interfere with devices already held by a CaptureBackend instance.
    """
    devices: list[DShowDeviceInfo] = []

    for idx in range(_MAX_PROBE_INDEX):
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if cap.isOpened():
            backend_name = cap.getBackendName()
            card = f"Camera {idx} ({backend_name})"
            cap.release()
            devices.append(DShowDeviceInfo(device_path=str(idx), card=card))
        else:
            cap.release()

    return devices


class DirectShowCapture(CaptureBackend):
    """Windows capture backend using OpenCV DirectShow.

    A background thread grabs frames via cv2.VideoCapture and keeps
    the latest decoded BGR frame + JPEG bytes available.
    """

    def __init__(self, device_path: str = "0") -> None:
        super().__init__(device_path)
        self._cap: Optional[cv2.VideoCapture] = None

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def open(self, device_path: Optional[str] = None) -> None:
        """Open the capture device via DirectShow."""
        self.release()

        path = device_path if device_path is not None else self._device_path
        self._device_path = path

        # Accept integer index (e.g. "0") or device name
        try:
            dev_index = int(path)
        except ValueError:
            dev_index = path

        cap = cv2.VideoCapture(dev_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Cannot open capture device: {path}")

        # Configure MJPEG format for hardware-compressed frames
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, _WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, 60)
        # Minimize internal buffer to always get the freshest frame
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._cap = cap
        self._start_reader()

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        logger.info(
            "Opened device %s via DirectShow — %dx%d @ %.1f fps",
            path, actual_w, actual_h, actual_fps,
        )

    def release(self) -> None:
        """Stop capture and release the VideoCapture."""
        self._stop_reader()

        if self._cap is not None:
            self._cap.release()
            self._cap = None

        with self._frame_lock:
            self._latest_frame = None
            self._latest_jpeg = None

    def _reader_loop(self) -> None:
        """Background thread: grab frames via VideoCapture, store latest."""
        while not self._stop_event.is_set():
            if self._cap is None or not self._cap.isOpened():
                break

            ret, frame = self._cap.read()
            if not ret:
                if not self._stop_event.is_set():
                    logger.warning("DirectShow read failed — device may be disconnected")
                break

            # Encode to JPEG for the preview WebSocket path
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            jpeg_data = buf.tobytes() if ok else None

            with self._frame_lock:
                self._latest_frame = frame
                self._last_frame_time = time.monotonic()
                if jpeg_data is not None:
                    self._latest_jpeg = jpeg_data
