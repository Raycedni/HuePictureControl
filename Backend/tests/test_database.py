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
