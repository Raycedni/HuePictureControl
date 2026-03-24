"""Unit tests for hue_client activate/deactivate entertainment config helpers."""
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
