import os
import aiosqlite

DATABASE_PATH = os.getenv("DATABASE_PATH", "/app/data/config.db")


async def init_db(db_path: str = DATABASE_PATH) -> aiosqlite.Connection:
    """Open a database connection, create schema, return the connection."""
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row

    await db.execute("""
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
    await db.execute("""
        CREATE TABLE IF NOT EXISTS entertainment_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            channel_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            id TEXT PRIMARY KEY,
            name TEXT,
            polygon TEXT NOT NULL,
            order_index INTEGER DEFAULT 0,
            light_id TEXT
        )
    """)
    # Migration: add light_id column to existing databases that predate this column
    try:
        await db.execute("ALTER TABLE regions ADD COLUMN light_id TEXT")
        await db.commit()
    except Exception:
        # Column already exists — safe to ignore OperationalError
        pass
    await db.execute("""
        CREATE TABLE IF NOT EXISTS light_assignments (
            region_id TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, channel_id, entertainment_config_id)
        )
    """)
    await db.commit()
    return db


async def close_db(db: aiosqlite.Connection) -> None:
    """Close the database connection."""
    await db.close()
