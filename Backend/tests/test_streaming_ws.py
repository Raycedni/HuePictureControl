"""Tests for the /ws/status WebSocket endpoint."""
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock


class TestWsStatusEndpoint:
    def test_websocket_connects_and_receives_initial_metrics(self, streaming_ws_client):
        """Connecting to /ws/status yields an initial JSON metrics snapshot."""
        with streaming_ws_client.websocket_connect("/ws/status") as ws:
            data = ws.receive_json()
        assert isinstance(data, dict)
        assert "state" in data

    def test_websocket_initial_metrics_has_expected_keys(self, streaming_ws_client):
        """Initial metrics snapshot contains fps, latency_ms, packets_sent, seq fields."""
        with streaming_ws_client.websocket_connect("/ws/status") as ws:
            data = ws.receive_json()
        expected_keys = {"state", "fps", "latency_ms", "packets_sent", "seq"}
        assert expected_keys.issubset(data.keys())

    def test_websocket_disconnect_handled_without_error(self, streaming_ws_client):
        """Closing the WebSocket connection does not raise an exception."""
        with streaming_ws_client.websocket_connect("/ws/status") as ws:
            ws.receive_json()  # receive initial snapshot, then close
        # If disconnect were not handled, the test would raise here

    def test_multiple_connections_accepted(self, streaming_ws_client):
        """Multiple simultaneous connections to /ws/status all receive metrics."""
        with streaming_ws_client.websocket_connect("/ws/status") as ws1:
            data1 = ws1.receive_json()
            with streaming_ws_client.websocket_connect("/ws/status") as ws2:
                data2 = ws2.receive_json()
        assert "state" in data1
        assert "state" in data2
