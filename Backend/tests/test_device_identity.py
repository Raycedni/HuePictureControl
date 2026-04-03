"""Unit tests for get_stable_id() in device_identity.py.

Sysfs filesystem reads are mocked — no real hardware needed.
"""
from unittest.mock import mock_open, patch, call, MagicMock
import builtins

import pytest

from services.device_identity import get_stable_id


# ---------------------------------------------------------------------------
# get_stable_id tests
# ---------------------------------------------------------------------------


def test_sysfs_stable_id():
    """Returns VID:PID:serial when all sysfs files are available."""
    sysfs_files = {
        "/sys/class/video4linux/video0/device/idVendor": "1234\n",
        "/sys/class/video4linux/video0/device/idProduct": "5678\n",
        "/sys/class/video4linux/video0/device/serial": "ABC\n",
    }

    def fake_open(path, *args, **kwargs):
        if path in sysfs_files:
            return mock_open(read_data=sysfs_files[path])()
        raise FileNotFoundError(f"No such file: {path}")

    with patch("builtins.open", side_effect=fake_open):
        stable_id, is_stable = get_stable_id("/dev/video0", "usb-bus", "Card")

    assert stable_id == "1234:5678:ABC"
    assert is_stable is True


def test_sysfs_no_serial():
    """Returns VID:PID (no serial) when serial file is absent."""
    vendor_mock = mock_open(read_data="1234\n")()
    product_mock = mock_open(read_data="5678\n")()

    def fake_open(path, *args, **kwargs):
        if path.endswith("idVendor"):
            return mock_open(read_data="1234\n")()
        elif path.endswith("idProduct"):
            return mock_open(read_data="5678\n")()
        elif path.endswith("serial"):
            raise FileNotFoundError("No serial file")
        raise FileNotFoundError(f"No such file: {path}")

    with patch("builtins.open", side_effect=fake_open):
        stable_id, is_stable = get_stable_id("/dev/video0", "usb-bus", "Card")

    assert stable_id == "1234:5678"
    assert is_stable is True


def test_degraded_stable_id():
    """Returns card@bus_info when sysfs idVendor is unavailable."""
    with patch("builtins.open", side_effect=FileNotFoundError("No sysfs")):
        stable_id, is_stable = get_stable_id(
            "/dev/video0", "usb-0000:00:14.0-2", "AV.io HD"
        )

    assert stable_id == "AV.io HD@usb-0000:00:14.0-2"
    assert is_stable is False


def test_degraded_on_oserror():
    """Returns degraded identity when sysfs access raises OSError."""
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        stable_id, is_stable = get_stable_id(
            "/dev/video1", "usb-0000:00:14.0-3", "Test Capture"
        )

    assert stable_id == "Test Capture@usb-0000:00:14.0-3"
    assert is_stable is False


def test_sysfs_path_uses_device_basename():
    """Sysfs path is derived from the basename of device_path."""
    calls = []

    def fake_open(path, *args, **kwargs):
        calls.append(path)
        raise FileNotFoundError("No such file")

    with patch("builtins.open", side_effect=fake_open):
        get_stable_id("/dev/video7", "usb-bus", "Some Card")

    # Should attempt idVendor under video7 (not video0 or any other)
    assert any("video7" in p for p in calls)


def test_stable_id_strips_whitespace():
    """VID, PID, and serial values have trailing newlines/whitespace stripped."""
    def fake_open(path, *args, **kwargs):
        if path.endswith("idVendor"):
            return mock_open(read_data="abcd\n")()
        elif path.endswith("idProduct"):
            return mock_open(read_data="ef01\n")()
        elif path.endswith("serial"):
            return mock_open(read_data="SN-XYZ  \n")()
        raise FileNotFoundError(f"No such file: {path}")

    with patch("builtins.open", side_effect=fake_open):
        stable_id, is_stable = get_stable_id("/dev/video0", "bus", "card")

    assert stable_id == "abcd:ef01:SN-XYZ"
    assert is_stable is True
