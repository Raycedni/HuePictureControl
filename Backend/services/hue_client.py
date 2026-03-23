"""Hue Bridge client functions for pairing, metadata fetch, and device discovery."""
import urllib3
import requests
import httpx

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
        "bridge_id": bridge_data["bridge_id"],
        "rid": bridge_data["id"],
        "hue_app_id": bridge_data["owner"]["rid"],
        "swversion": bridge_data["swversion"],
        "name": bridge_data["metadata"]["name"],
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

    Args:
        bridge_ip: IP address of the Hue Bridge.
        username: Application key obtained during pairing.

    Returns:
        List of dicts with id, name, type.
    """
    url = f"https://{bridge_ip}/clip/v2/resource/light"
    headers = {"hue-application-key": username}

    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        response = await client.get(url, headers=headers)
        data = response.json()

    lights = []
    for item in data.get("data", []):
        lights.append({
            "id": item["id"],
            "name": item["metadata"]["name"],
            "type": item.get("type", "light"),
        })
    return lights
