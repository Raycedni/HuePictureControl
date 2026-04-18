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


# ---------------------------------------------------------------------------
# Tests — cameras_available field (CAMA-04)
# ---------------------------------------------------------------------------


def test_cameras_available_true_with_devices(cameras_client):
    """GET /api/cameras returns cameras_available=True when devices list is non-empty."""
    client, *_ = cameras_client
    resp = client.get("/api/cameras")
    assert resp.status_code == 200
    body = resp.json()
    assert "cameras_available" in body
    assert body["cameras_available"] is True


def test_cameras_available_false_empty(cameras_client_empty):
    """GET /api/cameras returns cameras_available=False when no devices found."""
    resp = cameras_client_empty.get("/api/cameras")
    assert resp.status_code == 200
    body = resp.json()
    assert "cameras_available" in body
    assert body["cameras_available"] is False


# ---------------------------------------------------------------------------
# Tests — zone_health field (CAMA-04)
# ---------------------------------------------------------------------------


def test_zone_health_connected(cameras_client):
    """zone_health entry has connected=True when stable_id matches a scanned device."""
    client, _, _, db = cameras_client
    # Seed known_cameras and camera_assignments
    client.get("/api/cameras")  # seeds known_cameras with stable_id "1234:5678"

    async def _seed():
        await db.execute(
            "INSERT INTO camera_assignments (entertainment_config_id, camera_stable_id, camera_name) "
            "VALUES (?, ?, ?)",
            ("cfg-zone-1", "1234:5678", "AV.io HD"),
        )
        await db.commit()

    asyncio.get_event_loop().run_until_complete(_seed())

    resp = client.get("/api/cameras")
    assert resp.status_code == 200
    body = resp.json()
    assert "zone_health" in body
    zone_entries = body["zone_health"]
    assert len(zone_entries) == 1
    entry = zone_entries[0]
    assert entry["entertainment_config_id"] == "cfg-zone-1"
    assert entry["camera_stable_id"] == "1234:5678"
    assert entry["connected"] is True
    assert entry["device_path"] == "/dev/video0"


def test_zone_health_disconnected(cameras_client_empty):
    """zone_health entry has connected=False when stable_id not in current scan."""
    import asyncio as _asyncio

    # We need a client where the db has a camera_assignment but scan returns nothing
    # cameras_client_empty scans empty, so we need to seed the db manually
    # Re-use the fixture pattern with a fresh db that has an assignment row
    import aiosqlite as _aiosqlite

    async def _run():
        conn = await _aiosqlite.connect(":memory:")
        conn.row_factory = _aiosqlite.Row
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS known_cameras (
                stable_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
                last_seen_at TEXT, last_device_path TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS camera_assignments (
                entertainment_config_id TEXT PRIMARY KEY,
                camera_stable_id TEXT NOT NULL, camera_name TEXT NOT NULL
            )
        """)
        # Insert an assignment for a stable_id that won't be in the empty scan
        await conn.execute(
            "INSERT INTO camera_assignments (entertainment_config_id, camera_stable_id, camera_name) "
            "VALUES (?, ?, ?)",
            ("cfg-zone-2", "dead:beef", "Missing Cam"),
        )
        await conn.commit()
        return conn

    db_conn = _asyncio.get_event_loop().run_until_complete(_run())

    from routers.cameras import router as cameras_router
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from unittest.mock import patch

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = db_conn
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(cameras_router)

    with (
        patch("routers.cameras.enumerate_capture_devices", return_value=[]),
        patch("routers.cameras.get_stable_id", return_value=("fallback", False)),
        TestClient(app) as client,
    ):
        resp = client.get("/api/cameras")
        assert resp.status_code == 200
        body = resp.json()
        zone_entries = body["zone_health"]
        assert len(zone_entries) == 1
        entry = zone_entries[0]
        assert entry["entertainment_config_id"] == "cfg-zone-2"
        assert entry["camera_stable_id"] == "dead:beef"
        assert entry["connected"] is False
        assert entry["device_path"] is None

    _asyncio.get_event_loop().run_until_complete(db_conn.close())


# ---------------------------------------------------------------------------
# Tests — is_wireless tagging from PipelineManager (SCPY-02)
# ---------------------------------------------------------------------------


class TestWirelessCameraTagging:
    """Test that GET /api/cameras includes is_wireless flag from PipelineManager (SCPY-02)."""

    @pytest.mark.asyncio
    async def test_cameras_include_is_wireless_for_active_session(self):
        """When pipeline_manager has an active scrcpy session, its device appears as is_wireless=True."""
        db = await _make_db()

        # Pre-seed a known camera that matches the scrcpy virtual device
        await db.execute(
            "INSERT INTO known_cameras (stable_id, display_name, last_seen_at, last_device_path) VALUES (?, ?, ?, ?)",
            ("v4l2:video11:scrcpy", "scrcpy Input", "2026-04-16T12:00:00Z", "/dev/video11"),
        )
        await db.commit()

        mock_pm = MagicMock()
        mock_pm.get_sessions = MagicMock(return_value=[
            {
                "session_id": "sess-abc",
                "source_type": "android_scrcpy",
                "device_path": "/dev/video11",
                "status": "active",
                "error_message": None,
                "error_code": None,
                "started_at": "2026-04-16T12:00:00Z",
            }
        ])

        mock_enumerate = MagicMock(return_value=[
            V4L2DeviceInfo(device_path="/dev/video11", card="scrcpy Input", driver="v4l2loopback", bus_info="platform:v4l2loopback-011"),
        ])
        mock_stable_id = MagicMock(return_value=("v4l2:video11:scrcpy", True))

        from routers.cameras import router as cameras_router

        @asynccontextmanager
        async def test_lifespan(app):
            app.state.db = db
            app.state.pipeline_manager = mock_pm
            yield

        test_app = FastAPI(lifespan=test_lifespan)
        test_app.include_router(cameras_router)

        with patch("routers.cameras.enumerate_capture_devices", mock_enumerate), \
             patch("routers.cameras.get_stable_id", mock_stable_id):
            with TestClient(test_app) as client:
                resp = client.get("/api/cameras")
                assert resp.status_code == 200
                data = resp.json()
                wireless_devices = [d for d in data["devices"] if d.get("is_wireless")]
                assert len(wireless_devices) >= 1
                assert wireless_devices[0]["device_path"] == "/dev/video11"
                assert wireless_devices[0]["is_wireless"] is True

        await db.close()

    @pytest.mark.asyncio
    async def test_cameras_is_wireless_false_when_no_pipeline_manager(self):
        """When pipeline_manager is not on app.state, all devices have is_wireless=False."""
        db = await _make_db()

        await db.execute(
            "INSERT INTO known_cameras (stable_id, display_name, last_seen_at, last_device_path) VALUES (?, ?, ?, ?)",
            ("usb:cam0", "USB Cam", "2026-04-16T12:00:00Z", "/dev/video0"),
        )
        await db.commit()

        mock_enumerate = MagicMock(return_value=[
            V4L2DeviceInfo(device_path="/dev/video0", card="USB Cam", driver="uvcvideo", bus_info="usb-0000:00:14.0-1"),
        ])
        mock_stable_id = MagicMock(return_value=("usb:cam0", True))

        from routers.cameras import router as cameras_router

        @asynccontextmanager
        async def test_lifespan(app):
            app.state.db = db
            # Note: no pipeline_manager on app.state
            yield

        test_app = FastAPI(lifespan=test_lifespan)
        test_app.include_router(cameras_router)

        with patch("routers.cameras.enumerate_capture_devices", mock_enumerate), \
             patch("routers.cameras.get_stable_id", mock_stable_id):
            with TestClient(test_app) as client:
                resp = client.get("/api/cameras")
                assert resp.status_code == 200
                data = resp.json()
                for device in data["devices"]:
                    assert device["is_wireless"] is False

        await db.close()
