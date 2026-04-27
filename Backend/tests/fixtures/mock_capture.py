"""Mock capture fixture: deterministic frame producer for coordinator tests."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import numpy as np

# V4L2 paces wait_for_new_frame at hardware framerate (~60 Hz). With the
# default AsyncMock(return_value=...) the coordinator's _frame_loop becomes
# an unbounded tight asyncio loop, allocating millions of numpy arrays per
# `asyncio.sleep(2.0)` test window — pytest peak RSS ballooned to >20 GB.
# Pace the mock at 200 Hz (5 ms) so the loop yields like real hardware would.
# Stays well above every fps/packet-rate floor: e2e asserts >=40 fps, >=50
# packets in 2 s; at 200 Hz we deliver ~400 packets and ~200 fps with margin.
_MOCK_FRAME_PERIOD_S = 0.005


def _default_frame() -> np.ndarray:
    """480x640x3 BGR frame with 3 horizontal color bands (R, G, B left-to-right).

    Used to assert that sub_sample_gradient produces left-to-right ordered samples.
    OpenCV uses BGR ordering in the ndarray.
    """
    h, w = 480, 640
    frame = np.zeros((h, w, 3), dtype=np.uint8)
    third = w // 3
    # Left third: pure red  -> BGR (0, 0, 255)
    frame[:, :third] = [0, 0, 255]
    # Middle third: pure green -> BGR (0, 255, 0)
    frame[:, third:2 * third] = [0, 255, 0]
    # Right third: pure blue -> BGR (255, 0, 0)
    frame[:, 2 * third:] = [255, 0, 0]
    return frame


def make_mock_capture(frame: np.ndarray | None = None) -> MagicMock:
    """Return a MagicMock with async wait_for_new_frame / get_frame returning ``frame``.

    Defaults to a 3-band horizontal gradient when frame is None.
    """
    if frame is None:
        frame = _default_frame()

    async def _paced_wait():
        await asyncio.sleep(_MOCK_FRAME_PERIOD_S)
        return frame

    async def _paced_get():
        await asyncio.sleep(_MOCK_FRAME_PERIOD_S)
        return frame

    mock = MagicMock()
    mock.wait_for_new_frame = AsyncMock(side_effect=_paced_wait)
    mock.get_frame = AsyncMock(side_effect=_paced_get)
    mock.open = MagicMock()
    mock.release = MagicMock()
    mock._last_frame_time = time.monotonic()
    return mock
