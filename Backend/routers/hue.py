"""Hue Bridge REST endpoints: pairing, status, config/light discovery."""
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
    fetch_bridge_metadata,
    list_entertainment_configs,
    list_lights,
    pair_with_bridge,
)

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
