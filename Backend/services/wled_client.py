"""WLED JSON API client.

Single-responsibility httpx wrappers for the WLED JSON HTTP API.

Exports:
    fetch_wled_info  -- Async httpx GET /json/info returning
                        {name, led_count, ver, mac}. Called at device
                        registration (``POST /api/wled/devices``) and at no
                        other point — the UDP realtime pipeline does not poll
                        the JSON API.
    fetch_wled_state -- Async httpx GET /json/state returning a normalized
                        list of segments [{seg_index, start_led, stop_led,
                        name}]. Called by the refresh handler (Plan 19.1-04).
                        Per D-01, D-08, D-11: EXCLUSIVE seg.stop is converted
                        to INCLUSIVE stop_led at the parse boundary, and
                        array index is the canonical seg_index (seg.id is
                        ignored — see 19.1-RESEARCH.md §Defensive Parsing).
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


async def fetch_wled_state(ip: str, timeout: float = 5.0) -> list[dict]:
    """GET ``http://{ip}/json/state`` and return a normalized seg[] list.

    Each element is a dict ``{"seg_index": int, "start_led": int, "stop_led": int,
    "name": str | None}``. ``stop_led`` is INCLUSIVE — converted from WLED's
    exclusive ``seg.stop`` semantics (kno.wled.ge: "The Stop LED is not included
    in the Segment"). Phase 19.1 D-01, D-08, D-11.

    Defensive parse:
      - ``seg`` may be returned as object or array (WLED JSON API accepts both).
      - Missing ``seg`` key yields ``[]``; some firmwares nest it under ``state.seg``.
      - Per-segment ``n`` may be absent — caller falls back via ``segmentName``.
      - Segments with ``stop <= start`` are deleted-by-WLED — skipped.
      - Per-segment ``id`` field is IGNORED; array index is the canonical ``seg_index``.

    Raises:
        httpx.HTTPStatusError:  device returned a non-2xx response.
        httpx.ConnectError:     device unreachable.
        httpx.TimeoutException: device did not respond within ``timeout`` seconds.
        ValueError:             response body is not parseable JSON or top-level is not a dict.
    """
    url = f"http://{ip}/json/state"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        try:
            data = resp.json()
        except ValueError as exc:
            raise ValueError(f"WLED /json/state returned non-JSON body: {exc}")
    if not isinstance(data, dict):
        raise ValueError(
            f"WLED /json/state returned non-dict body: {type(data).__name__}"
        )
    seg_raw = data.get("seg")
    if seg_raw is None:
        nested = data.get("state")
        if isinstance(nested, dict):
            seg_raw = nested.get("seg")
    if seg_raw is None:
        return []
    if isinstance(seg_raw, dict):
        seg_raw = [seg_raw]
    if not isinstance(seg_raw, list):
        raise ValueError(
            f"seg field has unexpected type: {type(seg_raw).__name__}"
        )

    out: list[dict] = []
    for seg_index, seg in enumerate(seg_raw):
        if not isinstance(seg, dict):
            logger.warning("WLED %s seg[%d] is not a dict, skipping", ip, seg_index)
            continue
        start = seg.get("start")
        stop = seg.get("stop")
        if start is None or stop is None:
            seg_len = seg.get("len")
            if start is not None and seg_len is not None:
                stop = int(start) + int(seg_len)
            else:
                logger.warning(
                    "WLED %s seg[%d] missing start/stop/len, skipping",
                    ip,
                    seg_index,
                )
                continue
        try:
            start_int = int(start)
            stop_int = int(stop)
        except (TypeError, ValueError):
            logger.warning(
                "WLED %s seg[%d] start/stop not int-coercible", ip, seg_index
            )
            continue
        if stop_int <= start_int:
            continue
        name = seg.get("n")
        out.append(
            {
                "seg_index": seg_index,
                "start_led": start_int,
                "stop_led": stop_int - 1,
                "name": name if isinstance(name, str) else None,
            }
        )
    return out
