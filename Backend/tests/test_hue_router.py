"""Integration tests for Backend/routers/hue.py"""
import pytest
from unittest.mock import patch, AsyncMock
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import init_db, close_db


def make_test_app(db_path: str) -> FastAPI:
    """Build a FastAPI test app with the hue router and a temp-file DB."""
    from routers.hue import router as hue_router

    @asynccontextmanager
    async def test_lifespan(app: FastAPI):
        conn = await init_db(db_path)
        app.state.db = conn
        yield
        await close_db(conn)

    app = FastAPI(lifespan=test_lifespan)
    app.include_router(hue_router)
    return app


# ---------------------------------------------------------------------------
# Pairing endpoint
# ---------------------------------------------------------------------------

class TestPairEndpoint:
    def test_pair_endpoint_success(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        app = make_test_app(db_path)

        pair_result = {"username": "test-user", "clientkey": "AABBCCDD"}
        meta_result = {
            "bridge_id": "bridge-abc",
            "rid": "rid-123",
            "hue_app_id": "app-456",
            "swversion": 1968100080,
            "name": "My Bridge",
        }

        with patch("routers.hue.pair_with_bridge", return_value=pair_result), \
             patch("routers.hue.fetch_bridge_metadata", return_value=meta_result):
            with TestClient(app) as client:
                response = client.post(
                    "/api/hue/pair", json={"bridge_ip": "192.168.1.100"}
                )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "paired"
        assert body["bridge_ip"] == "192.168.1.100"
        assert body["bridge_name"] == "My Bridge"

    def test_pair_endpoint_credentials_stored_in_db(self, tmp_path):
        """Verify that after a successful pair the credentials are in the DB."""
        import asyncio
        import aiosqlite

        db_path = str(tmp_path / "test.db")
        app = make_test_app(db_path)

        pair_result = {"username": "test-user", "clientkey": "AABBCCDD"}
        meta_result = {
            "bridge_id": "bridge-abc",
            "rid": "rid-123",
            "hue_app_id": "app-456",
            "swversion": 1968100080,
            "name": "My Bridge",
        }

        with patch("routers.hue.pair_with_bridge", return_value=pair_result), \
             patch("routers.hue.fetch_bridge_metadata", return_value=meta_result):
            with TestClient(app) as client:
                client.post("/api/hue/pair", json={"bridge_ip": "192.168.1.100"})

        async def read_db():
            conn = await aiosqlite.connect(db_path)
            conn.row_factory = aiosqlite.Row
            async with conn.execute("SELECT * FROM bridge_config WHERE id=1") as cursor:
                row = await cursor.fetchone()
            await conn.close()
            return row

        row = asyncio.get_event_loop().run_until_complete(read_db())
        assert row is not None
        assert row["username"] == "test-user"
        assert row["client_key"] == "AABBCCDD"
        assert row["ip_address"] == "192.168.1.100"
        assert row["bridge_id"] == "bridge-abc"
        assert row["name"] == "My Bridge"

    def test_pair_endpoint_link_button_error(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        app = make_test_app(db_path)

        with patch(
            "routers.hue.pair_with_bridge",
            side_effect=ValueError("link button not pressed"),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/api/hue/pair", json={"bridge_ip": "192.168.1.100"}
                )

        assert response.status_code == 403

    def test_pair_endpoint_bridge_unreachable(self, tmp_path):
        import requests as req_lib

        db_path = str(tmp_path / "test.db")
        app = make_test_app(db_path)

        with patch(
            "routers.hue.pair_with_bridge",
            side_effect=req_lib.exceptions.ConnectionError("unreachable"),
        ):
            with TestClient(app) as client:
                response = client.post(
                    "/api/hue/pair", json={"bridge_ip": "192.168.1.100"}
                )

        assert response.status_code == 502


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

class TestStatusEndpoint:
    def test_status_unpaired(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        app = make_test_app(db_path)

        with TestClient(app) as client:
            response = client.get("/api/hue/status")

        assert response.status_code == 200
        body = response.json()
        assert body["paired"] is False

    def test_status_paired(self, tmp_path):
        import asyncio
        import aiosqlite

        db_path = str(tmp_path / "test.db")

        # Pre-populate DB with credentials
        async def seed_db():
            conn = await aiosqlite.connect(db_path)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bridge_config (
                    id INTEGER PRIMARY KEY, bridge_id TEXT NOT NULL, rid TEXT NOT NULL,
                    ip_address TEXT NOT NULL, username TEXT NOT NULL,
                    hue_app_id TEXT NOT NULL, client_key TEXT NOT NULL,
                    swversion INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT ''
                )
            """)
            await conn.execute(
                "INSERT OR REPLACE INTO bridge_config "
                "(id, bridge_id, rid, ip_address, username, hue_app_id, client_key, swversion, name) "
                "VALUES (1, 'brid', 'rid', '192.168.1.100', 'user', 'app', 'key', 123, 'Bridge')"
            )
            await conn.commit()
            await conn.close()

        asyncio.get_event_loop().run_until_complete(seed_db())

        app = make_test_app(db_path)

        with TestClient(app) as client:
            response = client.get("/api/hue/status")

        assert response.status_code == 200
        body = response.json()
        assert body["paired"] is True
        assert body["bridge_ip"] == "192.168.1.100"
        assert body["bridge_name"] == "Bridge"


# ---------------------------------------------------------------------------
# Configs endpoint
# ---------------------------------------------------------------------------

class TestConfigsEndpoint:
    def test_list_configs_endpoint(self, tmp_path):
        import asyncio
        import aiosqlite

        db_path = str(tmp_path / "test.db")

        async def seed_db():
            conn = await aiosqlite.connect(db_path)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bridge_config (
                    id INTEGER PRIMARY KEY, bridge_id TEXT NOT NULL, rid TEXT NOT NULL,
                    ip_address TEXT NOT NULL, username TEXT NOT NULL,
                    hue_app_id TEXT NOT NULL, client_key TEXT NOT NULL,
                    swversion INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT ''
                )
            """)
            await conn.execute(
                "INSERT OR REPLACE INTO bridge_config "
                "(id, bridge_id, rid, ip_address, username, hue_app_id, client_key, swversion, name) "
                "VALUES (1, 'brid', 'rid', '192.168.1.100', 'user', 'app', 'key', 123, 'Bridge')"
            )
            await conn.commit()
            await conn.close()

        asyncio.get_event_loop().run_until_complete(seed_db())

        configs = [{"id": "cfg-1", "name": "TV", "status": "inactive", "channel_count": 2}]

        app = make_test_app(db_path)

        with patch("routers.hue.list_entertainment_configs", new=AsyncMock(return_value=configs)):
            with TestClient(app) as client:
                response = client.get("/api/hue/configs")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == "cfg-1"
        assert body[0]["channel_count"] == 2

    def test_list_configs_unpaired(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        app = make_test_app(db_path)

        with TestClient(app) as client:
            response = client.get("/api/hue/configs")

        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Lights endpoint
# ---------------------------------------------------------------------------

class TestLightsEndpoint:
    def test_list_lights_endpoint(self, tmp_path):
        import asyncio
        import aiosqlite

        db_path = str(tmp_path / "test.db")

        async def seed_db():
            conn = await aiosqlite.connect(db_path)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS bridge_config (
                    id INTEGER PRIMARY KEY, bridge_id TEXT NOT NULL, rid TEXT NOT NULL,
                    ip_address TEXT NOT NULL, username TEXT NOT NULL,
                    hue_app_id TEXT NOT NULL, client_key TEXT NOT NULL,
                    swversion INTEGER NOT NULL DEFAULT 0, name TEXT NOT NULL DEFAULT ''
                )
            """)
            await conn.execute(
                "INSERT OR REPLACE INTO bridge_config "
                "(id, bridge_id, rid, ip_address, username, hue_app_id, client_key, swversion, name) "
                "VALUES (1, 'brid', 'rid', '192.168.1.100', 'user', 'app', 'key', 123, 'Bridge')"
            )
            await conn.commit()
            await conn.close()

        asyncio.get_event_loop().run_until_complete(seed_db())

        lights = [{"id": "light-1", "name": "Strip", "type": "light"}]

        app = make_test_app(db_path)

        with patch("routers.hue.list_lights", new=AsyncMock(return_value=lights)):
            with TestClient(app) as client:
                response = client.get("/api/hue/lights")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == "light-1"
        assert body[0]["name"] == "Strip"
