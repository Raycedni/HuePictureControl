"""Unit tests for services.wled_client.fetch_wled_info (Plan 17-03 Task 2)
and services.wled_client.fetch_wled_state (Plan 19.1-02 Task 1)."""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.wled_client import fetch_wled_info


def _install_mock_transport(monkeypatch, handler):
    """Inject an ``httpx.MockTransport`` into every ``httpx.AsyncClient``.

    Used by the Plan 19.1-02 ``fetch_wled_state`` tests so each handler
    closure can decide the mock response (status, json body, exceptions)
    without rebuilding the AsyncClient mock per test.
    """
    transport = httpx.MockTransport(handler)
    import httpx as _httpx
    original_init = _httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(_httpx.AsyncClient, "__init__", patched_init)


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


# ============================================================================
# Phase 19.1: fetch_wled_state defensive parsing (D-01, D-08, D-11)
# Test cases drawn from 19.1-RESEARCH.md §"Defensive Parsing" edge-case table.
# Stubs gated via pytest.importorskip + hasattr — emit SKIPPED until Plan 02
# lands `fetch_wled_state` in services.wled_client.
# ============================================================================


@pytest.mark.asyncio
async def test_fetch_wled_state_single_segment(monkeypatch):
    from services.wled_client import fetch_wled_state

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/json/state"
        return httpx.Response(200, json={"seg": [{"start": 0, "stop": 30, "n": "Strip"}]})

    _install_mock_transport(monkeypatch, handler)
    result = await fetch_wled_state("192.168.1.50")
    assert result == [{"seg_index": 0, "start_led": 0, "stop_led": 29, "name": "Strip"}]


@pytest.mark.asyncio
async def test_fetch_wled_state_stop_exclusive_converted_to_inclusive(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(200, json={"seg": [{"start": 0, "stop": 1}]}),
    )
    result = await fetch_wled_state("1.2.3.4")
    assert len(result) == 1
    assert result[0]["start_led"] == 0
    assert result[0]["stop_led"] == 0  # single-LED segment


@pytest.mark.asyncio
async def test_fetch_wled_state_missing_n_returns_none(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(200, json={"seg": [{"start": 0, "stop": 30}]}),
    )
    result = await fetch_wled_state("1.2.3.4")
    assert result[0]["name"] is None


@pytest.mark.asyncio
async def test_fetch_wled_state_ignores_seg_id_uses_array_index(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            json={
                "seg": [
                    {"id": 9, "start": 0, "stop": 30},
                    {"id": 0, "start": 30, "stop": 60},
                ]
            },
        ),
    )
    result = await fetch_wled_state("1.2.3.4")
    assert [r["seg_index"] for r in result] == [0, 1]  # D-11: array index wins


@pytest.mark.asyncio
async def test_fetch_wled_state_empty_seg_returns_empty_list(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(200, json={"seg": []}),
    )
    assert await fetch_wled_state("1.2.3.4") == []


@pytest.mark.asyncio
async def test_fetch_wled_state_missing_seg_returns_empty_list(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(monkeypatch, lambda req: httpx.Response(200, json={}))
    assert await fetch_wled_state("1.2.3.4") == []


@pytest.mark.asyncio
async def test_fetch_wled_state_dict_seg_normalizes_to_list(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(200, json={"seg": {"start": 0, "stop": 30}}),
    )
    result = await fetch_wled_state("1.2.3.4")
    assert len(result) == 1
    assert result[0]["seg_index"] == 0
    assert result[0]["start_led"] == 0
    assert result[0]["stop_led"] == 29


@pytest.mark.asyncio
async def test_fetch_wled_state_invalid_range_skipped(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(200, json={"seg": [{"start": 10, "stop": 10}]}),
    )
    assert await fetch_wled_state("1.2.3.4") == []


@pytest.mark.asyncio
async def test_fetch_wled_state_timeout_propagates(monkeypatch):
    from services.wled_client import fetch_wled_state

    def handler(req):
        raise httpx.TimeoutException("simulated timeout")

    _install_mock_transport(monkeypatch, handler)
    with pytest.raises(httpx.TimeoutException):
        await fetch_wled_state("1.2.3.4")


@pytest.mark.asyncio
async def test_fetch_wled_state_http_error_propagates(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(monkeypatch, lambda req: httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        await fetch_wled_state("1.2.3.4")


@pytest.mark.asyncio
async def test_fetch_wled_state_non_json_raises_value_error(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(
            200, text="garbage", headers={"content-type": "text/plain"}
        ),
    )
    with pytest.raises(ValueError):
        await fetch_wled_state("1.2.3.4")


@pytest.mark.asyncio
async def test_fetch_wled_state_non_dict_top_raises(monkeypatch):
    from services.wled_client import fetch_wled_state

    _install_mock_transport(
        monkeypatch,
        lambda req: httpx.Response(200, json=[1, 2, 3]),
    )
    with pytest.raises(ValueError):
        await fetch_wled_state("1.2.3.4")


@pytest.mark.asyncio
async def test_fetch_wled_state_default_timeout_is_5s(monkeypatch):
    from services.wled_client import fetch_wled_state

    captured = {}
    import httpx as _httpx
    original_init = _httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        kwargs["transport"] = httpx.MockTransport(
            lambda req: httpx.Response(200, json={"seg": []})
        )
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(_httpx.AsyncClient, "__init__", patched_init)
    await fetch_wled_state("1.2.3.4")
    assert captured["timeout"] == 5.0
