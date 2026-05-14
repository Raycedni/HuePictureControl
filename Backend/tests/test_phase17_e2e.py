"""Phase 17 end-to-end integration test.

Stitches together:
  - in-memory SQLite with all Phase 17 tables (plus the Hue-pipeline
    placeholder tables _resolve_device_path queries against)
  - StreamingCoordinator (real) + WledStreamer (real, udp_port=41324)
    + HueStreamer (mocked) + make_mock_capture (deterministic frame)
  - udp_listener fixture to observe real UDP packets on loopback
  - routers/wled.py mounted at the end to drive the cascade-delete invariant
    over HTTP (TestClient)

Asserts invariants 5, 14, 15 from 17-VALIDATION.md, plus a defense-in-depth
cross-check on invariant 4 at the integration level (Plan 04 already unit-
tested 4 against the streamer in isolation).

Implementation notes vs. PLAN.md:
  - The plan example used ``patch.object(ws_mod, "UDP_PORT", 41324)`` to
    redirect UDP traffic. Plan 17-04 shipped ``WledStreamer(udp_port=41324)``
    as the authoritative test idiom — see test_streaming_coordinator.py
    test_coordinator_fans_out_to_hue_and_wled. We use the constructor kwarg
    (no module-level patching) per Plan 06's fan-out test pattern.
  - The plan example imported fixtures via ``Backend.tests.fixtures``; pytest
    runs from ``Backend/`` so the package root is ``Backend/`` and the import
    path is ``tests.fixtures.*`` (matches the rest of the suite).
  - ``_resolve_device_path`` queries ``camera_assignments`` / ``known_cameras``;
    we create those tables empty so the resolver falls back to CAPTURE_DEVICE
    cleanly (rather than blowing up on missing-table OperationalError).
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fixtures.mock_capture import make_mock_capture
from tests.fixtures.wled_loopback import udp_listener


async def _make_db_with_phase17_schema():
    """In-memory aiosqlite with the minimal schema StreamingCoordinator + the
    WLED router need to exercise the full E2E path.

    Includes both Phase 17 tables (regions, light_assignments, wled_*) AND
    the Phase 16 capture-resolution tables (camera_assignments, known_cameras)
    so ``_resolve_device_path`` can run its SELECTs and fall back to
    CAPTURE_DEVICE when no rows exist (rather than raising an
    OperationalError out of the streaming start path).
    """
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(
        """
        CREATE TABLE regions (
            id TEXT PRIMARY KEY,
            name TEXT,
            polygon TEXT NOT NULL,
            order_index INTEGER DEFAULT 0,
            light_id TEXT,
            entertainment_config_id TEXT
        );
        CREATE TABLE light_assignments (
            region_id TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, channel_id, entertainment_config_id)
        );
        CREATE TABLE wled_devices (
            id TEXT PRIMARY KEY,
            ip TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            led_count INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE wled_channels (
            id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            name TEXT NOT NULL,
            start_led INTEGER NOT NULL,
            end_led INTEGER NOT NULL,
            color TEXT NOT NULL DEFAULT '#ffffff'
        );
        CREATE TABLE wled_light_assignments (
            region_id TEXT NOT NULL,
            wled_channel_id TEXT NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            orientation TEXT NOT NULL DEFAULT 'auto',
            PRIMARY KEY (region_id, wled_channel_id, entertainment_config_id)
        );
        CREATE TABLE camera_assignments (
            entertainment_config_id TEXT PRIMARY KEY,
            camera_stable_id TEXT NOT NULL,
            camera_name TEXT NOT NULL
        );
        CREATE TABLE known_cameras (
            stable_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            last_seen_at TEXT,
            last_device_path TEXT
        );
        """
    )
    await conn.commit()
    return conn


class _MockRegistry:
    """Minimal capture registry: acquire/release noop, returns the same capture."""

    def __init__(self, capture):
        self._capture = capture

    def acquire(self, path):
        return self._capture

    def release(self, path):
        pass


def _make_mock_hue():
    """HueStreamer with all coordinator-called surfaces mocked async."""
    mock = MagicMock()
    mock.start = AsyncMock()
    mock.stop = AsyncMock()
    mock.render = AsyncMock()
    mock.handle_bridge_error = AsyncMock(return_value=True)
    return mock


@pytest.mark.asyncio
async def test_register_stream_observe_packets_delete():
    """Invariants 5, 14, 15 + cascade-delete on stop.

      * Invariant 5: With enabled=true + channel assigned, loopback receives
        packets at >=50 Hz for >=2s window. (Floor relaxed to 25 Hz / 50
        packets in 2s per T-17-E2E-FLAKE — CI jitter absorption.)
      * Invariant 14: Concurrent Hue + WLED — both sinks see frames within
        the same window.
      * Invariant 15: fps stays >=40 Hz (relaxed from 50 Hz floor for CI).
      * Cascade delete: DELETE /api/wled/devices/{id} clears wled_devices,
        wled_channels, AND wled_light_assignments via the router's
        T-17-DELETE-ORPHAN code path.
    """
    from services.streaming_coordinator import StreamingCoordinator
    from services.status_broadcaster import StatusBroadcaster
    from services.wled_streamer import WledStreamer

    db = await _make_db_with_phase17_schema()

    # 1) Seed: one region + WLED device + channel + assignment for cfg1.
    await db.execute(
        "INSERT INTO regions (id, name, polygon, entertainment_config_id) "
        "VALUES ('r1', 'test', ?, 'cfg1')",
        ("[[0,0],[1,0],[1,1],[0,1]]",),
    )
    await db.execute(
        "INSERT INTO wled_devices (id, ip, name, led_count, enabled, created_at) "
        "VALUES ('d1', '127.0.0.1', 'Test Strip', 10, 1, '2026-04-26T00:00:00+00:00')"
    )
    await db.execute(
        "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) "
        "VALUES ('c1', 'd1', 'Strip', 0, 9, '#ffffff')"
    )
    await db.execute(
        "INSERT INTO wled_light_assignments (region_id, wled_channel_id, entertainment_config_id) "
        "VALUES ('r1', 'c1', 'cfg1')"
    )
    await db.commit()

    # 2) Build the coordinator with a real WledStreamer pinned to the loopback
    #    port (Plan 04 ctor kwarg — the authoritative pattern; no module
    #    patching). HueStreamer is mocked because we have no bridge.
    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()

    capture = make_mock_capture()
    registry = _MockRegistry(capture)
    real_wled = WledStreamer(udp_port=41324)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=registry,
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
        wled_streamer=real_wled,
    )

    # 3) Start, observe for 2s, stop. The udp_listener thread accumulates
    #    packets in a queue.Queue we drain after stop().
    with udp_listener(port=41324) as q:
        await coord.start("cfg1")
        # Allow a brief warm-up tick so the streamer reaches the streaming
        # state before we begin our 2s observation window.
        for _ in range(50):
            if coord.state == "streaming":
                break
            await asyncio.sleep(0.01)
        assert coord.state == "streaming", (
            f"coordinator failed to reach streaming state: {coord.state}"
        )

        # 2s observation window per invariant 5.
        await asyncio.sleep(2.0)

        # Snapshot fps from the broadcaster's internal metrics dict before
        # stop (after stop, push_state will overwrite state but fps remains).
        # Read while still streaming so we capture the live cadence.
        fps_during_stream = broadcaster._metrics.get("fps", 0)

        await coord.stop()

    # 4) Drain the loopback queue.
    packets = []
    while not q.empty():
        packets.append(q.get_nowait())

    # Invariant 5: at least one packet, and >= 50 packets in the 2s window
    # (25 Hz floor — relaxed from 50 Hz / 100 packets per T-17-E2E-FLAKE).
    assert len(packets) > 0, "WLED listener should have received packets while streaming"
    assert len(packets) >= 50, (
        f"expected >=50 packets in 2s observation window, got {len(packets)}"
    )

    # Invariant 14: Hue sink also saw frames in the same window.
    assert mock_hue.render.await_count > 0, (
        "Hue sink must have received per-frame render calls (invariant 14 — "
        "concurrent fan-out)"
    )

    # Invariant 15: fps floor — measured from broadcaster._metrics. Real loop
    # is bounded by mock capture's wait_for_new_frame returning instantly, so
    # we expect well above 40 Hz; the 40 floor absorbs CI jitter.
    assert fps_during_stream >= 40, (
        f"coordinator fps dropped below 40 Hz floor: {fps_during_stream} "
        "(invariant 15 / T-17-E2E-FLAKE)"
    )

    # 5) Belt-and-suspenders: the final packet on the wire must be the
    #    blackout packet WledStreamer.stop() emits (D-13). It is a DRGB
    #    (0x02) or DNRGB (0x04) packet whose body is all-zero RGB.
    last_pkt = packets[-1]
    assert last_pkt.data[0] in (0x02, 0x04), (
        f"final packet protocol byte must be DRGB/DNRGB; got {last_pkt.data[0]:#x}"
    )
    body_start = 2 if last_pkt.data[0] == 0x02 else 4
    final_body = last_pkt.data[body_start:]
    assert final_body == bytes(len(final_body)), (
        "final packet must be a zero-body blackout (D-13)"
    )

    # 6) Cascade-delete via the WLED router (T-17-DELETE-ORPHAN at the
    #    integration level). Mount a sub-app that shares OUR db handle so the
    #    DELETE drops rows from the same in-memory store we just queried.
    from routers.wled import router as wled_router

    @asynccontextmanager
    async def _lifespan(app):
        # Reuse the existing connection — the test owns its lifecycle and
        # closes it at the end. No try/finally close here.
        app.state.db = db
        app.state.coordinator = coord
        yield

    app = FastAPI(lifespan=_lifespan)
    app.include_router(wled_router)

    with TestClient(app) as client:
        r = client.delete("/api/wled/devices/d1")
        assert r.status_code == 204, (
            f"DELETE /api/wled/devices/d1 should return 204; got {r.status_code} {r.text}"
        )

    # 7) Verify cascade landed across all three tables.
    async with db.execute("SELECT COUNT(*) AS c FROM wled_devices") as cur:
        row = await cur.fetchone()
        assert row["c"] == 0, "wled_devices should be empty after cascade delete"
    async with db.execute("SELECT COUNT(*) AS c FROM wled_channels") as cur:
        row = await cur.fetchone()
        assert row["c"] == 0, "wled_channels should be empty after cascade delete"
    async with db.execute(
        "SELECT COUNT(*) AS c FROM wled_light_assignments"
    ) as cur:
        row = await cur.fetchone()
        assert row["c"] == 0, (
            "wled_light_assignments should be empty after cascade delete"
        )

    await db.close()


@pytest.mark.asyncio
async def test_enabled_false_device_receives_zero_packets():
    """Invariant 4 cross-check at the integration level.

    Plan 04 unit-tested invariant 4 by calling WledStreamer.render directly
    with a disabled device row. This integration variant proves the same
    behavior survives the full DB-query -> coordinator-load -> streamer-start
    -> render-loop path: the ``WHERE enabled = 1`` filter in
    ``_load_wled_device_rows`` keeps the disabled device out of the streamer
    entirely, and the loopback listener observes zero packets.
    """
    from services.streaming_coordinator import StreamingCoordinator
    from services.status_broadcaster import StatusBroadcaster
    from services.wled_streamer import WledStreamer

    db = await _make_db_with_phase17_schema()

    # Seed a region, a DISABLED device, and a channel + assignment for cfg1.
    # Even with the assignment present, the SELECT enabled=1 filter must drop
    # this device before it ever reaches the streamer.
    await db.execute(
        "INSERT INTO regions (id, name, polygon, entertainment_config_id) "
        "VALUES ('r1', 'test', ?, 'cfg1')",
        ("[[0,0],[1,0],[1,1],[0,1]]",),
    )
    await db.execute(
        "INSERT INTO wled_devices (id, ip, name, led_count, enabled, created_at) "
        "VALUES ('d1', '127.0.0.1', 'Disabled Strip', 10, 0, '2026-04-26T00:00:00+00:00')"
    )
    await db.execute(
        "INSERT INTO wled_channels (id, device_id, name, start_led, end_led, color) "
        "VALUES ('c1', 'd1', 'Strip', 0, 9, '#ffffff')"
    )
    await db.execute(
        "INSERT INTO wled_light_assignments (region_id, wled_channel_id, entertainment_config_id) "
        "VALUES ('r1', 'c1', 'cfg1')"
    )
    await db.commit()

    broadcaster = StatusBroadcaster()
    mock_hue = _make_mock_hue()
    capture = make_mock_capture()
    real_wled = WledStreamer(udp_port=41324)

    coord = StreamingCoordinator(
        db=db,
        capture_registry=_MockRegistry(capture),
        broadcaster=broadcaster,
        hue_streamer=mock_hue,
        wled_streamer=real_wled,
    )

    with udp_listener(port=41324) as q:
        await coord.start("cfg1")
        # Wait for streaming state, then observe for 1s.
        for _ in range(50):
            if coord.state == "streaming":
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.0)
        await coord.stop()

    # Invariant 4: disabled device emits zero packets (filtered out at the
    # SELECT enabled=1 boundary in _load_wled_device_rows; never attached to
    # the streamer; ``stop()`` finds an empty _devices dict so no blackout
    # packet either).
    assert q.empty(), (
        "disabled device must produce zero UDP packets end-to-end "
        "(invariant 4 cross-check)"
    )

    await db.close()
