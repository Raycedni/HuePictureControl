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
    # quick-task 260516-kra: global KV settings table. Same idempotent
    # CREATE/INSERT-OR-IGNORE pattern bridge_config / known_cameras use; NOT
    # the PRAGMA user_version guard (that one is reserved for Phase 19.1
    # schema upgrades). On a fresh DB the INSERT seeds the default 0.0; on
    # an upgrade the INSERT OR IGNORE keeps the user's persisted value.
    await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    await db.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        ("brightness_cutoff_threshold", "0.0"),
    )
    # quick-task 260704-iss: color vibrancy + saturation boost settings,
    # same idempotent seed pattern as brightness_cutoff_threshold above.
    await db.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        ("color_vibrancy", "0.0"),
    )
    await db.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        ("saturation_boost", "0.0"),
    )
    # quick-task 260704-w88: HDR input toggle (0.0 off / 1.0 on), same
    # idempotent seed pattern as color_vibrancy / saturation_boost above.
    await db.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
        ("hdr_input", "0.0"),
    )
    # Phase 17 D-07: WLED device table. wled_devices stays (Phase 19.1 keeps it
    # unchanged). The Phase 17 wled_channels + Phase 17/19 wled_light_assignments
    # are dropped + rewritten below under the PRAGMA user_version guard (D-20).
    # FK clauses are documentation-as-code only — SQLite does not enforce them
    # without `PRAGMA foreign_keys = ON`, which the project intentionally omits
    # (per 17-RESEARCH.md A5). Cascade deletes are implemented in router code.
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

    # Phase 19 (Channel-N numbering invariant per 19-RESEARCH.md): per-device
    # monotonic counter. Phase 19.1 D-10 Claude's Discretion: keep the column
    # as a dormant idempotent ALTER even though channel naming is gone — it's
    # harmless and avoids any extra migration footprint.
    try:
        await db.execute(
            "ALTER TABLE wled_devices "
            "ADD COLUMN next_channel_n INTEGER NOT NULL DEFAULT 1"
        )
        await db.commit()
    except Exception:
        # Column already exists — safe to ignore OperationalError.
        pass

    # =========================================================================
    # Phase 19.1: drop+recreate upgrade from Phase 19 paint-managed wled_channels
    # to refresh-mirrored wled_seg_cache. One-shot — gated by PRAGMA user_version
    # so the drop fires exactly once per database file regardless of restart count.
    # See .planning/phases/19.1-wled-segment-sync/19.1-RESEARCH.md §"SQLite Upgrade
    # Guard" for the full rationale (D-12, D-13, D-20).
    # =========================================================================
    PHASE_19_1_USER_VERSION = 1

    async with db.execute("PRAGMA user_version") as cur:
        version_row = await cur.fetchone()
    current_version = int(version_row[0]) if version_row else 0

    if current_version < PHASE_19_1_USER_VERSION:
        # D-20: hard-drop Phase 19 tables. DROP TABLE IF EXISTS is idempotent on
        # its own; the version gate guarantees we never re-drop a freshly-created
        # table on subsequent restarts.
        await db.execute("DROP TABLE IF EXISTS wled_channels")
        await db.execute("DROP TABLE IF EXISTS wled_light_assignments")
        # D-13: recreate wled_light_assignments with composite
        # (region_id, wled_device_id, seg_index, entertainment_config_id) PK.
        await db.execute("""
            CREATE TABLE wled_light_assignments (
                region_id TEXT NOT NULL,
                wled_device_id TEXT NOT NULL,
                seg_index INTEGER NOT NULL,
                entertainment_config_id TEXT NOT NULL,
                orientation TEXT NOT NULL DEFAULT 'auto',
                PRIMARY KEY (region_id, wled_device_id, seg_index, entertainment_config_id)
            )
        """)
        # D-12: new cache table mirroring WLED's /json/state seg[] per device.
        # stop_led is INCLUSIVE (converted from WLED's exclusive seg.stop at
        # parse boundary in services.wled_client.fetch_wled_state).
        await db.execute("""
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
        # Bump user_version LAST so a mid-migration failure does not mark the
        # upgrade complete; the guard will fire again on next boot.
        await db.execute(f"PRAGMA user_version = {PHASE_19_1_USER_VERSION}")
        await db.commit()
    else:
        # Already migrated. Defensive idempotent CREATE so a fresh-install
        # database (no prior Phase 19 tables) still gets both tables on first
        # boot at user_version=1 — and the second-call no-op path stays safe.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wled_light_assignments (
                region_id TEXT NOT NULL,
                wled_device_id TEXT NOT NULL,
                seg_index INTEGER NOT NULL,
                entertainment_config_id TEXT NOT NULL,
                orientation TEXT NOT NULL DEFAULT 'auto',
                PRIMARY KEY (region_id, wled_device_id, seg_index, entertainment_config_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS wled_seg_cache (
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
        await db.commit()

    await db.commit()
    return db


async def close_db(db: aiosqlite.Connection) -> None:
    """Close the database connection."""
    await db.close()
