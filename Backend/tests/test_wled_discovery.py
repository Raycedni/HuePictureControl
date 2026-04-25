"""Unit tests for services.wled_discovery (Plan 17-03 Task 3)."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.wled_discovery import WLED_SERVICE_TYPE, scan_for_wled_devices


def test_service_type_constant():
    assert WLED_SERVICE_TYPE == "_wled._tcp.local."


@pytest.mark.asyncio
async def test_scan_returns_empty_list_on_timeout():
    """With no devices and a 0.05s timeout, returns [] within ~0.3s."""
    mock_aiozc = AsyncMock()
    mock_aiozc.zeroconf = MagicMock()
    mock_aiozc.async_close = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.async_cancel = AsyncMock()

    with patch("services.wled_discovery.AsyncZeroconf", return_value=mock_aiozc), \
         patch("services.wled_discovery.AsyncServiceBrowser", return_value=mock_browser):
        start = time.monotonic()
        result = await scan_for_wled_devices(timeout_seconds=0.05)
        elapsed = time.monotonic() - start

    assert result == []
    assert elapsed < 0.3, f"timeout not honored: {elapsed:.3f}s"
    mock_browser.async_cancel.assert_awaited_once()
    mock_aiozc.async_close.assert_awaited_once()


@pytest.mark.asyncio
async def test_scan_returns_list_shape():
    """Function returns a list (possibly empty) of dicts with exact key set."""
    mock_aiozc = AsyncMock()
    mock_aiozc.zeroconf = MagicMock()
    mock_aiozc.async_close = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.async_cancel = AsyncMock()

    with patch("services.wled_discovery.AsyncZeroconf", return_value=mock_aiozc), \
         patch("services.wled_discovery.AsyncServiceBrowser", return_value=mock_browser):
        result = await scan_for_wled_devices(timeout_seconds=0.05)

    assert isinstance(result, list)
    for entry in result:
        assert set(entry.keys()) == {"ip", "name"}


@pytest.mark.asyncio
async def test_scan_cleans_up_on_exception():
    """If asyncio.sleep raises, browser cancel + aiozc close still run via finally."""
    mock_aiozc = AsyncMock()
    mock_aiozc.zeroconf = MagicMock()
    mock_aiozc.async_close = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.async_cancel = AsyncMock()

    async def boom(_):
        raise RuntimeError("simulated")

    with patch("services.wled_discovery.AsyncZeroconf", return_value=mock_aiozc), \
         patch("services.wled_discovery.AsyncServiceBrowser", return_value=mock_browser), \
         patch("services.wled_discovery.asyncio.sleep", side_effect=boom):
        with pytest.raises(RuntimeError):
            await scan_for_wled_devices(timeout_seconds=0.05)

    mock_browser.async_cancel.assert_awaited_once()
    mock_aiozc.async_close.assert_awaited_once()
