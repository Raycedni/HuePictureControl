import pytest
import aiosqlite
from database import init_db, close_db


async def test_db_tables_created(db):
    """All 4 required tables exist after schema initialization."""
    async with db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cursor:
        rows = await cursor.fetchall()
    table_names = {row["name"] for row in rows}
    assert "bridge_config" in table_names
    assert "entertainment_configs" in table_names
    assert "regions" in table_names
    assert "light_assignments" in table_names


async def test_credentials_persist(db):
    """Insert a bridge_config row, query it back, assert fields match."""
    await db.execute(
        """
        INSERT INTO bridge_config
            (bridge_id, rid, ip_address, username, hue_app_id, client_key, swversion, name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("bridge-abc", "rid-123", "192.168.1.1", "user-key", "app-id", "psk-key", 1234, "My Bridge"),
    )
    await db.commit()

    async with db.execute(
        "SELECT * FROM bridge_config WHERE bridge_id = ?", ("bridge-abc",)
    ) as cursor:
        row = await cursor.fetchone()

    assert row is not None
    assert row["bridge_id"] == "bridge-abc"
    assert row["rid"] == "rid-123"
    assert row["ip_address"] == "192.168.1.1"
    assert row["username"] == "user-key"
    assert row["client_key"] == "psk-key"
    assert row["swversion"] == 1234
    assert row["name"] == "My Bridge"


async def test_db_file_created(tmp_path):
    """Database file is created on disk after init_db is called."""
    db_path = str(tmp_path / "test.db")
    conn = await init_db(db_path)
    await close_db(conn)
    assert (tmp_path / "test.db").exists()


def test_health_endpoint(app_client):
    """GET /api/health returns 200 with expected JSON body."""
    response = app_client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


async def test_known_cameras_table_created():
    """known_cameras table is created by init_db()."""
    conn = await init_db(":memory:")
    try:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='known_cameras'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "known_cameras table was not created"
    finally:
        await close_db(conn)


async def test_camera_assignments_table_created():
    """camera_assignments table is created by init_db(). Per CAMA-01."""
    conn = await init_db(":memory:")
    try:
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='camera_assignments'"
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None, "camera_assignments table was not created"
    finally:
        await close_db(conn)


async def test_camera_assignment_persists(tmp_path):
    """Camera assignment row persists across DB close and reopen. Per CAMA-02."""
    db_path = str(tmp_path / "test_persist.db")

    conn = await init_db(db_path)
    await conn.execute(
        "INSERT INTO camera_assignments (entertainment_config_id, camera_stable_id, camera_name) "
        "VALUES (?, ?, ?)",
        ("cfg-1", "1234:5678", "Test Cam"),
    )
    await conn.commit()
    await close_db(conn)

    # Reopen and verify the row survived
    conn2 = await init_db(db_path)
    try:
        async with conn2.execute(
            "SELECT * FROM camera_assignments WHERE entertainment_config_id = ?",
            ("cfg-1",),
        ) as cursor:
            row = await cursor.fetchone()
        assert row is not None
        assert row["entertainment_config_id"] == "cfg-1"
        assert row["camera_stable_id"] == "1234:5678"
        assert row["camera_name"] == "Test Cam"
    finally:
        await close_db(conn2)


async def test_known_cameras_upsert(db):
    """INSERT OR REPLACE updates existing known_cameras row. Per D-09."""
    await db.execute(
        "INSERT INTO known_cameras (stable_id, display_name, last_seen_at, last_device_path) "
        "VALUES (?, ?, ?, ?)",
        ("1234:5678:ABC", "My Capture Card", "2026-01-01T00:00:00Z", "/dev/video0"),
    )
    await db.commit()

    # Upsert with updated fields
    await db.execute(
        "INSERT OR REPLACE INTO known_cameras (stable_id, display_name, last_seen_at, last_device_path) "
        "VALUES (?, ?, ?, ?)",
        ("1234:5678:ABC", "My Capture Card", "2026-04-03T12:00:00Z", "/dev/video2"),
    )
    await db.commit()

    async with db.execute(
        "SELECT * FROM known_cameras WHERE stable_id = ?", ("1234:5678:ABC",)
    ) as cursor:
        row = await cursor.fetchone()

    assert row is not None
    assert row["last_seen_at"] == "2026-04-03T12:00:00Z"
    assert row["last_device_path"] == "/dev/video2"


async def test_fallback_contract_documented(db):
    """Zones with no assignment have no row in camera_assignments. Per CAMA-03."""
    # Ensure no rows exist for an entertainment config with no assignment
    async with db.execute(
        "SELECT * FROM camera_assignments WHERE entertainment_config_id = ?",
        ("cfg-unassigned",),
    ) as cursor:
        row = await cursor.fetchone()

    assert row is None, "Expected no row for unassigned zone (fallback handled at API layer)"
