"""WLED JSON API client.

Single-responsibility httpx wrapper for ``GET http://{ip}/json/info``. Called
at device registration (``POST /api/wled/devices``) and at no other point —
the UDP realtime pipeline does not poll the JSON API.

Exports:
    fetch_wled_info -- Async httpx GET /json/info returning
                       {name, led_count, ver, mac}
"""
import logging

import httpx

logger = logging.getLogger(__name__)


async def fetch_wled_info(ip: str, timeout: float = 5.0) -> dict:
    """GET ``http://{ip}/json/info`` and return ``{name, led_count, ver, mac}``.

    Defensive parse: missing fields default to safe values
    (``name`` -> ``"WLED"``, ``led_count`` -> ``0``). Caller (Plan 17-07
    router) MUST reject ``led_count == 0`` before persisting.

    Raises:
        httpx.HTTPStatusError:  device returned a non-2xx response.
        httpx.ConnectError:     device unreachable.
        httpx.TimeoutException: device did not respond within ``timeout`` seconds.
    """
    url = f"http://{ip}/json/info"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return {
        "name": data.get("name", "WLED"),
        "led_count": int(data.get("leds", {}).get("count", 0)),
        "ver": data.get("ver", ""),
        "mac": data.get("mac", ""),
    }
