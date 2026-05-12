"""Phase 18 end-to-end integration test (HASS-01..05).

Walks: PUT zone -> PUT camera -> POST start -> (wait for streaming)
       -> GET status -> POST stop.

Wires a real ``StreamingCoordinator`` with mocked ``HueStreamer`` and a
mocked ``WledStreamer``. Uses the existing ``make_mock_capture`` fixture
so no real V4L2 device is needed.

The plan-level <verification> in 18-03-PLAN.md says one happy-path e2e
covers the HASS-01..05 cross-cut; edge cases live in
``test_ha_router.py``.
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.status_broadcaster import StatusBroadcaster
from services.streaming_coordinator import StreamingCoordinator
from tests.fixtures.mock_capture import make_mock_capture


# ---------------------------------------------------------------------------
# Helpers (adapted from test_phase17_e2e.py:109-129)
# ---------------------------------------------------------------------------


class _MockRegistry:
    """Capture registry stub — returns the same mock capture for any path."""

    def __init__(self, capture):
        self._capture = capture

    def acquire(self, path):
        return self._capture

    def release(self, path):
        pass


def _make_mock_hue():
    """Mock HueStreamer with all coroutine methods stubbed."""
    mock = MagicMock()
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    mock.render = AsyncMock()
    mock.handle_bridge_error = AsyncMock(return_value=True)
    return mock


def _make_mock_wled():
    """Mock WledStreamer (Phase 18 e2e does not assert WLED packet shape)."""
    mock = MagicMock()
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    mock.render = AsyncMock()
    mock.set_enabled = MagicMock()
    mock.health_snapshot = MagicMock(return_value={})
    return mock


async def _make_db_with_phase18_schema():
    """In-memory DB with every table the coordinator + routers/ha.py touches."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(
        """
        CREATE TABLE regions (
            id TEXT PRIMARY KEY, name TEXT, polygon TEXT NOT NULL,
            order_index INTEGER DEFAULT 0, light_id TEXT,
            entertainment_config_id TEXT
        );
        CREATE TABLE light_assignments (
            region_id TEXT NOT NULL, channel_id INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, channel_id, entertainment_config_id)
        );
        CREATE TABLE wled_devices (
            id TEXT PRIMARY KEY, ip TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            led_count INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE wled_channels (
            id TEXT PRIMARY KEY, device_id TEXT NOT NULL, name TEXT NOT NULL,
            start_led INTEGER NOT NULL, end_led INTEGER NOT NULL,
            color TEXT NOT NULL DEFAULT '#ffffff'
        );
        CREATE TABLE wled_light_assignments (
            region_id TEXT NOT NULL, wled_channel_id TEXT NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id)
        );
        CREATE TABLE camera_assignments (
            entertainment_config_id TEXT PRIMARY KEY,
            camera_stable_id TEXT NOT NULL, camera_name TEXT NOT NULL
        );
        CREATE TABLE known_cameras (
            stable_id TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            last_seen_at TEXT, last_device_path TEXT
        );
        CREATE TABLE bridge_config (
            id INTEGER PRIMARY KEY, bridge_id TEXT NOT NULL, rid TEXT NOT NULL,
            ip_address TEXT NOT NULL, username TEXT NOT NULL,
            hue_app_id TEXT NOT NULL, client_key TEXT NOT NULL,
            swversion INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE entertainment_configs (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            channel_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE camera_last_zone (
            camera_stable_id TEXT PRIMARY KEY,
            entertainment_config_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE ha_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_config_id TEXT, active_camera_stable_id TEXT,
            updated_at TEXT
        );
        """
    )
    await conn.commit()
    return conn


# ---------------------------------------------------------------------------
# The integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ha_e2e_full_flow():
    """End-to-end: PUT zone -> PUT camera -> POST start -> GET status -> POST stop.

    Asserts the cross-cut for HASS-01..05:
      * PUT zone + PUT camera persist into ha_state lazily
      * POST start drives the real coordinator into ``streaming`` state
        with the device_path_override resolved from
        ``known_cameras.last_device_path``
      * GET status surfaces active_* AND ha_selected_* with friendly
        names resolved server-side
      * POST stop drives the coordinator back to ``idle``
    """
    from routers.ha import router as ha_router

    db = await _make_db_with_phase18_schema()
    # Seed bridge, zone, camera
    await db.execute(
        "INSERT INTO bridge_config (id, bridge_id, rid, ip_address, username, "
        "hue_app_id, client_key, swversion, name) "
        "VALUES (1, 'b', 'r', '10.0.0.1', 'u', 'a', 'k', 1, 'Bridge')"
    )
    await db.execute(
        "INSERT INTO entertainment_configs (id, name, status, channel_count, raw_json) "
        "VALUES ('cfg1', 'TV-Bereich', 'active', 6, '{}')"
    )
    await db.execute(
        "INSERT INTO known_cameras (stable_id, display_name, last_seen_at, "
        "last_device_path) VALUES "
        "('cam1', 'USB Cam', '2026-05-11T00:00:00+00:00', '/dev/video10')"
    )
    await db.commit()

    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()
    mock_wled = _make_mock_wled()
    capture = make_mock_capture()
    registry = _MockRegistry(capture)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
        wled_streamer=mock_wled,
    )

    @asynccontextmanager
    async def _lifespan(app):
        app.state.db = db
        app.state.coordinator = coord
        app.state.broadcaster = broadcaster
        yield

    app = FastAPI(lifespan=_lifespan)
    app.include_router(ha_router)

    # Patch friendly-name lookup so /status resolves without a real bridge.
    bridge_configs = [
        {"id": "cfg1", "name": "TV-Bereich", "status": "active", "channel_count": 6},
    ]

    with patch(
        "routers.ha.list_entertainment_configs",
        AsyncMock(return_value=bridge_configs),
    ):
        with TestClient(app) as client:
            # 1. PUT zone
            r = client.put("/api/ha/zone", json={"zone_id": "cfg1"})
            assert r.status_code == 200, r.text
            assert r.json()["ha_selected_config_id"] == "cfg1"

            # 2. PUT camera
            r = client.put("/api/ha/camera", json={"stable_id": "cam1"})
            assert r.status_code == 200, r.text
            assert r.json()["ha_selected_camera_stable_id"] == "cam1"

            # 3. POST start
            r = client.post("/api/ha/start")
            assert r.status_code == 200, r.text

            # 4. Wait for coordinator to reach streaming state (warm-up loop
            #    adapted from test_phase17_e2e.py:196-202 — 50 * 50ms = 2.5s
            #    budget; well above the ~50-200ms typical transition time).
            for _ in range(50):
                if coord.state == "streaming":
                    break
                await asyncio.sleep(0.05)
            assert coord.state == "streaming", (
                f"coordinator failed to reach streaming state: {coord.state}"
            )

            # 5. GET status
            r = client.get("/api/ha/status")
            assert r.status_code == 200, r.text
            payload = r.json()
            assert payload["state"] == "streaming"
            assert payload["active_config_id"] == "cfg1"
            assert payload["active_config_name"] == "TV-Bereich"
            assert payload["active_device_path"] == "/dev/video10"
            assert payload["active_camera_stable_id"] == "cam1"
            assert payload["active_camera_name"] == "USB Cam"
            assert payload["ha_selected_config_id"] == "cfg1"
            assert payload["ha_selected_camera_stable_id"] == "cam1"
            assert payload["bridge_paired"] is True

            # 6. POST stop
            r = client.post("/api/ha/stop")
            assert r.status_code == 200, r.text

            # Wait for stop to settle back to idle.
            for _ in range(50):
                if coord.state == "idle":
                    break
                await asyncio.sleep(0.05)
            assert coord.state == "idle", (
                f"coordinator failed to reach idle state: {coord.state}"
            )

            # Final status assertion — state should reflect idle now.
            r = client.get("/api/ha/status")
            assert r.status_code == 200, r.text
            assert r.json()["state"] == "idle"

    await db.close()
