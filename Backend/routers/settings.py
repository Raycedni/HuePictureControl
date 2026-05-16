"""Global app-settings KV router (quick-task 260516-kra).

Exposes GET/PUT for ``brightness_cutoff_threshold``. The PUT handler updates
BOTH the persistent SQLite row AND ``request.app.state.brightness_cutoff_threshold``
so the live streaming sinks see the new value on the NEXT frame without a
stream restart.

Schema: ``settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)``. Values are
stored as TEXT (``str(float)``) for forward-compat with future non-numeric
settings; the brightness handler parses to float on read.

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


class BrightnessCutoffResponse(BaseModel):
    value: float


@router.get(
    "/brightness_cutoff_threshold",
    response_model=BrightnessCutoffResponse,
)
async def get_brightness_cutoff(request: Request) -> BrightnessCutoffResponse:
    db = request.app.state.db
    async with await db.execute(
        "SELECT value FROM settings WHERE key = ?",
        ("brightness_cutoff_threshold",),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return BrightnessCutoffResponse(value=0.0)
    try:
        return BrightnessCutoffResponse(value=float(row["value"]))
    except (TypeError, ValueError):
        return BrightnessCutoffResponse(value=0.0)


@router.put(
    "/brightness_cutoff_threshold",
    response_model=BrightnessCutoffResponse,
)
async def put_brightness_cutoff(request: Request) -> BrightnessCutoffResponse:
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
    if v < 0.0 or v > 1.0:
        raise HTTPException(
            status_code=422, detail="value must be in [0.0, 1.0]"
        )

    db = request.app.state.db
    await db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        ("brightness_cutoff_threshold", str(v)),
    )
    await db.commit()
    # Live update — the streamers read this on every render() call.
    request.app.state.brightness_cutoff_threshold = v
    return BrightnessCutoffResponse(value=v)
