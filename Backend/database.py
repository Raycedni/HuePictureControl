import os
import aiosqlite

_DEFAULT_DB = os.path.join(os.path.dirname(__file__), "data", "config.db")
DATABASE_PATH = os.getenv("DATABASE_PATH", _DEFAULT_DB)


async def init_db(db_path: str = DATABASE_PATH) -> aiosqlite.Connection:
    """Open a database connection, create schema, return the connection."""
    # Only create directories for file-based databases, not in-memory ones
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
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
    # Migration: add entertainment_config_id to regions for zone-camera join (Phase 9, D-08)
    try:
        await db.execute("ALTER TABLE regions ADD COLUMN entertainment_config_id TEXT")
        await db.commit()
    except Exception:
        # Column already exists — safe to ignore
        pass
    await db.execute("""
        CREATE TABLE IF NOT EXISTS light_assignments (
            region_id TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, channel_id, entertainment_config_id)
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS known_cameras (
            stable_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            last_seen_at TEXT,
            last_device_path TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS camera_assignments (
            entertainment_config_id TEXT PRIMARY KEY,
            camera_stable_id TEXT NOT NULL,
            camera_name TEXT NOT NULL
        )
    """)
    await db.commit()
    return db


async def close_db(db: aiosqlite.Connection) -> None:
    """Close the database connection."""
    await db.close()
