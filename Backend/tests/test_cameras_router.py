"""Tests for the cameras REST router.

Covers:
  - GET /api/cameras  (list + identity mode)
  - POST /api/cameras/reconnect
  - PUT /api/cameras/assignments/{config_id}
  - GET /api/cameras/assignments/{config_id}
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.capture_v4l2 import V4L2DeviceInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_db():
    """In-memory aiosqlite with known_cameras + camera_assignments schema."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS known_cameras (
            stable_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            last_seen_at TEXT,
            last_device_path TEXT
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS camera_assignments (
            entertainment_config_id TEXT PRIMARY KEY,
            camera_stable_id TEXT NOT NULL,
            camera_name TEXT NOT NULL
        )
    """)
    await conn.commit()
    return conn


def _make_cameras_app(mock_enumerate, mock_get_stable_id, db_conn):
    """Create a TestClient with cameras_router, mocked services, and in-memory DB."""
    from routers.cameras import router as cameras_router

    @asynccontextmanager
    async def test_lifespan(app):
        app.state.db = db_conn
        yield

    test_app = FastAPI(lifespan=test_lifespan)
    test_app.include_router(cameras_router)
    return test_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def cameras_client():
    """TestClient with mocked enumerate + get_stable_id returning one stable device."""
    db = await _make_db()
    fake_device = V4L2DeviceInfo(
        device_path="/dev/video0",
        card="AV.io HD",
        driver="uvcvideo",
        bus_info="usb-0000:00:14.0-2",
    )

    with (
        patch(
            "routers.cameras.enumerate_capture_devices",
            return_value=[fake_device],
        ) as mock_enum,
        patch(
            "routers.cameras.get_stable_id",
            return_value=("1234:5678", True),
        ) as mock_id,
    ):
        app = _make_cameras_app(mock_enum, mock_id, db)
        with TestClient(app) as client:
            yield client, mock_enum, mock_id, db

    await db.close()


@pytest.fixture
async def cameras_client_degraded():
    """TestClient where get_stable_id signals degraded identity."""
    db = await _make_db()
    fake_device = V4L2DeviceInfo(
        device_path="/dev/video0",
        card="AV.io HD",
        driver="uvcvideo",
        bus_info="usb-0000:00:14.0-2",
    )

    with (
        patch(
            "routers.cameras.enumerate_capture_devices",
            return_value=[fake_device],
        ),
        patch(
            "routers.cameras.get_stable_id",
            return_value=("AV.io HD@usb-0000:00:14.0-2", False),
        ),
    ):
        app = _make_cameras_app(None, None, db)
        with TestClient(app) as client:
            yield client

    await db.close()


@pytest.fixture
async def cameras_client_empty():
    """TestClient with no devices returned by enumerate."""
    db = await _make_db()

    with (
        patch(
            "routers.cameras.enumerate_capture_devices",
            return_value=[],
        ),
        patch(
            "routers.cameras.get_stable_id",
            return_value=("fallback@bus", False),
        ),
    ):
        app = _make_cameras_app(None, None, db)
        with TestClient(app) as client:
            yield client

    await db.close()


# ---------------------------------------------------------------------------
# Tests — GET /api/cameras
# ---------------------------------------------------------------------------


def test_list_cameras_returns_200(cameras_client):
    client, *_ = cameras_client
    resp = client.get("/api/cameras")
    assert resp.status_code == 200
    body = resp.json()
    assert "devices" in body
    assert "identity_mode" in body
    assert isinstance(body["devices"], list)
    assert isinstance(body["identity_mode"], str)


def test_device_fields(cameras_client):
    """Response device must have all required fields per D-03."""
    client, *_ = cameras_client
    resp = client.get("/api/cameras")
    assert resp.status_code == 200
    devices = resp.json()["devices"]
    assert len(devices) >= 1
    dev = devices[0]
    assert "device_path" in dev
    assert "stable_id" in dev
    assert "display_name" in dev
    assert "connected" in dev
    assert "last_seen_at" in dev


def test_stable_identity_mode(cameras_client):
    """When all devices have sysfs identity, identity_mode must be 'stable'."""
    client, *_ = cameras_client
    resp = client.get("/api/cameras")
    assert resp.json()["identity_mode"] == "stable"


def test_degraded_identity_mode(cameras_client_degraded):
    """When any device lacks sysfs, identity_mode must be 'degraded'."""
    resp = cameras_client_degraded.get("/api/cameras")
    assert resp.status_code == 200
    assert resp.json()["identity_mode"] == "degraded"


def test_no_cache(cameras_client):
    """enumerate_capture_devices must be called on each request (DEVC-03)."""
    client, mock_enum, *_ = cameras_client
    client.get("/api/cameras")
    client.get("/api/cameras")
    assert mock_enum.call_count == 2


def test_connected_flag_true(cameras_client):
    """Device found in current scan must have connected=True."""
    client, *_ = cameras_client
    resp = client.get("/api/cameras")
    devices = resp.json()["devices"]
    assert any(d["connected"] is True for d in devices)


def test_known_cameras_updated_on_scan(cameras_client):
    """GET /api/cameras must upsert scanned devices into known_cameras (D-09)."""
    client, _, _, db = cameras_client
    client.get("/api/cameras")

    # Query known_cameras synchronously via asyncio
    async def _query():
        async with db.execute("SELECT * FROM known_cameras") as cur:
            return await cur.fetchall()

    rows = asyncio.get_event_loop().run_until_complete(_query())
    assert len(rows) >= 1
    row = rows[0]
    assert row["stable_id"] == "1234:5678"
    assert row["last_device_path"] == "/dev/video0"
    assert row["last_seen_at"] is not None


# ---------------------------------------------------------------------------
# Tests — POST /api/cameras/reconnect
# ---------------------------------------------------------------------------


def test_reconnect_found(cameras_client):
    """When device with matching stable_id is in current scan, connected=True."""
    client, *_ = cameras_client
    # First, populate known_cameras via a list call
    client.get("/api/cameras")
    resp = client.post("/api/cameras/reconnect", json={"stable_id": "1234:5678"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["device_path"] == "/dev/video0"
    assert "display_name" in body


def test_reconnect_not_found(cameras_client):
    """When stable_id is in known_cameras but not in scan, connected=False."""
    client, *_ = cameras_client
    # Populate known_cameras first
    client.get("/api/cameras")

    # Now reconnect with a different enumerate (no devices)
    with patch(
        "routers.cameras.enumerate_capture_devices",
        return_value=[],
    ):
        resp = client.post("/api/cameras/reconnect", json={"stable_id": "1234:5678"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is False
    assert body["device_path"] is None
    assert "display_name" in body


def test_reconnect_unknown_stable_id(cameras_client):
    """Reconnect with stable_id not in known_cameras returns 404."""
    client, *_ = cameras_client
    resp = client.post("/api/cameras/reconnect", json={"stable_id": "unknown:id"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — PUT + GET /api/cameras/assignments/{config_id}
# ---------------------------------------------------------------------------


def test_put_assignment(cameras_client):
    """PUT persists an assignment, GET retrieves it."""
    client, *_ = cameras_client
    # Seed known_cameras
    client.get("/api/cameras")

    put_resp = client.put(
        "/api/cameras/assignments/cfg-1",
        json={"camera_stable_id": "1234:5678", "camera_name": "Test Cam"},
    )
    assert put_resp.status_code == 200

    get_resp = client.get("/api/cameras/assignments/cfg-1")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["entertainment_config_id"] == "cfg-1"
    assert body["camera_stable_id"] == "1234:5678"
    assert body["camera_name"] == "Test Cam"


def test_put_assignment_unknown_camera(cameras_client):
    """PUT with a camera_stable_id not in known_cameras returns 404."""
    client, *_ = cameras_client
    resp = client.put(
        "/api/cameras/assignments/cfg-1",
        json={"camera_stable_id": "unknown:id", "camera_name": "Ghost Cam"},
    )
    assert resp.status_code == 404


def test_get_assignment_not_found(cameras_client):
    """GET for a config with no assignment returns 404 per CAMA-03."""
    client, *_ = cameras_client
    resp = client.get("/api/cameras/assignments/nonexistent")
    assert resp.status_code == 404
    assert "detail" in resp.json()


def test_put_assignment_upsert(cameras_client):
    """Second PUT on same config_id overwrites, not duplicates."""
    client, *_ = cameras_client
    client.get("/api/cameras")

    client.put(
        "/api/cameras/assignments/cfg-1",
        json={"camera_stable_id": "1234:5678", "camera_name": "Cam A"},
    )
    client.put(
        "/api/cameras/assignments/cfg-1",
        json={"camera_stable_id": "1234:5678", "camera_name": "Cam B"},
    )

    get_resp = client.get("/api/cameras/assignments/cfg-1")
    assert get_resp.json()["camera_name"] == "Cam B"
