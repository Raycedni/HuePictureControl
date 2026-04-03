"""Unit tests for enumerate_capture_devices() in capture_v4l2.py.

All V4L2 ioctls and filesystem calls are mocked — no real device needed.
"""
import fcntl
import os
import struct
from unittest.mock import MagicMock, patch

import pytest

from services.capture_v4l2 import enumerate_capture_devices, V4L2DeviceInfo

_VIDIOC_QUERYCAP = 0x80685600


def _build_cap_buf(
    driver: str = "uvcvideo",
    card: str = "Test Card",
    bus_info: str = "usb-0000:00:14.0-2",
    device_caps: int = 0x05,
) -> bytearray:
    """Build a 104-byte VIDIOC_QUERYCAP response buffer with specified fields."""
    buf = bytearray(104)
    # driver at offset 0, 16 bytes
    driver_bytes = driver.encode("utf-8")[:16]
    buf[0 : len(driver_bytes)] = driver_bytes
    # card at offset 16, 32 bytes
    card_bytes = card.encode("utf-8")[:32]
    buf[16 : 16 + len(card_bytes)] = card_bytes
    # bus_info at offset 48, 32 bytes
    bus_bytes = bus_info.encode("utf-8")[:32]
    buf[48 : 48 + len(bus_bytes)] = bus_bytes
    # device_caps at offset 88 (4 bytes, little-endian)
    struct.pack_into("<I", buf, 88, device_caps)
    return buf


def _ioctl_side_effect(caps_by_fd: dict):
    """Return an ioctl side-effect that writes cap_buf content into the buffer arg."""

    def _ioctl(fd, request, buf):
        if request == _VIDIOC_QUERYCAP and fd in caps_by_fd:
            cap_data = caps_by_fd[fd]
            for i, b in enumerate(cap_data):
                buf[i] = b
        return 0

    return _ioctl


# ---------------------------------------------------------------------------
# enumerate_capture_devices tests
# ---------------------------------------------------------------------------


def test_only_capture_nodes_returned():
    """Only devices with V4L2_CAP_VIDEO_CAPTURE bit set are returned."""
    # video0: device_caps=0x05 (VIDEO_CAPTURE | STREAMING) → included
    # video1: device_caps=0x00 → excluded
    video0_cap = _build_cap_buf(device_caps=0x05)
    video1_cap = _build_cap_buf(device_caps=0x00)

    fd_map = {10: video0_cap, 11: video1_cap}

    def fake_open(path, flags):
        return 10 if "video0" in path else 11

    with (
        patch("glob.glob", return_value=["/dev/video0", "/dev/video1"]),
        patch("os.open", side_effect=fake_open),
        patch("os.close"),
        patch("fcntl.ioctl", side_effect=_ioctl_side_effect(fd_map)),
    ):
        result = enumerate_capture_devices()

    assert len(result) == 1
    assert result[0].device_path == "/dev/video0"


def test_metadata_node_excluded():
    """Nodes with META_CAPTURE only (no VIDEO_CAPTURE bit) are excluded."""
    # video0: device_caps=0x01 (VIDEO_CAPTURE) → included
    # video1: device_caps=0x00100000 (META_CAPTURE only) → excluded
    video0_cap = _build_cap_buf(device_caps=0x01)
    video1_cap = _build_cap_buf(device_caps=0x00100000)

    fd_map = {10: video0_cap, 11: video1_cap}

    def fake_open(path, flags):
        return 10 if "video0" in path else 11

    with (
        patch("glob.glob", return_value=["/dev/video0", "/dev/video1"]),
        patch("os.open", side_effect=fake_open),
        patch("os.close"),
        patch("fcntl.ioctl", side_effect=_ioctl_side_effect(fd_map)),
    ):
        result = enumerate_capture_devices()

    assert len(result) == 1
    assert result[0].device_path == "/dev/video0"


def test_enumerate_returns_card_driver_bus():
    """V4L2DeviceInfo fields are populated from VIDIOC_QUERYCAP response."""
    cap = _build_cap_buf(
        driver="uvcvideo",
        card="Test Card",
        bus_info="usb-0000:00:14.0-2",
        device_caps=0x05,
    )

    with (
        patch("glob.glob", return_value=["/dev/video0"]),
        patch("os.open", return_value=42),
        patch("os.close"),
        patch("fcntl.ioctl", side_effect=_ioctl_side_effect({42: cap})),
    ):
        result = enumerate_capture_devices()

    assert len(result) == 1
    info = result[0]
    assert info.device_path == "/dev/video0"
    assert info.card == "Test Card"
    assert info.driver == "uvcvideo"
    assert info.bus_info == "usb-0000:00:14.0-2"


def test_enumerate_handles_open_error():
    """OSError on os.open is caught; device is skipped, empty list returned."""
    with (
        patch("glob.glob", return_value=["/dev/video0"]),
        patch("os.open", side_effect=OSError("Permission denied")),
        patch("os.close"),
    ):
        result = enumerate_capture_devices()

    assert result == []


def test_enumerate_handles_ioctl_error():
    """OSError on fcntl.ioctl is caught; device is skipped, empty list returned."""
    with (
        patch("glob.glob", return_value=["/dev/video0"]),
        patch("os.open", return_value=5),
        patch("os.close"),
        patch("fcntl.ioctl", side_effect=OSError("ioctl failed")),
    ):
        result = enumerate_capture_devices()

    assert result == []


def test_enumerate_empty_when_no_devices():
    """Returns empty list when no /dev/video* nodes exist."""
    with patch("glob.glob", return_value=[]):
        result = enumerate_capture_devices()

    assert result == []


def test_enumerate_sorts_device_paths():
    """Devices are processed in sorted order (video0 before video1)."""
    video0_cap = _build_cap_buf(card="Card0", device_caps=0x01)
    video1_cap = _build_cap_buf(card="Card1", device_caps=0x01)

    fd_map = {10: video0_cap, 11: video1_cap}

    def fake_open(path, flags):
        return 10 if "video0" in path else 11

    # Return in reverse order — enumerate_capture_devices must sort
    with (
        patch("glob.glob", return_value=["/dev/video1", "/dev/video0"]),
        patch("os.open", side_effect=fake_open),
        patch("os.close"),
        patch("fcntl.ioctl", side_effect=_ioctl_side_effect(fd_map)),
    ):
        result = enumerate_capture_devices()

    assert result[0].device_path == "/dev/video0"
    assert result[1].device_path == "/dev/video1"
