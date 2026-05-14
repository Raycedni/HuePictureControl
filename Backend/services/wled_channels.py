"""Phase 19: WLED channel CRUD with atomic overlap auto-split.

This module owns the geometry that routes `routers/wled.py` channel endpoints
delegate to. Pure aiosqlite-coroutine helpers — no FastAPI dependency, no
HTTPException raises. The router translates ValueError -> HTTPException(422)
and "not found" -> HTTPException(404).

Decisions implemented:
  D-02 (overlap auto-split, cases A-G — see 19-RESEARCH.md §Overlap Auto-Split
       Algorithm for the case table).
  D-04 (delete cascades to wled_light_assignments).
  D-10 (Channel N monotonic counter per device; never recycles freed N's).
  D-03 (boundary resize atomically updates both adjacent channels).

Transactional model: every multi-statement helper wraps its body in
try / await db.commit() / except: await db.rollback(); raise. SQLite's
implicit transactions + aiosqlite's commit/rollback give us atomicity without
explicit BEGIN.

Cascade rule: SQLite FK enforcement is OFF in this project (see
database.py:92-97). Cascade-deletes are written in application code, mirroring
routers/wled.py:286-329.
"""
from __future__ import annotations

import logging
import uuid

import aiosqlite

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Channel-N invariant (D-10)
# ---------------------------------------------------------------------------


async def _next_channel_name(
    db: aiosqlite.Connection, device_id: str
) -> str:
    """Reserve the next 'Channel N' name for a device. Atomic read + increment.

    Uses the `next_channel_n` column added in Plan 19-03's idempotent
    migration. The Phase 17 seed 'Strip' channel does NOT increment this
    counter (seed is inserted via raw INSERT in routers/wled.py); first
    painted channel for a fresh device becomes 'Channel 1'.

    Survives both rename (counter lives in the column, not the name) and
    delete (counter never decrements — fulfils D-10's no-recycle rule).
    """
    async with db.execute(
        "SELECT next_channel_n FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"device {device_id!r} not found")
    try:
        n = int(row["next_channel_n"])
    except (TypeError, KeyError):
        n = int(row[0])
    await db.execute(
        "UPDATE wled_devices SET next_channel_n = next_channel_n + 1 WHERE id = ?",
        (device_id,),
    )
    return f"Channel {n}"


# ---------------------------------------------------------------------------
# Overlap auto-split (D-02 — cases A-G from 19-RESEARCH.md)
# ---------------------------------------------------------------------------


async def create_channel_with_split(
    db: aiosqlite.Connection,
    device_id: str,
    start_new: int,
    end_new: int,
) -> dict:
    """Insert a new channel and auto-split any overlaps. Single transaction.

    See 19-RESEARCH.md §Overlap Auto-Split Algorithm for the full case table.
    Identity rule: when a paint splits an existing channel into two halves,
    the LEFT half keeps the original (id, name); the right half gets a fresh
    id + the next 'Channel N' name. This matches the user's mental model.

    Raises ValueError on:
      - start_new > end_new
      - start_new < 0 OR end_new >= device.led_count
      - device_id not found
    """
    if start_new > end_new:
        raise ValueError(
            f"start_led ({start_new}) must be <= end_led ({end_new})"
        )

    # 1. Validate range against device LED count.
    async with db.execute(
        "SELECT led_count FROM wled_devices WHERE id = ?", (device_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise ValueError(f"device {device_id!r} not found")
    try:
        led_count = int(row["led_count"])
    except (TypeError, KeyError):
        led_count = int(row[0])
    if start_new < 0 or end_new >= led_count:
        raise ValueError(
            f"range [{start_new}, {end_new}] outside [0, {led_count - 1}]"
        )

    # 2. Load existing channels ordered by start_led for deterministic split.
    async with db.execute(
        "SELECT id, name, start_led, end_led FROM wled_channels "
        "WHERE device_id = ? ORDER BY start_led ASC",
        (device_id,),
    ) as cur:
        existing_rows = await cur.fetchall()

    # Convert rows to plain dicts so the planning logic doesn't depend on the
    # Row factory shape (existing code paths use both row_factory and raw tuples).
    existing: list[dict] = []
    for r in existing_rows:
        try:
            existing.append({
                "id": r["id"],
                "name": r["name"],
                "start_led": int(r["start_led"]),
                "end_led": int(r["end_led"]),
            })
        except (TypeError, KeyError):
            existing.append({
                "id": r[0], "name": r[1],
                "start_led": int(r[2]), "end_led": int(r[3]),
            })

    # 3. Categorise existing rows.
    #    NOTE: classification MUST happen before _next_channel_name is called
    #    so that a failure in classification does not waste a counter value.
    to_delete: list[str] = []
    to_update: list[tuple[str, int, int]] = []  # (id, new_start, new_end)
    to_insert_right_half: list[tuple[int, int]] = []  # (start, end)

    for ch in existing:
        s, e, cid = ch["start_led"], ch["end_led"], ch["id"]
        # Case A — no overlap: leave alone.
        if e < start_new or s > end_new:
            continue
        # Case G / part of F — fully swallowed: delete + cascade.
        if start_new <= s and e <= end_new:
            to_delete.append(cid)
            continue
        # Case B — strict interior split (new is fully inside existing).
        if s < start_new and end_new < e:
            # Left half keeps existing id+name; right half gets new id+name.
            to_update.append((cid, s, start_new - 1))
            to_insert_right_half.append((end_new + 1, e))
            continue
        # Case D — new crosses left boundary only (s is inside [start_new, end_new]).
        if start_new <= s <= end_new < e:
            to_update.append((cid, end_new + 1, e))
            continue
        # Case E — new crosses right boundary only (e is inside [start_new, end_new]).
        if s < start_new <= e <= end_new:
            to_update.append((cid, s, start_new - 1))
            continue
        # Defensive: should be unreachable given the cases above.
        logger.warning(
            "create_channel_with_split: unclassified overlap "
            "existing=(%d,%d) new=(%d,%d) — leaving alone",
            s, e, start_new, end_new,
        )

    # 4. Compute the new channel's name (increments next_channel_n counter).
    next_name = await _next_channel_name(db, device_id)

    # 5. Apply all mutations in a single transaction.
    try:
        # 5a. Delete swallowed channels + their assignments.
        for cid in to_delete:
            await db.execute(
                "DELETE FROM wled_light_assignments WHERE wled_channel_id = ?",
                (cid,),
            )
            await db.execute("DELETE FROM wled_channels WHERE id = ?", (cid,))

        # 5b. Resize survivors (left/right trim or Case B's left-half).
        for cid, ns, ne in to_update:
            await db.execute(
                "UPDATE wled_channels SET start_led = ?, end_led = ? WHERE id = ?",
                (ns, ne, cid),
            )

        # 5c. Insert right-half splits (Case B) with new ids + next-channel names.
        for rs, re_end in to_insert_right_half:
            right_id = str(uuid.uuid4())
            right_name = await _next_channel_name(db, device_id)
            await db.execute(
                "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) "
                "VALUES (?, ?, ?, ?, ?, '#ffffff')",
                (right_id, device_id, right_name, rs, re_end),
            )

        # 5d. Insert the painted range itself.
        new_channel_id = str(uuid.uuid4())
        await db.execute(
            "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) "
            "VALUES (?, ?, ?, ?, ?, '#ffffff')",
            (new_channel_id, device_id, next_name, start_new, end_new),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return {
        "id": new_channel_id,
        "device_id": device_id,
        "name": next_name,
        "start_led": start_new,
        "end_led": end_new,
    }


# ---------------------------------------------------------------------------
# Boundary resize (D-03)
# ---------------------------------------------------------------------------


async def resize_boundary(
    db: aiosqlite.Connection,
    left_channel_id: str,
    right_channel_id: str,
    boundary: int,
) -> None:
    """Atomically move the shared boundary between two adjacent channels.

    Both channels MUST currently be adjacent (left.end_led + 1 == right.start_led).
    Sets left.end_led = boundary - 1 and right.start_led = boundary in one
    transaction. Identity (id, name) is preserved for both rows.

    Raises ValueError if either channel is missing, the channels are not
    adjacent, or the new boundary would collapse either side below 1 LED.
    """
    async with db.execute(
        "SELECT id, start_led, end_led FROM wled_channels WHERE id = ?",
        (left_channel_id,),
    ) as cur:
        left = await cur.fetchone()
    async with db.execute(
        "SELECT id, start_led, end_led FROM wled_channels WHERE id = ?",
        (right_channel_id,),
    ) as cur:
        right = await cur.fetchone()
    if left is None or right is None:
        raise ValueError(
            f"channel not found: left={left_channel_id!r} right={right_channel_id!r}"
        )

    def _coerce(row, key: str, fallback_index: int) -> int:
        try:
            return int(row[key])
        except (TypeError, KeyError):
            return int(row[fallback_index])

    l_start = _coerce(left, "start_led", 1)
    l_end = _coerce(left, "end_led", 2)
    r_start = _coerce(right, "start_led", 1)
    r_end = _coerce(right, "end_led", 2)

    if l_end + 1 != r_start:
        raise ValueError(
            f"channels are not adjacent: left=({l_start}, {l_end}) "
            f"right=({r_start}, {r_end})"
        )

    # Clamp constraint: left zone must keep >= 1 LED (boundary >= l_start + 1)
    # AND right zone must keep >= 1 LED (boundary <= r_end).
    if boundary < l_start + 1 or boundary > r_end:
        raise ValueError(
            f"boundary {boundary} would collapse a zone "
            f"(must be in [{l_start + 1}, {r_end}])"
        )

    try:
        await db.execute(
            "UPDATE wled_channels SET end_led = ? WHERE id = ?",
            (boundary - 1, left_channel_id),
        )
        await db.execute(
            "UPDATE wled_channels SET start_led = ? WHERE id = ?",
            (boundary, right_channel_id),
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise


# ---------------------------------------------------------------------------
# Delete with cascade (D-04)
# ---------------------------------------------------------------------------


async def delete_channel_with_cascade(
    db: aiosqlite.Connection,
    channel_id: str,
) -> None:
    """Delete a channel and cascade to wled_light_assignments.

    Mirrors the device-delete cascade pattern at routers/wled.py:286-329 but
    scoped to a single channel id. Single transaction.

    Raises ValueError if the channel does not exist.
    """
    async with db.execute(
        "SELECT id FROM wled_channels WHERE id = ?", (channel_id,)
    ) as cur:
        existing = await cur.fetchone()
    if existing is None:
        raise ValueError(f"channel {channel_id!r} not found")

    try:
        await db.execute(
            "DELETE FROM wled_light_assignments WHERE wled_channel_id = ?",
            (channel_id,),
        )
        await db.execute(
            "DELETE FROM wled_channels WHERE id = ?", (channel_id,)
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
