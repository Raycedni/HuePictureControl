"""Phase 19 end-to-end smoke: paint → assign → orientation → restart → persistence.

Two coverage goals:
  1. test_persistence: prove channels + assignments + per-region orientation
     survive a DB connection reopen (Success #4).
  2. test_paint_assign_stream_smoke: prove the create-with-split + region
     resolution + sub_sample_gradient orientation override are all wired up
     end-to-end.

The streaming half of #2 uses a synthetic frame + the StreamingCoordinator's
private helpers without spinning up a real Hue/WLED sink.
"""
import uuid

import aiosqlite
import numpy as np
import pytest


async def test_persistence(tmp_path):
    """Painted channels + assignments + orientation survive a DB reopen."""
    pytest.importorskip("services.wled_channels")
    from database import init_db, close_db
    from services.wled_channels import create_channel_with_split

    db_path = str(tmp_path / "phase19.db")
    db = await init_db(db_path)

    # Seed a device.
    dev_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO wled_devices (id, ip, name, led_count, enabled, created_at) "
        "VALUES (?, '192.168.1.99', 'Test', 300, 1, '2026-05-14T00:00:00Z')",
        (dev_id,),
    )
    await db.commit()

    # Paint a channel.
    ch = await create_channel_with_split(db, dev_id, 50, 100)

    # Assign + set orientation.
    region_id = "region-x"
    config_id = "config-y"
    await db.execute(
        "INSERT INTO wled_light_assignments "
        "(region_id, wled_channel_id, entertainment_config_id, orientation) "
        "VALUES (?, ?, ?, ?)",
        (region_id, ch["id"], config_id, "horizontal-LTR"),
    )
    await db.commit()
    await close_db(db)

    # Reopen and verify.
    db2 = await init_db(db_path)
    db2.row_factory = aiosqlite.Row
    async with db2.execute(
        "SELECT name, start_led, end_led FROM wled_channels WHERE id = ?",
        (ch["id"],),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None, "channel did not persist"
    assert int(row["start_led"]) == 50
    assert int(row["end_led"]) == 100

    async with db2.execute(
        "SELECT orientation FROM wled_light_assignments "
        "WHERE region_id = ? AND wled_channel_id = ? AND entertainment_config_id = ?",
        (region_id, ch["id"], config_id),
    ) as cur:
        a = await cur.fetchone()
    assert a is not None, "assignment did not persist"
    assert a["orientation"] == "horizontal-LTR"
    await close_db(db2)


async def test_paint_assign_stream_smoke(tmp_path):
    """Synthetic-frame smoke through _build_region_plan + sub_sample_gradient."""
    pytest.importorskip("services.wled_channels")
    from database import init_db, close_db
    from services.wled_channels import create_channel_with_split
    from services.color_math import sub_sample_gradient
    from services.streaming_coordinator import StreamingCoordinator

    db_path = str(tmp_path / "phase19_stream.db")
    db = await init_db(db_path)
    db.row_factory = aiosqlite.Row

    # Seed device + region + assignment.
    dev_id = str(uuid.uuid4())
    region_id = str(uuid.uuid4())
    config_id = "cfg-1"
    await db.execute(
        "INSERT INTO wled_devices (id, ip, name, led_count, enabled, created_at) "
        "VALUES (?, '192.168.1.42', 'Test', 300, 1, '2026-05-14T00:00:00Z')",
        (dev_id,),
    )
    # Region with a full-frame polygon (normalized).
    await db.execute(
        "INSERT INTO regions (id, name, polygon, entertainment_config_id) "
        "VALUES (?, 'R1', ?, ?)",
        (region_id, '[[0,0],[1,0],[1,1],[0,1]]', config_id),
    )
    await db.commit()
    ch = await create_channel_with_split(db, dev_id, 0, 99)
    await db.execute(
        "INSERT INTO wled_light_assignments "
        "(region_id, wled_channel_id, entertainment_config_id, orientation) "
        "VALUES (?, ?, ?, 'horizontal-RTL')",
        (region_id, ch["id"], config_id),
    )
    await db.commit()

    # Drive a synthetic frame and resolve the region plan.
    # Use StreamingCoordinator.__new__ to access _build_region_plan without
    # spinning up the full streaming machinery (no real capture/bridge needed).
    coord = StreamingCoordinator.__new__(StreamingCoordinator)
    coord._db = db
    plan = await coord._build_region_plan(config_id)
    assert region_id in plan, f"plan missing region: {list(plan.keys())}"
    entry = plan[region_id]
    # Tuple shape: (mask, n_region, orientation)
    assert len(entry) == 3, f"plan tuple should be 3-element, got: {entry}"
    mask, n_region, orientation = entry
    assert orientation == "horizontal-RTL", f"orientation must reflect assignment: {orientation}"
    assert n_region == 100  # end_led - start_led + 1 = 99 - 0 + 1

    # Build a synthetic horizontal red->blue gradient (BGR frame).
    # build_polygon_mask defaults to 640x480; the frame must match so that
    # roi_mask and roi_frame have the same shape when cv2.mean is called.
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    for x in range(640):
        t = x / 639
        frame[:, x, 0] = int(t * 255)       # B increases left-to-right
        frame[:, x, 2] = int((1 - t) * 255) # R decreases left-to-right
    out = sub_sample_gradient(frame, mask, n_region, orientation=orientation)
    # sub_sample_gradient returns RGB order (cv2.mean BGR is converted to RGB).
    # With horizontal-RTL the output is reversed: first sample = right edge of frame.
    # Right edge of frame: BGR Blue (frame[:,:,0]) is high, BGR Red (frame[:,:,2]) is low.
    # In RGB output: index 0 = R, index 1 = G, index 2 = B.
    # So at the right edge: out[0][2] (B) is high and out[0][0] (R) is low.
    assert out[0][2] > out[0][0], (
        f"horizontal-RTL: first output sample should be high-blue (right edge in RGB), "
        f"got R={out[0][0]} B={out[0][2]}"
    )
    await close_db(db)
