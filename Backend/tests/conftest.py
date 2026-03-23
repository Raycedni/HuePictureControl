import asyncio
import os
import pytest
import aiosqlite
from contextlib import asynccontextmanager
from fastapi.testclient import TestClient


@pytest.fixture
async def db():
    """In-memory aiosqlite connection with full schema initialized."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bridge_config (
            id INTEGER PRIMARY KEY,
            bridge_id TEXT NOT NULL,
            rid TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            username TEXT NOT NULL,
            hue_app_id TEXT NOT NULL,
            client_key TEXT NOT NULL,
            swversion INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT ''
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS entertainment_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            channel_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            id TEXT PRIMARY KEY,
            name TEXT,
            polygon TEXT NOT NULL,
            order_index INTEGER DEFAULT 0
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS light_assignments (
            region_id TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, channel_id, entertainment_config_id)
        )
    """)
    await conn.commit()
    yield conn
    await conn.close()


@pytest.fixture
def app_client(tmp_path):
    """FastAPI TestClient with lifespan using a temp file DB."""
    from database import init_db, close_db

    db_path = str(tmp_path / "test.db")

    @asynccontextmanager
    async def test_lifespan(app):
        conn = await init_db(db_path)
        app.state.db = conn
        yield
        await close_db(conn)

    from fastapi import FastAPI
    from routers.health import router as health_router

    test_app = FastAPI(lifespan=test_lifespan)
    test_app.include_router(health_router)

    with TestClient(test_app) as client:
        yield client
