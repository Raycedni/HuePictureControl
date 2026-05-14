"""Phase 19.1 e2e: V4 persistence + refresh smoke (D-23 V4, D-20).

Replaces test_phase19_e2e.py once Plan 05 deletes it.
Until Plan 03 ships services.wled_segments, all tests skip via pytest.importorskip.
"""
from __future__ import annotations

import aiosqlite
import pytest

pytestmark = pytest.mark.asyncio


async def test_cache_survives_db_reopen(tmp_path):
    """D-23 V4: wled_seg_cache + wled_light_assignments persist across init_db round-trip."""
    pytest.importorskip("services.wled_segments")
    from database import init_db, close_db
    from services.wled_segments import reconcile_segments

    db_path = str(tmp_path / "phase19_1.db")
    db = await init_db(db_path)
    db.row_factory = aiosqlite.Row
    try:
        await db.execute(
            "INSERT INTO wled_devices (id, ip, name, led_count) VALUES (?, ?, ?, ?)",
            ("dev-1", "192.168.1.50", "Test", 300),
        )
        await db.commit()
        await reconcile_segments(db, "dev-1", [
            {"seg_index": 0, "start_led": 0, "stop_led": 99, "name": "Sofa"},
        ])
        await db.execute(
            "INSERT INTO wled_light_assignments (region_id, wled_device_id, seg_index, entertainment_config_id, orientation) VALUES (?, ?, ?, ?, ?)",
            ("region-A", "dev-1", 0, "cfg-1", "left-to-right"),
        )
        await db.commit()
    finally:
        await close_db(db)

    # Reopen and verify
    db2 = await init_db(db_path)
    db2.row_factory = aiosqlite.Row
    try:
        async with db2.execute(
            "SELECT name, start_led, stop_led FROM wled_seg_cache WHERE device_id = 'dev-1' AND seg_index = 0"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row["name"] == "Sofa"
        assert row["start_led"] == 0
        assert row["stop_led"] == 99

        async with db2.execute(
            "SELECT orientation FROM wled_light_assignments WHERE region_id = 'region-A' AND wled_device_id = 'dev-1' AND seg_index = 0"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row["orientation"] == "left-to-right"
    finally:
        await close_db(db2)


async def test_refresh_smoke_against_mock_transport(tmp_path):
    """Smoke: fetch_wled_state + reconcile_segments via httpx.MockTransport.

    Wired in Plan 04 (router) — until then this just imports and skips.
    """
    pytest.importorskip("services.wled_segments")
    pytest.skip("Plan 04 wires refresh router; this smoke test activates then.")
