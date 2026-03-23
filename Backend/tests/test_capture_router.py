"""Tests for the capture router endpoints.

Uses a mock LatestFrameCapture on app.state.capture.
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSnapshotEndpoint:
    def test_snapshot_returns_jpeg(self, capture_app_client):
        """GET /api/capture/snapshot returns 200 with JPEG content-type."""
        response = capture_app_client.get("/api/capture/snapshot")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"

    def test_snapshot_body_starts_with_jpeg_magic(self, capture_app_client):
        """GET /api/capture/snapshot body starts with JPEG magic bytes FFD8."""
        response = capture_app_client.get("/api/capture/snapshot")
        assert response.status_code == 200
        assert response.content[:2] == b"\xff\xd8"

    def test_snapshot_returns_503_when_get_frame_raises(self, capture_app_client_broken):
        """GET /api/capture/snapshot returns 503 when get_frame raises RuntimeError."""
        response = capture_app_client_broken.get("/api/capture/snapshot")
        assert response.status_code == 503


class TestSetDeviceEndpoint:
    def test_set_device_calls_open_and_returns_200(self, capture_app_client):
        """PUT /api/capture/device with valid path calls open() and returns 200."""
        response = capture_app_client.put(
            "/api/capture/device",
            json={"device_path": "/dev/video1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["device_path"] == "/dev/video1"
        assert data["status"] == "opened"

    def test_set_device_returns_503_when_open_raises(self, capture_app_client_broken_open):
        """PUT /api/capture/device returns 503 when open() raises RuntimeError."""
        response = capture_app_client_broken_open.put(
            "/api/capture/device",
            json={"device_path": "/dev/video99"},
        )
        assert response.status_code == 503


class TestDebugColorEndpoint:
    def test_debug_color_returns_xy(self, capture_app_client):
        """GET /api/capture/debug/color returns JSON with xy field containing two floats."""
        response = capture_app_client.get("/api/capture/debug/color")
        assert response.status_code == 200
        data = response.json()
        assert "xy" in data
        assert len(data["xy"]) == 2
        assert all(isinstance(v, float) for v in data["xy"])

    def test_debug_color_returns_rgb(self, capture_app_client):
        """GET /api/capture/debug/color returns JSON with rgb field."""
        response = capture_app_client.get("/api/capture/debug/color")
        assert response.status_code == 200
        data = response.json()
        assert "rgb" in data
        assert len(data["rgb"]) == 3
