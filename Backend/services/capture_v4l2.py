"""V4L2 capture backend for Linux.

Reads MJPEG frames directly from the V4L2 device via mmap, bypassing
OpenCV's broken V4L2 backend in pip-installed opencv-python-headless.
Decodes MJPEG to BGR with cv2.imdecode.

Also provides enumerate_capture_devices() for listing available V4L2
capture nodes without opening a streaming session.
"""
import ctypes
import fcntl
import glob
import logging
import mmap
import os
import struct
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from services.capture_service import CaptureBackend

logger = logging.getLogger(__name__)

_WIDTH = 320
_HEIGHT = 240
_NUM_BUFFERS = 4

# ---- V4L2 ctypes structs (64-bit safe) ----

_V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
_V4L2_MEMORY_MMAP = 1
_V4L2_PIX_FMT_MJPEG = 0x47504A4D  # 'MJPG'


class _timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class _v4l2_timecode(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("frames", ctypes.c_uint8),
        ("seconds", ctypes.c_uint8),
        ("minutes", ctypes.c_uint8),
        ("hours", ctypes.c_uint8),
        ("userbits", ctypes.c_uint8 * 4),
    ]


class _v4l2_buffer_m(ctypes.Union):
    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("userptr", ctypes.c_ulong),
        ("planes", ctypes.c_void_p),
        ("fd", ctypes.c_int32),
    ]


class _v4l2_buffer(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("bytesused", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("timestamp", _timeval),
        ("timecode", _v4l2_timecode),
        ("sequence", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("m", _v4l2_buffer_m),
        ("length", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("request_fd", ctypes.c_int32),
    ]


# Compute ioctl numbers from struct size (architecture-safe)
_IOC_W = 1
_IOC_R = 2
_v4l2_buf_size = ctypes.sizeof(_v4l2_buffer)


def _iowr(magic: int, nr: int, size: int) -> int:
    return ((_IOC_R | _IOC_W) << 30) | (size << 16) | (magic << 8) | nr


_VIDIOC_QUERYCAP = 0x80685600
_VIDIOC_S_FMT = 0xC0D05605
_VIDIOC_REQBUFS = 0xC0145608
_VIDIOC_QUERYBUF = _iowr(ord("V"), 9, _v4l2_buf_size)
_VIDIOC_QBUF = _iowr(ord("V"), 15, _v4l2_buf_size)
_VIDIOC_DQBUF = _iowr(ord("V"), 17, _v4l2_buf_size)
_VIDIOC_STREAMON = 0x40045612
_VIDIOC_STREAMOFF = 0x40045613
_VIDIOC_S_PARM = 0xC0CC5616


# ---------------------------------------------------------------------------
# Device enumeration
# ---------------------------------------------------------------------------


@dataclass
class V4L2DeviceInfo:
    """Metadata for a V4L2 capture-capable device node."""

    device_path: str
    card: str
    driver: str
    bus_info: str


def enumerate_capture_devices() -> list[V4L2DeviceInfo]:
    """Return all /dev/video* nodes that support V4L2_CAP_VIDEO_CAPTURE.

    Opens each node with O_RDWR | O_NONBLOCK (non-blocking prevents stalling
    on devices already held by the capture backend). Issues VIDIOC_QUERYCAP
    and filters to nodes where the device_caps field has bit 0x01 set.

    Inaccessible or non-capture nodes are silently skipped.

    Returns:
        List of V4L2DeviceInfo sorted by device_path.
    """
    devices: list[V4L2DeviceInfo] = []

    for path in sorted(glob.glob("/dev/video*")):
        fd = None
        try:
            fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
            cap_buf = bytearray(104)
            fcntl.ioctl(fd, _VIDIOC_QUERYCAP, cap_buf)

            device_caps = struct.unpack_from("<I", cap_buf, 88)[0]
            if not (device_caps & 0x01):
                # Not a VIDEO_CAPTURE node — skip (e.g. metadata nodes)
                continue

            driver = cap_buf[0:16].rstrip(b"\x00").decode("utf-8", errors="replace")
            card = cap_buf[16:48].rstrip(b"\x00").decode("utf-8", errors="replace")
            bus_info = cap_buf[48:80].rstrip(b"\x00").decode("utf-8", errors="replace")

            devices.append(
                V4L2DeviceInfo(
                    device_path=path,
                    card=card,
                    driver=driver,
                    bus_info=bus_info,
                )
            )
        except OSError:
            # Device inaccessible, busy, or not a V4L2 node — skip silently
            pass
        finally:
            if fd is not None:
                os.close(fd)

    return devices


# ---------------------------------------------------------------------------
# Streaming capture backend
# ---------------------------------------------------------------------------


class V4L2Capture(CaptureBackend):
    """V4L2 capture backend using direct ioctls + mmap.

    A background thread dequeues MJPEG frames from the kernel and keeps
    the latest decoded BGR frame available. get_frame() returns
    immediately with zero pipe overhead.
    """

    def __init__(self, device_path: str = "/dev/video0") -> None:
        super().__init__(device_path)
        self._fd: Optional[int] = None
        self._buffers: list[mmap.mmap] = []

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def open(self, device_path: Optional[str] = None) -> None:
        """Open the V4L2 device, configure MJPEG, mmap buffers, start streaming."""
        self.release()

        path = device_path if device_path is not None else self._device_path
        self._device_path = path

        if not os.path.exists(path):
            raise RuntimeError(f"Capture device not found: {path}")

        try:
            self._fd = os.open(path, os.O_RDWR)
        except OSError as exc:
            raise RuntimeError(f"Cannot open {path}: {exc}") from exc

        try:
            self._setup_device()
        except Exception:
            os.close(self._fd)
            self._fd = None
            raise

        self._start_reader()
        logger.info("Opened %s — MJPEG %dx%d, %d buffers", path, _WIDTH, _HEIGHT, _NUM_BUFFERS)

    def _setup_device(self) -> None:
        fd = self._fd

        # Verify VIDEO_CAPTURE capability
        cap_buf = bytearray(104)
        fcntl.ioctl(fd, _VIDIOC_QUERYCAP, cap_buf)
        device_caps = struct.unpack_from("<I", cap_buf, 88)[0]
        if not (device_caps & 0x01):
            raise RuntimeError("Device does not support VIDEO_CAPTURE")

        # Set format: MJPEG 640x480
        fmt = bytearray(208)
        struct.pack_into("<I", fmt, 0, _V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into("<II", fmt, 4, _WIDTH, _HEIGHT)
        struct.pack_into("<I", fmt, 12, _V4L2_PIX_FMT_MJPEG)
        fcntl.ioctl(fd, _VIDIOC_S_FMT, fmt)

        # Request mmap buffers
        reqbufs = bytearray(20)
        struct.pack_into("<III", reqbufs, 0, _NUM_BUFFERS, _V4L2_BUF_TYPE_VIDEO_CAPTURE, _V4L2_MEMORY_MMAP)
        fcntl.ioctl(fd, _VIDIOC_REQBUFS, reqbufs)
        count = struct.unpack_from("<I", reqbufs, 0)[0]

        # Query, mmap, and queue each buffer
        self._buffers = []
        for i in range(count):
            vbuf = _v4l2_buffer()
            vbuf.index = i
            vbuf.type = _V4L2_BUF_TYPE_VIDEO_CAPTURE
            vbuf.memory = _V4L2_MEMORY_MMAP
            fcntl.ioctl(fd, _VIDIOC_QUERYBUF, vbuf)

            buf = mmap.mmap(fd, vbuf.length, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=vbuf.m.offset)
            self._buffers.append(buf)

            # Queue buffer
            qbuf = _v4l2_buffer()
            qbuf.index = i
            qbuf.type = _V4L2_BUF_TYPE_VIDEO_CAPTURE
            qbuf.memory = _V4L2_MEMORY_MMAP
            fcntl.ioctl(fd, _VIDIOC_QBUF, qbuf)

        # Request highest framerate (60fps) — device will clamp to its max
        parm = bytearray(204)
        struct.pack_into("<I", parm, 0, _V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into("<II", parm, 8, 1, 60)
        try:
            fcntl.ioctl(fd, _VIDIOC_S_PARM, parm)
            actual_num = struct.unpack_from("<I", parm, 8)[0]
            actual_den = struct.unpack_from("<I", parm, 12)[0]
            if actual_num > 0:
                logger.info("Capture framerate set to %d/%d fps", actual_den, actual_num)
        except OSError:
            logger.debug("VIDIOC_S_PARM not supported, using device default framerate")

        # Start V4L2 streaming
        buf_type = struct.pack("<I", _V4L2_BUF_TYPE_VIDEO_CAPTURE)
        fcntl.ioctl(fd, _VIDIOC_STREAMON, buf_type)

    def release(self) -> None:
        """Stop streaming and release all resources."""
        self._stop_reader()

        if self._fd is not None:
            try:
                buf_type = struct.pack("<I", _V4L2_BUF_TYPE_VIDEO_CAPTURE)
                fcntl.ioctl(self._fd, _VIDIOC_STREAMOFF, buf_type)
            except OSError:
                pass
            for buf in self._buffers:
                buf.close()
            self._buffers = []
            os.close(self._fd)
            self._fd = None

        with self._frame_lock:
            self._latest_frame = None
            self._latest_jpeg = None

    def _reader_loop(self) -> None:
        """Background thread: DQBUF -> decode MJPEG -> store latest -> QBUF."""
        while not self._stop_event.is_set():
            try:
                dqbuf = _v4l2_buffer()
                dqbuf.type = _V4L2_BUF_TYPE_VIDEO_CAPTURE
                dqbuf.memory = _V4L2_MEMORY_MMAP
                fcntl.ioctl(self._fd, _VIDIOC_DQBUF, dqbuf)

                idx = dqbuf.index
                used = dqbuf.bytesused

                mmapped = self._buffers[idx]
                # Copy JPEG bytes and re-queue immediately so kernel
                # gets the buffer back before we spend time decoding.
                jpeg_data = mmapped[:used]

                qbuf = _v4l2_buffer()
                qbuf.index = idx
                qbuf.type = _V4L2_BUF_TYPE_VIDEO_CAPTURE
                qbuf.memory = _V4L2_MEMORY_MMAP
                fcntl.ioctl(self._fd, _VIDIOC_QBUF, qbuf)

                # Decode MJPEG after buffer is re-queued
                frame = cv2.imdecode(
                    np.frombuffer(jpeg_data, dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
                if frame is not None:
                    with self._frame_lock:
                        self._latest_frame = frame
                        self._latest_jpeg = jpeg_data
                        self._last_frame_time = time.monotonic()

            except OSError:
                if not self._stop_event.is_set():
                    logger.warning("V4L2 DQBUF failed — device may be disconnected")
                break
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.warning("Capture reader error: %s", exc)
                break
