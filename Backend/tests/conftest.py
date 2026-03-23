import asyncio
import os
import pytest
import aiosqlite
import numpy as np
from contextlib import asynccontextmanager
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
async def db():
    """In-memory aiosqlite connection with full schema initialized."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bridge_config (
            id INTEGER PRIMARY KEY,
            bridge_id TEXT NOT NULL,
            rid TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            username TEXT NOT NULL,
            hue_app_id TEXT NOT NULL,
            client_key TEXT NOT NULL,
            swversion INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT ''
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS entertainment_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            channel_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            id TEXT PRIMARY KEY,
            name TEXT,
            polygon TEXT NOT NULL,
            order_index INTEGER DEFAULT 0
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS light_assignments (
            region_id TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, channel_id, entertainment_config_id)
        )
    """)
    await conn.commit()
    yield conn
    await conn.close()


@pytest.fixture
def app_client(tmp_path):
    """FastAPI TestClient with lifespan using a temp file DB."""
    from database import init_db, close_db

    db_path = str(tmp_path / "test.db")

    @asynccontextmanager
    async def test_lifespan(app):
        conn = await init_db(db_path)
        app.state.db = conn
        yield
        await close_db(conn)

    from fastapi import FastAPI
    from routers.health import router as health_router

    test_app = FastAPI(lifespan=test_lifespan)
    test_app.include_router(health_router)

    with TestClient(test_app) as client:
        yield client


def _make_capture_mock(get_frame_side_effect=None, open_side_effect=None):
    """Build a mock LatestFrameCapture for capture router tests."""
    mock_capture = MagicMock()
    # A solid blue 480x640x3 frame (BGR: blue=255, green=0, red=0)
    solid_blue_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    solid_blue_frame[:, :, 0] = 255  # blue channel

    if get_frame_side_effect is not None:
        mock_capture.get_frame = AsyncMock(side_effect=get_frame_side_effect)
    else:
        mock_capture.get_frame = AsyncMock(return_value=solid_blue_frame)

    if open_side_effect is not None:
        mock_capture.open = MagicMock(side_effect=open_side_effect)
    else:
        mock_capture.open = MagicMock()

    return mock_capture


def _make_capture_app_client(mock_capture):
    """Create a TestClient with a FastAPI app that has mock capture on app.state."""
    from fastapi import FastAPI
    from routers.capture import router as capture_router

    @asynccontextmanager
    async def capture_lifespan(app):
        app.state.capture = mock_capture
        yield

    test_app = FastAPI(lifespan=capture_lifespan)
    test_app.include_router(capture_router)
    return TestClient(test_app)


@pytest.fixture
def capture_app_client():
    """TestClient with a working mock LatestFrameCapture (solid-blue frame)."""
    mock_capture = _make_capture_mock()
    with _make_capture_app_client(mock_capture) as client:
        yield client


@pytest.fixture
def capture_app_client_broken():
    """TestClient where get_frame raises RuntimeError (device unavailable)."""
    mock_capture = _make_capture_mock(
        get_frame_side_effect=RuntimeError("Capture device is not open")
    )
    with _make_capture_app_client(mock_capture) as client:
        yield client


@pytest.fixture
def capture_app_client_broken_open():
    """TestClient where open() raises RuntimeError (invalid device path)."""
    mock_capture = _make_capture_mock(
        open_side_effect=RuntimeError("Could not open capture device: /dev/video99")
    )
    with _make_capture_app_client(mock_capture) as client:
        yield client
