"""V4L2 capture backend for Linux.

Reads MJPEG frames directly from the V4L2 device via mmap, bypassing
OpenCV's broken V4L2 backend in pip-installed opencv-python-headless.
Decodes MJPEG to BGR with cv2.imdecode.

Also provides enumerate_capture_devices() for listing available V4L2
capture nodes without opening a streaming session.
"""
import ctypes
import errno
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

_WIDTH = 640
_HEIGHT = 480
_NUM_BUFFERS = 2

# ---- V4L2 ctypes structs (64-bit safe) ----

_V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
_V4L2_MEMORY_MMAP = 1
_V4L2_PIX_FMT_MJPEG = 0x47504A4D  # 'MJPG'
_V4L2_PIX_FMT_YUYV = 0x56595559  # 'YUYV' -- packed 4:2:2, 2 bytes/pixel
_V4L2_PIX_FMT_YU12 = 0x32315559  # 'YU12' / I420 -- planar 4:2:0, 1.5 bytes/pixel


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
_VIDIOC_G_FMT = 0xC0D05604
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
        self._pixelformat: int = _V4L2_PIX_FMT_MJPEG
        self._width: int = _WIDTH
        self._height: int = _HEIGHT

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
        logger.info(
            "Opened %s -- pixelformat=0x%08X %dx%d, %d buffers",
            path, self._pixelformat, self._width, self._height, _NUM_BUFFERS,
        )

    def _setup_device(self) -> None:
        """Configure V4L2 format + buffers. Format-agnostic: falls back to
        G_FMT when the producer owns the format (scrcpy via v4l2loopback
        exclusive-caps=1). See VERIFICATION.md G-13-01."""
        fd = self._fd

        # Verify VIDEO_CAPTURE capability
        cap_buf = bytearray(104)
        fcntl.ioctl(fd, _VIDIOC_QUERYCAP, cap_buf)
        device_caps = struct.unpack_from("<I", cap_buf, 88)[0]
        if not (device_caps & 0x01):
            raise RuntimeError("Device does not support VIDEO_CAPTURE")

        # Try to negotiate MJPEG 640x480 (physical UVC cameras). If the producer
        # owns the format (v4l2loopback with --exclusive-caps=1, as scrcpy uses),
        # the kernel returns EINVAL -- fall back to G_FMT to adopt the producer's
        # pixel format, width, and height. See VERIFICATION.md G-13-01.
        #
        # struct v4l2_format layout on 64-bit Linux: the `fmt` union contains
        # structs with pointers (v4l2_window.clips), so it has 8-byte alignment.
        # This adds 4 bytes of padding after `type`, putting the pix fields at
        # offsets 8 / 12 / 16 — not 4 / 8 / 12. (Phase 1's original code also
        # used the wrong offsets; UVC cameras tolerated it by falling back to
        # their own defaults, but v4l2loopback is strict.)
        fmt = bytearray(208)
        struct.pack_into("<I",  fmt, 0,  _V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into("<II", fmt, 8,  _WIDTH, _HEIGHT)
        struct.pack_into("<I",  fmt, 16, _V4L2_PIX_FMT_MJPEG)

        try:
            fcntl.ioctl(fd, _VIDIOC_S_FMT, fmt)
            # S_FMT succeeded -- the kernel may still have rounded w/h/fmt, so read back.
            self._width       = struct.unpack_from("<I", fmt, 8)[0] or _WIDTH
            self._height      = struct.unpack_from("<I", fmt, 12)[0] or _HEIGHT
            self._pixelformat = struct.unpack_from("<I", fmt, 16)[0] or _V4L2_PIX_FMT_MJPEG
            logger.info(
                "S_FMT negotiated pixelformat=0x%08X %dx%d",
                self._pixelformat, self._width, self._height,
            )
        except OSError as exc:
            if exc.errno != errno.EINVAL:
                raise
            # Producer owns the format (e.g. v4l2loopback exclusive-caps=1 fed by scrcpy).
            # Read the current format via G_FMT.
            gfmt = bytearray(208)
            struct.pack_into("<I", gfmt, 0, _V4L2_BUF_TYPE_VIDEO_CAPTURE)
            fcntl.ioctl(fd, _VIDIOC_G_FMT, gfmt)
            self._width       = struct.unpack_from("<I", gfmt, 8)[0]
            self._height      = struct.unpack_from("<I", gfmt, 12)[0]
            self._pixelformat = struct.unpack_from("<I", gfmt, 16)[0]
            logger.info(
                "S_FMT rejected (EINVAL) -- producer owns format; G_FMT reports "
                "pixelformat=0x%08X %dx%d",
                self._pixelformat, self._width, self._height,
            )

        if self._pixelformat not in (_V4L2_PIX_FMT_MJPEG, _V4L2_PIX_FMT_YUYV, _V4L2_PIX_FMT_YU12):
            raise RuntimeError(
                f"Unsupported V4L2 pixel format 0x{self._pixelformat:08X} "
                f"on {self._device_path}; supported: MJPEG, YUYV, YU12 (I420)"
            )

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
        # v4l2_streamparm layout:
        #   0: type (4B), 4: capability (4B), 8: capturemode (4B),
        #  12: timeperframe.numerator (4B), 16: timeperframe.denominator (4B)
        parm = bytearray(204)
        struct.pack_into("<I", parm, 0, _V4L2_BUF_TYPE_VIDEO_CAPTURE)
        struct.pack_into("<II", parm, 12, 1, 60)  # numerator=1, denominator=60
        try:
            fcntl.ioctl(fd, _VIDIOC_S_PARM, parm)
            actual_num = struct.unpack_from("<I", parm, 12)[0]
            actual_den = struct.unpack_from("<I", parm, 16)[0]
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
                # Copy payload and re-queue immediately so the kernel gets the buffer back
                # before we spend time decoding.
                raw_data = mmapped[:used]

                qbuf = _v4l2_buffer()
                qbuf.index = idx
                qbuf.type = _V4L2_BUF_TYPE_VIDEO_CAPTURE
                qbuf.memory = _V4L2_MEMORY_MMAP
                fcntl.ioctl(self._fd, _VIDIOC_QBUF, qbuf)

                # Decode based on the negotiated pixel format
                frame = None
                jpeg_bytes: Optional[bytes] = None

                if self._pixelformat == _V4L2_PIX_FMT_MJPEG:
                    frame = cv2.imdecode(
                        np.frombuffer(raw_data, dtype=np.uint8),
                        cv2.IMREAD_COLOR,
                    )
                    jpeg_bytes = bytes(raw_data)
                elif self._pixelformat == _V4L2_PIX_FMT_YUYV:
                    expected = self._width * self._height * 2
                    if used < expected:
                        logger.debug("Short YUYV frame: got %d bytes, expected %d", used, expected)
                        continue
                    arr = np.frombuffer(raw_data, dtype=np.uint8, count=expected)
                    arr = arr.reshape((self._height, self._width, 2))
                    frame = cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_YUYV)
                elif self._pixelformat == _V4L2_PIX_FMT_YU12:
                    expected = self._width * self._height * 3 // 2
                    if used < expected:
                        logger.debug("Short YU12 frame: got %d bytes, expected %d", used, expected)
                        continue
                    arr = np.frombuffer(raw_data, dtype=np.uint8, count=expected)
                    arr = arr.reshape((self._height * 3 // 2, self._width))
                    frame = cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_I420)
                else:
                    # Unreachable -- _setup_device already rejects unsupported formats.
                    if not self._stop_event.is_set():
                        logger.warning(
                            "Unsupported pixelformat 0x%08X in reader loop -- dropping frame",
                            self._pixelformat,
                        )
                    continue

                if frame is not None:
                    # For raw-YUV paths we need to encode to JPEG for the
                    # preview WebSocket (which calls get_jpeg). Downscale to
                    # 480p-equivalent first so encoding a 1080x2400 frame on
                    # every DQBUF doesn't saturate the CPU.
                    if jpeg_bytes is None:
                        h, w = frame.shape[:2]
                        target_h = 480
                        if h > target_h:
                            new_w = max(1, int(w * target_h / h))
                            preview = cv2.resize(frame, (new_w, target_h), interpolation=cv2.INTER_AREA)
                        else:
                            preview = frame
                        ok, buf = cv2.imencode(".jpg", preview, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                        if ok:
                            jpeg_bytes = buf.tobytes()

                    with self._frame_lock:
                        self._latest_frame = frame
                        self._latest_jpeg = jpeg_bytes
                        self._last_frame_time = time.monotonic()
                        self._frame_seq += 1
                    self._new_frame_event.set()

            except OSError:
                if not self._stop_event.is_set():
                    logger.warning("V4L2 DQBUF failed — device may be disconnected")
                break
            except Exception as exc:
                if not self._stop_event.is_set():
                    logger.warning("Capture reader error: %s", exc)
                break
