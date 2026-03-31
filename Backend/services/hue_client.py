"""Hue Bridge client functions for pairing, metadata fetch, and device discovery."""
import asyncio
import collections
import logging
import urllib3
import requests
import httpx

logger = logging.getLogger(__name__)

# Suppress InsecureRequestWarning for self-signed bridge certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def pair_with_bridge(bridge_ip: str) -> dict:
    """POST to bridge /api to obtain username and clientkey.

    Args:
        bridge_ip: IP address of the Hue Bridge.

    Returns:
        dict with 'username' and 'clientkey'.

    Raises:
        ValueError: If the link button has not been pressed or another bridge error occurs.
        requests.RequestException: If the bridge is unreachable.
    """
    url = f"https://{bridge_ip}/api"
    payload = {"devicetype": "HuePictureControl#backend", "generateclientkey": True}
    response = requests.post(url, json=payload, verify=False, timeout=10)
    data = response.json()

    # Hue v1 API returns a list; first element is success or error
    if not data:
        raise ValueError("Empty response from bridge during pairing")

    first = data[0]
    if "error" in first:
        error = first["error"]
        description = error.get("description", "Unknown error")
        raise ValueError(f"Bridge pairing error: {description}")

    success = first.get("success", {})
    return {
        "username": success["username"],
        "clientkey": success["clientkey"],
    }


def fetch_bridge_metadata(bridge_ip: str, username: str) -> dict:
    """Fetch bridge identification via CLIP v2 /resource/bridge.

    Args:
        bridge_ip: IP address of the Hue Bridge.
        username: Application key (username) obtained during pairing.

    Returns:
        dict with bridge_id, rid, hue_app_id, swversion, name.
    """
    url = f"https://{bridge_ip}/clip/v2/resource/bridge"
    headers = {"hue-application-key": username}
    response = requests.get(url, headers=headers, verify=False, timeout=10)
    data = response.json()

    bridge_data = data["data"][0]
    return {
        "bridge_id": bridge_data.get("bridge_id", ""),
        "rid": bridge_data.get("id", ""),
        "hue_app_id": bridge_data.get("owner", {}).get("rid", ""),
        "swversion": bridge_data.get("swversion", bridge_data.get("software_version", "0")),
        "name": bridge_data.get("metadata", {}).get("name", "Hue Bridge"),
    }


async def list_entertainment_configs(bridge_ip: str, username: str) -> list[dict]:
    """List entertainment configurations from the paired bridge.

    Args:
        bridge_ip: IP address of the Hue Bridge.
        username: Application key obtained during pairing.

    Returns:
        List of dicts with id, name, status, channel_count.
    """
    url = f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration"
    headers = {"hue-application-key": username}

    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        response = await client.get(url, headers=headers)
        data = response.json()

    configs = []
    for item in data.get("data", []):
        configs.append({
            "id": item["id"],
            "name": item["metadata"]["name"],
            "status": item.get("status", "inactive"),
            "channel_count": len(item.get("channels", [])),
        })
    return configs


async def list_lights(bridge_ip: str, username: str) -> list[dict]:
    """List lights from the paired bridge.

    Fetches both /resource/light and /resource/device so we can resolve
    each light's product archetype (e.g. "hue play", "lightstrip plus").
    The light resource's metadata.archetype is often missing; the device
    resource's product_data.product_archetype is reliable.

    Args:
        bridge_ip: IP address of the Hue Bridge.
        username: Application key obtained during pairing.

    Returns:
        List of dicts with id, name, type.
    """
    headers = {"hue-application-key": username}

    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        light_resp, device_resp = await asyncio.gather(
            client.get(f"https://{bridge_ip}/clip/v2/resource/light", headers=headers),
            client.get(f"https://{bridge_ip}/clip/v2/resource/device", headers=headers),
        )

    light_data = light_resp.json()
    device_data = device_resp.json()

    # Build lookup: service RID -> device product archetype
    rid_to_archetype: dict[str, str] = {}
    for device in device_data.get("data", []):
        archetype = (
            device.get("product_data", {})
            .get("product_archetype", "unknown")
            .replace("_", " ")
        )
        for service in device.get("services", []):
            rid_to_archetype[service.get("rid", "")] = archetype

    lights = []
    for item in light_data.get("data", []):
        light_id = item["id"]
        light_type = rid_to_archetype.get(light_id, "light")
        gradient = item.get("gradient")
        is_gradient = gradient is not None and gradient.get("points_capable", 0) > 0
        points_capable = gradient.get("points_capable", 0) if gradient else 0
        lights.append({
            "id": light_id,
            "name": item["metadata"]["name"],
            "type": light_type,
            "is_gradient": is_gradient,
            "points_capable": points_capable,
        })
    return lights


async def activate_entertainment_config(bridge_ip: str, username: str, config_id: str) -> None:
    """Activate an entertainment configuration on the bridge (action=start).

    Args:
        bridge_ip: IP address of the Hue Bridge.
        username: Application key obtained during pairing.
        config_id: UUID of the entertainment configuration to activate.

    Raises:
        httpx.HTTPStatusError: If the bridge returns a non-2xx response.
    """
    url = f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration/{config_id}"
    headers = {"hue-application-key": username}
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.put(url, json={"action": "start"}, headers=headers)
        resp.raise_for_status()


async def fetch_entertainment_config_channels(
    bridge_ip: str, username: str, config_id: str
) -> list[dict]:
    """Fetch channel position data for a specific entertainment configuration.

    Args:
        bridge_ip: IP address of the Hue Bridge.
        username: Application key obtained during pairing.
        config_id: UUID of the entertainment configuration.

    Returns:
        List of dicts with channel_id (int) and position ({x, y, z}).

    Raises:
        httpx.HTTPStatusError: If the bridge returns a non-2xx response.
    """
    url = f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration/{config_id}"
    headers = {"hue-application-key": username}

    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()

    channels = []
    config_data = data.get("data", [{}])[0]
    for ch in config_data.get("channels", []):
        members = ch.get("members", [])
        if members:
            first_member = members[0]
            service_rid = first_member.get("service", {}).get("rid", None)
            segment_index = first_member.get("index", 0)
        else:
            service_rid = None
            segment_index = 0
        channels.append({
            "channel_id": ch["channel_id"],
            "position": ch.get("position", {"x": 0.0, "y": 0.0, "z": 0.0}),
            "service_rid": service_rid,
            "segment_index": segment_index,
        })
    return channels


def build_light_segment_map(channels: list[dict]) -> dict[str, int]:
    """Map entertainment service_rid -> segment count from extended channel list.

    Args:
        channels: List of channel dicts with service_rid field (from
            fetch_entertainment_config_channels).

    Returns:
        dict mapping service_rid (str) to segment count (int).
        Channels with service_rid=None are skipped.
    """
    counts: dict[str, int] = collections.defaultdict(int)
    for ch in channels:
        rid = ch.get("service_rid")
        if rid is not None:
            counts[rid] += 1
    return dict(counts)


async def deactivate_entertainment_config(bridge_ip: str, username: str, config_id: str) -> None:
    """Deactivate an entertainment configuration on the bridge (action=stop).

    Best-effort: logs a warning on failure but does not raise, so shutdown
    sequences are never interrupted by a bridge communication error.

    Args:
        bridge_ip: IP address of the Hue Bridge.
        username: Application key obtained during pairing.
        config_id: UUID of the entertainment configuration to deactivate.
    """
    url = f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration/{config_id}"
    headers = {"hue-application-key": username}
    try:
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            await client.put(url, json={"action": "stop"}, headers=headers)
    except Exception:
        logger.warning("Failed to deactivate entertainment config %s (best-effort)", config_id)
