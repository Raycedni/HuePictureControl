"""Tests for the /ws/preview WebSocket endpoint — device-routed frame streaming.

Tests cover:
- WebSocket without ?device= param is rejected with close code 1008
- _resolve_device_path returns device path as-is when it starts with /dev/
- _resolve_device_path resolves stable_id via known_cameras lookup
- _resolve_device_path returns None for unknown stable_id
- WebSocket with ?device= calls registry.get(device_path) not get_default()
"""
import asyncio
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_preview_ws_app(registry=None, db=None):
    """Build a minimal FastAPI app with preview_ws router, mock registry and db."""
    from routers.preview_ws import router as preview_ws_router

    mock_registry = registry or MagicMock()
    mock_db = db or MagicMock()

    @asynccontextmanager
    async def lifespan(app):
        app.state.capture_registry = mock_registry
        app.state.db = mock_db
        yield

    test_app = FastAPI(lifespan=lifespan)
    test_app.include_router(preview_ws_router)
    return test_app


class _FakeCursor:
    """Async context manager cursor that returns a fixed row."""

    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def fetchone(self):
        return self._row


class _FakeDB:
    """Minimal fake async DB that answers SELECT from known_cameras."""

    def __init__(self, row):
        self._row = row

    def execute(self, sql, params=None):
        return _FakeCursor(self._row)


# ---------------------------------------------------------------------------
# _resolve_device_path unit tests
# ---------------------------------------------------------------------------


class TestResolveDevicePath:
    @pytest.mark.asyncio
    async def test_resolve_device_path_direct(self):
        """Direct /dev/ path is returned unchanged without DB lookup."""
        from routers.preview_ws import _resolve_device_path

        result = await _resolve_device_path(db=None, device="/dev/video0")
        assert result == "/dev/video0"

    @pytest.mark.asyncio
    async def test_resolve_device_path_stable_id(self):
        """Stable ID is resolved to last_device_path via known_cameras."""
        from routers.preview_ws import _resolve_device_path

        # Simulate a row returned from known_cameras
        row = {"last_device_path": "/dev/video2"}
        fake_db = _FakeDB(row=row)

        result = await _resolve_device_path(db=fake_db, device="vid:pid:serial")
        assert result == "/dev/video2"

    @pytest.mark.asyncio
    async def test_resolve_device_path_unknown_stable_id(self):
        """Unknown stable_id (not in known_cameras) returns None."""
        from routers.preview_ws import _resolve_device_path

        fake_db = _FakeDB(row=None)

        result = await _resolve_device_path(db=fake_db, device="vid:pid:unknown")
        assert result is None


# ---------------------------------------------------------------------------
# WebSocket handler tests
# ---------------------------------------------------------------------------


class TestPreviewWsEndpoint:
    def test_missing_device_param(self):
        """Connecting without ?device= closes with code 1008 before accept."""
        app = _make_preview_ws_app()
        with TestClient(app) as client:
            with pytest.raises(Exception):
                # TestClient raises on non-accepted close
                with client.websocket_connect("/ws/preview") as ws:
                    # The server closes before accept; reading should raise
                    ws.receive_bytes()

    def test_device_param_calls_registry_get(self):
        """WebSocket with ?device=/dev/video0 calls registry.get('/dev/video0')."""
        mock_backend = MagicMock()
        mock_backend.get_jpeg = AsyncMock(return_value=b"\xff\xd8fake")

        call_count = {"n": 0}

        def get_side_effect(path):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return mock_backend
            return None  # Stop the loop after first frame

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(side_effect=get_side_effect)

        app = _make_preview_ws_app(registry=mock_registry)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with TestClient(app) as client:
                with client.websocket_connect("/ws/preview?device=/dev/video0") as ws:
                    data = ws.receive_bytes()

        mock_registry.get.assert_called_with("/dev/video0")
        assert data == b"\xff\xd8fake"

    def test_device_param_does_not_call_get_default(self):
        """WebSocket with ?device= uses registry.get(), never registry.get_default()."""
        mock_backend = MagicMock()
        mock_backend.get_jpeg = AsyncMock(return_value=b"\xff\xd8fake")

        call_count = {"n": 0}

        def get_side_effect(path):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return mock_backend
            return None

        mock_registry = MagicMock()
        mock_registry.get = MagicMock(side_effect=get_side_effect)
        mock_registry.get_default = MagicMock()

        app = _make_preview_ws_app(registry=mock_registry)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with TestClient(app) as client:
                with client.websocket_connect("/ws/preview?device=/dev/video0") as ws:
                    ws.receive_bytes()

        mock_registry.get_default.assert_not_called()
