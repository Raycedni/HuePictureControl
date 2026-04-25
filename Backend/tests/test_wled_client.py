"""Unit tests for services.wled_client.fetch_wled_info (Plan 17-03 Task 2)."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.wled_client import fetch_wled_info


def _make_httpx_client(response):
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


@pytest.mark.asyncio
async def test_fetch_wled_info_parses_full_response():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={
        "name": "My WLED",
        "leds": {"count": 300},
        "ver": "0.14.0",
        "mac": "aa:bb:cc:dd:ee:ff",
    })
    mock_client = _make_httpx_client(resp)
    with patch("services.wled_client.httpx.AsyncClient", return_value=mock_client):
        info = await fetch_wled_info("192.168.1.50")
    assert info == {
        "name": "My WLED",
        "led_count": 300,
        "ver": "0.14.0",
        "mac": "aa:bb:cc:dd:ee:ff",
    }
    mock_client.get.assert_awaited_once_with("http://192.168.1.50/json/info")


@pytest.mark.asyncio
async def test_fetch_wled_info_defaults_on_partial_response():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={})
    with patch(
        "services.wled_client.httpx.AsyncClient",
        return_value=_make_httpx_client(resp),
    ):
        info = await fetch_wled_info("10.0.0.5")
    assert info["name"] == "WLED"
    assert info["led_count"] == 0
    assert info["ver"] == ""
    assert info["mac"] == ""


@pytest.mark.asyncio
async def test_fetch_wled_info_led_count_is_int():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"leds": {"count": "250"}})
    with patch(
        "services.wled_client.httpx.AsyncClient",
        return_value=_make_httpx_client(resp),
    ):
        info = await fetch_wled_info("10.0.0.5")
    assert info["led_count"] == 250
    assert isinstance(info["led_count"], int)


@pytest.mark.asyncio
async def test_fetch_wled_info_raise_for_status_propagates():
    resp = MagicMock()
    resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
        "404", request=MagicMock(), response=MagicMock(status_code=404)
    ))
    with patch(
        "services.wled_client.httpx.AsyncClient",
        return_value=_make_httpx_client(resp),
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_wled_info("10.0.0.5")


@pytest.mark.asyncio
async def test_fetch_wled_info_connect_error_propagates():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with patch("services.wled_client.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.ConnectError):
            await fetch_wled_info("10.0.0.5")


@pytest.mark.asyncio
async def test_fetch_wled_info_timeout_propagates():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    with patch("services.wled_client.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.TimeoutException):
            await fetch_wled_info("10.0.0.5")


@pytest.mark.asyncio
async def test_fetch_wled_info_default_timeout_is_5_seconds():
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={})
    mock_client = _make_httpx_client(resp)
    with patch(
        "services.wled_client.httpx.AsyncClient",
        return_value=mock_client,
    ) as Ctor:
        await fetch_wled_info("10.0.0.5")
    timeout_kw = Ctor.call_args.kwargs.get("timeout")
    timeout_pos = Ctor.call_args.args
    assert timeout_kw == 5.0 or 5.0 in timeout_pos or 5 in timeout_pos
