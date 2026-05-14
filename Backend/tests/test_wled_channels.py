"""Phase 19 D-02 / D-10 / D-21 — overlap-split + numbering + boundary + cascade unit tests.

These tests target Backend/services/wled_channels.py which is introduced in Plan
19-04. Until that module lands, the suite skips via pytest.importorskip — which
keeps `python -m pytest` green at Wave 0 while still failing fast in Wave 2 once
the helpers exist.
"""
import pytest
import uuid

import aiosqlite

# Reuse the Phase 17 in-memory fixture pattern. We extend it inline so this file
# is independent (no cross-test-module imports).


async def _make_db():
    """In-memory aiosqlite seeded with Phase 17 wled_* tables + Phase 19 columns."""
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


async def _seed_device(db, *, led_count=300):
    dev_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO wled_devices (id, ip, name, led_count, enabled, created_at, next_channel_n) "
        "VALUES (?, '192.168.1.99', 'Test', ?, 1, '2026-05-14T00:00:00Z', 1)",
        (dev_id, led_count),
    )
    # Phase 17 seed channel "Strip" covering full range
    seed_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) "
        "VALUES (?, ?, 'Strip', 0, ?, '#ffffff')",
        (seed_id, dev_id, led_count - 1),
    )
    await db.commit()
    return dev_id, seed_id


# ---------------------------------------------------------------------------
# Overlap-split cases A through G (WMAP-01 D-02)
# ---------------------------------------------------------------------------


async def test_overlap_split_case_a_no_overlap():
    """Case A: paint fully outside existing — INSERT new, no other changes."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, _seed = await _seed_device(db, led_count=300)
    # Re-seed manually with NO existing channels so case A applies:
    await db.execute("DELETE FROM wled_channels")
    await db.commit()
    result = await create_channel_with_split(db, dev_id, 50, 100)
    async with db.execute(
        "SELECT COUNT(*) AS c FROM wled_channels WHERE device_id = ?", (dev_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row["c"] == 1, "Case A: only the painted channel should exist"
    assert result["start_led"] == 50
    assert result["end_led"] == 100
    assert result["name"] == "Channel 1"
    await db.close()


async def test_overlap_split_case_b_strict_interior():
    """Case B: new range fully inside one existing — split existing into two halves."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, seed_id = await _seed_device(db, led_count=300)
    # Existing 'Strip' covers 0..299. Paint 100..199 (strict interior).
    result = await create_channel_with_split(db, dev_id, 100, 199)
    # Should now have 3 channels: left half (0..99), painted (100..199), right half (200..299)
    async with db.execute(
        "SELECT id, name, start_led, end_led FROM wled_channels WHERE device_id = ? ORDER BY start_led",
        (dev_id,),
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 3, f"Case B: expected 3 channels after interior split, got {len(rows)}: {[dict(r) for r in rows]}"
    # Left half must keep the original seed id (identity preserved)
    left = rows[0]
    assert left["id"] == seed_id, "Case B: left half must keep original id"
    assert left["start_led"] == 0
    assert left["end_led"] == 99
    # Painted range in the middle
    mid = rows[1]
    assert mid["start_led"] == 100
    assert mid["end_led"] == 199
    assert mid["id"] == result["id"]
    # Right half is a new row
    right = rows[2]
    assert right["start_led"] == 200
    assert right["end_led"] == 299
    await db.close()


async def test_overlap_split_case_c_exact_match():
    """Case C: new range exactly matches existing — existing deleted, new inserted with fresh name."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, seed_id = await _seed_device(db, led_count=100)
    # Strip covers 0..99 exactly. Paint 0..99.
    result = await create_channel_with_split(db, dev_id, 0, 99)
    async with db.execute(
        "SELECT id, name, start_led, end_led FROM wled_channels WHERE device_id = ?",
        (dev_id,),
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1, f"Case C: expected 1 channel after exact match, got {len(rows)}"
    ch = rows[0]
    assert ch["start_led"] == 0
    assert ch["end_led"] == 99
    # Original seed id should be gone (fresh row for the new channel)
    assert ch["id"] == result["id"]
    await db.close()


async def test_overlap_split_case_d_crosses_left_boundary():
    """Case D: new range crosses left boundary of existing — trim existing start."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, seed_id = await _seed_device(db, led_count=300)
    # Strip covers 0..299. Paint 0..99 — overlaps left boundary of Strip only.
    result = await create_channel_with_split(db, dev_id, 0, 99)
    async with db.execute(
        "SELECT id, name, start_led, end_led FROM wled_channels WHERE device_id = ? ORDER BY start_led",
        (dev_id,),
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 2, f"Case D: expected 2 channels, got {len(rows)}: {[dict(r) for r in rows]}"
    painted = rows[0]
    assert painted["start_led"] == 0
    assert painted["end_led"] == 99
    trimmed = rows[1]
    # Original seed_id kept but trimmed from the left
    assert trimmed["id"] == seed_id, "Case D: original id must be kept after left-trim"
    assert trimmed["start_led"] == 100
    assert trimmed["end_led"] == 299
    await db.close()


async def test_overlap_split_case_e_crosses_right_boundary():
    """Case E: new range crosses right boundary of existing — trim existing end."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, seed_id = await _seed_device(db, led_count=300)
    # Strip covers 0..299. Paint 200..299 — overlaps right boundary of Strip only.
    result = await create_channel_with_split(db, dev_id, 200, 299)
    async with db.execute(
        "SELECT id, name, start_led, end_led FROM wled_channels WHERE device_id = ? ORDER BY start_led",
        (dev_id,),
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 2, f"Case E: expected 2 channels, got {len(rows)}: {[dict(r) for r in rows]}"
    trimmed = rows[0]
    # Original seed_id kept but trimmed from the right
    assert trimmed["id"] == seed_id, "Case E: original id must be kept after right-trim"
    assert trimmed["start_led"] == 0
    assert trimmed["end_led"] == 199
    painted = rows[1]
    assert painted["start_led"] == 200
    assert painted["end_led"] == 299
    await db.close()


async def test_overlap_split_case_f_multiple_swallowed():
    """Case F: new range spans from one existing to another, swallowing channels in between."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, _seed = await _seed_device(db, led_count=300)
    # Set up: ch_a=0..49, ch_b=50..99, ch_c=100..149, ch_d=150..199, ch_e=200..299
    await db.execute("DELETE FROM wled_channels")
    await db.commit()
    ids = {}
    for name, s, e in [("ch_a", 0, 49), ("ch_b", 50, 99), ("ch_c", 100, 149), ("ch_d", 150, 199), ("ch_e", 200, 299)]:
        ch_id = str(uuid.uuid4())
        ids[name] = ch_id
        await db.execute(
            "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) VALUES (?, ?, ?, ?, ?, '#fff')",
            (ch_id, dev_id, name, s, e),
        )
    await db.commit()
    # Paint 30..179 — crosses ch_a's right boundary (case E), swallows ch_b, ch_c, crosses ch_d's left (case D)
    result = await create_channel_with_split(db, dev_id, 30, 179)
    async with db.execute(
        "SELECT id, name, start_led, end_led FROM wled_channels WHERE device_id = ? ORDER BY start_led",
        (dev_id,),
    ) as cur:
        rows = await cur.fetchall()
    # Expected: ch_a trimmed (0..29), new channel (30..179), ch_d trimmed (180..199), ch_e intact (200..299)
    assert len(rows) == 4, f"Case F: expected 4 channels, got {len(rows)}: {[dict(r) for r in rows]}"
    assert rows[0]["id"] == ids["ch_a"], "Case F: ch_a identity preserved (left edge)"
    assert rows[0]["start_led"] == 0 and rows[0]["end_led"] == 29
    assert rows[1]["start_led"] == 30 and rows[1]["end_led"] == 179
    assert rows[2]["id"] == ids["ch_d"], "Case F: ch_d identity preserved (right edge)"
    assert rows[2]["start_led"] == 180 and rows[2]["end_led"] == 199
    assert rows[3]["id"] == ids["ch_e"], "Case F: ch_e unchanged"
    await db.close()


async def test_overlap_split_case_g_encloses_existing():
    """Case G: new range encloses one existing entirely — swallowed channel deleted."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, _seed = await _seed_device(db, led_count=300)
    # Set up: ch_a=0..49, ch_b=50..99, ch_c=100..149
    await db.execute("DELETE FROM wled_channels")
    await db.commit()
    ids = {}
    for name, s, e in [("ch_a", 0, 49), ("ch_b", 50, 99), ("ch_c", 100, 149)]:
        ch_id = str(uuid.uuid4())
        ids[name] = ch_id
        await db.execute(
            "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) VALUES (?, ?, ?, ?, ?, '#fff')",
            (ch_id, dev_id, name, s, e),
        )
    await db.commit()
    # Paint 40..109 — encloses ch_b fully (50..99), trims ch_a and ch_c
    result = await create_channel_with_split(db, dev_id, 40, 109)
    async with db.execute(
        "SELECT id, name, start_led, end_led FROM wled_channels WHERE device_id = ? ORDER BY start_led",
        (dev_id,),
    ) as cur:
        rows = await cur.fetchall()
    # Expected: ch_a trimmed (0..39), new painted (40..109), ch_c trimmed (110..149)
    assert len(rows) == 3, f"Case G: expected 3 channels, got {len(rows)}: {[dict(r) for r in rows]}"
    assert rows[0]["id"] == ids["ch_a"]
    assert rows[0]["start_led"] == 0 and rows[0]["end_led"] == 39
    assert rows[1]["start_led"] == 40 and rows[1]["end_led"] == 109
    assert rows[2]["id"] == ids["ch_c"]
    assert rows[2]["start_led"] == 110 and rows[2]["end_led"] == 149
    # ch_b must be gone (swallowed)
    async with db.execute("SELECT id FROM wled_channels WHERE id = ?", (ids["ch_b"],)) as cur:
        gone = await cur.fetchone()
    assert gone is None, "Case G: ch_b must be deleted (fully swallowed)"
    await db.close()


# ---------------------------------------------------------------------------
# Channel-N Numbering Invariant (D-10)
# ---------------------------------------------------------------------------


async def test_next_channel_name_monotonic():
    """Channel N never reuses freed N's after delete (D-10)."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split, delete_channel_with_cascade
    db = await _make_db()
    dev_id, _seed = await _seed_device(db, led_count=300)
    await db.execute("DELETE FROM wled_channels")
    await db.commit()
    c1 = await create_channel_with_split(db, dev_id, 0, 50)
    c2 = await create_channel_with_split(db, dev_id, 60, 100)
    assert c1["name"] == "Channel 1"
    assert c2["name"] == "Channel 2"
    await delete_channel_with_cascade(db, c1["id"])
    c3 = await create_channel_with_split(db, dev_id, 110, 150)
    assert c3["name"] == "Channel 3", "N MUST NOT recycle 1 after delete"
    await db.close()


async def test_next_channel_name_survives_rename():
    """Renaming a channel does not affect next_channel_n (R8 mitigation)."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, _seed = await _seed_device(db, led_count=300)
    await db.execute("DELETE FROM wled_channels")
    await db.commit()
    c1 = await create_channel_with_split(db, dev_id, 0, 50)
    # Rename Channel 1 -> TV Top
    await db.execute(
        "UPDATE wled_channels SET name = 'TV Top' WHERE id = ?", (c1["id"],)
    )
    await db.commit()
    c2 = await create_channel_with_split(db, dev_id, 60, 100)
    assert c2["name"] == "Channel 2", "next_channel_n must not be derived from name regex"
    await db.close()


async def test_seed_strip_does_not_consume_n():
    """Phase 17 seed 'Strip' is NOT a numbered channel — first paint becomes Channel 1."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, seed_id = await _seed_device(db, led_count=300)
    # Seed exists, next_channel_n is still 1 (D-10: seed does not increment).
    c1 = await create_channel_with_split(db, dev_id, 100, 200)
    assert c1["name"] == "Channel 1"
    await db.close()


# ---------------------------------------------------------------------------
# Boundary resize (WMAP-04)
# ---------------------------------------------------------------------------


async def test_resize_boundary_atomic_two_row_update():
    """resize_boundary updates both sides atomically (WMAP-04)."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split, resize_boundary
    db = await _make_db()
    dev_id, _seed = await _seed_device(db, led_count=300)
    await db.execute("DELETE FROM wled_channels")
    await db.commit()
    left = await create_channel_with_split(db, dev_id, 0, 99)
    right = await create_channel_with_split(db, dev_id, 100, 199)
    # Drag boundary from 100 -> 80
    await resize_boundary(db, left["id"], right["id"], 80)
    async with db.execute(
        "SELECT start_led, end_led FROM wled_channels WHERE id = ?", (left["id"],)
    ) as cur:
        l = await cur.fetchone()
    async with db.execute(
        "SELECT start_led, end_led FROM wled_channels WHERE id = ?", (right["id"],)
    ) as cur:
        r = await cur.fetchone()
    assert (l["start_led"], l["end_led"]) == (0, 79)
    assert (r["start_led"], r["end_led"]) == (80, 199)
    await db.close()


async def test_resize_boundary_min_1_led_clamp():
    """resize_boundary refuses to collapse either side below 1 LED."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split, resize_boundary
    db = await _make_db()
    dev_id, _seed = await _seed_device(db, led_count=300)
    await db.execute("DELETE FROM wled_channels")
    await db.commit()
    left = await create_channel_with_split(db, dev_id, 0, 99)
    right = await create_channel_with_split(db, dev_id, 100, 199)
    with pytest.raises(ValueError):
        await resize_boundary(db, left["id"], right["id"], 0)  # would collapse left to -1..0
    await db.close()


# ---------------------------------------------------------------------------
# Cascade delete (Success #5)
# ---------------------------------------------------------------------------


async def test_delete_channel_cascades_to_assignments():
    """DELETE channel removes orphan wled_light_assignments rows (Success #5)."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split, delete_channel_with_cascade
    db = await _make_db()
    dev_id, _seed = await _seed_device(db, led_count=300)
    await db.execute("DELETE FROM wled_channels")
    await db.commit()
    c = await create_channel_with_split(db, dev_id, 0, 99)
    await db.execute(
        "INSERT INTO wled_light_assignments (region_id, wled_channel_id, entertainment_config_id, orientation) "
        "VALUES ('region-x', ?, 'config-y', 'auto')",
        (c["id"],),
    )
    await db.commit()
    await delete_channel_with_cascade(db, c["id"])
    async with db.execute("SELECT COUNT(*) AS c FROM wled_light_assignments") as cur:
        row = await cur.fetchone()
    assert row["c"] == 0, "assignments must cascade to zero rows"
    async with db.execute("SELECT COUNT(*) AS c FROM wled_channels WHERE id = ?", (c["id"],)) as cur:
        row = await cur.fetchone()
    assert row["c"] == 0, "channel row must be gone"
    await db.close()


async def test_create_channel_rejects_invalid_range():
    """422-equivalent rejection at the service layer for start > end or out-of-range."""
    pytest.importorskip("services.wled_channels")
    from services.wled_channels import create_channel_with_split
    db = await _make_db()
    dev_id, _seed = await _seed_device(db, led_count=300)
    with pytest.raises(ValueError):
        await create_channel_with_split(db, dev_id, 100, 50)  # inverted
    with pytest.raises(ValueError):
        await create_channel_with_split(db, dev_id, -1, 50)
    with pytest.raises(ValueError):
        await create_channel_with_split(db, dev_id, 250, 300)  # 300 >= led_count
    await db.close()
