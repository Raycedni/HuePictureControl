"""Unit tests for routers/ha.py (Phase 18 — HASS-01..05).

Mirrors `test_wled_router.py` structure:
  * In-memory aiosqlite with only the tables routers/ha.py touches.
  * FastAPI app built per-test with a lifespan that attaches db (and
    optional coordinator / broadcaster) onto ``app.state``.
  * Synchronous TestClient drives the HTTP surface; ``asyncio.run`` powers
    direct-DB-poke assertions (Phase 17 lock pattern).

External services mocked at the router import path:
  * ``routers.ha.list_entertainment_configs``
  * ``routers.ha._scan_devices``

Coverage map (24 tests, names locked by RESEARCH §Phase Requirements → Test Map):
  POST /api/ha/start (HASS-01) — 4 tests
  POST /api/ha/stop  (HASS-02) — 2 tests
  PUT  /api/ha/camera (HASS-03) — 3 tests (incl. D-07 negative)
  PUT  /api/ha/zone   (HASS-04) — 5 tests (incl. D-06 dual-write)
  GET  /api/ha/status (HASS-05) — 8 tests (incl. D-09 curated shape)
  GET  /api/ha/zones  (D-11)    — 1 happy + 2 error
  GET  /api/ha/cameras (D-11)   — 1 curated shape
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Reuse the shared coordinator-mock helper from conftest.py
from tests.conftest import _make_coordinator_mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_db():
    """In-memory aiosqlite with only the tables routers/ha.py touches."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(
        """
        CREATE TABLE bridge_config (
            id INTEGER PRIMARY KEY,
            bridge_id TEXT NOT NULL,
            rid TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            username TEXT NOT NULL,
            hue_app_id TEXT NOT NULL,
            client_key TEXT NOT NULL,
            swversion INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE entertainment_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            channel_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE known_cameras (
            stable_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            last_seen_at TEXT,
            last_device_path TEXT
        );
        CREATE TABLE camera_assignments (
            entertainment_config_id TEXT PRIMARY KEY,
            camera_stable_id TEXT NOT NULL,
            camera_name TEXT NOT NULL
        );
        CREATE TABLE camera_last_zone (
            camera_stable_id TEXT PRIMARY KEY,
            entertainment_config_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE ha_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_config_id TEXT,
            active_camera_stable_id TEXT,
            updated_at TEXT
        );
        """
    )
    await conn.commit()
    return conn


async def _make_db_partial_bridge():
    """Variant of _make_db where bridge_config allows NULL ip_address / username.

    Locks the broadened ``except (httpx.HTTPError, TypeError, ValueError, KeyError)``
    behaviour in ``_build_status_response`` against partial rows. Production
    schema enforces NOT NULL on these columns; this test-only schema lets us
    seed the degraded shape and prove the endpoint stays 200.
    """
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(
        """
        CREATE TABLE bridge_config (
            id INTEGER PRIMARY KEY,
            bridge_id TEXT,
            rid TEXT,
            ip_address TEXT,
            username TEXT,
            hue_app_id TEXT,
            client_key TEXT,
            swversion INTEGER DEFAULT 0,
            name TEXT DEFAULT ''
        );
        CREATE TABLE entertainment_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            channel_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE known_cameras (
            stable_id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            last_seen_at TEXT,
            last_device_path TEXT
        );
        CREATE TABLE camera_assignments (
            entertainment_config_id TEXT PRIMARY KEY,
            camera_stable_id TEXT NOT NULL,
            camera_name TEXT NOT NULL
        );
        CREATE TABLE camera_last_zone (
            camera_stable_id TEXT PRIMARY KEY,
            entertainment_config_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE ha_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_config_id TEXT,
            active_camera_stable_id TEXT,
            updated_at TEXT
        );
        """
    )
    await conn.commit()
    return conn


def _make_client(coordinator=None, broadcaster=None, db_factory=_make_db):
    """Build a FastAPI app with routers/ha.py mounted.

    Returns ``(TestClient, FastAPI)``. Caller wraps the client in a ``with``
    block to drive the lifespan, then can post-poke ``app.state.db`` via
    ``asyncio.run``.
    """
    from routers.ha import router as ha_router

    @asynccontextmanager
    async def _lifespan(app):
        db = await db_factory()
        app.state.db = db
        if coordinator is not None:
            app.state.coordinator = coordinator
        if broadcaster is not None:
            app.state.broadcaster = broadcaster
        try:
            yield
        finally:
            await db.close()

    app = FastAPI(lifespan=_lifespan)
    app.include_router(ha_router)
    return TestClient(app), app


def _make_broadcaster_mock(state="idle", **metrics_overrides):
    """Return a MagicMock with a ``_metrics`` dict matching the broadcaster shape."""
    mock = MagicMock()
    mock._metrics = {
        "state": state,
        "fps": 0,
        "latency_ms": 0,
        "packets_sent": 0,
        "packets_dropped": 0,
        "seq": 0,
        "active_config_id": None,
        "active_device_path": None,
        "wled_devices": {},
    }
    mock._metrics.update(metrics_overrides)
    return mock


async def _seed_bridge(db):
    await db.execute(
        "INSERT INTO bridge_config (id, bridge_id, rid, ip_address, username, "
        "hue_app_id, client_key, swversion, name) VALUES (1, 'b', 'r', '10.0.0.1', "
        "'u', 'a', 'k', 1, 'Bridge')"
    )
    await db.commit()


async def _seed_zone(db, zone_id="cfg1", name="TV-Bereich"):
    await db.execute(
        "INSERT INTO entertainment_configs (id, name, status, channel_count, raw_json) "
        "VALUES (?, ?, 'active', 6, '{}')",
        (zone_id, name),
    )
    await db.commit()


async def _seed_camera(db, stable_id="cam1", name="USB Camera", path="/dev/video10"):
    await db.execute(
        "INSERT INTO known_cameras (stable_id, display_name, last_seen_at, "
        "last_device_path) VALUES (?, ?, '2026-05-11T00:00:00+00:00', ?)",
        (stable_id, name, path),
    )
    await db.commit()


async def _seed_ha_state(db, config_id=None, camera_stable_id=None):
    await db.execute(
        "INSERT INTO ha_state (id, active_config_id, active_camera_stable_id, updated_at) "
        "VALUES (1, ?, ?, '2026-05-11T00:00:00+00:00')",
        (config_id, camera_stable_id),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# POST /api/ha/start (HASS-01) — 4 tests
# ---------------------------------------------------------------------------


def test_start_400_when_no_zone_selected():
    """Empty ha_state → 400 with a descriptive detail (D-08 step 1)."""
    coord = _make_coordinator_mock()
    client, app = _make_client(coordinator=coord)
    with client:
        r = client.post("/api/ha/start")
    assert r.status_code == 400
    assert "no zone selected" in r.json()["detail"].lower()


def test_start_404_when_zone_deleted():
    """ha_state references a config that's no longer in entertainment_configs (D-08 step 2)."""
    coord = _make_coordinator_mock()
    client, app = _make_client(coordinator=coord)

    async def _seed():
        await _seed_ha_state(app.state.db, config_id="cfg-gone")

    with client:
        asyncio.run(_seed())
        r = client.post("/api/ha/start")
    assert r.status_code == 404
    assert "zone not found" in r.json()["detail"].lower()


def test_start_calls_coordinator_with_resolved_path():
    """Happy path: device_path resolved from ha_state.active_camera_stable_id (D-08 step 3a)."""
    coord = _make_coordinator_mock()
    broadcaster = _make_broadcaster_mock()
    client, app = _make_client(coordinator=coord, broadcaster=broadcaster)

    async def _seed():
        await _seed_bridge(app.state.db)
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")
        await _seed_camera(app.state.db, "cam1", "USB Camera", "/dev/video10")
        await _seed_ha_state(app.state.db, config_id="cfg1", camera_stable_id="cam1")

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha.list_entertainment_configs",
            AsyncMock(return_value=[{"id": "cfg1", "name": "TV-Bereich",
                                      "status": "active", "channel_count": 6}]),
        ):
            r = client.post("/api/ha/start")
    assert r.status_code == 200, r.text
    coord.start.assert_awaited_once_with("cfg1", device_path_override="/dev/video10")


def test_start_idempotent_when_streaming():
    """Coordinator already streaming → coordinator.start is a silent no-op; HTTP returns 200."""
    coord = _make_coordinator_mock()
    # Override state to "streaming"
    type(coord).state = property(lambda self: "streaming")
    broadcaster = _make_broadcaster_mock(state="streaming",
                                          active_config_id="cfg1",
                                          active_device_path="/dev/video10")
    client, app = _make_client(coordinator=coord, broadcaster=broadcaster)

    async def _seed():
        await _seed_bridge(app.state.db)
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")
        await _seed_camera(app.state.db, "cam1", "USB Camera", "/dev/video10")
        await _seed_ha_state(app.state.db, config_id="cfg1", camera_stable_id="cam1")

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha.list_entertainment_configs",
            AsyncMock(return_value=[{"id": "cfg1", "name": "TV-Bereich",
                                      "status": "active", "channel_count": 6}]),
        ):
            r = client.post("/api/ha/start")
    assert r.status_code == 200, r.text
    body = r.json()
    # HaStatusResponse shape
    assert body["state"] == "streaming"
    assert body["active_config_id"] == "cfg1"


# ---------------------------------------------------------------------------
# POST /api/ha/stop (HASS-02) — 2 tests
# ---------------------------------------------------------------------------


def test_stop_calls_coordinator():
    """coordinator.stop() awaited exactly once."""
    coord = _make_coordinator_mock()
    type(coord).state = property(lambda self: "streaming")
    broadcaster = _make_broadcaster_mock(state="streaming")
    client, app = _make_client(coordinator=coord, broadcaster=broadcaster)
    with client:
        r = client.post("/api/ha/stop")
    assert r.status_code == 200, r.text
    coord.stop.assert_awaited_once()


def test_stop_idempotent_when_idle():
    """Idle coordinator → coordinator.stop returns 200 no-op."""
    coord = _make_coordinator_mock()
    broadcaster = _make_broadcaster_mock(state="idle")
    client, app = _make_client(coordinator=coord, broadcaster=broadcaster)
    with client:
        r = client.post("/api/ha/stop")
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# PUT /api/ha/camera (HASS-03) — 3 tests (incl. D-07 negative)
# ---------------------------------------------------------------------------


def test_put_camera_persists_lazy():
    """PUT camera with no pre-existing ha_state row → row created via ON CONFLICT (D-05)."""
    client, app = _make_client()

    async def _seed():
        await _seed_camera(app.state.db, "cam1", "USB Camera", "/dev/video10")

    with client:
        asyncio.run(_seed())
        r = client.put("/api/ha/camera", json={"stable_id": "cam1"})
        assert r.status_code == 200, r.text

        async def _check_row():
            db = app.state.db
            async with db.execute(
                "SELECT active_camera_stable_id, active_config_id FROM ha_state WHERE id = 1"
            ) as cur:
                row = await cur.fetchone()
            assert row is not None
            assert row["active_camera_stable_id"] == "cam1"
            assert row["active_config_id"] is None

        asyncio.run(_check_row())


def test_put_camera_404_unknown():
    """Empty known_cameras → 404 with descriptive detail."""
    client, app = _make_client()
    with client:
        r = client.put("/api/ha/camera", json={"stable_id": "nope"})
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_put_camera_does_not_touch_assignments():
    """D-07 NEGATIVE: PUT camera writes ha_state only, not camera_assignments."""
    client, app = _make_client()

    async def _seed():
        await _seed_camera(app.state.db, "cam1", "USB Camera", "/dev/video10")

    with client:
        asyncio.run(_seed())
        r = client.put("/api/ha/camera", json={"stable_id": "cam1"})
        assert r.status_code == 200, r.text

        async def _check_assignments():
            db = app.state.db
            async with db.execute(
                "SELECT COUNT(*) AS c FROM camera_assignments"
            ) as cur:
                row = await cur.fetchone()
            assert row["c"] == 0, "D-07 — HA must NOT write camera_assignments"

        asyncio.run(_check_assignments())


# ---------------------------------------------------------------------------
# PUT /api/ha/zone (HASS-04) — 5 tests (incl. D-06 dual-write)
# ---------------------------------------------------------------------------


def test_put_zone_persists_lazy():
    """PUT zone with no pre-existing ha_state row → row created (D-05)."""
    client, app = _make_client()

    async def _seed():
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")

    with client:
        asyncio.run(_seed())
        r = client.put("/api/ha/zone", json={"zone_id": "cfg1"})
        assert r.status_code == 200, r.text

        async def _check_row():
            db = app.state.db
            async with db.execute(
                "SELECT active_config_id, active_camera_stable_id FROM ha_state WHERE id = 1"
            ) as cur:
                row = await cur.fetchone()
            assert row is not None
            assert row["active_config_id"] == "cfg1"
            assert row["active_camera_stable_id"] is None

        asyncio.run(_check_row())


def test_put_zone_404_unknown():
    """Empty entertainment_configs → 404 with descriptive detail."""
    client, app = _make_client()
    with client:
        r = client.put("/api/ha/zone", json={"zone_id": "nope"})
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_put_zone_dual_writes_camera_last_zone():
    """D-06: PUT zone after a camera is set ALSO writes camera_last_zone."""
    client, app = _make_client()

    async def _seed():
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")
        await _seed_camera(app.state.db, "cam1", "USB Camera", "/dev/video10")

    with client:
        asyncio.run(_seed())
        # 1) PUT camera first so ha_state has active_camera_stable_id
        r1 = client.put("/api/ha/camera", json={"stable_id": "cam1"})
        assert r1.status_code == 200, r1.text
        # 2) PUT zone — dual-write should fire
        r2 = client.put("/api/ha/zone", json={"zone_id": "cfg1"})
        assert r2.status_code == 200, r2.text

        async def _check_dual_write():
            db = app.state.db
            async with db.execute(
                "SELECT entertainment_config_id FROM camera_last_zone "
                "WHERE camera_stable_id = 'cam1'"
            ) as cur:
                row = await cur.fetchone()
            assert row is not None
            assert row["entertainment_config_id"] == "cfg1"

        asyncio.run(_check_dual_write())


def test_put_zone_skips_dual_write_when_no_camera():
    """D-06 step 4: no active_camera_stable_id → no camera_last_zone write."""
    client, app = _make_client()

    async def _seed():
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")

    with client:
        asyncio.run(_seed())
        r = client.put("/api/ha/zone", json={"zone_id": "cfg1"})
        assert r.status_code == 200, r.text

        async def _check_no_dual_write():
            db = app.state.db
            async with db.execute(
                "SELECT COUNT(*) AS c FROM camera_last_zone"
            ) as cur:
                row = await cur.fetchone()
            assert row["c"] == 0, (
                "D-06 step 4 — without a camera set, camera_last_zone must NOT be written"
            )

        asyncio.run(_check_no_dual_write())


def test_put_zone_preserves_camera():
    """Pitfall 1 (REPLACE-drops-columns) mitigation: ON CONFLICT preserves camera across zone updates."""
    client, app = _make_client()

    async def _seed():
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")
        await _seed_zone(app.state.db, "cfg2", "Other Zone")
        await _seed_camera(app.state.db, "cam1", "USB Camera", "/dev/video10")

    with client:
        asyncio.run(_seed())
        r1 = client.put("/api/ha/camera", json={"stable_id": "cam1"})
        assert r1.status_code == 200, r1.text
        r2 = client.put("/api/ha/zone", json={"zone_id": "cfg1"})
        assert r2.status_code == 200, r2.text
        r3 = client.put("/api/ha/zone", json={"zone_id": "cfg2"})
        assert r3.status_code == 200, r3.text

        async def _check_state():
            db = app.state.db
            async with db.execute(
                "SELECT active_config_id, active_camera_stable_id FROM ha_state WHERE id = 1"
            ) as cur:
                row = await cur.fetchone()
            assert row["active_config_id"] == "cfg2"
            assert row["active_camera_stable_id"] == "cam1"

        asyncio.run(_check_state())


# ---------------------------------------------------------------------------
# GET /api/ha/status (HASS-05) — 8 tests
# ---------------------------------------------------------------------------


def test_status_schema_when_streaming():
    """D-09: status payload mirrors broadcaster._metrics + friendly-name lookup."""
    broadcaster = _make_broadcaster_mock(
        state="streaming",
        active_config_id="cfg1",
        active_device_path="/dev/video10",
        fps=60,
        latency_ms=12.3,
    )
    client, app = _make_client(broadcaster=broadcaster)

    async def _seed():
        await _seed_bridge(app.state.db)
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")
        await _seed_camera(app.state.db, "cam1", "USB Camera", "/dev/video10")

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha.list_entertainment_configs",
            AsyncMock(return_value=[{"id": "cfg1", "name": "TV-Bereich",
                                      "status": "active", "channel_count": 6}]),
        ):
            r = client.get("/api/ha/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "streaming"
    assert body["active_config_id"] == "cfg1"
    assert body["active_config_name"] == "TV-Bereich"
    assert body["active_camera_stable_id"] == "cam1"
    assert body["active_camera_name"] == "USB Camera"
    assert body["active_device_path"] == "/dev/video10"
    assert body["fps"] == 60
    assert body["latency_ms"] == 12.3
    assert body["bridge_paired"] is True


def test_status_includes_ha_selected():
    """D-10: ha_selected_* mirrors ha_state regardless of active streaming state."""
    broadcaster = _make_broadcaster_mock(state="idle")
    client, app = _make_client(broadcaster=broadcaster)

    async def _seed():
        await _seed_bridge(app.state.db)
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")
        await _seed_camera(app.state.db, "cam1", "USB Camera", "/dev/video10")
        await _seed_ha_state(app.state.db, config_id="cfg1", camera_stable_id="cam1")

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha.list_entertainment_configs",
            AsyncMock(return_value=[{"id": "cfg1", "name": "TV-Bereich",
                                      "status": "active", "channel_count": 6}]),
        ):
            r = client.get("/api/ha/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ha_selected_config_id"] == "cfg1"
    assert body["ha_selected_config_name"] == "TV-Bereich"
    assert body["ha_selected_camera_stable_id"] == "cam1"
    assert body["ha_selected_camera_name"] == "USB Camera"


def test_status_resolves_friendly_names():
    """D-09: active_config_name resolved server-side from list_entertainment_configs."""
    broadcaster = _make_broadcaster_mock(
        state="streaming",
        active_config_id="cfg1",
    )
    client, app = _make_client(broadcaster=broadcaster)

    async def _seed():
        await _seed_bridge(app.state.db)
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha.list_entertainment_configs",
            AsyncMock(return_value=[{"id": "cfg1", "name": "FriendlyName",
                                      "status": "active", "channel_count": 6}]),
        ):
            r = client.get("/api/ha/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active_config_name"] == "FriendlyName"


def test_status_bridge_unpaired():
    """Empty bridge_config → 200 + bridge_paired=False, no exception."""
    broadcaster = _make_broadcaster_mock(state="idle")
    client, app = _make_client(broadcaster=broadcaster)
    with client:
        r = client.get("/api/ha/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bridge_paired"] is False
    assert body.get("active_config_name") is None


def test_status_bridge_http_error():
    """Bridge unreachable → 200 + bridge_paired=True but friendly names null (Pitfall 4)."""
    broadcaster = _make_broadcaster_mock(state="streaming", active_config_id="cfg1")
    client, app = _make_client(broadcaster=broadcaster)

    async def _seed():
        await _seed_bridge(app.state.db)
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha.list_entertainment_configs",
            AsyncMock(side_effect=httpx.ConnectError("refused")),
        ):
            r = client.get("/api/ha/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bridge_paired"] is True
    assert body.get("active_config_name") is None  # graceful degrade


def test_status_curated_payload_shape():
    """D-09 SEALED CONTRACT: response keys match exactly the curated set.

    `packets_sent`, `packets_dropped`, `seq`, `wled_devices` MUST NOT appear
    even though the broadcaster's _metrics contains them. Asserted by literal
    set comparison.
    """
    broadcaster = _make_broadcaster_mock(
        state="streaming",
        active_config_id="cfg1",
        active_device_path="/dev/video10",
        packets_sent=999,
        packets_dropped=5,
        seq=42,
        wled_devices={"d1": {"fail_count": 0}},
    )
    client, app = _make_client(broadcaster=broadcaster)

    async def _seed():
        await _seed_bridge(app.state.db)
        await _seed_zone(app.state.db, "cfg1", "TV-Bereich")

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha.list_entertainment_configs",
            AsyncMock(return_value=[{"id": "cfg1", "name": "TV-Bereich",
                                      "status": "active", "channel_count": 6}]),
        ):
            r = client.get("/api/ha/status")
    assert r.status_code == 200, r.text
    keys = set(r.json().keys())

    # D-09 SEALED CONTRACT: the response key set MUST be a subset of the
    # curated allow-list. `response_model_exclude_none=True` may drop optional
    # keys whose value is None (e.g. ha_selected_* when ha_state row absent),
    # which is fine — what matters is that NO key outside the curated set
    # appears, especially the internal _metrics fields below.
    allowed_keys = {
        "state",
        "active_config_id",
        "active_config_name",
        "active_camera_stable_id",
        "active_camera_name",
        "active_device_path",
        "fps",
        "latency_ms",
        "ha_selected_config_id",
        "ha_selected_config_name",
        "ha_selected_camera_stable_id",
        "ha_selected_camera_name",
        "bridge_paired",
        "error",  # additive, only present when broadcaster surfaces an error
    }
    # Internal metrics MUST NOT leak.
    forbidden_keys = {"packets_sent", "packets_dropped", "seq", "wled_devices"}
    assert forbidden_keys.isdisjoint(keys), (
        f"D-09 leak: internal _metrics keys present in response: "
        f"{forbidden_keys & keys}"
    )
    # Belt-and-suspenders: nothing unexpected sneaks in either.
    extra = keys - allowed_keys
    assert not extra, f"D-09 unexpected keys in response: {extra}"
    # Core fields that must always be present (non-nullable in the model).
    must_have = {"state", "fps", "latency_ms", "bridge_paired"}
    missing = must_have - keys
    assert not missing, f"D-09 required keys missing: {missing}"


def test_status_error_field_optional():
    """error field surfaces only when broadcaster._metrics['error'] is set (D-09 additive)."""
    # Case 1: error set
    broadcaster = _make_broadcaster_mock(state="error", error="boom")
    client, app = _make_client(broadcaster=broadcaster)
    with client:
        r = client.get("/api/ha/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("error") == "boom"

    # Case 2: error absent — response_model_exclude_none drops the key entirely
    broadcaster2 = _make_broadcaster_mock(state="streaming")
    client2, app2 = _make_client(broadcaster=broadcaster2)
    with client2:
        r2 = client2.get("/api/ha/status")
    assert r2.status_code == 200, r2.text
    assert "error" not in r2.json()


def test_status_handles_partial_bridge_config_row():
    """T-18-12 mitigation: partial bridge_config row (NULL ip/username) → 200, no raise.

    Uses the test-only ``_make_db_partial_bridge`` schema variant because the
    production schema's NOT NULL constraints would reject the partial INSERT.
    The behaviour under test is the broadened
    ``except (httpx.HTTPError, TypeError, ValueError, KeyError)`` clause in
    ``_build_status_response``, which keeps the endpoint 200 even when
    Hue client calls explode on missing credentials.
    """
    broadcaster = _make_broadcaster_mock(state="idle")
    client, app = _make_client(broadcaster=broadcaster, db_factory=_make_db_partial_bridge)

    async def _seed_partial():
        # Seed a row with NULL ip_address / username — the broadened except
        # clause must absorb the resulting TypeError when the Hue client
        # tries to format the URL.
        await app.state.db.execute(
            "INSERT INTO bridge_config (id, bridge_id, rid, ip_address, username, "
            "hue_app_id, client_key, swversion, name) VALUES "
            "(1, 'b', 'r', NULL, NULL, 'a', 'k', 1, 'Bridge')"
        )
        await app.state.db.commit()

    with client:
        asyncio.run(_seed_partial())
        r = client.get("/api/ha/status")
    assert r.status_code == 200, r.text
    body = r.json()
    # bridge_paired requires non-null ip/username per 3-clause AND in helper.
    assert body["bridge_paired"] is False
    assert body.get("active_config_name") is None


# ---------------------------------------------------------------------------
# GET /api/ha/zones (D-11) — curated shape + 503/502 error mapping
# ---------------------------------------------------------------------------


def test_zones_curated_shape():
    """D-11: zones response is [{id, name}] only — no status, no channel_count."""
    client, app = _make_client()

    async def _seed():
        await _seed_bridge(app.state.db)

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha.list_entertainment_configs",
            AsyncMock(return_value=[{"id": "cfg1", "name": "TV",
                                      "status": "active", "channel_count": 6}]),
        ):
            r = client.get("/api/ha/zones")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"zones": [{"id": "cfg1", "name": "TV"}]}


def test_zones_503_when_unpaired():
    """No bridge → 503 HA-friendly mapping."""
    client, app = _make_client()
    with client:
        r = client.get("/api/ha/zones")
    assert r.status_code == 503
    assert "not paired" in r.json()["detail"].lower()


def test_zones_502_on_bridge_error():
    """Transient bridge HTTP error → 502."""
    client, app = _make_client()

    async def _seed():
        await _seed_bridge(app.state.db)

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha.list_entertainment_configs",
            AsyncMock(side_effect=httpx.ConnectError("refused")),
        ):
            r = client.get("/api/ha/zones")
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"].lower()


# ---------------------------------------------------------------------------
# GET /api/ha/cameras (D-11) — curated shape
# ---------------------------------------------------------------------------


def test_cameras_curated_shape():
    """D-11: cameras response is [{stable_id, name, connected}] only.

    Includes both connected and known-but-disconnected cameras. No
    last_seen_at, no last_device_path leakage.
    """
    client, app = _make_client()

    async def _seed():
        await _seed_camera(app.state.db, "cam1", "USB Camera", "/dev/video10")
        await _seed_camera(app.state.db, "cam2", "Other Camera", "/dev/video20")

    with client:
        asyncio.run(_seed())
        with patch(
            "routers.ha._scan_devices",
            AsyncMock(return_value=({"cam1": {"path": "/dev/video10"}}, False)),
        ):
            r = client.get("/api/ha/cameras")
    assert r.status_code == 200, r.text
    body = r.json()
    cameras = body["cameras"]
    assert len(cameras) == 2
    by_id = {c["stable_id"]: c for c in cameras}
    assert set(by_id["cam1"].keys()) == {"stable_id", "name", "connected"}
    assert set(by_id["cam2"].keys()) == {"stable_id", "name", "connected"}
    assert by_id["cam1"]["connected"] is True
    assert by_id["cam2"]["connected"] is False
    assert by_id["cam1"]["name"] == "USB Camera"
    assert by_id["cam2"]["name"] == "Other Camera"
