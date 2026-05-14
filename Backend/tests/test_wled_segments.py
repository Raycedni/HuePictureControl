"""Phase 19.1: Tests for services/wled_segments.reconcile_segments (D-14, D-19).

All cases are stubbed via pytest.importorskip until Wave 2 (Plan 03) lands
the service module. The fixture and case skeletons are mirrored from
test_wled_channels.py.
"""
from __future__ import annotations

import aiosqlite
import pytest

pytestmark = pytest.mark.asyncio


async def _make_db():
    """In-memory aiosqlite with Phase 19.1 schema (D-12, D-13)."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("""
        CREATE TABLE wled_devices (
            id TEXT PRIMARY KEY,
            ip TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            led_count INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        )
    """)
    await conn.execute("""
        CREATE TABLE wled_seg_cache (
            device_id TEXT NOT NULL,
            seg_index INTEGER NOT NULL,
            start_led INTEGER NOT NULL,
            stop_led INTEGER NOT NULL,
            name TEXT,
            refreshed_at TEXT NOT NULL,
            PRIMARY KEY (device_id, seg_index),
            FOREIGN KEY (device_id) REFERENCES wled_devices(id) ON DELETE CASCADE
        )
    """)
    await conn.execute("""
        CREATE TABLE wled_light_assignments (
            region_id TEXT NOT NULL,
            wled_device_id TEXT NOT NULL,
            seg_index INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            orientation TEXT NOT NULL DEFAULT 'auto',
            PRIMARY KEY (region_id, wled_device_id, seg_index, entertainment_config_id)
        )
    """)
    await conn.commit()
    return conn


async def _seed_device(db, device_id="dev-1", led_count=300):
    await db.execute(
        "INSERT INTO wled_devices (id, ip, name, led_count) VALUES (?, ?, ?, ?)",
        (device_id, "192.168.1.50", "WLED-Test", led_count),
    )
    await db.commit()
    return device_id


async def test_reconcile_inserts_new_segs():
    """D-14.2: Empty cache -> N segments -> N rows persisted."""
    pytest.importorskip("services.wled_segments")
    from services.wled_segments import reconcile_segments  # noqa: F401

    db = await _make_db()
    try:
        dev = await _seed_device(db)
        segments = [
            {"seg_index": 0, "start_led": 0, "stop_led": 99, "name": "Sofa"},
            {"seg_index": 1, "start_led": 100, "stop_led": 199, "name": None},
        ]
        dropped = await reconcile_segments(db, dev, segments)
        assert dropped == 0
        async with db.execute(
            "SELECT COUNT(*) AS c FROM wled_seg_cache WHERE device_id = ?", (dev,)
        ) as cur:
            row = await cur.fetchone()
        assert row["c"] == 2
    finally:
        await db.close()


async def test_reconcile_wipes_cache():
    """D-14.1, D-19: DELETE-then-INSERT atomicity — old rows do not survive."""
    pytest.importorskip("services.wled_segments")
    from services.wled_segments import reconcile_segments

    db = await _make_db()
    try:
        dev = await _seed_device(db)
        await reconcile_segments(db, dev, [
            {"seg_index": 0, "start_led": 0, "stop_led": 49, "name": "Old0"},
            {"seg_index": 1, "start_led": 50, "stop_led": 99, "name": "Old1"},
        ])
        # Second reconcile — completely different segments
        await reconcile_segments(db, dev, [
            {"seg_index": 0, "start_led": 0, "stop_led": 19, "name": "New0"},
        ])
        async with db.execute(
            "SELECT seg_index, name FROM wled_seg_cache WHERE device_id = ? ORDER BY seg_index", (dev,)
        ) as cur:
            rows = await cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["seg_index"] == 0
        assert rows[0]["name"] == "New0"
    finally:
        await db.close()


async def test_reconcile_drops_orphan_assignments():
    """D-14.3, D-15: assignments pointing at vanished seg_index are hard-deleted."""
    pytest.importorskip("services.wled_segments")
    from services.wled_segments import reconcile_segments

    db = await _make_db()
    try:
        dev = await _seed_device(db)
        # Seed cache with 2 segs and an assignment on each
        await reconcile_segments(db, dev, [
            {"seg_index": 0, "start_led": 0, "stop_led": 49, "name": None},
            {"seg_index": 1, "start_led": 50, "stop_led": 99, "name": None},
        ])
        await db.executemany(
            "INSERT INTO wled_light_assignments (region_id, wled_device_id, seg_index, entertainment_config_id, orientation) VALUES (?, ?, ?, ?, ?)",
            [("region-A", dev, 0, "cfg-1", "auto"),
             ("region-B", dev, 1, "cfg-1", "left-to-right")],
        )
        await db.commit()
        # Refresh — only seg_index=0 remains
        dropped = await reconcile_segments(db, dev, [
            {"seg_index": 0, "start_led": 0, "stop_led": 49, "name": None},
        ])
        assert dropped == 1
        async with db.execute(
            "SELECT seg_index FROM wled_light_assignments WHERE wled_device_id = ?", (dev,)
        ) as cur:
            rows = await cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["seg_index"] == 0
    finally:
        await db.close()


async def test_reconcile_range_change_preserves_assignment():
    """D-14.4, D-16: Range change on existing seg_index does NOT drop the assignment row."""
    pytest.importorskip("services.wled_segments")
    from services.wled_segments import reconcile_segments

    db = await _make_db()
    try:
        dev = await _seed_device(db)
        await reconcile_segments(db, dev, [
            {"seg_index": 0, "start_led": 0, "stop_led": 49, "name": None},
        ])
        await db.execute(
            "INSERT INTO wled_light_assignments (region_id, wled_device_id, seg_index, entertainment_config_id, orientation) VALUES (?, ?, ?, ?, ?)",
            ("region-A", dev, 0, "cfg-1", "auto"),
        )
        await db.commit()
        # Refresh with new RANGE but same seg_index
        dropped = await reconcile_segments(db, dev, [
            {"seg_index": 0, "start_led": 10, "stop_led": 99, "name": None},
        ])
        assert dropped == 0
        async with db.execute(
            "SELECT start_led, stop_led FROM wled_seg_cache WHERE device_id = ?", (dev,)
        ) as cur:
            row = await cur.fetchone()
        assert row["start_led"] == 10
        assert row["stop_led"] == 99
        async with db.execute(
            "SELECT COUNT(*) AS c FROM wled_light_assignments WHERE wled_device_id = ?", (dev,)
        ) as cur:
            row = await cur.fetchone()
        assert row["c"] == 1
    finally:
        await db.close()


async def test_reconcile_n_to_zero_wipes_all_assignments():
    """D-15: Device reports zero segments -> all assignments cascade-deleted."""
    pytest.importorskip("services.wled_segments")
    from services.wled_segments import reconcile_segments

    db = await _make_db()
    try:
        dev = await _seed_device(db)
        await reconcile_segments(db, dev, [
            {"seg_index": 0, "start_led": 0, "stop_led": 49, "name": None},
            {"seg_index": 1, "start_led": 50, "stop_led": 99, "name": None},
        ])
        await db.executemany(
            "INSERT INTO wled_light_assignments (region_id, wled_device_id, seg_index, entertainment_config_id, orientation) VALUES (?, ?, ?, ?, ?)",
            [("region-A", dev, 0, "cfg-1", "auto"),
             ("region-B", dev, 1, "cfg-1", "auto")],
        )
        await db.commit()
        dropped = await reconcile_segments(db, dev, [])
        assert dropped == 2
        async with db.execute(
            "SELECT COUNT(*) AS c FROM wled_seg_cache WHERE device_id = ?", (dev,)
        ) as cur:
            assert (await cur.fetchone())["c"] == 0
        async with db.execute(
            "SELECT COUNT(*) AS c FROM wled_light_assignments WHERE wled_device_id = ?", (dev,)
        ) as cur:
            assert (await cur.fetchone())["c"] == 0
    finally:
        await db.close()


async def test_reconcile_growth_n_to_n_plus_one():
    """D-14: Growth case — assignments on existing indices survive, new seg has no assignment."""
    pytest.importorskip("services.wled_segments")
    from services.wled_segments import reconcile_segments

    db = await _make_db()
    try:
        dev = await _seed_device(db)
        await reconcile_segments(db, dev, [
            {"seg_index": 0, "start_led": 0, "stop_led": 49, "name": None},
        ])
        await db.execute(
            "INSERT INTO wled_light_assignments (region_id, wled_device_id, seg_index, entertainment_config_id, orientation) VALUES (?, ?, ?, ?, ?)",
            ("region-A", dev, 0, "cfg-1", "auto"),
        )
        await db.commit()
        dropped = await reconcile_segments(db, dev, [
            {"seg_index": 0, "start_led": 0, "stop_led": 49, "name": None},
            {"seg_index": 1, "start_led": 50, "stop_led": 99, "name": "New"},
        ])
        assert dropped == 0
        async with db.execute(
            "SELECT COUNT(*) AS c FROM wled_seg_cache WHERE device_id = ?", (dev,)
        ) as cur:
            assert (await cur.fetchone())["c"] == 2
    finally:
        await db.close()
