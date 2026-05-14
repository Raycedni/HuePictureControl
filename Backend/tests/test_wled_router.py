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
    """In-memory aiosqlite with the Phase 17 wled_* tables + Phase 19 columns."""
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
            created_at TEXT NOT NULL,
            next_channel_n INTEGER NOT NULL DEFAULT 1
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
            orientation TEXT NOT NULL DEFAULT 'auto',
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
# Phase 19 channel-CRUD + orientation PATCH — Wave 3 (Plan 19-08)
# ---------------------------------------------------------------------------


def test_create_channel_basic():
    """POST /api/wled/devices/{id}/channels inserts (start, end) — WMAP-01."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={"name": "W", "led_count": 100, "ver": "", "mac": ""}
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.1"})
        assert r.status_code == 201
        dev_id = r.json()["id"]

        rc = client.post(
            f"/api/wled/devices/{dev_id}/channels",
            json={"start_led": 10, "end_led": 49},
        )
        assert rc.status_code == 201, rc.text
        body = rc.json()
        assert body["device_id"] == dev_id
        assert body["start_led"] == 10
        assert body["end_led"] == 49
        assert "id" in body
        assert "name" in body


def test_list_channels_for_device():
    """GET /api/wled/devices/{id}/channels returns ordered list."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={"name": "W", "led_count": 200, "ver": "", "mac": ""}
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.2"})
        assert r.status_code == 201
        dev_id = r.json()["id"]

        # Create two channels (auto-split carves into the seed 'Strip').
        client.post(
            f"/api/wled/devices/{dev_id}/channels",
            json={"start_led": 0, "end_led": 49},
        )
        client.post(
            f"/api/wled/devices/{dev_id}/channels",
            json={"start_led": 50, "end_led": 99},
        )

        rl = client.get(f"/api/wled/devices/{dev_id}/channels")
        assert rl.status_code == 200, rl.text
        channels = rl.json()["channels"]
        # At least our two freshly painted channels are present.
        assert len(channels) >= 2
        # Ordered by start_led ASC.
        starts = [c["start_led"] for c in channels]
        assert starts == sorted(starts)


def test_update_channel_rename():
    """PUT /api/wled/devices/{id}/channels/{cid} with {name} renames in place."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={"name": "W", "led_count": 100, "ver": "", "mac": ""}
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.3"})
        assert r.status_code == 201
        dev_id = r.json()["id"]

        # Grab the auto-seeded 'Strip' channel.
        rl = client.get(f"/api/wled/devices/{dev_id}/channels")
        assert rl.status_code == 200
        ch_id = rl.json()["channels"][0]["id"]

        rp = client.put(
            f"/api/wled/devices/{dev_id}/channels/{ch_id}",
            json={"name": "Foo"},
        )
        assert rp.status_code == 200, rp.text
        assert rp.json()["name"] == "Foo"
        assert rp.json()["id"] == ch_id


def test_boundary_resize_atomic():
    """PUT /api/wled/devices/{id}/channels/boundary updates both adjacent rows."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={"name": "W", "led_count": 100, "ver": "", "mac": ""}
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.4"})
        assert r.status_code == 201
        dev_id = r.json()["id"]

        # Paint two non-overlapping channels that together cover the whole strip.
        r1 = client.post(
            f"/api/wled/devices/{dev_id}/channels",
            json={"start_led": 0, "end_led": 49},
        )
        r2 = client.post(
            f"/api/wled/devices/{dev_id}/channels",
            json={"start_led": 50, "end_led": 99},
        )
        assert r1.status_code == 201
        assert r2.status_code == 201

        # Fetch channel list to find the left and right channels (by start_led).
        rl = client.get(f"/api/wled/devices/{dev_id}/channels")
        channels = sorted(rl.json()["channels"], key=lambda c: c["start_led"])
        # Find a left channel ending at 49 and right channel starting at 50.
        left = next(c for c in channels if c["end_led"] == 49)
        right = next(c for c in channels if c["start_led"] == 50)

        rb = client.put(
            f"/api/wled/devices/{dev_id}/channels/boundary",
            json={
                "left_channel_id": left["id"],
                "right_channel_id": right["id"],
                "boundary": 60,
            },
        )
        assert rb.status_code == 200, rb.text
        assert rb.json()["ok"] is True

        # Verify both rows were updated atomically.
        rl2 = client.get(f"/api/wled/devices/{dev_id}/channels")
        updated = {c["id"]: c for c in rl2.json()["channels"]}
        assert updated[left["id"]]["end_led"] == 59   # boundary - 1
        assert updated[right["id"]]["start_led"] == 60  # boundary


def test_delete_channel_cascades():
    """DELETE /api/wled/devices/{id}/channels/{cid} cascades to wled_light_assignments."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={"name": "W", "led_count": 100, "ver": "", "mac": ""}
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.7"})
        assert r.status_code == 201
        dev_id = r.json()["id"]

        # Get the auto-seeded channel id.
        rl = client.get(f"/api/wled/devices/{dev_id}/channels")
        ch_id = rl.json()["channels"][0]["id"]

        # Seed a light assignment for this channel via direct DB write.
        async def _seed():
            db = app.state.db
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_channel_id, entertainment_config_id, orientation) "
                "VALUES ('r1', ?, 'cfg1', 'auto')",
                (ch_id,),
            )
            await db.commit()

        asyncio.run(_seed())

        # Delete the channel — must cascade to the assignment.
        rd = client.delete(f"/api/wled/devices/{dev_id}/channels/{ch_id}")
        assert rd.status_code == 204

        # Assignment row must be gone.
        async def _check():
            db = app.state.db
            async with db.execute(
                "SELECT COUNT(*) AS c FROM wled_light_assignments "
                "WHERE wled_channel_id = ?",
                (ch_id,),
            ) as cur:
                row = await cur.fetchone()
            assert row["c"] == 0

        asyncio.run(_check())


def test_patch_region_orientation_writes_all_rows():
    """PATCH /api/wled/regions/{rid}/orientation?config={cid} writes ALL matching rows."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={"name": "W", "led_count": 100, "ver": "", "mac": ""}
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.8"})
        assert r.status_code == 201
        dev_id = r.json()["id"]

        # Get two channels to assign to the same region.
        r1 = client.post(
            f"/api/wled/devices/{dev_id}/channels",
            json={"start_led": 0, "end_led": 49},
        )
        r2 = client.post(
            f"/api/wled/devices/{dev_id}/channels",
            json={"start_led": 50, "end_led": 99},
        )
        ch1_id = r1.json()["id"]
        ch2_id = r2.json()["id"]

        # Seed two assignment rows for the SAME region+config with different orientations.
        async def _seed():
            db = app.state.db
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_channel_id, entertainment_config_id, orientation) "
                "VALUES ('region-A', ?, 'cfg-X', 'auto')",
                (ch1_id,),
            )
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_channel_id, entertainment_config_id, orientation) "
                "VALUES ('region-A', ?, 'cfg-X', 'horizontal-LTR')",
                (ch2_id,),
            )
            await db.commit()

        asyncio.run(_seed())

        # PATCH orientation for region-A + cfg-X — must write both rows.
        rp = client.patch(
            "/api/wled/regions/region-A/orientation?config=cfg-X",
            json={"orientation": "vertical-TTB"},
        )
        assert rp.status_code == 200, rp.text
        assert rp.json()["updated"] == 2

        # Verify both rows have the new orientation.
        async def _check():
            db = app.state.db
            async with db.execute(
                "SELECT orientation FROM wled_light_assignments "
                "WHERE region_id = 'region-A' AND entertainment_config_id = 'cfg-X'",
            ) as cur:
                rows = await cur.fetchall()
            assert len(rows) == 2
            for row in rows:
                assert row["orientation"] == "vertical-TTB"

        asyncio.run(_check())


def test_upsert_assignment_inherits_region_orientation():
    """PUT /api/wled/assignments inserts new row carrying the region's current orientation."""
    app = _make_app()
    with TestClient(app) as client:
        with patch(
            "routers.wled.fetch_wled_info",
            AsyncMock(
                return_value={"name": "W", "led_count": 100, "ver": "", "mac": ""}
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.9"})
        assert r.status_code == 201
        dev_id = r.json()["id"]

        # Create two channels.
        r1 = client.post(
            f"/api/wled/devices/{dev_id}/channels",
            json={"start_led": 0, "end_led": 49},
        )
        r2 = client.post(
            f"/api/wled/devices/{dev_id}/channels",
            json={"start_led": 50, "end_led": 99},
        )
        ch1_id = r1.json()["id"]
        ch2_id = r2.json()["id"]

        # Seed an existing assignment for ch1 with orientation 'vertical-TTB'.
        async def _seed():
            db = app.state.db
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_channel_id, entertainment_config_id, orientation) "
                "VALUES ('region-B', ?, 'cfg-Y', 'vertical-TTB')",
                (ch1_id,),
            )
            await db.commit()

        asyncio.run(_seed())

        # PUT a NEW assignment for ch2 WITHOUT specifying orientation.
        # It must inherit 'vertical-TTB' from the region's existing row.
        rp = client.put(
            "/api/wled/assignments",
            json={
                "region_id": "region-B",
                "wled_channel_id": ch2_id,
                "entertainment_config_id": "cfg-Y",
            },
        )
        assert rp.status_code == 200, rp.text
        body = rp.json()
        assert body["orientation"] == "vertical-TTB"
        assert body["region_id"] == "region-B"
        assert body["wled_channel_id"] == ch2_id
