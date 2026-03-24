"""Unit tests for the auto-mapping service.

Tests cover:
- channel_pos_to_screen pure function (boundary values)
- make_square_polygon center, edge, and corner cases
- persist_channel_regions persistence and idempotency
- auto_map_entertainment_config ValueError on empty channels
"""
import json
import pytest
import aiosqlite

from database import init_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """In-memory aiosqlite connection with full schema initialized."""
    conn = await init_db(":memory:")
    yield conn
    await conn.close()


# ---------------------------------------------------------------------------
# channel_pos_to_screen tests
# ---------------------------------------------------------------------------


class TestChannelPosToScreen:
    def test_negative_corner_maps_to_zero(self):
        """channel_pos_to_screen(x=-1, z=-1) returns (0.0, 0.0)."""
        from services.auto_mapping import channel_pos_to_screen

        result = channel_pos_to_screen(x=-1.0, z=-1.0)
        assert result == (0.0, 0.0)

    def test_positive_corner_maps_to_one(self):
        """channel_pos_to_screen(x=1, z=1) returns (1.0, 1.0)."""
        from services.auto_mapping import channel_pos_to_screen

        result = channel_pos_to_screen(x=1.0, z=1.0)
        assert result == (1.0, 1.0)

    def test_center_maps_to_half(self):
        """channel_pos_to_screen(x=0, z=0) returns (0.5, 0.5)."""
        from services.auto_mapping import channel_pos_to_screen

        result = channel_pos_to_screen(x=0.0, z=0.0)
        assert result == (0.5, 0.5)

    def test_clamps_below_zero(self):
        """Values below -1 are clamped to 0.0."""
        from services.auto_mapping import channel_pos_to_screen

        sx, sy = channel_pos_to_screen(x=-2.0, z=-2.0)
        assert sx == 0.0
        assert sy == 0.0

    def test_clamps_above_one(self):
        """Values above 1 are clamped to 1.0."""
        from services.auto_mapping import channel_pos_to_screen

        sx, sy = channel_pos_to_screen(x=2.0, z=2.0)
        assert sx == 1.0
        assert sy == 1.0


# ---------------------------------------------------------------------------
# make_square_polygon tests
# ---------------------------------------------------------------------------


class TestMakeSquarePolygon:
    def test_center_polygon(self):
        """make_square_polygon(0.5, 0.5, 0.10) returns four corners at ±0.10."""
        from services.auto_mapping import make_square_polygon

        poly = make_square_polygon(0.5, 0.5, 0.10)
        assert poly == [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]

    def test_top_left_corner_clamped(self):
        """make_square_polygon(0.0, 0.0, 0.10) clamps to top-left origin."""
        from services.auto_mapping import make_square_polygon

        poly = make_square_polygon(0.0, 0.0, 0.10)
        assert poly == [[0.0, 0.0], [0.1, 0.0], [0.1, 0.1], [0.0, 0.1]]

    def test_bottom_right_corner_clamped(self):
        """make_square_polygon(1.0, 1.0, 0.10) clamps to bottom-right boundary."""
        from services.auto_mapping import make_square_polygon

        poly = make_square_polygon(1.0, 1.0, 0.10)
        assert poly == [[0.9, 0.9], [1.0, 0.9], [1.0, 1.0], [0.9, 1.0]]

    def test_all_coords_in_range(self):
        """All polygon coordinates are within [0, 1] range (REGN-04)."""
        from services.auto_mapping import make_square_polygon

        for cx in [0.0, 0.25, 0.5, 0.75, 1.0]:
            for cy in [0.0, 0.25, 0.5, 0.75, 1.0]:
                poly = make_square_polygon(cx, cy, 0.15)
                for point in poly:
                    assert 0.0 <= point[0] <= 1.0, f"x={point[0]} out of range for cx={cx}"
                    assert 0.0 <= point[1] <= 1.0, f"y={point[1]} out of range for cy={cy}"

    def test_returns_four_points(self):
        """Polygon always has exactly 4 points."""
        from services.auto_mapping import make_square_polygon

        poly = make_square_polygon(0.5, 0.5, 0.10)
        assert len(poly) == 4


# ---------------------------------------------------------------------------
# persist_channel_regions tests
# ---------------------------------------------------------------------------

MOCK_CHANNELS = [
    {"channel_id": 0, "position": {"x": -0.5, "y": 0.0, "z": -0.5}},
    {"channel_id": 1, "position": {"x": 0.5, "y": 0.0, "z": 0.5}},
]


class TestPersistChannelRegions:
    async def test_writes_regions_rows(self, db):
        """persist_channel_regions inserts rows into regions table."""
        from services.auto_mapping import persist_channel_regions

        count = await persist_channel_regions(db, "cfg-001", MOCK_CHANNELS)
        assert count == 2

        async with db.execute("SELECT COUNT(*) FROM regions") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2

    async def test_writes_light_assignments_rows(self, db):
        """persist_channel_regions inserts rows into light_assignments table."""
        from services.auto_mapping import persist_channel_regions

        await persist_channel_regions(db, "cfg-001", MOCK_CHANNELS)

        async with db.execute("SELECT COUNT(*) FROM light_assignments") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2

    async def test_deterministic_region_ids(self, db):
        """Region IDs follow the 'auto:{config_id}:{channel_id}' pattern."""
        from services.auto_mapping import persist_channel_regions

        await persist_channel_regions(db, "cfg-001", MOCK_CHANNELS)

        async with db.execute("SELECT id FROM regions ORDER BY id") as cursor:
            rows = await cursor.fetchall()

        ids = [row[0] for row in rows]
        assert "auto:cfg-001:0" in ids
        assert "auto:cfg-001:1" in ids

    async def test_idempotent_on_rerun(self, db):
        """Calling persist_channel_regions twice produces same row count (idempotent)."""
        from services.auto_mapping import persist_channel_regions

        await persist_channel_regions(db, "cfg-001", MOCK_CHANNELS)
        await persist_channel_regions(db, "cfg-001", MOCK_CHANNELS)

        async with db.execute("SELECT COUNT(*) FROM regions") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2

        async with db.execute("SELECT COUNT(*) FROM light_assignments") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2

    async def test_polygon_coordinates_in_range(self, db):
        """All stored polygon coordinates are clamped to [0..1] (REGN-04)."""
        from services.auto_mapping import persist_channel_regions

        await persist_channel_regions(db, "cfg-001", MOCK_CHANNELS)

        async with db.execute("SELECT polygon FROM regions") as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            polygon = json.loads(row[0])
            for point in polygon:
                assert 0.0 <= point[0] <= 1.0
                assert 0.0 <= point[1] <= 1.0

    async def test_persistence_after_reopen(self, tmp_path):
        """Regions persist after closing and reopening the database (REGN-05)."""
        from services.auto_mapping import persist_channel_regions

        db_path = str(tmp_path / "persist_test.db")

        # Write data
        conn1 = await init_db(db_path)
        await persist_channel_regions(conn1, "cfg-001", MOCK_CHANNELS)
        await conn1.close()

        # Reopen and verify
        conn2 = await init_db(db_path)
        async with conn2.execute("SELECT COUNT(*) FROM regions") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2

        async with conn2.execute("SELECT COUNT(*) FROM light_assignments") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2

        await conn2.close()


# ---------------------------------------------------------------------------
# auto_map_entertainment_config tests
# ---------------------------------------------------------------------------


class TestAutoMapEntertainmentConfig:
    async def test_raises_value_error_on_empty_channels(self, db):
        """auto_map_entertainment_config raises ValueError when channels list is empty."""
        from services.auto_mapping import auto_map_entertainment_config
        from unittest.mock import AsyncMock, patch

        with patch(
            "services.auto_mapping.fetch_entertainment_config_channels",
            new=AsyncMock(return_value=[]),
        ):
            with pytest.raises(ValueError, match="empty"):
                await auto_map_entertainment_config(
                    db, "192.168.1.1", "test-user", "cfg-001"
                )

    async def test_calls_persist_on_valid_channels(self, db):
        """auto_map_entertainment_config writes regions when channels are returned."""
        from services.auto_mapping import auto_map_entertainment_config
        from unittest.mock import AsyncMock, patch

        with patch(
            "services.auto_mapping.fetch_entertainment_config_channels",
            new=AsyncMock(return_value=MOCK_CHANNELS),
        ):
            count = await auto_map_entertainment_config(
                db, "192.168.1.1", "test-user", "cfg-001"
            )

        assert count == 2

        async with db.execute("SELECT COUNT(*) FROM regions") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2
