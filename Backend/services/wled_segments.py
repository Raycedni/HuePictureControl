"""Phase 19.1: WLED segment-cache reconciliation transaction.

Owns the DELETE/INSERT-then-cascade write that mirrors a device's
``/json/state seg[]`` into ``wled_seg_cache`` and hard-deletes orphan
``wled_light_assignments`` rows pointing at vanished segments
(D-14, D-15, D-19, D-21).

Transactional model: implicit aiosqlite transaction, explicit ``db.commit()``,
``try``/``except`` with ``db.rollback()`` on failure. Pattern mirrors
``services/wled_channels.py`` (to be removed in Plan 08). Cascade-deletes run
in application code because SQLite FK enforcement is OFF in this project
(see ``database.py`` comment at lines 92-97).

Network I/O does NOT live here. Caller (the refresh endpoint in
``routers/wled.py``) must call ``services.wled_client.fetch_wled_state`` first,
translate httpx/ValueError exceptions to HTTP responses, and only then call
``reconcile_segments`` with a pre-parsed list. See 19.1-RESEARCH.md
§"Reconciliation Transaction" → "Why NOT wrap the fetch in the transaction".
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiosqlite

logger = logging.getLogger(__name__)


async def reconcile_segments(
    db: aiosqlite.Connection,
    device_id: str,
    segments: list[dict],
) -> int:
    """Replace ``wled_seg_cache`` for ``device_id`` with ``segments[]``.

    Cascade-delete any ``wled_light_assignments`` rows for this device whose
    ``seg_index`` is not in the new segment set. Single transaction.

    Args:
        db: An open aiosqlite connection.
        device_id: Primary key of the WLED device in ``wled_devices``.
        segments: Pre-parsed list of dicts. Each must contain keys ``seg_index``
            (int), ``start_led`` (int), ``stop_led`` (int, INCLUSIVE), and
            optionally ``name`` (str | None). Produced by
            ``services.wled_client.fetch_wled_state``.

    Returns:
        Count of dropped ``wled_light_assignments`` rows (D-17 response field
        ``dropped_assignments``). Always ``>= 0``.

    Raises:
        Whatever ``aiosqlite`` raises on constraint violation or DB error. The
        transaction is rolled back before re-raising; no partial-write state
        survives.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        # Step 1 (D-14.1, D-19): wipe cache for this device.
        await db.execute(
            "DELETE FROM wled_seg_cache WHERE device_id = ?",
            (device_id,),
        )
        # Step 2 (D-14.2): insert new rows. Guard against empty list so
        # executemany is never called with zero rows (D-15 N->0 edge case
        # — cascade still runs in Step 3).
        rows = [
            (
                device_id,
                int(s["seg_index"]),
                int(s["start_led"]),
                int(s["stop_led"]),
                s.get("name"),
                now_iso,
            )
            for s in segments
        ]
        if rows:
            await db.executemany(
                "INSERT INTO wled_seg_cache "
                "(device_id, seg_index, start_led, stop_led, name, refreshed_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
        # Step 3 (D-14.3, D-15, D-21): cascade-delete orphan assignments.
        # NOT IN against the freshly-written cache works because steps 1+2
        # are already serialized inside this implicit transaction; the
        # sub-SELECT sees the new rows written in Step 2, not the rows that
        # existed before Step 1.
        cur = await db.execute(
            "DELETE FROM wled_light_assignments "
            "WHERE wled_device_id = ? AND seg_index NOT IN ("
            "    SELECT seg_index FROM wled_seg_cache WHERE device_id = ?"
            ")",
            (device_id, device_id),
        )
        dropped = cur.rowcount or 0
        await db.commit()
        logger.info(
            "reconcile_segments device=%s segments=%d dropped_assignments=%d",
            device_id, len(rows), dropped,
        )
        return dropped
    except Exception:
        await db.rollback()
        logger.exception("reconcile_segments failed for device=%s", device_id)
        raise
