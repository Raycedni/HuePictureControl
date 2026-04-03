"""Device identity module for stable cross-reboot identification of V4L2 devices.

Provides get_stable_id() which returns a consistent identifier for a capture
device using USB VID/PID/serial from sysfs when available, or a degraded
card@bus_info fallback when sysfs is inaccessible (e.g., some Docker setups).
"""
import os
from typing import Tuple


def get_stable_id(device_path: str, bus_info: str, card: str) -> Tuple[str, bool]:
    """Return a stable identifier for a V4L2 capture device.

    Attempts to read USB identity from sysfs:
      /sys/class/video4linux/{device}/device/idVendor
      /sys/class/video4linux/{device}/device/idProduct
      /sys/class/video4linux/{device}/device/serial  (optional)

    Args:
        device_path: Absolute path to device node, e.g. "/dev/video0".
        bus_info: Bus info string from VIDIOC_QUERYCAP, e.g. "usb-0000:00:14.0-2".
        card: Card name string from VIDIOC_QUERYCAP, e.g. "AV.io HD".

    Returns:
        Tuple of (stable_id, is_stable) where:
          - stable_id: "{vid}:{pid}:{serial}" or "{vid}:{pid}" if sysfs available,
                       or "{card}@{bus_info}" in degraded/fallback mode.
          - is_stable: True if sysfs identity was used, False if degraded fallback.
    """
    device_name = os.path.basename(device_path)
    sysfs_base = f"/sys/class/video4linux/{device_name}/device"

    try:
        with open(f"{sysfs_base}/idVendor") as f:
            vid = f.read().strip()
        with open(f"{sysfs_base}/idProduct") as f:
            pid = f.read().strip()

        try:
            with open(f"{sysfs_base}/serial") as f:
                serial = f.read().strip()
            return (f"{vid}:{pid}:{serial}", True)
        except (FileNotFoundError, OSError):
            return (f"{vid}:{pid}", True)

    except (FileNotFoundError, OSError):
        return (f"{card}@{bus_info}", False)
