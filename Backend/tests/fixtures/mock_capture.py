"""Mock capture fixture: deterministic frame producer for coordinator tests."""
import time
from unittest.mock import AsyncMock, MagicMock

import numpy as np


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

    mock = MagicMock()
    mock.wait_for_new_frame = AsyncMock(return_value=frame)
    mock.get_frame = AsyncMock(return_value=frame)
    mock.open = MagicMock()
    mock.release = MagicMock()
    mock._last_frame_time = time.monotonic()
    return mock
