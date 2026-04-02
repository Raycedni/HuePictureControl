"""Hue Bridge REST endpoints: pairing, status, config/light discovery."""
import logging
import requests
from fastapi import APIRouter, HTTPException, Request

from models.hue import (
    BridgeStatusResponse,
    EntertainmentConfigResponse,
    LightResponse,
    PairRequest,
    PairResponse,
)
from services.hue_client import (
    build_light_segment_map,
    fetch_bridge_metadata,
    fetch_entertainment_config_channels,
    list_entertainment_configs,
    list_lights,
    pair_with_bridge,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hue", tags=["hue"])


@router.post("/pair", response_model=PairResponse)
async def pair(body: PairRequest, request: Request) -> PairResponse:
    """Pair with a Hue Bridge and persist all credentials to the DB."""
    db = request.app.state.db

    try:
        credentials = pair_with_bridge(body.bridge_ip)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        raise HTTPException(status_code=502, detail=f"Bridge unreachable: {exc}")

    username = credentials["username"]
    clientkey = credentials["clientkey"]

    try:
        meta = fetch_bridge_metadata(body.bridge_ip, username)
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        raise HTTPException(status_code=502, detail=f"Bridge unreachable: {exc}")

    await db.execute(
        """
        INSERT OR REPLACE INTO bridge_config
            (id, bridge_id, rid, ip_address, username, hue_app_id, client_key, swversion, name)
        VALUES (1, :bridge_id, :rid, :ip_address, :username, :hue_app_id, :client_key, :swversion, :name)
        """,
        {
            "bridge_id": meta["bridge_id"],
            "rid": meta["rid"],
            "ip_address": body.bridge_ip,
            "username": username,
            "hue_app_id": meta["hue_app_id"],
            "client_key": clientkey,
            "swversion": meta["swversion"],
            "name": meta["name"],
        },
    )
    await db.commit()

    return PairResponse(
        status="paired",
        bridge_ip=body.bridge_ip,
        bridge_name=meta["name"],
    )


@router.get("/status", response_model=BridgeStatusResponse)
async def status(request: Request) -> BridgeStatusResponse:
    """Return current pairing state."""
    db = request.app.state.db

    async with db.execute("SELECT ip_address, name FROM bridge_config WHERE id=1") as cursor:
        row = await cursor.fetchone()

    if row is None:
        return BridgeStatusResponse(paired=False)

    return BridgeStatusResponse(
        paired=True,
        bridge_ip=row["ip_address"],
        bridge_name=row["name"],
    )


@router.delete("/bridge", status_code=204)
async def delete_bridge(request: Request):
    """Delete stored bridge credentials, effectively unpairing."""
    db = request.app.state.db
    await db.execute("DELETE FROM bridge_config WHERE id=1")
    await db.commit()


@router.get("/configs", response_model=list[EntertainmentConfigResponse])
async def configs(request: Request) -> list[EntertainmentConfigResponse]:
    """Return entertainment configurations from the paired bridge."""
    db = request.app.state.db

    async with db.execute(
        "SELECT ip_address, username FROM bridge_config WHERE id=1"
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=400, detail="Bridge not paired")

    raw = await list_entertainment_configs(row["ip_address"], row["username"])
    return [EntertainmentConfigResponse(**item) for item in raw]


@router.get("/config/{config_id}/channels")
async def config_channels(config_id: str, request: Request) -> list[dict]:
    """Return full channel-to-light mapping for a given entertainment configuration.

    For each channel, returns:
      - channel_id, segment_index
      - light_id, light_name, light_type
      - is_gradient, segment_count (how many channels share this light's entertainment service)

    The mapping resolves: channel.service_rid (entertainment service)
    -> device.services -> light service ID.
    """
    import httpx as _httpx

    db = request.app.state.db

    async with db.execute(
        "SELECT ip_address, username FROM bridge_config WHERE id=1"
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=400, detail="Bridge not paired")

    bridge_ip = row["ip_address"]
    username = row["username"]

    # Fetch channels (with service_rid and segment_index)
    channels = await fetch_entertainment_config_channels(bridge_ip, username, config_id)

    # Fetch lights (with is_gradient and points_capable)
    lights_list = await list_lights(bridge_ip, username)
    lights_by_id = {light["id"]: light for light in lights_list}

    # Build segment map: entertainment service_rid -> segment count
    segment_map = build_light_segment_map(channels)

    # Build entertainment_rid -> light_id mapping via device data
    # Each device has a "services" array with {rid, rtype} entries
    # We match rtype="entertainment" entries to rtype="light" entries on the same device
    headers = {"hue-application-key": username}
    async with _httpx.AsyncClient(verify=False, timeout=10) as client:
        device_resp = await client.get(
            f"https://{bridge_ip}/clip/v2/resource/device", headers=headers
        )
    device_data = device_resp.json()

    # For each device, collect all service RIDs by type
    ent_rid_to_light_id: dict[str, str] = {}
    for device in device_data.get("data", []):
        services = device.get("services", [])
        light_rids = [s["rid"] for s in services if s.get("rtype") == "light"]
        ent_rids = [s["rid"] for s in services if s.get("rtype") == "entertainment"]
        # Each device should have at most one light service and one entertainment service
        if light_rids and ent_rids:
            for ent_rid in ent_rids:
                ent_rid_to_light_id[ent_rid] = light_rids[0]
                logger.info(
                    "Mapped entertainment_rid=%s -> light_id=%s (device %s)",
                    ent_rid,
                    light_rids[0],
                    device.get("id", "?"),
                )

    # Assemble response: one entry per channel from the bridge config
    result = []
    for ch in channels:
        service_rid = ch.get("service_rid")
        light_id = ent_rid_to_light_id.get(service_rid) if service_rid else None
        light = lights_by_id.get(light_id) if light_id else None
        segment_count = segment_map.get(service_rid, 1) if service_rid else 1

        result.append({
            "channel_id": ch["channel_id"],
            "segment_index": ch["segment_index"],
            "light_id": light_id,
            "light_name": light["name"] if light else None,
            "light_type": light["type"] if light else None,
            "is_gradient": light["is_gradient"] if light else False,
            "segment_count": segment_count,
        })

    # Re-number segment_index per light to be contiguous (0, 1, 2...)
    by_light: dict[str, list[dict]] = {}
    for item in result:
        key = item["light_id"] or f"_ch{item['channel_id']}"
        by_light.setdefault(key, []).append(item)
    for group in by_light.values():
        group.sort(key=lambda x: x["segment_index"])
        for i, item in enumerate(group):
            item["segment_index"] = i

    return result


@router.get("/lights", response_model=list[LightResponse])
async def lights(request: Request) -> list[LightResponse]:
    """Return lights discovered from the paired bridge."""
    db = request.app.state.db

    async with db.execute(
        "SELECT ip_address, username FROM bridge_config WHERE id=1"
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=400, detail="Bridge not paired")

    raw = await list_lights(row["ip_address"], row["username"])
    return [LightResponse(**item) for item in raw]
