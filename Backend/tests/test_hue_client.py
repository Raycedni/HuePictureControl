"""Unit tests for hue_client activate/deactivate entertainment config helpers."""
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# fetch_entertainment_config_channels (extended with gradient member info)
# ---------------------------------------------------------------------------

def _make_channel_response(channels_data):
    """Build a mock httpx response for entertainment config with channels."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json = MagicMock(return_value={
        "data": [{"channels": channels_data}]
    })
    return mock_resp


def _make_httpx_client(response):
    """Build a mock httpx.AsyncClient that returns the given response on GET."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


@pytest.mark.asyncio
async def test_fetch_channels_returns_service_rid_and_segment_index():
    """fetch_entertainment_config_channels returns service_rid and segment_index from members[0]."""
    from services.hue_client import fetch_entertainment_config_channels

    channels_data = [
        {
            "channel_id": 0,
            "position": {"x": -0.5, "y": 0.0, "z": 0.0},
            "members": [
                {"service": {"rid": "ent-service-abc", "rtype": "entertainment"}, "index": 2}
            ],
        },
        {
            "channel_id": 1,
            "position": {"x": 0.5, "y": 0.0, "z": 0.0},
            "members": [
                {"service": {"rid": "ent-service-abc", "rtype": "entertainment"}, "index": 3}
            ],
        },
    ]

    resp = _make_channel_response(channels_data)
    mock_client = _make_httpx_client(resp)

    with patch("services.hue_client.httpx.AsyncClient", return_value=mock_client):
        channels = await fetch_entertainment_config_channels("192.168.1.1", "user", "cfg-001")

    assert len(channels) == 2
    assert channels[0]["service_rid"] == "ent-service-abc"
    assert channels[0]["segment_index"] == 2
    assert channels[1]["service_rid"] == "ent-service-abc"
    assert channels[1]["segment_index"] == 3


@pytest.mark.asyncio
async def test_fetch_channels_empty_members_returns_defaults():
    """fetch_entertainment_config_channels returns segment_index=0 and service_rid=None when members empty."""
    from services.hue_client import fetch_entertainment_config_channels

    channels_data = [
        {
            "channel_id": 0,
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "members": [],
        }
    ]

    resp = _make_channel_response(channels_data)
    mock_client = _make_httpx_client(resp)

    with patch("services.hue_client.httpx.AsyncClient", return_value=mock_client):
        channels = await fetch_entertainment_config_channels("192.168.1.1", "user", "cfg-001")

    assert len(channels) == 1
    assert channels[0]["service_rid"] is None
    assert channels[0]["segment_index"] == 0


# ---------------------------------------------------------------------------
# build_light_segment_map
# ---------------------------------------------------------------------------

def test_build_light_segment_map_counts_channels_per_rid():
    """build_light_segment_map returns {rid: count} for channels with same service_rid (3 times)."""
    from services.hue_client import build_light_segment_map

    channels = [
        {"channel_id": 0, "service_rid": "ent-rid-1", "segment_index": 0},
        {"channel_id": 1, "service_rid": "ent-rid-1", "segment_index": 1},
        {"channel_id": 2, "service_rid": "ent-rid-1", "segment_index": 2},
    ]

    result = build_light_segment_map(channels)
    assert result == {"ent-rid-1": 3}


def test_build_light_segment_map_unique_rids():
    """build_light_segment_map returns {rid: 1} for each unique service_rid."""
    from services.hue_client import build_light_segment_map

    channels = [
        {"channel_id": 0, "service_rid": "rid-a", "segment_index": 0},
        {"channel_id": 1, "service_rid": "rid-b", "segment_index": 0},
        {"channel_id": 2, "service_rid": "rid-c", "segment_index": 0},
    ]

    result = build_light_segment_map(channels)
    assert result == {"rid-a": 1, "rid-b": 1, "rid-c": 1}


def test_build_light_segment_map_skips_none_rid():
    """build_light_segment_map skips channels with service_rid=None."""
    from services.hue_client import build_light_segment_map

    channels = [
        {"channel_id": 0, "service_rid": None, "segment_index": 0},
        {"channel_id": 1, "service_rid": "rid-x", "segment_index": 0},
    ]

    result = build_light_segment_map(channels)
    assert result == {"rid-x": 1}
    assert None not in result


# ---------------------------------------------------------------------------
# list_lights (extended with gradient detection)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_lights_returns_is_gradient_true_for_gradient_device():
    """list_lights returns is_gradient=True and points_capable=5 for a light with gradient.points_capable=5."""
    from services.hue_client import list_lights

    light_resp_data = {
        "data": [
            {
                "id": "light-abc",
                "metadata": {"name": "Hue Play Bar"},
                "gradient": {"points_capable": 5},
            }
        ]
    }
    device_resp_data = {
        "data": [
            {
                "id": "device-abc",
                "product_data": {"product_archetype": "hue_play"},
                "services": [{"rid": "light-abc", "rtype": "light"}],
            }
        ]
    }

    mock_light_resp = MagicMock()
    mock_light_resp.json = MagicMock(return_value=light_resp_data)
    mock_device_resp = MagicMock()
    mock_device_resp.json = MagicMock(return_value=device_resp_data)

    mock_client = AsyncMock()
    # gather calls both concurrently; simulate via side_effect list
    mock_client.get = AsyncMock(side_effect=[mock_light_resp, mock_device_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.hue_client.httpx.AsyncClient", return_value=mock_client):
        lights = await list_lights("192.168.1.1", "user")

    assert len(lights) == 1
    assert lights[0]["is_gradient"] is True
    assert lights[0]["points_capable"] == 5


@pytest.mark.asyncio
async def test_list_lights_returns_is_gradient_false_without_gradient_field():
    """list_lights returns is_gradient=False and points_capable=0 for a light without gradient field."""
    from services.hue_client import list_lights

    light_resp_data = {
        "data": [
            {
                "id": "light-xyz",
                "metadata": {"name": "Hue Bulb"},
                # No "gradient" key
            }
        ]
    }
    device_resp_data = {
        "data": [
            {
                "id": "device-xyz",
                "product_data": {"product_archetype": "sultan_bulb"},
                "services": [{"rid": "light-xyz", "rtype": "light"}],
            }
        ]
    }

    mock_light_resp = MagicMock()
    mock_light_resp.json = MagicMock(return_value=light_resp_data)
    mock_device_resp = MagicMock()
    mock_device_resp.json = MagicMock(return_value=device_resp_data)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[mock_light_resp, mock_device_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.hue_client.httpx.AsyncClient", return_value=mock_client):
        lights = await list_lights("192.168.1.1", "user")

    assert len(lights) == 1
    assert lights[0]["is_gradient"] is False
    assert lights[0]["points_capable"] == 0


# ---------------------------------------------------------------------------
# activate_entertainment_config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_activate_sends_put_with_action_start():
    """activate_entertainment_config sends PUT with action=start."""
    from services.hue_client import activate_entertainment_config

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.hue_client.httpx.AsyncClient", return_value=mock_client):
        await activate_entertainment_config("192.168.1.10", "my-username", "cfg-001")

    mock_client.put.assert_called_once()
    call_kwargs = mock_client.put.call_args
    url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs.kwargs.get("url", call_kwargs[1].get("url"))
    # Get from positional or keyword
    args, kwargs = call_kwargs
    if args:
        url = args[0]
    else:
        url = kwargs["url"]
    assert "entertainment_configuration/cfg-001" in url
    assert kwargs.get("json") == {"action": "start"}
    assert kwargs.get("headers", {}).get("hue-application-key") == "my-username"


@pytest.mark.asyncio
async def test_activate_raises_on_non_2xx():
    """activate_entertainment_config raises on non-2xx (resp.raise_for_status)."""
    from services.hue_client import activate_entertainment_config

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
    )

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.hue_client.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            await activate_entertainment_config("192.168.1.10", "my-username", "cfg-001")


# ---------------------------------------------------------------------------
# deactivate_entertainment_config
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deactivate_sends_put_with_action_stop():
    """deactivate_entertainment_config sends PUT with action=stop."""
    from services.hue_client import deactivate_entertainment_config

    mock_resp = MagicMock()

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.hue_client.httpx.AsyncClient", return_value=mock_client):
        await deactivate_entertainment_config("192.168.1.10", "my-username", "cfg-001")

    mock_client.put.assert_called_once()
    args, kwargs = mock_client.put.call_args
    if args:
        url = args[0]
    else:
        url = kwargs["url"]
    assert "entertainment_configuration/cfg-001" in url
    assert kwargs.get("json") == {"action": "stop"}
    assert kwargs.get("headers", {}).get("hue-application-key") == "my-username"


@pytest.mark.asyncio
async def test_deactivate_does_not_raise_on_failure(caplog):
    """deactivate_entertainment_config is best-effort: logs warning, does not raise."""
    from services.hue_client import deactivate_entertainment_config
    import logging

    mock_client = AsyncMock()
    mock_client.put = AsyncMock(side_effect=Exception("Network error"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("services.hue_client.httpx.AsyncClient", return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="services.hue_client"):
            # Should NOT raise
            await deactivate_entertainment_config("192.168.1.10", "my-username", "cfg-001")

    assert any("best-effort" in r.message or "deactivate" in r.message.lower()
               for r in caplog.records), "Expected warning log for failed deactivate"
