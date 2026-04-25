"""Self-test for the make_mock_capture fixture."""
import asyncio

import numpy as np

from tests.fixtures.mock_capture import make_mock_capture


def test_default_frame_is_480x640x3_bgr():
    cap = make_mock_capture()
    frame = asyncio.run(cap.wait_for_new_frame())
    assert isinstance(frame, np.ndarray)
    assert frame.shape == (480, 640, 3)
    assert frame.dtype == np.uint8
    # Left pixel = BGR red = [0, 0, 255]
    assert tuple(frame[0, 0]) == (0, 0, 255)
    # Right pixel = BGR blue = [255, 0, 0]
    assert tuple(frame[0, 639]) == (255, 0, 0)


def test_custom_frame_passthrough():
    custom = np.full((10, 10, 3), 42, dtype=np.uint8)
    cap = make_mock_capture(frame=custom)
    frame = asyncio.run(cap.get_frame())
    assert (frame == 42).all()
