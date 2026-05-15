"""Integration tests for /api/wled/* endpoints (Phase 19.1).

Strategy: TestClient + in-memory aiosqlite DB matching the Phase 19.1 schema
(wled_devices, wled_seg_cache, wled_light_assignments — the dropped
wled_channels table is gone per D-10/D-20). The coordinator is intentionally
NOT wired in these tests — `set_enabled` falls back to a direct DB UPDATE so
we can assert CRUD behavior without spinning up a streamer.

External services are mocked at the router-import path:
  - `routers.wled.fetch_wled_info`        (httpx /json/info probe)
  - `routers.wled.fetch_wled_state`       (httpx /json/state probe — D-02 / D-17)
  - `routers.wled.scan_for_wled_devices`  (zeroconf scan)

Coverage map:
  T-17-INPUT          test_add_device_rejects_malformed_ip
  T-17-NETWORK        test_add_device_unreachable_returns_502
  T-17-SHAPE          test_add_device_zero_led_count_returns_422
  D-02 atomic register test_add_device_persists_and_writes_seg_cache,
                       test_register_device_fetches_state,
                       test_register_device_rolls_back_on_state_failure
  GET /devices        test_list_after_add
  T-17-DUPE           test_duplicate_ip_returns_409
  T-17-DELETE-ORPHAN  test_delete_cascades_seg_cache_and_assignments
  404 hygiene         test_delete_unknown_returns_404,
                       test_put_enabled_unknown_returns_404,
                       test_post_segments_refresh_404_for_unknown_device,
                       test_get_segments_404_for_unknown_device
  WLED-02             test_put_enabled_toggles_row_without_coordinator
  zeroconf scan       test_scan_returns_candidates_list
  D-17 refresh        test_post_segments_refresh,
                       test_post_segments_refresh_502_on_timeout,
                       test_post_segments_refresh_422_on_malformed_response
  D-18 list-segments  test_get_segments_no_device_contact,
                       test_get_segments_returns_cached_rows
  D-04 offline        test_refresh_preserves_cache_on_502
  D-13 assignment     test_upsert_assignment_basic,
                       test_upsert_assignment_inherits_region_orientation,
                       test_delete_assignment_basic
  D-16 orientation    test_patch_region_orientation_writes_all_rows
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
    """In-memory aiosqlite mirroring the Phase 19.1 schema in `database.py`.

    Matches `init_db` post-PHASE_19_1_USER_VERSION=1: wled_devices stays
    unchanged, wled_seg_cache is new (D-12), wled_light_assignments has the
    rewritten composite PK (D-13). wled_channels is intentionally absent —
    Phase 19.1 D-20 drops it.
    """
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
        CREATE TABLE IF NOT EXISTS wled_seg_cache (
            device_id TEXT NOT NULL,
            seg_index INTEGER NOT NULL,
            start_led INTEGER NOT NULL,
            stop_led INTEGER NOT NULL,
            name TEXT,
            refreshed_at TEXT NOT NULL,
            PRIMARY KEY (device_id, seg_index)
        )
        """
    )
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wled_light_assignments (
            region_id TEXT NOT NULL,
            wled_device_id TEXT NOT NULL,
            seg_index INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            orientation TEXT NOT NULL DEFAULT 'auto',
            PRIMARY KEY (region_id, wled_device_id, seg_index, entertainment_config_id)
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


def _fake_state_segments():
    """Standard mock /json/state response used by registration happy paths.

    Returns one full-strip segment so registration succeeds and writes one
    cache row. Tests that care about specific segment shapes patch
    `routers.wled.fetch_wled_state` themselves.
    """
    return [
        {"seg_index": 0, "start_led": 0, "stop_led": 99, "name": "Strip"},
    ]


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
        ), patch(
            "routers.wled.fetch_wled_state",
            AsyncMock(return_value=_fake_state_segments()),
        ):
            r = client.post("/api/wled/devices", json={"ip": "192.168.1.50"})
    assert r.status_code == 422


def test_add_device_persists_and_writes_seg_cache():
    """Phase 19.1 D-02 happy path: 201 + wled_seg_cache row seeded from /json/state.

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
        ), patch(
            "routers.wled.fetch_wled_state",
            AsyncMock(
                return_value=[
                    {"seg_index": 0, "start_led": 0, "stop_led": 99, "name": "Sofa"},
                    {"seg_index": 1, "start_led": 100, "stop_led": 199, "name": None},
                ]
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

        # D-02 cache seed: wled_seg_cache rows exist post-register.
        async def _check_cache():
            db = app.state.db
            async with db.execute(
                "SELECT seg_index, start_led, stop_led, name FROM wled_seg_cache "
                "WHERE device_id = ? ORDER BY seg_index",
                (dev_id,),
            ) as cur:
                rows = await cur.fetchall()
            assert len(rows) == 2
            assert rows[0]["seg_index"] == 0
            assert rows[0]["start_led"] == 0
            assert rows[0]["stop_led"] == 99
            assert rows[0]["name"] == "Sofa"
            assert rows[1]["seg_index"] == 1
            assert rows[1]["name"] is None

        asyncio.run(_check_cache())


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
        ), patch(
            "routers.wled.fetch_wled_state",
            AsyncMock(return_value=_fake_state_segments()),
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
        ), patch(
            "routers.wled.fetch_wled_state",
            AsyncMock(return_value=_fake_state_segments()),
        ):
            r1 = client.post("/api/wled/devices", json={"ip": "10.0.0.5"})
            assert r1.status_code == 201
            r2 = client.post("/api/wled/devices", json={"ip": "10.0.0.5"})
        assert r2.status_code == 409


def test_register_device_fetches_state():
    """D-02: registration calls /json/info AND /json/state in the same coroutine."""
    app = _make_app()
    info_called = {"n": 0}
    state_called = {"n": 0}

    async def fake_info(ip, timeout=5.0):
        info_called["n"] += 1
        return {
            "name": "WLED-Test",
            "led_count": 300,
            "ver": "0.14.0",
            "mac": "AA:BB:CC:DD:EE:FF",
        }

    async def fake_state(ip, timeout=5.0):
        state_called["n"] += 1
        return [
            {"seg_index": 0, "start_led": 0, "stop_led": 99, "name": "Initial"},
        ]

    with TestClient(app) as client:
        with patch("routers.wled.fetch_wled_info", fake_info), patch(
            "routers.wled.fetch_wled_state", fake_state
        ):
            r = client.post("/api/wled/devices", json={"ip": "1.1.1.2"})
        assert r.status_code == 201, r.text
        body = r.json()
        device_id = body["id"]
        assert info_called["n"] == 1
        assert state_called["n"] == 1

        # Cache row exists post-register.
        async def _check_seeded():
            db = app.state.db
            async with db.execute(
                "SELECT name FROM wled_seg_cache WHERE device_id = ?",
                (device_id,),
            ) as cur:
                row = await cur.fetchone()
            assert row is not None
            assert row["name"] == "Initial"

        asyncio.run(_check_seeded())


def test_register_device_rolls_back_on_state_failure():
    """D-02 atomic: if /json/state fails, no device row is left behind."""
    app = _make_app()

    async def fake_info(ip, timeout=5.0):
        return {
            "name": "WLED-Test",
            "led_count": 300,
            "ver": "0.14.0",
            "mac": "AA:BB:CC:DD:EE:FF",
        }

    async def fake_state(ip, timeout=5.0):
        raise httpx.TimeoutException("simulated")

    with TestClient(app) as client:
        with patch("routers.wled.fetch_wled_info", fake_info), patch(
            "routers.wled.fetch_wled_state", fake_state
        ):
            r = client.post("/api/wled/devices", json={"ip": "1.1.1.99"})
        assert r.status_code == 502

        async def _check_zero_devices():
            db = app.state.db
            async with db.execute(
                "SELECT COUNT(*) AS c FROM wled_devices WHERE ip = '1.1.1.99'"
            ) as cur:
                row = await cur.fetchone()
            assert row["c"] == 0
            async with db.execute(
                "SELECT COUNT(*) AS c FROM wled_seg_cache"
            ) as cur:
                row = await cur.fetchone()
            assert row["c"] == 0

        asyncio.run(_check_zero_devices())


# ---------------------------------------------------------------------------
# Tests — DELETE /api/wled/devices/{id}
# ---------------------------------------------------------------------------


def test_delete_cascades_seg_cache_and_assignments():
    """DELETE wipes the device, its wled_seg_cache rows, and any
    wled_light_assignments referencing the device (T-17-DELETE-ORPHAN)."""
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
        ), patch(
            "routers.wled.fetch_wled_state",
            AsyncMock(
                return_value=[
                    {
                        "seg_index": 0,
                        "start_led": 0,
                        "stop_led": 99,
                        "name": None,
                    }
                ]
            ),
        ):
            r = client.post("/api/wled/devices", json={"ip": "10.0.0.5"})
        assert r.status_code == 201, r.text
        dev_id = r.json()["id"]

        # Insert a phantom assignment via direct DB write so we can assert
        # that DELETE truly cascades through wled_light_assignments.
        async def _seed_assignment():
            db = app.state.db
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_device_id, seg_index, entertainment_config_id, orientation) "
                "VALUES ('r1', ?, 0, 'cfg1', 'auto')",
                (dev_id,),
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
                "SELECT COUNT(*) AS c FROM wled_seg_cache"
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
        ), patch(
            "routers.wled.fetch_wled_state",
            AsyncMock(return_value=_fake_state_segments()),
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
# Phase 19.1 — D-17 segment refresh endpoint
# ---------------------------------------------------------------------------


def _seed_device_directly(app, device_id: str, ip: str = "1.1.1.1", led_count: int = 300):
    """Insert a wled_devices row directly so refresh/list tests can run without
    going through the registration handler (avoids needing to mock fetch_wled_*
    twice). Returns nothing — assertions live in caller."""
    async def _seed():
        db = app.state.db
        await db.execute(
            "INSERT INTO wled_devices (id, ip, name, led_count, enabled, created_at) "
            "VALUES (?, ?, ?, ?, 1, '2026-05-14T00:00:00+00:00')",
            (device_id, ip, "Test", led_count),
        )
        await db.commit()

    asyncio.run(_seed())


def test_post_segments_refresh():
    """D-17: refresh endpoint fetches state, reconciles cache, returns segments + dropped count."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        async def fake_fetch_wled_state(ip, timeout=5.0):
            return [
                {"seg_index": 0, "start_led": 0, "stop_led": 99, "name": "Sofa"},
                {"seg_index": 1, "start_led": 100, "stop_led": 199, "name": None},
            ]

        with patch("routers.wled.fetch_wled_state", fake_fetch_wled_state):
            resp = client.post("/api/wled/devices/dev-1/segments/refresh")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["segments"]) == 2
        assert body["segments"][0]["seg_index"] == 0
        assert body["segments"][0]["start_led"] == 0
        assert body["segments"][0]["stop_led"] == 99
        assert body["segments"][0]["name"] == "Sofa"
        assert body["segments"][0]["refreshed_at"] is not None
        assert body["segments"][1]["name"] is None
        assert body["dropped_assignments"] == 0


def test_post_segments_refresh_404_for_unknown_device():
    """Refresh on a missing device returns 404 before any httpx call fires."""
    app = _make_app()
    with TestClient(app) as client:
        # Patch fetch to assert it's never called when the device is unknown.
        called = {"n": 0}

        async def fake(ip, timeout=5.0):
            called["n"] += 1
            return []

        with patch("routers.wled.fetch_wled_state", fake):
            resp = client.post("/api/wled/devices/nope/segments/refresh")
        assert resp.status_code == 404
        assert called["n"] == 0


def test_post_segments_refresh_502_on_timeout():
    """httpx.TimeoutException -> 502 with detail mentioning 'timeout'."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        async def fake(ip, timeout=5.0):
            raise httpx.TimeoutException("simulated")

        with patch("routers.wled.fetch_wled_state", fake):
            resp = client.post("/api/wled/devices/dev-1/segments/refresh")
        assert resp.status_code == 502
        assert "timeout" in resp.json()["detail"].lower()


def test_post_segments_refresh_422_on_malformed_response():
    """ValueError (defensive-parse) -> 422 with detail 'Invalid WLED response'."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        async def fake(ip, timeout=5.0):
            raise ValueError("seg field has unexpected type: int")

        with patch("routers.wled.fetch_wled_state", fake):
            resp = client.post("/api/wled/devices/dev-1/segments/refresh")
        assert resp.status_code == 422
        assert "invalid wled response" in resp.json()["detail"].lower()


def test_refresh_preserves_cache_on_502():
    """D-04: 502 on refresh does NOT wipe the cache (offline behavior)."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        # Pre-seed a cache row directly.
        async def _seed_cache():
            db = app.state.db
            await db.execute(
                "INSERT INTO wled_seg_cache "
                "(device_id, seg_index, start_led, stop_led, name, refreshed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("dev-1", 0, 0, 99, "Pre", "2026-05-14T00:00:00+00:00"),
            )
            await db.commit()

        asyncio.run(_seed_cache())

        async def fake(ip, timeout=5.0):
            raise httpx.TimeoutException("offline")

        with patch("routers.wled.fetch_wled_state", fake):
            resp = client.post("/api/wled/devices/dev-1/segments/refresh")
        assert resp.status_code == 502

        # Cache row STILL EXISTS.
        async def _check_cache_survives():
            db = app.state.db
            async with db.execute(
                "SELECT name FROM wled_seg_cache "
                "WHERE device_id = 'dev-1' AND seg_index = 0"
            ) as cur:
                row = await cur.fetchone()
            assert row is not None
            assert row["name"] == "Pre"

        asyncio.run(_check_cache_survives())


# ---------------------------------------------------------------------------
# Phase 19.1 — D-18 list-segments endpoint
# ---------------------------------------------------------------------------


def test_get_segments_no_device_contact():
    """D-18: GET reads cache only, never calls the device."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        async def _seed_cache():
            db = app.state.db
            await db.execute(
                "INSERT INTO wled_seg_cache "
                "(device_id, seg_index, start_led, stop_led, name, refreshed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("dev-1", 0, 0, 99, "Cached", "2026-05-14T00:00:00+00:00"),
            )
            await db.commit()

        asyncio.run(_seed_cache())

        called = {"n": 0}

        async def fake(ip, timeout=5.0):
            called["n"] += 1
            return []

        with patch("routers.wled.fetch_wled_state", fake):
            resp = client.get("/api/wled/devices/dev-1/segments")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["segments"]) == 1
        assert body["segments"][0]["name"] == "Cached"
        # CRITICAL: never called the device.
        assert called["n"] == 0


def test_get_segments_returns_cached_rows():
    """GET returns the rows we wrote, ordered by seg_index."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        async def _seed_cache():
            db = app.state.db
            # Insert out-of-order to verify ORDER BY seg_index ASC.
            await db.execute(
                "INSERT INTO wled_seg_cache "
                "(device_id, seg_index, start_led, stop_led, name, refreshed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("dev-1", 2, 200, 299, "Third", "2026-05-14T00:00:00+00:00"),
            )
            await db.execute(
                "INSERT INTO wled_seg_cache "
                "(device_id, seg_index, start_led, stop_led, name, refreshed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("dev-1", 0, 0, 99, "First", "2026-05-14T00:00:00+00:00"),
            )
            await db.commit()

        asyncio.run(_seed_cache())

        resp = client.get("/api/wled/devices/dev-1/segments")
        assert resp.status_code == 200
        body = resp.json()
        assert [s["seg_index"] for s in body["segments"]] == [0, 2]
        assert body["segments"][0]["name"] == "First"
        assert body["segments"][1]["name"] == "Third"


def test_get_segments_404_for_unknown_device():
    """GET /segments on a missing device returns 404."""
    with _make_client() as client:
        r = client.get("/api/wled/devices/nope/segments")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Phase 19.1 — D-13 assignment endpoints (new composite shape)
# ---------------------------------------------------------------------------


def test_upsert_assignment_basic():
    """PUT /api/wled/assignments inserts a row with the new D-13 shape."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        async def _seed_cache_row():
            db = app.state.db
            await db.execute(
                "INSERT INTO wled_seg_cache "
                "(device_id, seg_index, start_led, stop_led, name, refreshed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("dev-1", 0, 0, 99, "Sofa", "2026-05-14T00:00:00+00:00"),
            )
            await db.commit()

        asyncio.run(_seed_cache_row())

        resp = client.put(
            "/api/wled/assignments",
            json={
                "region_id": "region-A",
                "wled_device_id": "dev-1",
                "seg_index": 0,
                "entertainment_config_id": "cfg-1",
                "orientation": "horizontal-LTR",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["region_id"] == "region-A"
        assert body["wled_device_id"] == "dev-1"
        assert body["seg_index"] == 0
        assert body["entertainment_config_id"] == "cfg-1"
        assert body["orientation"] == "horizontal-LTR"

        # Upsert: re-PUT with a new orientation updates in place.
        resp2 = client.put(
            "/api/wled/assignments",
            json={
                "region_id": "region-A",
                "wled_device_id": "dev-1",
                "seg_index": 0,
                "entertainment_config_id": "cfg-1",
                "orientation": "vertical-TTB",
            },
        )
        assert resp2.status_code == 200
        assert resp2.json()["orientation"] == "vertical-TTB"

        # Confirm only one row exists for the composite PK.
        async def _check_row_count():
            db = app.state.db
            async with db.execute(
                "SELECT COUNT(*) AS c FROM wled_light_assignments "
                "WHERE region_id = 'region-A' AND wled_device_id = 'dev-1' "
                "AND seg_index = 0 AND entertainment_config_id = 'cfg-1'"
            ) as cur:
                row = await cur.fetchone()
            assert row["c"] == 1

        asyncio.run(_check_row_count())


def test_upsert_assignment_inherits_region_orientation():
    """PUT with orientation=None inherits the region's current orientation (D-16)."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        async def _seed():
            db = app.state.db
            # Seed an existing assignment for seg 0 with orientation 'vertical-TTB'.
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_device_id, seg_index, entertainment_config_id, orientation) "
                "VALUES ('region-B', 'dev-1', 0, 'cfg-Y', 'vertical-TTB')"
            )
            await db.commit()

        asyncio.run(_seed())

        # PUT a NEW assignment for seg 1 WITHOUT specifying orientation.
        # It must inherit 'vertical-TTB' from the region's existing row.
        resp = client.put(
            "/api/wled/assignments",
            json={
                "region_id": "region-B",
                "wled_device_id": "dev-1",
                "seg_index": 1,
                "entertainment_config_id": "cfg-Y",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["orientation"] == "vertical-TTB"
        assert body["region_id"] == "region-B"
        assert body["seg_index"] == 1


def test_delete_assignment_basic():
    """DELETE /api/wled/assignments removes the row with the composite key."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        async def _seed():
            db = app.state.db
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_device_id, seg_index, entertainment_config_id, orientation) "
                "VALUES ('region-A', 'dev-1', 0, 'cfg-1', 'auto')"
            )
            await db.commit()

        asyncio.run(_seed())

        # FastAPI/TestClient sends a body on DELETE via the `request` arg.
        resp = client.request(
            "DELETE",
            "/api/wled/assignments",
            json={
                "region_id": "region-A",
                "wled_device_id": "dev-1",
                "seg_index": 0,
                "entertainment_config_id": "cfg-1",
            },
        )
        assert resp.status_code == 204, resp.text

        async def _check_gone():
            db = app.state.db
            async with db.execute(
                "SELECT COUNT(*) AS c FROM wled_light_assignments"
            ) as cur:
                row = await cur.fetchone()
            assert row["c"] == 0

        asyncio.run(_check_gone())


# ---------------------------------------------------------------------------
# Phase 19.1 — Region orientation PATCH (D-16/D-22, new column names)
# ---------------------------------------------------------------------------


def test_patch_region_orientation_writes_all_rows():
    """PATCH /api/wled/regions/{rid}/orientation?config={cid} writes ALL matching rows."""
    app = _make_app()
    with TestClient(app) as client:
        _seed_device_directly(app, "dev-1")

        async def _seed():
            db = app.state.db
            # Two assignment rows for the SAME region+config but different segs.
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_device_id, seg_index, entertainment_config_id, orientation) "
                "VALUES ('region-A', 'dev-1', 0, 'cfg-X', 'auto')"
            )
            await db.execute(
                "INSERT INTO wled_light_assignments "
                "(region_id, wled_device_id, seg_index, entertainment_config_id, orientation) "
                "VALUES ('region-A', 'dev-1', 1, 'cfg-X', 'horizontal-LTR')"
            )
            await db.commit()

        asyncio.run(_seed())

        rp = client.patch(
            "/api/wled/regions/region-A/orientation?config=cfg-X",
            json={"orientation": "vertical-TTB"},
        )
        assert rp.status_code == 200, rp.text
        assert rp.json()["updated"] == 2

        async def _check_both_updated():
            db = app.state.db
            async with db.execute(
                "SELECT orientation FROM wled_light_assignments "
                "WHERE region_id = 'region-A' AND entertainment_config_id = 'cfg-X'"
            ) as cur:
                rows = await cur.fetchall()
            assert len(rows) == 2
            for row in rows:
                assert row["orientation"] == "vertical-TTB"

        asyncio.run(_check_both_updated())
