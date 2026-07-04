"""Tests for /api/settings/* router (quick-task 260516-kra).

Uses a real in-memory aiosqlite DB initialized by ``init_db(":memory:")``
mounted on a minimal FastAPI app (no full lifespan needed — the router
reads ``request.app.state.db`` directly). The FastAPI TestClient enters its
own context manager; we attach app.state.db inside a lifespan so it's live
when the test issues HTTP requests.
"""
import math
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from database import init_db, close_db
from routers.settings import router as settings_router


@asynccontextmanager
async def _lifespan_with_db(app: FastAPI):
    db = await init_db(":memory:")
    app.state.db = db
    try:
        yield
    finally:
        await close_db(db)


def _make_client() -> TestClient:
    app = FastAPI(lifespan=_lifespan_with_db)
    app.include_router(settings_router)
    return TestClient(app)


def test_get_returns_default_zero_on_fresh_db():
    """Fresh DB ships with ('brightness_cutoff_threshold', '0.0') seeded by init_db."""
    with _make_client() as client:
        r = client.get("/api/settings/brightness_cutoff_threshold")
    assert r.status_code == 200
    assert r.json() == {"value": 0.0}


def test_put_round_trip():
    """PUT then GET returns the same value."""
    with _make_client() as client:
        r1 = client.put(
            "/api/settings/brightness_cutoff_threshold",
            json={"value": 0.7},
        )
        assert r1.status_code == 200
        assert r1.json() == {"value": 0.7}

        r2 = client.get("/api/settings/brightness_cutoff_threshold")
    assert r2.status_code == 200
    assert r2.json() == {"value": 0.7}


def test_put_accepts_boundary_zero():
    """PUT value=0.0 succeeds (the default/disabled value)."""
    with _make_client() as client:
        r = client.put(
            "/api/settings/brightness_cutoff_threshold",
            json={"value": 0.0},
        )
    assert r.status_code == 200
    assert r.json() == {"value": 0.0}


def test_put_accepts_boundary_one():
    """PUT value=1.0 succeeds (everything goes off — degenerate but valid)."""
    with _make_client() as client:
        r = client.put(
            "/api/settings/brightness_cutoff_threshold",
            json={"value": 1.0},
        )
    assert r.status_code == 200
    assert r.json() == {"value": 1.0}


def test_put_rejects_above_one():
    """PUT value=1.5 is rejected by Pydantic Field(le=1.0)."""
    with _make_client() as client:
        r = client.put(
            "/api/settings/brightness_cutoff_threshold",
            json={"value": 1.5},
        )
    assert r.status_code == 422


def test_put_rejects_below_zero():
    """PUT value=-0.01 is rejected by Pydantic Field(ge=0.0)."""
    with _make_client() as client:
        r = client.put(
            "/api/settings/brightness_cutoff_threshold",
            json={"value": -0.01},
        )
    assert r.status_code == 422


def test_put_rejects_nan():
    """PUT value=NaN is rejected by the explicit NaN guard.

    JSON has no NaN literal, so we send it as the JSON string "NaN" wrapped
    in a manual body. Pydantic v2 will float-coerce "NaN"->NaN in some paths;
    the handler's `v != v` check returns 422.
    """
    # Sending NaN via JSON body — use a raw string so we bypass Python's
    # JSON serialization. requests/httpx will reject `float('nan')` in json=,
    # so we send the raw content.
    with _make_client() as client:
        r = client.put(
            "/api/settings/brightness_cutoff_threshold",
            content=b'{"value": NaN}',
            headers={"Content-Type": "application/json"},
        )
    # Either Pydantic rejects NaN at parse time (422) or our explicit guard
    # catches it (422) — both are 422. We assert the contract, not the layer.
    assert r.status_code == 422


def test_put_updates_app_state():
    """PUT must update request.app.state.brightness_cutoff_threshold live.

    This is the LIVE-UPDATE guarantee: streamers read app.state once per
    frame, so PUT must mutate the same attribute the streamers see.
    """
    app = FastAPI(lifespan=_lifespan_with_db)
    app.include_router(settings_router)
    with TestClient(app) as client:
        # Sanity: default not yet set on app.state (the router PUT sets it).
        # We don't require the GET handler to seed app.state — only PUT.
        r = client.put(
            "/api/settings/brightness_cutoff_threshold",
            json={"value": 0.4},
        )
        assert r.status_code == 200
        # The PUT handler set request.app.state.brightness_cutoff_threshold.
        # TestClient shares app.state with the running test_app instance.
        assert math.isclose(
            app.state.brightness_cutoff_threshold, 0.4, rel_tol=1e-9
        )


def test_put_overwrites_previous_value():
    """Successive PUTs replace, not stack — the DB row is upserted."""
    with _make_client() as client:
        client.put("/api/settings/brightness_cutoff_threshold", json={"value": 0.2})
        client.put("/api/settings/brightness_cutoff_threshold", json={"value": 0.6})
        r = client.get("/api/settings/brightness_cutoff_threshold")
    assert r.status_code == 200
    assert r.json() == {"value": 0.6}


# ---------------------------------------------------------------------------
# color_vibrancy + saturation_boost (quick-task 260704-iss)
# ---------------------------------------------------------------------------
# Same contract as brightness_cutoff_threshold above, parameterized over the
# two new keys so both endpoints get full coverage without duplicating each
# test body twice.


@pytest.mark.parametrize("key", ["color_vibrancy", "saturation_boost"])
def test_new_setting_get_returns_default_zero_on_fresh_db(key):
    with _make_client() as client:
        r = client.get(f"/api/settings/{key}")
    assert r.status_code == 200
    assert r.json() == {"value": 0.0}


@pytest.mark.parametrize("key", ["color_vibrancy", "saturation_boost"])
def test_new_setting_put_round_trip(key):
    with _make_client() as client:
        r1 = client.put(f"/api/settings/{key}", json={"value": 0.7})
        assert r1.status_code == 200
        assert r1.json() == {"value": 0.7}

        r2 = client.get(f"/api/settings/{key}")
    assert r2.status_code == 200
    assert r2.json() == {"value": 0.7}


@pytest.mark.parametrize("key", ["color_vibrancy", "saturation_boost"])
def test_new_setting_put_accepts_boundary_zero(key):
    with _make_client() as client:
        r = client.put(f"/api/settings/{key}", json={"value": 0.0})
    assert r.status_code == 200
    assert r.json() == {"value": 0.0}


@pytest.mark.parametrize("key", ["color_vibrancy", "saturation_boost"])
def test_new_setting_put_accepts_boundary_one(key):
    with _make_client() as client:
        r = client.put(f"/api/settings/{key}", json={"value": 1.0})
    assert r.status_code == 200
    assert r.json() == {"value": 1.0}


@pytest.mark.parametrize("key", ["color_vibrancy", "saturation_boost"])
def test_new_setting_put_rejects_above_one(key):
    with _make_client() as client:
        r = client.put(f"/api/settings/{key}", json={"value": 1.5})
    assert r.status_code == 422


@pytest.mark.parametrize("key", ["color_vibrancy", "saturation_boost"])
def test_new_setting_put_rejects_below_zero(key):
    with _make_client() as client:
        r = client.put(f"/api/settings/{key}", json={"value": -0.01})
    assert r.status_code == 422


@pytest.mark.parametrize("key", ["color_vibrancy", "saturation_boost"])
def test_new_setting_put_rejects_nan(key):
    with _make_client() as client:
        r = client.put(
            f"/api/settings/{key}",
            content=b'{"value": NaN}',
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 422


@pytest.mark.parametrize("key", ["color_vibrancy", "saturation_boost"])
def test_new_setting_put_updates_app_state(key):
    app = FastAPI(lifespan=_lifespan_with_db)
    app.include_router(settings_router)
    with TestClient(app) as client:
        r = client.put(f"/api/settings/{key}", json={"value": 0.4})
        assert r.status_code == 200
        assert math.isclose(getattr(app.state, key), 0.4, rel_tol=1e-9)


@pytest.mark.parametrize("key", ["color_vibrancy", "saturation_boost"])
def test_new_setting_put_overwrites_previous_value(key):
    with _make_client() as client:
        client.put(f"/api/settings/{key}", json={"value": 0.2})
        client.put(f"/api/settings/{key}", json={"value": 0.6})
        r = client.get(f"/api/settings/{key}")
    assert r.status_code == 200
    assert r.json() == {"value": 0.6}
