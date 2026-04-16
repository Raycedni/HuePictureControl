"""Tests for Backend/routers/wireless.py endpoints."""
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from routers.wireless import router as wireless_router


def _make_wireless_app_client(mock_pm=None):
    """Create a TestClient with mock pipeline_manager on app.state."""
    if mock_pm is None:
        mock_pm = MagicMock()
        mock_pm.get_sessions = MagicMock(return_value=[])

    @asynccontextmanager
    async def lifespan(app):
        app.state.pipeline_manager = mock_pm
        yield

    test_app = FastAPI(lifespan=lifespan)
    test_app.include_router(wireless_router)
    return TestClient(test_app)


class TestCapabilitiesEndpoint:
    @patch("routers.wireless._check_nic_p2p", new_callable=AsyncMock)
    @patch("routers.wireless._check_tool", new_callable=AsyncMock)
    def test_capabilities_returns_json(self, mock_tool, mock_nic):
        mock_tool.return_value = (True, "ffmpeg version 6.0")
        from models.wireless import NicCapability
        mock_nic.return_value = NicCapability(p2p_supported=False)

        with _make_wireless_app_client() as client:
            resp = client.get("/api/wireless/capabilities")
            assert resp.status_code == 200
            data = resp.json()
            assert "ffmpeg" in data
            assert "ready" in data
            assert "miracast_ready" in data
            assert "scrcpy_ready" in data

    @patch("routers.wireless._check_nic_p2p", new_callable=AsyncMock)
    @patch("routers.wireless._check_tool", new_callable=AsyncMock)
    def test_capabilities_all_missing(self, mock_tool, mock_nic):
        mock_tool.return_value = (False, "")
        from models.wireless import NicCapability
        mock_nic.return_value = NicCapability(p2p_supported=False)

        with _make_wireless_app_client() as client:
            resp = client.get("/api/wireless/capabilities")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ready"] is False
            assert data["miracast_ready"] is False
            assert data["scrcpy_ready"] is False


class TestSessionsEndpoint:
    def test_sessions_empty(self):
        mock_pm = MagicMock()
        mock_pm.get_sessions = MagicMock(return_value=[])

        with _make_wireless_app_client(mock_pm) as client:
            resp = client.get("/api/wireless/sessions")
            assert resp.status_code == 200
            data = resp.json()
            assert data["sessions"] == []

    def test_sessions_returns_data(self):
        mock_pm = MagicMock()
        mock_pm.get_sessions = MagicMock(return_value=[
            {
                "session_id": "abc-123",
                "source_type": "miracast",
                "device_path": "/dev/video10",
                "status": "active",
                "error_message": None,
                "started_at": "2026-04-14T22:00:00Z",
            }
        ])

        with _make_wireless_app_client(mock_pm) as client:
            resp = client.get("/api/wireless/sessions")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["sessions"]) == 1
            assert data["sessions"][0]["session_id"] == "abc-123"
            assert data["sessions"][0]["status"] == "active"


class TestScrcpyEndpoints:
    """Tests for POST /api/wireless/scrcpy and DELETE /api/wireless/scrcpy/{session_id}."""

    def test_post_scrcpy_success(self):
        mock_pm = MagicMock()
        mock_pm.start_android_scrcpy = AsyncMock(return_value="sess-abc")
        mock_pm.get_session = MagicMock(return_value=MagicMock(
            session_id="sess-abc",
            source_type="android_scrcpy",
            device_path="/dev/video11",
            status="active",
            error_message=None,
            error_code=None,
            started_at="2026-04-16T12:00:00Z",
        ))

        with _make_wireless_app_client(mock_pm) as client:
            resp = client.post("/api/wireless/scrcpy", json={"device_ip": "192.168.1.50"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["session_id"] == "sess-abc"
            assert data["source_type"] == "android_scrcpy"
            assert data["device_path"] == "/dev/video11"
            assert data["status"] == "active"
            mock_pm.start_android_scrcpy.assert_called_once_with("192.168.1.50")

    def test_post_scrcpy_adb_refused(self):
        mock_pm = MagicMock()
        mock_pm.start_android_scrcpy = AsyncMock(
            side_effect=RuntimeError("ADB connect failed: adb_refused")
        )
        mock_session = MagicMock(error_code="adb_refused")
        mock_pm.get_session_by_ip = MagicMock(return_value=mock_session)

        with _make_wireless_app_client(mock_pm) as client:
            resp = client.post("/api/wireless/scrcpy", json={"device_ip": "192.168.1.50"})
            assert resp.status_code == 422
            data = resp.json()
            assert data["detail"]["error_code"] == "adb_refused"

    def test_post_scrcpy_adb_unauthorized(self):
        mock_pm = MagicMock()
        mock_pm.start_android_scrcpy = AsyncMock(
            side_effect=RuntimeError("ADB connect failed: adb_unauthorized")
        )
        mock_session = MagicMock(error_code="adb_unauthorized")
        mock_pm.get_session_by_ip = MagicMock(return_value=mock_session)

        with _make_wireless_app_client(mock_pm) as client:
            resp = client.post("/api/wireless/scrcpy", json={"device_ip": "192.168.1.50"})
            assert resp.status_code == 422
            data = resp.json()
            assert data["detail"]["error_code"] == "adb_unauthorized"

    def test_post_scrcpy_producer_timeout(self):
        mock_pm = MagicMock()
        mock_pm.start_android_scrcpy = AsyncMock(
            side_effect=RuntimeError("Producer did not start within 15s timeout")
        )
        mock_session = MagicMock(error_code="producer_timeout")
        mock_pm.get_session_by_ip = MagicMock(return_value=mock_session)

        with _make_wireless_app_client(mock_pm) as client:
            resp = client.post("/api/wireless/scrcpy", json={"device_ip": "192.168.1.50"})
            assert resp.status_code == 422
            data = resp.json()
            assert data["detail"]["error_code"] == "producer_timeout"

    def test_post_scrcpy_missing_body(self):
        with _make_wireless_app_client() as client:
            resp = client.post("/api/wireless/scrcpy", json={})
            assert resp.status_code == 422  # Pydantic validation error

    def test_delete_scrcpy_success(self):
        mock_pm = MagicMock()
        mock_pm.get_session = MagicMock(return_value=MagicMock())
        mock_pm.stop_session = AsyncMock()

        with _make_wireless_app_client(mock_pm) as client:
            resp = client.delete("/api/wireless/scrcpy/sess-abc")
            assert resp.status_code == 204
            mock_pm.stop_session.assert_called_once_with("sess-abc")

    def test_delete_scrcpy_not_found(self):
        mock_pm = MagicMock()
        mock_pm.get_session = MagicMock(return_value=None)

        with _make_wireless_app_client(mock_pm) as client:
            resp = client.delete("/api/wireless/scrcpy/nonexistent")
            assert resp.status_code == 404
