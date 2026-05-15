"""Phase 19.1 e2e: V4 persistence + refresh smoke (D-23 V4, D-20).

Replaces test_phase19_e2e.py once Plan 05 deletes it.
Until Plan 03 ships services.wled_segments, all tests skip via pytest.importorskip.
"""
from __future__ import annotations

import aiosqlite
import pytest

pytestmark = pytest.mark.asyncio


async def test_cache_survives_db_reopen(tmp_path):
    """D-23 V4: wled_seg_cache + wled_light_assignments persist across init_db round-trip.

    Plan 04 fix: include `created_at` (NOT NULL in the production schema) when
    seeding wled_devices, and use a Phase-19 valid orientation literal
    ('horizontal-LTR') instead of the Plan-01 stub's invented 'left-to-right'.
    The Phase 19.1 D-13 schema preserves Phase 19's orientation enum unchanged
    (see WledOrientation in Backend/routers/wled.py).
    """
    pytest.importorskip("services.wled_segments")
    from database import init_db, close_db
    from services.wled_segments import reconcile_segments

    db_path = str(tmp_path / "phase19_1.db")
    db = await init_db(db_path)
    db.row_factory = aiosqlite.Row
    try:
        await db.execute(
            "INSERT INTO wled_devices (id, ip, name, led_count, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("dev-1", "192.168.1.50", "Test", 300, "2026-05-14T00:00:00+00:00"),
        )
        await db.commit()
        await reconcile_segments(db, "dev-1", [
            {"seg_index": 0, "start_led": 0, "stop_led": 99, "name": "Sofa"},
        ])
        await db.execute(
            "INSERT INTO wled_light_assignments "
            "(region_id, wled_device_id, seg_index, entertainment_config_id, orientation) "
            "VALUES (?, ?, ?, ?, ?)",
            ("region-A", "dev-1", 0, "cfg-1", "horizontal-LTR"),
        )
        await db.commit()
    finally:
        await close_db(db)

    # Reopen and verify
    db2 = await init_db(db_path)
    db2.row_factory = aiosqlite.Row
    try:
        async with db2.execute(
            "SELECT name, start_led, stop_led FROM wled_seg_cache "
            "WHERE device_id = 'dev-1' AND seg_index = 0"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row["name"] == "Sofa"
        assert row["start_led"] == 0
        assert row["stop_led"] == 99

        async with db2.execute(
            "SELECT orientation FROM wled_light_assignments "
            "WHERE region_id = 'region-A' AND wled_device_id = 'dev-1' "
            "AND seg_index = 0"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row["orientation"] == "horizontal-LTR"
    finally:
        await close_db(db2)


async def test_refresh_smoke_against_mock_transport(tmp_path):
    """Smoke: fetch_wled_state + reconcile_segments end-to-end via httpx.MockTransport.

    Plan 04 activation: routers/wled.py now exposes
    POST /api/wled/devices/{id}/segments/refresh. This e2e variant boots the
    real FastAPI lifespan against a tmp_path SQLite file (init_db round-trip),
    POSTs the refresh, and asserts wled_seg_cache was actually written. The
    canonical unit-level coverage of refresh response shape / 404 / 502 / 422
    lives in test_wled_router.py — this case is the end-to-end smoke that
    confirms the router, services.wled_client.fetch_wled_state, and
    services.wled_segments.reconcile_segments cooperate over a real DB.
    """
    pytest.importorskip("services.wled_segments")

    from contextlib import asynccontextmanager
    from unittest.mock import patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from database import init_db, close_db
    from routers.wled import router as wled_router

    db_path = str(tmp_path / "phase19_1_refresh_smoke.db")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = await init_db(db_path)
        app.state.db = db
        try:
            yield
        finally:
            await close_db(db)

    app = FastAPI(lifespan=lifespan)
    app.include_router(wled_router)

    async def fake_fetch_wled_state(ip, timeout=5.0):
        return [
            {"seg_index": 0, "start_led": 0, "stop_led": 99, "name": "Sofa"},
            {"seg_index": 1, "start_led": 100, "stop_led": 199, "name": "TV"},
        ]

    with TestClient(app) as client:
        # Seed a device directly so we can skip the registration httpx mocks.
        db = app.state.db
        await db.execute(
            "INSERT INTO wled_devices (id, ip, name, led_count, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("dev-1", "192.168.1.50", "Test", 300, "2026-05-14T00:00:00+00:00"),
        )
        await db.commit()

        with patch("routers.wled.fetch_wled_state", fake_fetch_wled_state):
            resp = client.post("/api/wled/devices/dev-1/segments/refresh")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["segments"]) == 2
        assert body["dropped_assignments"] == 0
        assert body["segments"][0]["name"] == "Sofa"
        assert body["segments"][1]["name"] == "TV"

        # Verify the cache was actually written to the real DB.
        async with db.execute(
            "SELECT COUNT(*) AS c FROM wled_seg_cache WHERE device_id = 'dev-1'"
        ) as cur:
            row = await cur.fetchone()
        assert row["c"] == 2
