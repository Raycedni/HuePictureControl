"""Auto-mapping service: converts Hue entertainment channel positions into
normalized [0..1] screen-region polygons and persists them to SQLite.

Exports:
    channel_pos_to_screen  -- Map Hue x/z coordinates to normalized screen coords
    make_square_polygon    -- Build a clamped 4-point rectangle centered at (cx, cy)
    persist_channel_regions -- Write regions + light_assignments to DB
    auto_map_entertainment_config -- Fetch channels from bridge then persist regions
"""
import json
import logging

import aiosqlite

from services.hue_client import (
    fetch_entertainment_config_channels,
    resolve_entertainment_rid_to_light_id,
)

logger = logging.getLogger(__name__)


def channel_pos_to_screen(x: float, z: float) -> tuple[float, float]:
    """Map Hue entertainment channel position to normalized screen coordinates.

    Hue uses a right-handed 3D coordinate system where:
    - x ranges from -1 (left) to +1 (right)
    - z ranges from -1 (front/top) to +1 (back/bottom)

    This maps linearly to [0..1] screen space.

    Args:
        x: Hue x-axis position in [-1, 1].
        z: Hue z-axis position in [-1, 1].

    Returns:
        Tuple (screen_x, screen_y), each clamped to [0.0, 1.0].
    """
    screen_x = (x + 1.0) / 2.0
    screen_y = (z + 1.0) / 2.0
    screen_x = max(0.0, min(1.0, screen_x))
    screen_y = max(0.0, min(1.0, screen_y))
    return (screen_x, screen_y)


def make_square_polygon(cx: float, cy: float, half: float = 0.10) -> list[list[float]]:
    """Build a 4-point square polygon centered at (cx, cy) with given half-width.

    All coordinates are clamped to [0.0, 1.0].

    Args:
        cx: Center x coordinate (normalized [0..1]).
        cy: Center y coordinate (normalized [0..1]).
        half: Half the side length of the square (default 0.10).

    Returns:
        List of four [x, y] points: top-left, top-right, bottom-right, bottom-left.
        Points are ordered clockwise starting from top-left.
    """
    def clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    left = clamp(cx - half)
    right = clamp(cx + half)
    top = clamp(cy - half)
    bottom = clamp(cy + half)

    return [
        [left, top],
        [right, top],
        [right, bottom],
        [left, bottom],
    ]


async def persist_channel_regions(
    db: aiosqlite.Connection,
    config_id: str,
    channels: list[dict],
    ent_rid_to_light_id: dict[str, str] | None = None,
    half: float = 0.10,
) -> int:
    """Write normalized polygon regions and light assignments to SQLite.

    Uses INSERT OR REPLACE for idempotency — re-running with the same
    config_id and channels will overwrite existing rows without creating
    duplicates.

    Region IDs are deterministic: "auto:{config_id}:{channel_id}"

    Args:
        db: Open aiosqlite connection with regions and light_assignments tables.
        config_id: Entertainment configuration UUID from the Hue Bridge.
        channels: List of dicts with channel_id (int), position ({x, y, z}),
            and service_rid (str|None).
        ent_rid_to_light_id: Mapping from entertainment service_rid to light
            resource id, used to populate regions.light_id for streaming.
        half: Half-width of the generated square polygon (default 0.10).

    Returns:
        Number of regions written.
    """
    if ent_rid_to_light_id is None:
        ent_rid_to_light_id = {}

    count = 0
    for ch in channels:
        channel_id = ch["channel_id"]
        pos = ch.get("position", {"x": 0.0, "y": 0.0, "z": 0.0})
        sx, sy = channel_pos_to_screen(pos.get("x", 0.0), pos.get("z", 0.0))
        polygon = make_square_polygon(sx, sy, half)
        region_id = f"auto:{config_id}:{channel_id}"
        region_name = f"Channel {channel_id}"

        service_rid = ch.get("service_rid")
        light_id = ent_rid_to_light_id.get(service_rid) if service_rid else None

        await db.execute(
            """
            INSERT OR REPLACE INTO regions (id, name, polygon, order_index, light_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (region_id, region_name, json.dumps(polygon), channel_id, light_id),
        )

        await db.execute(
            """
            INSERT OR REPLACE INTO light_assignments
                (region_id, channel_id, entertainment_config_id)
            VALUES (?, ?, ?)
            """,
            (region_id, channel_id, config_id),
        )

        count += 1

    await db.commit()
    logger.info(
        "Auto-mapped %d channels for entertainment config %s", count, config_id
    )
    return count


async def auto_map_entertainment_config(
    db: aiosqlite.Connection,
    bridge_ip: str,
    username: str,
    config_id: str,
    polygon_half: float = 0.10,
) -> int:
    """Fetch entertainment config channels from the bridge and persist as regions.

    Args:
        db: Open aiosqlite connection.
        bridge_ip: IP address of the Hue Bridge.
        username: Application key obtained during pairing.
        config_id: UUID of the entertainment configuration to map.
        polygon_half: Half-width of the generated square polygons (default 0.10).

    Returns:
        Number of regions created/updated.

    Raises:
        ValueError: If the entertainment config has no channels.
        httpx.HTTPStatusError: If the bridge returns a non-2xx response.
    """
    channels = await fetch_entertainment_config_channels(bridge_ip, username, config_id)

    if not channels:
        raise ValueError(
            f"Entertainment config '{config_id}' has empty channels list — cannot auto-map"
        )

    ent_rid_to_light_id = await resolve_entertainment_rid_to_light_id(
        bridge_ip, username
    )

    return await persist_channel_regions(
        db, config_id, channels, ent_rid_to_light_id, polygon_half
    )
