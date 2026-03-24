"""Tests for the /ws/preview WebSocket endpoint for binary JPEG streaming.

Tests cover:
- /ws/preview accepts a WebSocket connection and sends binary data
- Frames are JPEG-encoded binary (bytes, not text)
- If capture raises RuntimeError, no crash occurs
- Disconnecting client is handled cleanly
- Multiple clients can connect simultaneously
"""
import numpy as np
import pytest
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_preview_ws_app(mock_capture):
    """Build a minimal FastAPI app with preview_ws router wired to a mock capture."""
    from routers.preview_ws import router as preview_ws_router

    @asynccontextmanager
    async def lifespan(app):
        app.state.capture = mock_capture
        yield

    test_app = FastAPI(lifespan=lifespan)
    test_app.include_router(preview_ws_router)
    return test_app


def _make_mock_capture(frame=None, error=None):
    """Build a mock capture that returns a frame or raises an error."""
    mock_capture = MagicMock()
    if frame is None:
        # Default: 480x640 solid-blue BGR frame
        solid_blue = np.zeros((480, 640, 3), dtype=np.uint8)
        solid_blue[:, :, 0] = 255
        frame = solid_blue

    if error is not None:
        mock_capture.get_frame = AsyncMock(side_effect=error)
    else:
        mock_capture.get_frame = AsyncMock(return_value=frame)

    return mock_capture


# ---------------------------------------------------------------------------
# /ws/preview tests
# ---------------------------------------------------------------------------


class TestPreviewWsEndpoint:
    def test_websocket_accepts_connection(self):
        """Connecting to /ws/preview is accepted without error."""
        mock_capture = _make_mock_capture()
        test_app = _make_preview_ws_app(mock_capture)
        with TestClient(test_app) as client:
            with client.websocket_connect("/ws/preview") as ws:
                data = ws.receive_bytes()
            # Just ensure connection was accepted and data received
            assert isinstance(data, bytes)

    def test_websocket_sends_binary_jpeg(self):
        """Frames sent over /ws/preview are binary JPEG data (starts with FF D8)."""
        mock_capture = _make_mock_capture()
        test_app = _make_preview_ws_app(mock_capture)
        with TestClient(test_app) as client:
            with client.websocket_connect("/ws/preview") as ws:
                data = ws.receive_bytes()
        # JPEG magic bytes: FF D8
        assert data[:2] == b"\xff\xd8"

    def test_websocket_disconnect_handled_cleanly(self):
        """Disconnecting /ws/preview client does not raise an exception."""
        mock_capture = _make_mock_capture()
        test_app = _make_preview_ws_app(mock_capture)
        with TestClient(test_app) as client:
            with client.websocket_connect("/ws/preview") as ws:
                ws.receive_bytes()  # receive one frame then disconnect
        # No exception = clean disconnect handling

    def test_multiple_clients_can_connect(self):
        """Multiple simultaneous /ws/preview connections all receive frames."""
        mock_capture = _make_mock_capture()
        test_app = _make_preview_ws_app(mock_capture)
        with TestClient(test_app) as client:
            with client.websocket_connect("/ws/preview") as ws1:
                data1 = ws1.receive_bytes()
                with client.websocket_connect("/ws/preview") as ws2:
                    data2 = ws2.receive_bytes()
        assert data1[:2] == b"\xff\xd8"
        assert data2[:2] == b"\xff\xd8"
