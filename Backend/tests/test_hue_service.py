"""Unit tests for Backend/services/hue_client.py"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestPairWithBridge:
    def test_pair_success(self):
        from services.hue_client import pair_with_bridge

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"success": {"username": "test-user", "clientkey": "AABBCCDD"}}
        ]

        with patch("services.hue_client.requests.post", return_value=mock_response):
            result = pair_with_bridge("192.168.1.100")

        assert result["username"] == "test-user"
        assert result["clientkey"] == "AABBCCDD"

    def test_pair_link_button_not_pressed(self):
        from services.hue_client import pair_with_bridge

        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"error": {"type": 101, "description": "link button not pressed"}}
        ]

        with patch("services.hue_client.requests.post", return_value=mock_response):
            with pytest.raises(ValueError) as exc_info:
                pair_with_bridge("192.168.1.100")

        assert "link button" in str(exc_info.value).lower()


class TestFetchBridgeMetadata:
    def test_fetch_bridge_metadata(self):
        from services.hue_client import fetch_bridge_metadata

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "bridge_id": "abc",
                    "id": "rid-123",
                    "owner": {"rid": "app-456"},
                    "swversion": 1968100080,
                    "metadata": {"name": "My Bridge"},
                }
            ]
        }

        with patch("services.hue_client.requests.get", return_value=mock_response):
            result = fetch_bridge_metadata("192.168.1.100", "test-user")

        assert result["bridge_id"] == "abc"
        assert result["rid"] == "rid-123"
        assert result["hue_app_id"] == "app-456"
        assert result["swversion"] == 1968100080
        assert result["name"] == "My Bridge"


class TestListEntertainmentConfigs:
    @pytest.mark.asyncio
    async def test_list_entertainment_configs(self):
        from services.hue_client import list_entertainment_configs

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "cfg-1",
                    "metadata": {"name": "TV"},
                    "status": "inactive",
                    "channels": [{"channel_id": 0}, {"channel_id": 1}],
                }
            ]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch("services.hue_client.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await list_entertainment_configs("192.168.1.100", "test-user")

        assert len(result) == 1
        assert result[0]["id"] == "cfg-1"
        assert result[0]["name"] == "TV"
        assert result[0]["status"] == "inactive"
        assert result[0]["channel_count"] == 2


class TestListLights:
    @pytest.mark.asyncio
    async def test_list_lights(self):
        from services.hue_client import list_lights

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "id": "light-1",
                    "metadata": {"name": "Strip"},
                    "type": "light",
                }
            ]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch("services.hue_client.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__.return_value = mock_client
            result = await list_lights("192.168.1.100", "test-user")

        assert len(result) == 1
        assert result[0]["id"] == "light-1"
        assert result[0]["name"] == "Strip"
        assert result[0]["type"] == "light"
