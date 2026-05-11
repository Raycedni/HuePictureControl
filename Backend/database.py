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
    await db.execute("""
        CREATE TABLE IF NOT EXISTS camera_last_zone (
            camera_stable_id TEXT PRIMARY KEY,
            entertainment_config_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # Phase 18 D-04: HA selection state (single-row, lazy-created).
    # No eager INSERT seed — D-05 mandates lazy row creation by the first
    # PUT /api/ha/zone or PUT /api/ha/camera via ON CONFLICT DO UPDATE.
    await db.execute("""
        CREATE TABLE IF NOT EXISTS ha_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_config_id TEXT,
            active_camera_stable_id TEXT,
            updated_at TEXT
        )
    """)
    # Phase 17 D-07: WLED device + channel + region-assignment schema.
    # FK clauses are documentation-as-code only — SQLite does not enforce them
    # without `PRAGMA foreign_keys = ON`, which the project intentionally omits
    # (per 17-RESEARCH.md A5). Cascade deletes are implemented in router code
    # (Plan 17-07).
    await db.execute("""
        CREATE TABLE IF NOT EXISTS wled_devices (
            id TEXT PRIMARY KEY,
            ip TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            led_count INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS wled_channels (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            name TEXT NOT NULL,
            start_led INTEGER NOT NULL,
            end_led INTEGER NOT NULL,
            color TEXT NOT NULL DEFAULT '#ffffff',
            FOREIGN KEY (device_id) REFERENCES wled_devices(id) ON DELETE CASCADE
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS wled_light_assignments (
            region_id TEXT NOT NULL,
            wled_channel_id TEXT NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id),
            FOREIGN KEY (wled_channel_id) REFERENCES wled_channels(id) ON DELETE CASCADE
        )
    """)
    await db.commit()
    return db


async def close_db(db: aiosqlite.Connection) -> None:
    """Close the database connection."""
    await db.close()
