"""Integration tests for /api/wled/* endpoints.

Strategy: TestClient + in-memory aiosqlite DB matching the wled_* schema
created by Backend/database.py (Plan 17-02). The coordinator is intentionally
NOT wired in these tests — `set_enabled` falls back to a direct DB UPDATE so
we can assert CRUD behavior without spinning up a streamer.

External services are mocked at the router-import path:
  - `routers.wled.fetch_wled_info`     (httpx /json/info probe)
  - `routers.wled.scan_for_wled_devices` (zeroconf scan)

Coverage map (11 tests):
  T-17-INPUT          test_add_device_rejects_malformed_ip
  T-17-NETWORK        test_add_device_unreachable_returns_502
  T-17-SHAPE          test_add_device_zero_led_count_returns_422
  WLED-01 / D-09      test_add_device_persists_and_auto_seeds_channel
  GET /devices        test_list_after_add
  T-17-DUPE           test_duplicate_ip_returns_409
  T-17-DELETE-ORPHAN  test_delete_cascades_channels_and_assignments
  404 hygiene         test_delete_unknown_returns_404
  WLED-02             test_put_enabled_toggles_row_without_coordinator
  404 hygiene         test_put_enabled_unknown_returns_404
  zeroconf scan       test_scan_returns_candidates_list
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import aiosqlite
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_db():
    """In-memory aiosqlite with the Plan 17-02 wled_* tables."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wled_devices (
            id TEXT PRIMARY KEY,
            ip TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            led_count INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wled_channels (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            name TEXT NOT NULL,
            start_led INTEGER NOT NULL,
            end_led INTEGER NOT NULL,
            color TEXT NOT NULL DEFAULT '#ffffff'
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wled_light_assignments (
            region_id TEXT NOT NULL,
            wled_channel_id TEXT NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id)
        )
        """
    )
    await conn.commit()
    return conn


@asynccontextmanager
async def _wled_app_lifespan(app):
    db = await _make_db()
    app.state.db = db
    try:
        yield
    finally:
        await db.close()


def _make_client() -> TestClient:
    """Build a fresh TestClient with only the wled router mounted."""
    from routers.wled import router as wled_router

    app = FastAPI(lifespan=_wled_app_lifespan)
    app.include_router(wled_router)
    return TestClient(app)


def _make_app() -> FastAPI:
    """Same as `_make_client` but returns the bare app so tests can poke
    `app.state.db` after a request via `asyncio.run`. TestClient is created
    by the caller inside a `with` block to drive the lifespan."""
    from routers.wled import router as wled_router

    app = FastAPI(lifespan=_wled_app_lifespan)
    app.include_router(wled_router)
    return app


# ---------------------------------------------------------------------------
# Tests — POST /api/wled/devices (validation + probe)
# ---------------------------------------------------------------------------


def test_add_device_rejects_malformed_ip():
    """Pydantic regex returns 422 before the handler runs (T-17-INPUT)."""
    with _make_client() as client:
        r = client.post("/api/wled/devices", json={"ip": "not-an-ip"})
    assert r.status_code == 422


def test_add_device_unreachable_returns_502():
    """httpx.ConnectError -> 502 with a descriptive detail."""
    with _make_client() as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(side_effect=httpx.ConnectError("refused")),
        ):
            r = client.post("/api/wled/devices", json={"ip": "192.168.1.99"})
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"].lower()


def test_add_device_zero_led_count_returns_422():
    """Malformed /json/info (led_count == 0) -> 422 (D-09 prerequisite)."""
    with _make_client() as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={"name": "X", "led_count": 0, "ver": "", "mac": ""}
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "192.168.1.50"})
    assert r.status_code == 422


def test_add_device_persists_and_auto_seeds_channel():
    """Happy path: 201 + auto-seeded channel covering the full strip (D-09).

    With no coordinator wired the health dict is empty, so connected is derived
    from led_count > 0 (idle-state reachability; fix for wled-always-offline).
    """
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={
                    "name": "My WLED",
                    "led_count": 300,
                    "ver": "0.14",
                    "mac": "ab",
                }
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "192.168.1.50"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "My WLED"
        assert body["led_count"] == 300
        assert body["enabled"] is True
        # No coordinator -> health dict empty -> connected derived from led_count > 0.
        assert body["connected"] is True
        dev_id = body["id"]

        # Auto-seeded channel covers [0 .. led_count-1]
        async def _check_channel():
            db = app.state.db
            async with db.execute(
                "SELECT id, name, start_led, end_led, color "
                "FROM wled_channels WHERE device_id = ?",
                (dev_id,),
            ) as cur:
                rows = await cur.fetchall()
            assert len(rows) == 1
            ch = rows[0]
            assert ch["name"] == "Strip"
            assert ch["start_led"] == 0
            assert ch["end_led"] == 299
            assert ch["color"] == "#ffffff"

        asyncio.run(_check_channel())


def test_list_after_add():
    """POST then GET inside the same app context returns the new device."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={
                    "name": "My WLED",
                    "led_count": 300,
                    "ver": "0.14",
                    "mac": "ab",
                }
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "192.168.1.50"})
        assert r.status_code == 201, r.text
        created = r.json()

        r2 = client.get("/api/wled/devices")
        assert r2.status_code == 200
        devices = r2.json()["devices"]
        assert len(devices) == 1
        assert devices[0]["id"] == created["id"]
        assert devices[0]["ip"] == "192.168.1.50"


def test_duplicate_ip_returns_409():
    """Pre-INSERT SELECT catches the duplicate before httpx fires (T-17-DUPE)."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={
                    "name": "W",
                    "led_count": 100,
                    "ver": "",
                    "mac": "",
                }
            ),
        ):
            r1 = client.post("/api/wled/devices", json={"ip": "10.0.0.5"})
            assert r1.status_code == 201
            r2 = client.post("/api/wled/devices", json={"ip": "10.0.0.5"})
        assert r2.status_code == 409


# ---------------------------------------------------------------------------
# Tests — DELETE /api/wled/devices/{id}
# ---------------------------------------------------------------------------


def test_delete_cascades_channels_and_assignments():
    """DELETE wipes the device, its channels, and any region assignments
    referencing those channels (T-17-DELETE-ORPHAN)."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={
                    "name": "W",
                    "led_count": 100,
                    "ver": "",
                    "mac": "",
                }
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.5"})
        assert r.status_code == 201, r.text
        dev_id = r.json()["id"]

        # Insert a phantom assignment via direct DB write so we can assert
        # that DELETE truly cascades through wled_light_assignments.
        async def _seed_assignment():
            db = app.state.db
            async with db.execute(
                "SELECT id FROM wled_channels WHERE device_id = ?",
                (dev_id,),
            ) as cur:
                ch = await cur.fetchone()
            assert ch is not None
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_channel_id, entertainment_config_id) "
                "VALUES ('r1', ?, 'cfg1')",
                (ch["id"],),
            )
            await db.commit()

        asyncio.run(_seed_assignment())

        rd = client.delete(f"/api/wled/devices/{dev_id}")
        assert rd.status_code == 204

        # Verify cascade: all three tables empty for this device.
        async def _check_empty():
            db = app.state.db
            async with db.execute(
                "SELECT COUNT(*) AS c FROM wled_devices"
            ) as cur:
                assert (await cur.fetchone())["c"] == 0
            async with db.execute(
                "SELECT COUNT(*) AS c FROM wled_channels"
            ) as cur:
                assert (await cur.fetchone())["c"] == 0
            async with db.execute(
                "SELECT COUNT(*) AS c FROM wled_light_assignments"
            ) as cur:
                assert (await cur.fetchone())["c"] == 0

        asyncio.run(_check_empty())


def test_delete_unknown_returns_404():
    """DELETE on a non-existent device id returns 404 with a clear detail."""
    with _make_client() as client:
        r = client.delete("/api/wled/devices/does-not-exist")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Tests — PUT /api/wled/devices/{id}/enabled
# ---------------------------------------------------------------------------


def test_put_enabled_toggles_row_without_coordinator():
    """Without a coordinator the handler updates the DB row directly so the
    enabled gate persists across restarts (D-12, test-only fallback path)."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={
                    "name": "W",
                    "led_count": 10,
                    "ver": "",
                    "mac": "",
                }
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.6"})
        assert r.status_code == 201, r.text
        dev_id = r.json()["id"]

        rp = client.put(
            f"/api/wled/devices/{dev_id}/enabled", json={"enabled": False}
        )
        assert rp.status_code == 200
        body = rp.json()
        assert body["id"] == dev_id
        assert body["enabled"] is False

        # Confirm the underlying row was updated to enabled=0.
        async def _check_row():
            db = app.state.db
            async with db.execute(
                "SELECT enabled FROM wled_devices WHERE id = ?", (dev_id,)
            ) as cur:
                row = await cur.fetchone()
                assert row["enabled"] == 0

        asyncio.run(_check_row())


def test_put_enabled_unknown_returns_404():
    """PUT /enabled on a missing device returns 404 (no row update)."""
    with _make_client() as client:
        r = client.put(
            "/api/wled/devices/unknown/enabled", json={"enabled": True}
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests — POST /api/wled/scan
# ---------------------------------------------------------------------------


def test_scan_returns_candidates_list():
    """Scan endpoint wraps zeroconf results into the WledScanResponse shape."""
    with _make_client() as client:
        with patch(
            "routers.wled.scan_for_wled_devices",
            AsyncMock(
                return_value=[
                    {"ip": "192.168.1.51", "name": "WLED-Living"},
                    {"ip": "192.168.1.52", "name": "WLED-Bedroom"},
                ]
            ),
        ):
            r = client.post("/api/wled/scan")
    assert r.status_code == 200
    body = r.json()
    assert "candidates" in body
    assert len(body["candidates"]) == 2
    ips = {c["ip"] for c in body["candidates"]}
    assert ips == {"192.168.1.51", "192.168.1.52"}


# ---------------------------------------------------------------------------
# Phase 19 channel-CRUD + orientation PATCH stubs — Plan 19-05 fills these in.
# ---------------------------------------------------------------------------


async def test_create_channel_basic():
    """POST /api/wled/devices/{id}/channels inserts (start, end) — WMAP-01."""
    pytest.importorskip("services.wled_channels")
    pytest.skip("Wave 3 wires routers/wled.py to services.wled_channels.create_channel_with_split.")


async def test_list_channels_for_device():
    """GET /api/wled/devices/{id}/channels returns ordered list."""
    pytest.importorskip("services.wled_channels")
    pytest.skip("Wave 3 wires routers/wled.py list endpoint.")


async def test_update_channel_rename():
    """PUT /api/wled/devices/{id}/channels/{cid} with {name} renames in place."""
    pytest.importorskip("services.wled_channels")
    pytest.skip("Wave 3 wires routers/wled.py PUT endpoint.")


async def test_boundary_resize_atomic():
    """PUT /api/wled/devices/{id}/channels/boundary updates both adjacent rows."""
    pytest.importorskip("services.wled_channels")
    pytest.skip("Wave 3 wires routers/wled.py boundary endpoint to resize_boundary.")


async def test_delete_channel_cascades():
    """DELETE /api/wled/devices/{id}/channels/{cid} cascades to wled_light_assignments."""
    pytest.importorskip("services.wled_channels")
    pytest.skip("Wave 3 wires routers/wled.py DELETE cascade.")


async def test_patch_region_orientation_writes_all_rows():
    """PATCH /api/wled/regions/{rid}/orientation?config={cid} writes ALL matching rows."""
    pytest.importorskip("services.wled_channels")
    pytest.skip("Wave 3 implements PATCH /api/wled/regions/{rid}/orientation.")


async def test_upsert_assignment_inherits_region_orientation():
    """PUT /api/wled/assignments inserts new row carrying the region's current orientation."""
    pytest.importorskip("services.wled_channels")
    pytest.skip("Wave 3 implements PUT /api/wled/assignments.")
