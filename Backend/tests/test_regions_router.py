"""Integration tests for the regions router endpoints.

Tests cover:
- POST /api/regions/auto-map returns 400 when bridge not paired
- GET /api/regions returns empty list initially
- GET /api/regions returns regions after DB insert
- POST /api/regions/auto-map returns 422 on empty channels (ValueError)
- POST /api/regions/auto-map includes warning when streaming is active
- POST /api/regions creates a region (CRUD)
- PUT /api/regions/{id} updates polygon and/or light_id
- DELETE /api/regions/{id} removes a region
- GET /api/regions/ includes light_id field in each region
"""
import json
import pytest
import aiosqlite
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_regions_app(db_conn, streaming_state="idle"):
    """Build a minimal FastAPI app with regions router and a pre-wired DB."""
    from routers.regions import router as regions_router

    mock_streaming = MagicMock()
    type(mock_streaming).state = property(lambda self: streaming_state)

    @asynccontextmanager
    async def lifespan(app):
        app.state.db = db_conn
        app.state.streaming = mock_streaming
        yield

    test_app = FastAPI(lifespan=lifespan)
    test_app.include_router(regions_router)
    return test_app


@pytest.fixture
async def db():
    """In-memory aiosqlite connection with full schema initialized."""
    from database import init_db

    conn = await init_db(":memory:")
    yield conn
    await conn.close()


@pytest.fixture
async def regions_client(db):
    """TestClient wired with an empty in-memory DB (bridge not paired)."""
    test_app = _make_regions_app(db)
    with TestClient(test_app) as client:
        yield client, db


@pytest.fixture
async def regions_client_with_bridge(db):
    """TestClient wired with DB that has bridge credentials inserted."""
    await db.execute(
        """
        INSERT INTO bridge_config
            (id, bridge_id, rid, ip_address, username, hue_app_id, client_key, swversion, name)
        VALUES (1, 'bridge-001', 'rid-001', '192.168.1.1', 'test-user', 'app-001', 'key-001', 0, 'Test Bridge')
        """
    )
    await db.commit()

    test_app = _make_regions_app(db)
    with TestClient(test_app) as client:
        yield client, db


@pytest.fixture
async def regions_client_streaming_active(db):
    """TestClient with bridge configured and streaming active state."""
    await db.execute(
        """
        INSERT INTO bridge_config
            (id, bridge_id, rid, ip_address, username, hue_app_id, client_key, swversion, name)
        VALUES (1, 'bridge-001', 'rid-001', '192.168.1.1', 'test-user', 'app-001', 'key-001', 0, 'Test Bridge')
        """
    )
    await db.commit()

    test_app = _make_regions_app(db, streaming_state="streaming")
    with TestClient(test_app) as client:
        yield client, db


# ---------------------------------------------------------------------------
# GET /api/regions/ tests
# ---------------------------------------------------------------------------


class TestListRegions:
    async def test_returns_empty_list_initially(self, regions_client):
        """GET /api/regions/ returns an empty list when no regions are stored."""
        client, _ = regions_client
        response = client.get("/api/regions/")
        assert response.status_code == 200
        assert response.json() == []

    async def test_returns_regions_after_insert(self, regions_client):
        """GET /api/regions/ returns stored regions after manual DB insert."""
        client, db = regions_client

        polygon = [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]
        await db.execute(
            "INSERT INTO regions (id, name, polygon, order_index) VALUES (?, ?, ?, ?)",
            ("test-region-1", "Test Region", json.dumps(polygon), 0),
        )
        await db.commit()

        response = client.get("/api/regions/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "test-region-1"
        assert data[0]["name"] == "Test Region"
        assert data[0]["polygon"] == polygon
        assert data[0]["order_index"] == 0

    async def test_returns_regions_ordered_by_order_index(self, regions_client):
        """GET /api/regions/ returns regions sorted by order_index."""
        client, db = regions_client

        polygon = [[0.4, 0.4], [0.6, 0.4], [0.6, 0.6], [0.4, 0.6]]
        await db.execute(
            "INSERT INTO regions (id, name, polygon, order_index) VALUES (?, ?, ?, ?)",
            ("region-2", "Region 2", json.dumps(polygon), 2),
        )
        await db.execute(
            "INSERT INTO regions (id, name, polygon, order_index) VALUES (?, ?, ?, ?)",
            ("region-0", "Region 0", json.dumps(polygon), 0),
        )
        await db.commit()

        response = client.get("/api/regions/")
        assert response.status_code == 200
        data = response.json()
        assert data[0]["id"] == "region-0"
        assert data[1]["id"] == "region-2"


# ---------------------------------------------------------------------------
# POST /api/regions/auto-map tests
# ---------------------------------------------------------------------------


class TestAutoMapEndpoint:
    async def test_returns_400_when_bridge_not_paired(self, regions_client):
        """POST /api/regions/auto-map returns 400 when no bridge config exists."""
        client, _ = regions_client
        response = client.post("/api/regions/auto-map", json={"config_id": "cfg-001"})
        assert response.status_code == 400
        assert "not paired" in response.json()["detail"].lower()

    async def test_returns_422_on_empty_channels(self, regions_client_with_bridge):
        """POST /api/regions/auto-map returns 422 when ValueError (empty channels) raised."""
        client, _ = regions_client_with_bridge

        with patch(
            "services.auto_mapping.fetch_entertainment_config_channels",
            new=AsyncMock(return_value=[]),
        ):
            response = client.post(
                "/api/regions/auto-map", json={"config_id": "cfg-001"}
            )

        assert response.status_code == 422

    async def test_returns_regions_created_count(self, regions_client_with_bridge):
        """POST /api/regions/auto-map returns regions_created count on success."""
        client, _ = regions_client_with_bridge

        mock_channels = [
            {"channel_id": 0, "position": {"x": -0.5, "y": 0.0, "z": -0.5}},
            {"channel_id": 1, "position": {"x": 0.5, "y": 0.0, "z": 0.5}},
        ]

        with patch(
            "services.auto_mapping.fetch_entertainment_config_channels",
            new=AsyncMock(return_value=mock_channels),
        ):
            response = client.post(
                "/api/regions/auto-map", json={"config_id": "cfg-001"}
            )

        assert response.status_code == 200
        data = response.json()
        assert data["regions_created"] == 2

    async def test_includes_warning_when_streaming_active(
        self, regions_client_streaming_active
    ):
        """POST /api/regions/auto-map includes warning when streaming is active."""
        client, _ = regions_client_streaming_active

        mock_channels = [
            {"channel_id": 0, "position": {"x": 0.0, "y": 0.0, "z": 0.0}},
        ]

        with patch(
            "services.auto_mapping.fetch_entertainment_config_channels",
            new=AsyncMock(return_value=mock_channels),
        ):
            response = client.post(
                "/api/regions/auto-map", json={"config_id": "cfg-001"}
            )

        assert response.status_code == 200
        data = response.json()
        assert "warning" in data
        assert "streaming" in data["warning"].lower()

    async def test_no_warning_when_streaming_idle(self, regions_client_with_bridge):
        """POST /api/regions/auto-map has no warning when streaming is idle."""
        client, _ = regions_client_with_bridge

        mock_channels = [
            {"channel_id": 0, "position": {"x": 0.0, "y": 0.0, "z": 0.0}},
        ]

        with patch(
            "services.auto_mapping.fetch_entertainment_config_channels",
            new=AsyncMock(return_value=mock_channels),
        ):
            response = client.post(
                "/api/regions/auto-map", json={"config_id": "cfg-001"}
            )

        assert response.status_code == 200
        data = response.json()
        assert "warning" not in data

    async def test_persists_regions_to_db(self, regions_client_with_bridge):
        """POST /api/regions/auto-map writes regions to DB so GET returns them."""
        client, db = regions_client_with_bridge

        mock_channels = [
            {"channel_id": 0, "position": {"x": 0.0, "y": 0.0, "z": 0.0}},
        ]

        with patch(
            "services.auto_mapping.fetch_entertainment_config_channels",
            new=AsyncMock(return_value=mock_channels),
        ):
            post_response = client.post(
                "/api/regions/auto-map", json={"config_id": "cfg-001"}
            )

        assert post_response.status_code == 200

        get_response = client.get("/api/regions/")
        assert get_response.status_code == 200
        regions = get_response.json()
        assert len(regions) == 1
        assert regions[0]["id"] == "auto:cfg-001:0"


# ---------------------------------------------------------------------------
# CRUD endpoint tests (POST, PUT, DELETE, GET with light_id)
# ---------------------------------------------------------------------------


class TestCreateRegion:
    async def test_create_region_returns_201(self, regions_client):
        """POST /api/regions returns 201 with created region including id."""
        client, _ = regions_client
        payload = {
            "name": "Left Zone",
            "polygon": [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]],
        }
        response = client.post("/api/regions/", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["name"] == "Left Zone"
        assert data["polygon"] == payload["polygon"]
        assert data["light_id"] is None

    async def test_create_region_with_light_id(self, regions_client):
        """POST /api/regions with light_id stores and returns it."""
        client, _ = regions_client
        payload = {
            "name": "Right Zone",
            "polygon": [[0.5, 0.0], [1.0, 0.0], [1.0, 0.5], [0.5, 0.5]],
            "light_id": "light-abc-123",
        }
        response = client.post("/api/regions/", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["light_id"] == "light-abc-123"

    async def test_create_region_generates_unique_id(self, regions_client):
        """POST /api/regions generates distinct UUIDs for each region."""
        client, _ = regions_client
        polygon = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
        r1 = client.post("/api/regions/", json={"name": "R1", "polygon": polygon})
        r2 = client.post("/api/regions/", json={"name": "R2", "polygon": polygon})
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]


class TestUpdateRegion:
    async def test_update_region_polygon(self, regions_client):
        """PUT /api/regions/{id} updates polygon and returns updated region."""
        client, _ = regions_client
        polygon = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
        create_resp = client.post("/api/regions/", json={"name": "Zone", "polygon": polygon})
        region_id = create_resp.json()["id"]

        new_polygon = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
        response = client.put(f"/api/regions/{region_id}", json={"polygon": new_polygon})
        assert response.status_code == 200
        data = response.json()
        assert data["polygon"] == new_polygon

    async def test_update_region_light_id(self, regions_client):
        """PUT /api/regions/{id} updates light_id assignment."""
        client, _ = regions_client
        polygon = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
        create_resp = client.post("/api/regions/", json={"name": "Zone", "polygon": polygon})
        region_id = create_resp.json()["id"]

        response = client.put(f"/api/regions/{region_id}", json={"light_id": "light-xyz"})
        assert response.status_code == 200
        assert response.json()["light_id"] == "light-xyz"

    async def test_update_nonexistent_returns_404(self, regions_client):
        """PUT /api/regions/{id} returns 404 when region not found."""
        client, _ = regions_client
        response = client.put(
            "/api/regions/nonexistent-id",
            json={"polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]},
        )
        assert response.status_code == 404


class TestDeleteRegion:
    async def test_delete_region_returns_204(self, regions_client):
        """DELETE /api/regions/{id} returns 204 on success."""
        client, _ = regions_client
        polygon = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
        create_resp = client.post("/api/regions/", json={"name": "Zone", "polygon": polygon})
        region_id = create_resp.json()["id"]

        response = client.delete(f"/api/regions/{region_id}")
        assert response.status_code == 204

    async def test_delete_nonexistent_returns_404(self, regions_client):
        """DELETE /api/regions/{id} returns 404 when region not found."""
        client, _ = regions_client
        response = client.delete("/api/regions/nonexistent-id")
        assert response.status_code == 404

    async def test_delete_removes_from_list(self, regions_client):
        """After DELETE, region no longer appears in GET /api/regions/."""
        client, _ = regions_client
        polygon = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
        create_resp = client.post("/api/regions/", json={"name": "Zone", "polygon": polygon})
        region_id = create_resp.json()["id"]

        client.delete(f"/api/regions/{region_id}")
        get_resp = client.get("/api/regions/")
        ids = [r["id"] for r in get_resp.json()]
        assert region_id not in ids


class TestListRegionsIncludesLightId:
    async def test_list_regions_includes_light_id(self, regions_client):
        """GET /api/regions/ includes light_id field (null by default)."""
        client, _ = regions_client
        polygon = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
        client.post("/api/regions/", json={"name": "Zone", "polygon": polygon})

        response = client.get("/api/regions/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert "light_id" in data[0]
        assert data[0]["light_id"] is None

    async def test_list_regions_shows_assigned_light_id(self, regions_client):
        """GET /api/regions/ shows non-null light_id when assigned."""
        client, _ = regions_client
        polygon = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
        create_resp = client.post(
            "/api/regions/",
            json={"name": "Zone", "polygon": polygon, "light_id": "light-abc"},
        )
        region_id = create_resp.json()["id"]

        response = client.get("/api/regions/")
        region = next(r for r in response.json() if r["id"] == region_id)
        assert region["light_id"] == "light-abc"
