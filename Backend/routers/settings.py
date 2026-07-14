"""Global app-settings KV router (quick-task 260516-kra; extended 260704-iss,
260704-w88).

Exposes GET/PUT for ``brightness_cutoff_threshold``, ``color_vibrancy``,
``saturation_boost``, and ``hdr_input``. Each PUT handler updates BOTH the
persistent SQLite row
AND the matching ``request.app.state.<key>`` attribute so the live streaming
coordinator/sinks see the new value on the NEXT frame without a stream
restart.

Schema: ``settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)``. Values are
stored as TEXT (``str(float)``) for forward-compat with future non-numeric
settings; each handler parses to float on read.

PUT validation path: the body is parsed manually instead of via a Pydantic
body-model parameter so that NaN/Infinity rejection produces a clean 422
JSON response. FastAPI's default RequestValidationError handler re-serializes
the offending input value into the 422 body; when that value is NaN the
JSON encoder raises ``ValueError: Out of range float values are not JSON
compliant: nan`` and FastAPI returns a 500. Parsing manually lets us reject
NaN/Inf with a fixed string detail that always JSON-encodes.
"""
import json
import math

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingValueResponse(BaseModel):
    value: float


# Backward-compat alias — brightness_cutoff_threshold's original response
# model name, kept so any external import of this symbol keeps working.
BrightnessCutoffResponse = SettingValueResponse


async def _get_setting(request: Request, key: str) -> SettingValueResponse:
    db = request.app.state.db
    async with await db.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return SettingValueResponse(value=0.0)
    try:
        return SettingValueResponse(value=float(row["value"]))
    except (TypeError, ValueError):
        return SettingValueResponse(value=0.0)


async def _put_setting(
    request: Request, key: str, min_value: float = 0.0, max_value: float = 1.0
) -> SettingValueResponse:
    # Manual body parsing — see module docstring for the NaN-in-422 rationale.
    raw = await request.body()
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=422, detail="invalid JSON body")

    if not isinstance(body, dict) or "value" not in body:
        raise HTTPException(
            status_code=422, detail="body must be an object with key 'value'"
        )
    raw_v = body["value"]
    if isinstance(raw_v, bool) or not isinstance(raw_v, (int, float)):
        # bool is a subclass of int — exclude it explicitly.
        raise HTTPException(status_code=422, detail="value must be a number")
    v = float(raw_v)
    if not math.isfinite(v):
        raise HTTPException(
            status_code=422, detail="value must be a finite number"
        )
    if v < min_value or v > max_value:
        raise HTTPException(
            status_code=422,
            detail=f"value must be in [{min_value}, {max_value}]",
        )

    db = request.app.state.db
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(v)),
    )
    await db.commit()
    # Live update — the coordinator/streamers read this on every frame.
    setattr(request.app.state, key, v)
    return SettingValueResponse(value=v)


@router.get(
    "/brightness_cutoff_threshold",
    response_model=SettingValueResponse,
)
async def get_brightness_cutoff(request: Request) -> SettingValueResponse:
    return await _get_setting(request, "brightness_cutoff_threshold")


@router.put(
    "/brightness_cutoff_threshold",
    response_model=SettingValueResponse,
)
async def put_brightness_cutoff(request: Request) -> SettingValueResponse:
    return await _put_setting(request, "brightness_cutoff_threshold")


@router.get(
    "/color_vibrancy",
    response_model=SettingValueResponse,
)
async def get_color_vibrancy(request: Request) -> SettingValueResponse:
    return await _get_setting(request, "color_vibrancy")


@router.put(
    "/color_vibrancy",
    response_model=SettingValueResponse,
)
async def put_color_vibrancy(request: Request) -> SettingValueResponse:
    return await _put_setting(request, "color_vibrancy")


@router.get(
    "/saturation_boost",
    response_model=SettingValueResponse,
)
async def get_saturation_boost(request: Request) -> SettingValueResponse:
    return await _get_setting(request, "saturation_boost")


@router.put(
    "/saturation_boost",
    response_model=SettingValueResponse,
)
async def put_saturation_boost(request: Request) -> SettingValueResponse:
    return await _put_setting(request, "saturation_boost", -1.0, 1.0)


@router.get(
    "/hdr_input",
    response_model=SettingValueResponse,
)
async def get_hdr_input(request: Request) -> SettingValueResponse:
    return await _get_setting(request, "hdr_input")


@router.put(
    "/hdr_input",
    response_model=SettingValueResponse,
)
async def put_hdr_input(request: Request) -> SettingValueResponse:
    return await _put_setting(request, "hdr_input")
