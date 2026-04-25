"""WLED mDNS discovery via zeroconf AsyncServiceBrowser.

One-shot scan for ``_wled._tcp.local.`` services with a bounded timeout.
Invoked by ``POST /api/wled/scan``; never continuous background browsing.

Exports:
    WLED_SERVICE_TYPE        -- "_wled._tcp.local." constant
    scan_for_wled_devices    -- async one-shot scan, returns list of {ip, name}
"""
import asyncio
import logging

from zeroconf import ServiceStateChange
from zeroconf.asyncio import (
    AsyncServiceBrowser,
    AsyncServiceInfo,
    AsyncZeroconf,
)

logger = logging.getLogger(__name__)

WLED_SERVICE_TYPE: str = "_wled._tcp.local."


async def scan_for_wled_devices(timeout_seconds: float = 3.0) -> list[dict]:
    """Scan the local network for ``_wled._tcp.local.`` services.

    Always awaits the full ``timeout_seconds`` before returning so trickling
    mDNS advertisements are not missed by an early exit.

    Returns:
        List of ``{"ip": str, "name": str}`` dicts — empty if no devices
        respond in time (or the LAN has no WLED).
    """
    discovered: dict[str, dict] = {}
    aiozc = AsyncZeroconf()

    async def _resolve_service(name: str) -> None:
        info = AsyncServiceInfo(WLED_SERVICE_TYPE, name)
        try:
            if await info.async_request(aiozc.zeroconf, timeout=1000):
                addrs = info.parsed_addresses()
                if addrs:
                    discovered[name] = {
                        "ip": addrs[0],
                        "name": (info.server or name).rstrip("."),
                    }
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Failed to resolve WLED service %s: %s", name, exc)

    def on_state_change(zc, service_type, name, state_change):  # noqa: ARG001
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            asyncio.create_task(_resolve_service(name))

    browser = AsyncServiceBrowser(
        aiozc.zeroconf,
        [WLED_SERVICE_TYPE],
        handlers=[on_state_change],
    )
    try:
        await asyncio.sleep(timeout_seconds)
    finally:
        await browser.async_cancel()
        await aiozc.async_close()
        if not discovered:
            logger.info(
                "zeroconf scan for %s completed with zero results "
                "(timeout=%.1fs). If a device is known to be online, check "
                "for Docker bridge multicast blocking.",
                WLED_SERVICE_TYPE, timeout_seconds,
            )
    return list(discovered.values())
