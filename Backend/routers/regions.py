"""Regions REST endpoints: auto-map from entertainment config, list regions, CRUD.

Exports:
    router -- APIRouter for /api/regions prefix
"""
import json
import logging
import os
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from services.auto_mapping import auto_map_entertainment_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/regions", tags=["regions"])

# Minimum polygon area in normalized [0..1] space. Default 0.001 = 0.1% of canvas.
MIN_REGION_AREA = float(os.getenv("MIN_REGION_AREA", "0.001"))


def polygon_area(polygon: list[list[float]]) -> float:
    """Compute the area of a polygon using the shoelace formula.

    Args:
        polygon: List of [x, y] points in normalized [0..1] coordinates.

    Returns:
        Absolute area of the polygon.
    """
    n = len(polygon)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += polygon[i][0] * polygon[j][1]
        area -= polygon[j][0] * polygon[i][1]
    return abs(area) / 2.0


class AutoMapRequest(BaseModel):
    config_id: str
    polygon_half: float = 0.10


class CreateRegionRequest(BaseModel):
    name: str
    polygon: list[list[float]]
    light_id: str | None = None


class UpdateRegionRequest(BaseModel):
    name: str | None = None
    polygon: list[list[float]] | None = None
    light_id: str | None = None


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


@router.post("/", status_code=201)
async def create_region(body: CreateRegionRequest, request: Request):
    """Create a new region with polygon and optional light assignment.

    Args:
        body: JSON body with ``name``, ``polygon`` (list of [x,y] pairs), and
              optional ``light_id``.

    Returns:
        201 JSON with the created region object including generated id.
    """
    db = request.app.state.db

    if polygon_area(body.polygon) < MIN_REGION_AREA:
        raise HTTPException(
            status_code=422,
            detail=f"Region too small — minimum area is {MIN_REGION_AREA} (normalized)",
        )

    region_id = str(uuid.uuid4())

    # Determine next order_index
    async with db.execute("SELECT MAX(order_index) FROM regions") as cursor:
        row = await cursor.fetchone()
    max_index = row[0] if row[0] is not None else -1
    order_index = max_index + 1

    await db.execute(
        "INSERT INTO regions (id, name, polygon, order_index, light_id) VALUES (?, ?, ?, ?, ?)",
        (region_id, body.name, json.dumps(body.polygon), order_index, body.light_id),
    )
    await db.commit()

    return {
        "id": region_id,
        "name": body.name,
        "polygon": body.polygon,
        "order_index": order_index,
        "light_id": body.light_id,
    }


@router.put("/{region_id}")
async def update_region(region_id: str, body: UpdateRegionRequest, request: Request):
    """Update an existing region's polygon, name, and/or light assignment.

    Args:
        region_id: Path parameter — the region's UUID.
        body: JSON body with optional ``name``, ``polygon``, and/or ``light_id``.

    Returns:
        200 JSON with the updated region object.
        404 if the region does not exist.
    """
    db = request.app.state.db

    # Check region exists
    async with db.execute(
        "SELECT id, name, polygon, order_index, light_id FROM regions WHERE id=?",
        (region_id,),
    ) as cursor:
        existing = await cursor.fetchone()

    if existing is None:
        raise HTTPException(status_code=404, detail="Region not found")

    if body.polygon is not None and polygon_area(body.polygon) < MIN_REGION_AREA:
        raise HTTPException(
            status_code=422,
            detail=f"Region too small — minimum area is {MIN_REGION_AREA} (normalized)",
        )

    # Build update fields dynamically from non-None request fields
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.polygon is not None:
        updates["polygon"] = json.dumps(body.polygon)
    if body.light_id is not None:
        updates["light_id"] = body.light_id

    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [region_id]
        await db.execute(
            f"UPDATE regions SET {set_clause} WHERE id=?", values
        )
        await db.commit()

    # Fetch the updated record
    async with db.execute(
        "SELECT id, name, polygon, order_index, light_id FROM regions WHERE id=?",
        (region_id,),
    ) as cursor:
        updated = await cursor.fetchone()

    return {
        "id": updated["id"],
        "name": updated["name"],
        "polygon": json.loads(updated["polygon"]),
        "order_index": updated["order_index"],
        "light_id": updated["light_id"],
    }


@router.delete("/{region_id}", status_code=204)
async def delete_region(region_id: str, request: Request):
    """Delete a region and its light assignments.

    Args:
        region_id: Path parameter — the region's UUID.

    Returns:
        204 on success.
        404 if the region does not exist.
    """
    db = request.app.state.db

    # Check region exists
    async with db.execute(
        "SELECT id FROM regions WHERE id=?", (region_id,)
    ) as cursor:
        existing = await cursor.fetchone()

    if existing is None:
        raise HTTPException(status_code=404, detail="Region not found")

    await db.execute("DELETE FROM regions WHERE id=?", (region_id,))
    await db.execute(
        "DELETE FROM light_assignments WHERE region_id=?", (region_id,)
    )
    await db.commit()

    return Response(status_code=204)


@router.delete("/")
async def delete_all_regions(request: Request):
    """Delete all regions and their light assignments."""
    db = request.app.state.db
    await db.execute("DELETE FROM light_assignments")
    await db.execute("DELETE FROM regions")
    await db.commit()
    return Response(status_code=204)


@router.get("/settings")
async def region_settings():
    """Return region configuration values (e.g. minimum area threshold)."""
    return {"min_region_area": MIN_REGION_AREA}


@router.get("/")
async def list_regions(request: Request):
    """Return all stored regions with polygon coordinates and light assignment.

    Returns:
        200 JSON list of regions: [{"id": str, "name": str, "polygon": [[x,y],...],
        "order_index": int, "light_id": str | null}]
    """
    db = request.app.state.db

    async with db.execute(
        "SELECT id, name, polygon, order_index, light_id FROM regions ORDER BY order_index"
    ) as cursor:
        rows = await cursor.fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "polygon": json.loads(row["polygon"]),
            "order_index": row["order_index"],
            "light_id": row["light_id"],
        }
        for row in rows
    ]
