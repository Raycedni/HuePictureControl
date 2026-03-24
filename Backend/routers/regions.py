"""Regions REST endpoints: auto-map from entertainment config, list regions.

Exports:
    router -- APIRouter for /api/regions prefix
"""
import json
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.auto_mapping import auto_map_entertainment_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/regions", tags=["regions"])


class AutoMapRequest(BaseModel):
    config_id: str
    polygon_half: float = 0.10


@router.post("/auto-map")
async def auto_map(body: AutoMapRequest, request: Request):
    """Trigger auto-mapping from a Hue entertainment configuration.

    Fetches channel positions from the bridge and writes normalized polygon
    regions to SQLite. Re-running with the same config_id is idempotent.

    Args:
        body: JSON body with ``config_id`` (required) and optional ``polygon_half``.

    Returns:
        200 JSON {"regions_created": N} on success.
        400 if bridge is not paired.
        422 if the entertainment config has no channels (ValueError).
        502 on bridge communication error.
    """
    db = request.app.state.db

    # Read bridge credentials from bridge_config table
    async with db.execute(
        "SELECT ip_address, username FROM bridge_config WHERE id=1"
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=400, detail="Bridge not paired")

    bridge_ip = row["ip_address"]
    username = row["username"]

    try:
        count = await auto_map_entertainment_config(
            db, bridge_ip, username, body.config_id, body.polygon_half
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Bridge communication error: {exc.response.status_code}",
        )

    response = {"regions_created": count}

    # Warn if streaming is currently active (new regions won't take effect until restart)
    streaming = getattr(request.app.state, "streaming", None)
    if streaming is not None and getattr(streaming, "state", "idle") != "idle":
        response["warning"] = (
            "Streaming is active — restart streaming to use new regions"
        )

    return response


@router.get("/")
async def list_regions(request: Request):
    """Return all stored regions with polygon coordinates.

    Returns:
        200 JSON list of regions: [{"id": str, "name": str, "polygon": [[x,y],...],
        "order_index": int}]
    """
    db = request.app.state.db

    async with db.execute(
        "SELECT id, name, polygon, order_index FROM regions ORDER BY order_index"
    ) as cursor:
        rows = await cursor.fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "polygon": json.loads(row["polygon"]),
            "order_index": row["order_index"],
        }
        for row in rows
    ]
