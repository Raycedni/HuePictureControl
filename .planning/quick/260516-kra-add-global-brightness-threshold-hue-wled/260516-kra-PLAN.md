---
phase: quick-260516-kra
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - Backend/database.py
  - Backend/routers/settings.py
  - Backend/main.py
  - Backend/services/streaming_service.py
  - Backend/services/streaming_coordinator.py
  - Backend/services/wled_streamer.py
  - Backend/tests/test_streaming_service.py
  - Backend/tests/test_wled_streamer.py
  - Backend/tests/test_settings_router.py
  - Frontend/src/api/settings.ts
  - Frontend/src/components/Settings/BrightnessCutoffControl.tsx
  - Frontend/src/components/Settings/BrightnessCutoffControl.test.tsx
  - Frontend/src/components/Settings/SettingsPage.tsx
  - Frontend/src/components/Settings/SettingsPanel.tsx
autonomous: true
requirements:
  - quick-260516-kra
must_haves:
  truths:
    - "A global numeric setting `brightness_cutoff_threshold` exists in the SQLite `settings` table with value '0.0' on first boot of any database (fresh or migrated)."
    - "GET /api/settings/brightness_cutoff_threshold returns the current value; PUT /api/settings/brightness_cutoff_threshold validates and persists a new float in [0.0, 1.0]."
    - "When `app.state.brightness_cutoff_threshold == 0.0`, HueStreamer.render produces byte-identical DTLS bytes for a fixture frame compared to the pre-change path (the existing `bri < 0.01` floor still applies, dark scenes still emit a clamped non-zero brightness)."
    - "When `app.state.brightness_cutoff_threshold > 0.0` and a Hue channel's region mean luma < threshold, the channel's DTLS record encodes `b_u16 == 0` (x/y still gamut-projected)."
    - "When `app.state.brightness_cutoff_threshold > 0.0` and a WLED channel's region mean luma < threshold, the LEDs in that channel's `[start_led, end_led]` range are written as `(0, 0, 0)` in the packet body."
    - "Editing the slider/input in the Settings UI persists the value via PUT and the change takes effect on the next frame WITHOUT restarting the stream."
    - "All new backend unit tests pass (`python -m pytest`) and all new frontend unit tests pass (`npx vitest run`)."
  artifacts:
    - path: "Backend/database.py"
      provides: "`settings` KV table CREATE + idempotent insert of ('brightness_cutoff_threshold', '0.0')"
      contains: "CREATE TABLE IF NOT EXISTS settings"
    - path: "Backend/routers/settings.py"
      provides: "GET + PUT /api/settings/brightness_cutoff_threshold"
      exports: ["router"]
    - path: "Backend/services/streaming_service.py"
      provides: "HueStreamer.render reads app.state.brightness_cutoff_threshold once per frame and zeros bri below threshold"
      contains: "brightness_cutoff_threshold"
    - path: "Backend/services/wled_streamer.py"
      provides: "WledStreamer.render zeros a channel's LED slice when the channel's region mean luma is below the cutoff"
      contains: "brightness_cutoff_threshold"
    - path: "Frontend/src/components/Settings/BrightnessCutoffControl.tsx"
      provides: "Slider + numeric input + caption that loads via GET on mount and persists via PUT on change"
      min_lines: 30
  key_links:
    - from: "Backend/main.py"
      to: "Backend/routers/settings.py"
      via: "app.include_router(settings_router) and app.state.brightness_cutoff_threshold init"
      pattern: "from routers.settings import"
    - from: "Backend/routers/settings.py"
      to: "app.state.brightness_cutoff_threshold"
      via: "PUT handler updates DB + app.state in same handler"
      pattern: "app\\.state\\.brightness_cutoff_threshold"
    - from: "Backend/services/streaming_service.py"
      to: "app.state.brightness_cutoff_threshold"
      via: "HueStreamer holds `_app_state` ref captured at start(); render() reads `_app_state.brightness_cutoff_threshold` once per frame"
      pattern: "brightness_cutoff_threshold"
    - from: "Backend/services/wled_streamer.py"
      to: "app.state.brightness_cutoff_threshold"
      via: "WledStreamer holds `_app_state` ref; _render_one_device reads threshold once per call and zeros sub-slices below it"
      pattern: "brightness_cutoff_threshold"
    - from: "Frontend/src/components/Settings/BrightnessCutoffControl.tsx"
      to: "/api/settings/brightness_cutoff_threshold"
      via: "GET on mount, PUT on slider change"
      pattern: "/api/settings/brightness_cutoff_threshold"
---

<objective>
Add a single global brightness-cutoff threshold (float in [0.0, 1.0], default 0.0) that, when > 0, forces individual lights to "off" whenever their assigned region's mean Rec.709 luma falls below the threshold. Default 0.0 = disabled = byte-identical output to today's behavior. Setting persists in SQLite, is exposed as GET/PUT under `/api/settings/`, surfaces in the existing Settings UI as a slider, and is read by both `HueStreamer.render` and `WledStreamer._render_one_device` once per frame so changes take effect without restarting the stream.

Purpose: When watching dark content (e.g. a sunset clip where one bottom region drifts near black), the existing 0.01 Hue floor still produces a visible glow and WLED keeps sending non-zero RGB to that strip portion. A user-configurable cutoff lets the viewer force-off lights tied to dark regions while keeping bright regions live — a feature the existing solutions in this space lack.

Output: One new `settings` KV table, one new `routers/settings.py`, render-path edits in both streamers, a new `BrightnessCutoffControl` React component wired into both `SettingsPage` and `SettingsPanel`, plus unit-test coverage for backend render gating, default-byte-identity, router validation, and the frontend control.
</objective>

<execution_context>
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/PROJECT.md
@./CLAUDE.md
@Backend/services/streaming_service.py
@Backend/services/wled_streamer.py
@Backend/services/streaming_coordinator.py
@Backend/database.py
@Backend/main.py
@Backend/routers/wled.py
@Backend/tests/test_streaming_service.py
@Backend/tests/test_wled_streamer.py
@Frontend/src/components/Settings/SettingsPage.tsx
@Frontend/src/components/Settings/SettingsPanel.tsx
@Frontend/src/api/wled.ts

<interfaces>
<!-- Key interfaces and shapes the executor needs. Extracted from the codebase. -->

From `Backend/services/streaming_service.py` — current HueStreamer.render contract (the gating insertion point is right after the `bri = ...` line near line 228):
```python
# lines ~219-243 (current)
for channel_id, region_id in self._channel_to_region.items():
    gradient = region_gradients.get(region_id)
    if gradient is None or len(gradient) == 0:
        continue
    mean_rgb = gradient.mean(axis=0)
    r = int(mean_rgb[0]); g = int(mean_rgb[1]); b = int(mean_rgb[2])
    x, y = rgb_to_xy(r, g, b)
    bri = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255.0
    if bri < 0.01:
        bri = 0.01  # dark-scene floor
    # ... pack to DTLS record (or fallback_inputs)
```

From `Backend/services/wled_streamer.py` — current per-device fill loop (insertion point is inside `_render_one_device` right after `slice_arr` is computed, before `colors[clip_lo:clip_hi] = ...`):
```python
# lines ~351-389 (current)
colors = np.zeros((led_count, 3), dtype=np.uint8)
populated = False
for ch in snap["channels"]:
    region_id = ch.get("region_id")
    if region_id is None:
        continue
    gradient = region_gradients.get(region_id)
    if gradient is None:
        continue
    start = int(ch["start_led"]); end = int(ch["end_led"])
    range_len = end - start + 1
    # ... compute slice_arr (size range_len) ...
    colors[clip_lo:clip_hi] = np.asarray(slice_arr[src_lo:src_hi], dtype=np.uint8)
    populated = True
```

From `Backend/database.py` — the migration pattern that the new `settings` table must follow (idempotent CREATE TABLE IF NOT EXISTS, NOT the PRAGMA user_version guard which is reserved for Phase 19.1):
```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS bridge_config (
        id INTEGER PRIMARY KEY,
        ...
    )
""")
```

From `Backend/main.py` — lifespan startup hook where `app.state.brightness_cutoff_threshold` is initialized (line ~28-56):
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db = await init_db(DATABASE_PATH)
    app.state.db = db
    # ... existing setup ...
```

From `Backend/services/streaming_coordinator.py` — sinks are constructed once in `__init__` and `start()` does not pass app.state through. The simplest wiring per the task spec is to give each streamer an `app_state` attribute that the coordinator sets in `__init__` (the coordinator holds `app.state` via the FastAPI lifespan having access to it — see Task 1.B).

Hue Entertainment v2 channel record format (from lines 240-243 of `streaming_service.py`):
```
struct.pack(">BHHH", int(channel_id), x_u16, y_u16, b_u16)
# b_u16 = int(max(0.0, min(1.0, bri)) * 65535)
# bri==0 → b_u16==0 (the "off" signal)
```

WLED DRGB body format (from `build_drgb_packet` in `wled_streamer.py`):
```
header = bytes([0x02, 0x02])  # DRGB protocol + 2s timeout
body = colors.tobytes()       # (N, 3) uint8 → R0 G0 B0 R1 G1 B1 ...
# A zeroed slice colors[s:e] = 0 → those triplets in body are b"\x00\x00\x00" each
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend persistence + router + app.state wiring</name>
  <files>
    Backend/database.py,
    Backend/routers/settings.py,
    Backend/main.py,
    Backend/tests/test_settings_router.py
  </files>
  <action>
**1.A — `Backend/database.py`**: After the existing `CREATE TABLE IF NOT EXISTS known_cameras` block and BEFORE the Phase 19.1 PRAGMA `user_version` guard, add:

```python
await db.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
""")
# Idempotent seed of the brightness cutoff (quick-task 260516-kra).
# INSERT OR IGNORE guarantees existing rows on upgrade keep the user's value.
await db.execute(
    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
    ("brightness_cutoff_threshold", "0.0"),
)
```

Do NOT touch the PRAGMA user_version guard (it is reserved for Phase 19.1 schema upgrades). The `CREATE TABLE IF NOT EXISTS` + `INSERT OR IGNORE` pair is self-idempotent — this is the same pattern used by `bridge_config`, `known_cameras`, etc.

**1.B — Create `Backend/routers/settings.py`** with:

```python
"""Global app-settings KV router (quick-task 260516-kra).

Exposes GET/PUT for `brightness_cutoff_threshold`. The PUT handler updates
BOTH the persistent SQLite row AND `request.app.state.brightness_cutoff_threshold`
so the live streaming sinks see the new value on the NEXT frame without a
stream restart.

Schema: settings(key TEXT PRIMARY KEY, value TEXT NOT NULL). Values are
stored as TEXT (str(float)) for forward-compat with future non-numeric
settings; the brightness handler parses to float on read.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/settings", tags=["settings"])


class BrightnessCutoffPayload(BaseModel):
    value: float = Field(..., ge=0.0, le=1.0)


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
async def put_brightness_cutoff(
    payload: BrightnessCutoffPayload,
    request: Request,
) -> BrightnessCutoffResponse:
    # Pydantic Field(ge=0.0, le=1.0) already returns 422 on out-of-range.
    # We still guard against NaN explicitly — Pydantic v2 accepts NaN through
    # numeric coercion in some paths.
    v = float(payload.value)
    if v != v:  # NaN check
        raise HTTPException(status_code=422, detail="value must be a number")
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
```

**1.C — `Backend/main.py`**: After `app.state.db = db` and before the regions-purge block, add live-state hydration:

```python
# quick-task 260516-kra: hydrate live brightness cutoff from DB so streamers
# pick it up on first frame after startup. Default 0.0 (disabled).
app.state.brightness_cutoff_threshold = 0.0
try:
    async with db.execute(
        "SELECT value FROM settings WHERE key = ?",
        ("brightness_cutoff_threshold",),
    ) as cur:
        row = await cur.fetchone()
    if row is not None:
        try:
            app.state.brightness_cutoff_threshold = float(row["value"])
        except (TypeError, ValueError):
            pass
except Exception:
    # settings table may not exist if init_db ran against a stale DB image —
    # safe default already set above.
    pass
```

Also add the router registration alongside the existing `app.include_router(...)` block:

```python
from routers.settings import router as settings_router
# ...
app.include_router(settings_router)
```

**1.D — Wire `app.state` into both streamers via the coordinator.** In `main.py`, change the `StreamingCoordinator(...)` construction to pass app.state:

```python
coordinator = StreamingCoordinator(
    db=db,
    capture_registry=registry,
    broadcaster=broadcaster,
    app_state=app.state,
)
```

In `Backend/services/streaming_coordinator.py`, add an `app_state` parameter to `StreamingCoordinator.__init__` (default None for test back-compat). After constructing `self._hue` and `self._wled`, set:

```python
self._app_state = app_state
if app_state is not None:
    # Optional attribute attached AFTER construction so existing test mocks
    # for HueStreamer / WledStreamer (which don't accept the kwarg) still
    # work. Sinks read self._app_state defensively in render().
    self._hue._app_state = app_state
    self._wled._app_state = app_state
```

This is intentionally minimal — the streamer constructors stay unchanged so every existing test (incl. the `MagicMock` HueStreamer / WledStreamer in test_streaming_coordinator.py) keeps passing.

**1.E — Tests**: Create `Backend/tests/test_settings_router.py` with FastAPI TestClient + an in-memory SQLite DB:

- `test_get_returns_default_zero_on_fresh_db`: fresh DB → GET returns `{"value": 0.0}`.
- `test_put_round_trip`: PUT `{"value": 0.7}` returns 200 + `{"value": 0.7}`; subsequent GET returns 0.7.
- `test_put_rejects_above_one`: PUT `{"value": 1.5}` returns 422.
- `test_put_rejects_below_zero`: PUT `{"value": -0.01}` returns 422.
- `test_put_rejects_nan`: PUT `{"value": float("nan")}` returns 422.
- `test_put_updates_app_state`: PUT `{"value": 0.4}` → `app.state.brightness_cutoff_threshold == 0.4`.

Use the same `init_db(":memory:")` pattern test_database.py uses and mount the router on a minimal `FastAPI()` app for the test (no full lifespan needed — just attach `app.state.db = db` manually).
  </action>
  <verify>
    <automated>cd Backend && python -m pytest tests/test_settings_router.py tests/test_database.py -x -q</automated>
  </verify>
  <done>
    - `settings` table exists in a freshly-initialized DB and contains `('brightness_cutoff_threshold', '0.0')`.
    - GET/PUT endpoints round-trip values; out-of-range returns 422.
    - PUT updates both DB row and `app.state.brightness_cutoff_threshold`.
    - All new tests in `test_settings_router.py` pass; no existing backend test regresses.
  </done>
</task>

<task type="auto">
  <name>Task 2: HueStreamer + WledStreamer render-path gating + render tests</name>
  <files>
    Backend/services/streaming_service.py,
    Backend/services/wled_streamer.py,
    Backend/tests/test_streaming_service.py,
    Backend/tests/test_wled_streamer.py
  </files>
  <action>
**2.A — `HueStreamer.render` gating** (`Backend/services/streaming_service.py`):

At the top of `render()` (after the `if self._streaming is None: return` check, before the per-channel loop), read the threshold once per frame:

```python
# quick-task 260516-kra: per-frame read of the global brightness cutoff.
# 0.0 = disabled (default). Read defensively — _app_state may be absent in
# tests that instantiate HueStreamer directly without going through main.py.
threshold = 0.0
app_state = getattr(self, "_app_state", None)
if app_state is not None:
    try:
        threshold = float(getattr(app_state, "brightness_cutoff_threshold", 0.0))
    except (TypeError, ValueError):
        threshold = 0.0
```

Then, inside the per-channel loop, replace the existing `bri` block (currently lines ~228-230):

```python
bri = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255.0
if bri < 0.01:
    bri = 0.01  # dark-scene floor
```

with:

```python
bri = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255.0
if threshold > 0.0 and bri < threshold:
    # Below cutoff — force the channel off. The DTLS record is still
    # emitted so the bulb sees a black frame (any other state-keeping logic
    # in the bulb sees a frame, not a dropout).
    bri = 0.0
elif bri < 0.01:
    bri = 0.01  # dark-scene floor (only applies when threshold==0 OR bri >= threshold)
```

This preserves the byte-identical default path: when `threshold == 0.0`, the `threshold > 0.0` branch never fires and the original `if bri < 0.01: bri = 0.01` logic runs unchanged. The fallback `set_input` path (test-only) automatically picks up the new `bri=0.0` value too because it uses the same `bri` variable.

**2.B — `WledStreamer._render_one_device` gating** (`Backend/services/wled_streamer.py`):

In `_render_one_device`, after the existing `if not populated: return` check is reached we already have a `colors` (led_count, 3) uint8 buffer. We need to zero per-channel slices based on the channel's region luma. The natural insertion point is INSIDE the existing `for ch in snap["channels"]` loop, after `slice_arr` is computed and just before `colors[clip_lo:clip_hi] = ...`.

Add a per-frame threshold read at the top of `_render_one_device`, immediately after the `led_count = snap["led_count"]; if led_count <= 0: return` guard:

```python
# quick-task 260516-kra: per-frame read. _app_state may be absent in unit
# tests that exercise WledStreamer directly without the coordinator wiring.
threshold = 0.0
app_state = getattr(self, "_app_state", None)
if app_state is not None:
    try:
        threshold = float(getattr(app_state, "brightness_cutoff_threshold", 0.0))
    except (TypeError, ValueError):
        threshold = 0.0
```

Inside the channel loop, after `slice_arr` is built (size matches `range_len`) and before the `clip_lo / clip_hi` slice write, add:

```python
if threshold > 0.0:
    # Mean luma of the source gradient — same Rec.709 weights HueStreamer uses.
    # mean(axis=0) reduces (src_n, 3) → (3,); float() forces scalar division.
    mean_rgb = gradient.mean(axis=0)
    luma = (
        float(mean_rgb[0]) * 0.2126
        + float(mean_rgb[1]) * 0.7152
        + float(mean_rgb[2]) * 0.0722
    ) / 255.0
    if luma < threshold:
        # Zero this channel's LED range — np.zeros_like keeps dtype uint8.
        # We zero slice_arr BEFORE the colors[...] = ... write so the
        # subsequent intersect-and-clip math stays unchanged.
        slice_arr = np.zeros_like(np.asarray(slice_arr, dtype=np.uint8))
```

The clip-and-write line that follows is unchanged — it now writes zeros into the buffer for that channel's LEDs. Note: when `threshold == 0.0` we skip the luma compute entirely (per-frame cost stays at zero for users who never enable the feature).

Important: the luma compute uses `gradient` (the source N-point gradient for this region), NOT `slice_arr` (which may already be a broadcast/resampled view). The decision is per-region, not per-LED — keeps the per-frame allocator cheap as the spec requires.

**2.C — Hue render tests** (`Backend/tests/test_streaming_service.py`):

Append the following tests after the existing `test_render_brightness_clamped_for_black`:

- `test_render_zero_threshold_keeps_existing_floor`: with `sink._app_state = None` AND with `sink._app_state = SimpleNamespace(brightness_cutoff_threshold=0.0)`, a black region still gets `bri >= 0.01` (existing dark-scene clamp preserved). Use the fallback `set_input` path (no `_dtls_socket`).
- `test_render_above_threshold_zeros_bri_in_batched_packet`: wire up the batched DTLS path (`_dtls_socket`, `_entertainment_id_bytes`), set `_app_state.brightness_cutoff_threshold = 0.5`, send a region with mean RGB ~(76, 76, 76) (luma ≈ 0.298, below 0.5). Assert the channel's encoded record has `b_u16 == 0` while `x_u16` and `y_u16` are still the standard gamut-projected values (> 0). Unpack with `struct.unpack(">BHHH", record)`.
- `test_render_default_byte_identical_for_canonical_frame`: a "snapshot" test — pick a fixture: 3 channels, RGB `(120, 150, 200)`, `(0, 0, 0)`, `(200, 50, 50)`. Run `render()` with `_app_state.brightness_cutoff_threshold = 0.0`. Capture `dtls_sock.send.call_args.args[0]`. Compare to the bytes produced by the SAME code path before this change — easiest way: hardcode the expected byte sequence in the test by running it once during implementation and pasting the result. The test pins "byte-identity when disabled" so future refactors can't drift the default path.

**2.D — WLED render tests** (`Backend/tests/test_wled_streamer.py`):

Append after `test_render_no_assigned_channel_sends_nothing`:

- `test_render_zero_threshold_no_change`: with `streamer._app_state = SimpleNamespace(brightness_cutoff_threshold=0.0)`, send a region with mean luma 0.1 (e.g. `_gradient(10, [25, 25, 25])`). Assert the received packet body contains those exact RGB bytes (byte-identical to today's output) — same as `test_render_sends_drgb_for_small_strip` shape.
- `test_render_above_threshold_zeros_led_slice`: with `streamer._app_state = SimpleNamespace(brightness_cutoff_threshold=0.5)`, register a device with `led_count=10` and a single channel `[0, 9]` driven by region `r1`. Send `_gradient(10, [76, 76, 76])` (luma 0.298). Assert the received DRGB packet body `pkt.data[2:32]` is all `b"\x00"` — every LED triplet is zero.
- `test_render_above_threshold_only_zeros_below_threshold_channels`: device with TWO channels — channel A on LEDs [0,4] driven by region `rDark` (gradient mean luma 0.1), channel B on LEDs [5,9] driven by region `rBright` (gradient mean luma 0.8). Threshold 0.5. Assert packet body LEDs 0-4 are zero and LEDs 5-9 carry the bright color's RGB.

All four new WLED tests use the existing `udp_listener(port=LOOPBACK_PORT)` fixture from `tests/fixtures/wled_loopback.py` and `WledStreamer(udp_port=LOOPBACK_PORT)` per the established pattern (lines 140-216 of `test_wled_streamer.py`).
  </action>
  <verify>
    <automated>cd Backend && python -m pytest tests/test_streaming_service.py tests/test_wled_streamer.py -x -q</automated>
  </verify>
  <done>
    - All existing Hue + WLED streamer tests still pass (no regression on the default `threshold == 0.0` path).
    - New Hue tests prove `b_u16 == 0` for below-threshold channels; default path still clamps to 0.01 floor.
    - New WLED tests prove below-threshold LED slices are zeroed and above-threshold channels are untouched.
    - The "byte-identical default" snapshot test passes (pin against the captured pre-change bytes).
  </done>
</task>

<task type="auto">
  <name>Task 3: Frontend BrightnessCutoffControl + Settings wiring + vitest</name>
  <files>
    Frontend/src/api/settings.ts,
    Frontend/src/components/Settings/BrightnessCutoffControl.tsx,
    Frontend/src/components/Settings/BrightnessCutoffControl.test.tsx,
    Frontend/src/components/Settings/SettingsPage.tsx,
    Frontend/src/components/Settings/SettingsPanel.tsx
  </files>
  <action>
**3.A — Typed REST client** — create `Frontend/src/api/settings.ts`:

```typescript
// quick-task 260516-kra: typed client for /api/settings/*.
// Mirrors the shape of api/wled.ts (typed exports + a dedicated error class).

export class SettingsApiError extends Error {
  public status: number
  constructor(status: number, message?: string) {
    super(message ?? `HTTP ${status}`)
    this.name = 'SettingsApiError'
    this.status = status
  }
}

export interface BrightnessCutoffResponse {
  value: number
}

export async function getBrightnessCutoff(): Promise<BrightnessCutoffResponse> {
  const res = await fetch('/api/settings/brightness_cutoff_threshold')
  if (!res.ok) throw new SettingsApiError(res.status)
  return res.json()
}

export async function putBrightnessCutoff(
  value: number,
): Promise<BrightnessCutoffResponse> {
  const res = await fetch('/api/settings/brightness_cutoff_threshold', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
  if (!res.ok) throw new SettingsApiError(res.status)
  return res.json()
}
```

**3.B — React component** — create `Frontend/src/components/Settings/BrightnessCutoffControl.tsx`:

```tsx
// quick-task 260516-kra: single slider for the global brightness-cutoff
// threshold. 0.00 = disabled (default; existing behavior unchanged). Above
// 0, lights whose region's mean luma falls below the threshold turn off
// (Hue sends bri=0; WLED writes (0,0,0) to those LEDs).
//
// Native <input type="range"> + a small numeric readout — keeps the
// dependency surface at zero new packages per CLAUDE.md ("react-konva +
// shadcn primitives only"). The Settings tab already mixes raw inputs
// (WledDevicesPanel.tsx line 119) with shadcn buttons, so this stays
// consistent.

import { useCallback, useEffect, useState } from 'react'
import {
  getBrightnessCutoff,
  putBrightnessCutoff,
  SettingsApiError,
} from '@/api/settings'

const STEP = 0.01
const MIN = 0.0
const MAX = 1.0

export function BrightnessCutoffControl() {
  const [value, setValue] = useState<number>(0.0)
  const [loaded, setLoaded] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)

  // Load current value on mount.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const r = await getBrightnessCutoff()
        if (!cancelled) {
          setValue(r.value)
          setLoaded(true)
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof SettingsApiError
              ? `Load failed (HTTP ${err.status})`
              : (err as Error).message,
          )
          setLoaded(true)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Persist on every change. The backend is local + cheap; debounce would
  // add complexity for no measurable benefit at 60Hz UI input.
  const persist = useCallback(async (next: number) => {
    setError(null)
    try {
      const r = await putBrightnessCutoff(next)
      setValue(r.value)
    } catch (err) {
      setError(
        err instanceof SettingsApiError
          ? `Save failed (HTTP ${err.status})`
          : (err as Error).message,
      )
    }
  }, [])

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const next = Number(e.target.value)
      if (Number.isFinite(next)) {
        setValue(next)
        void persist(next)
      }
    },
    [persist],
  )

  return (
    <section
      data-testid="brightness-cutoff-control"
      className="flex flex-col gap-2 p-3 border border-white/[0.08] rounded-md"
    >
      <div className="flex items-baseline justify-between">
        <label
          htmlFor="brightness-cutoff-slider"
          className="text-sm font-semibold"
        >
          Brightness cutoff (0 = off)
        </label>
        <span
          data-testid="brightness-cutoff-value"
          className="text-xs tabular-nums text-muted-foreground"
        >
          {value.toFixed(2)}
        </span>
      </div>
      <input
        id="brightness-cutoff-slider"
        data-testid="brightness-cutoff-slider"
        type="range"
        min={MIN}
        max={MAX}
        step={STEP}
        value={value}
        onChange={handleChange}
        disabled={!loaded}
      />
      <p className="text-xs text-muted-foreground">
        Lights below this brightness will turn off.
      </p>
      {error && (
        <p data-testid="brightness-cutoff-error" className="text-xs text-red-400">
          {error}
        </p>
      )}
    </section>
  )
}
```

**3.C — Wire into Settings** — in both `Frontend/src/components/Settings/SettingsPage.tsx` and `Frontend/src/components/Settings/SettingsPanel.tsx`, import the new component and render it at the top of the existing flex container (above the strip painter / device panel pair). For `SettingsPage.tsx`, the change is to insert one line before the `<div className="flex-1 flex flex-col md:flex-row gap-4 min-h-0">` block:

```tsx
import { BrightnessCutoffControl } from './BrightnessCutoffControl'
// ...
<div className="flex flex-col flex-1 min-h-0 p-4 text-left" data-testid="settings-page">
  <h2 className="text-sm font-semibold mb-3">Settings</h2>
  <div className="mb-3">
    <BrightnessCutoffControl />
  </div>
  <div className="flex-1 flex flex-col md:flex-row gap-4 min-h-0">
    {/* existing strip/sidebar/devices block — unchanged */}
    ...
  </div>
</div>
```

Do the same single-line `<BrightnessCutoffControl />` insertion inside the modal `SettingsPanel.tsx`, right after the header element and before the existing flex content row. Both surfaces share the component instance so any change persisted from one shows up on the other after remount (GET on mount).

**3.D — Vitest tests** — create `Frontend/src/components/Settings/BrightnessCutoffControl.test.tsx`:

Use the same patterns as `WledDevicesPanel.test.tsx` / `LightPanel.test.tsx`. Mock `fetch` globally with `vi.stubGlobal('fetch', ...)`. Tests:

- `renders default value 0.00 from GET on mount`: stub GET to return `{value: 0}`. After `await screen.findByTestId('brightness-cutoff-slider')`, assert the value display reads "0.00" and the slider input value is "0".
- `slider change triggers PUT with the new value`: stub GET → `{value: 0}`, PUT → `{value: 0.5}`. After mount, `fireEvent.change(slider, { target: { value: '0.5' } })`. Assert `fetch` was called with `/api/settings/brightness_cutoff_threshold`, method PUT, body containing `"value":0.5`.
- `displays loaded value from server`: stub GET → `{value: 0.42}`. Assert the value display eventually reads "0.42".
- `shows error caption when PUT fails`: stub PUT → 500. After change, assert `findByTestId('brightness-cutoff-error')` is rendered with text containing "500".

Reset stubs between tests with `vi.restoreAllMocks()` in `afterEach`.
  </action>
  <verify>
    <automated>cd Frontend && npx vitest run src/components/Settings/BrightnessCutoffControl.test.tsx src/components/Settings/WledDevicesPanel.test.tsx</automated>
  </verify>
  <done>
    - `BrightnessCutoffControl.tsx` mounts in both `SettingsPage` and `SettingsPanel`.
    - On mount it fires GET and renders the loaded value (or 0.00 default).
    - Slider change fires PUT with `{value: <float>}` and updates the displayed readout.
    - Errors surface inline via the error caption.
    - All 4 new vitest specs pass; no existing frontend test regresses.
  </done>
</task>

<task type="auto">
  <name>Task 4: Full preflight — backend + frontend test suites end-to-end</name>
  <files>(no source changes — verification only)</files>
  <action>
Run the full backend and frontend test suites to catch any regression from Tasks 1-3 that wasn't covered by the targeted per-task verification. This is a safety net for the global render-path edits in Task 2, which touch hot-path code shared by every existing streaming test.

Sequence:

1. Backend full suite:
   ```bash
   cd Backend && python -m pytest -x
   ```
   Expected: all 167+ tests pass. If anything in `test_streaming_coordinator.py` or `test_phase17_e2e.py` regresses, it's almost certainly the `app_state` wiring in Task 1.D — the coordinator constructor signature change must remain back-compat (default `app_state=None`).

2. Frontend full suite:
   ```bash
   cd Frontend && npx vitest run
   ```
   Expected: all 30+ tests pass. Any regression is almost certainly in `SettingsPage.test.tsx` / `SettingsPanel.test.tsx` if those files exist and snapshot the children — search with `grep -ri "SettingsPage\|SettingsPanel" Frontend/src/**/*.test.*` and fix snapshots if needed.

3. Smoke-check the backend boot:
   ```bash
   curl -s http://localhost:8000/api/health || true
   curl -s http://localhost:8000/api/settings/brightness_cutoff_threshold
   ```
   The second curl is informational — it requires the backend dev server to be running. If it isn't running, skip; the test suites above are authoritative.

If any test fails:
- Read the failure, identify the root cause (do NOT mass-skip).
- If it's a wiring issue (e.g. `StreamingCoordinator` test pasing positional args that now collide with `app_state`), fix the wiring to remain back-compat.
- If it's a real semantic regression (e.g. default-path bytes changed), revert the byte-identity drift in `streaming_service.py` — the `threshold == 0.0` branch must produce byte-identical output to the pre-change path.
  </action>
  <verify>
    <automated>cd Backend && python -m pytest -x -q && cd ../Frontend && npx vitest run</automated>
  </verify>
  <done>
    - Full backend test suite green (no regressions).
    - Full frontend test suite green (no regressions).
    - The new feature is observable end-to-end: backend persists the value, both streamers honor it on the next frame, frontend slider drives the change.
  </done>
</task>

</tasks>

<verification>
- Backend persistence: `sqlite3 Backend/data/config.db "SELECT * FROM settings;"` shows `brightness_cutoff_threshold|0.0` on a fresh DB.
- Backend API: `curl -X PUT -H "Content-Type: application/json" -d '{"value": 0.5}' http://localhost:8000/api/settings/brightness_cutoff_threshold` returns 200; subsequent GET returns `{"value": 0.5}`. PUT with `{"value": 1.5}` returns 422.
- Render gating (Hue): with threshold 0.5 and a dark region (luma 0.3), the channel's DTLS record has `b_u16 == 0` (covered by `test_render_above_threshold_zeros_bri_in_batched_packet`).
- Render gating (WLED): with threshold 0.5 and a dark region driving LEDs 0-9, the DRGB packet body bytes 2..32 are zero (covered by `test_render_above_threshold_zeros_led_slice`).
- Default-byte-identity: covered by `test_render_default_byte_identical_for_canonical_frame` (Hue) and `test_render_zero_threshold_no_change` (WLED). These pin the "0.0 = disabled = unchanged" contract.
- Frontend: Settings tab shows the "Brightness cutoff (0 = off)" slider with caption "Lights below this brightness will turn off." Slider change persists via PUT and survives page reload (re-fetched on next mount).
- Live update: changing the slider while streaming changes light behavior on the next frame (no stream restart needed — verified by `app.state.brightness_cutoff_threshold` being read once per `render()` call).
</verification>

<success_criteria>
1. `cd Backend && python -m pytest -x` — all tests green (existing + 6 new in `test_settings_router.py` + 3 new in `test_streaming_service.py` + 3 new in `test_wled_streamer.py`).
2. `cd Frontend && npx vitest run` — all tests green (existing + 4 new in `BrightnessCutoffControl.test.tsx`).
3. `curl -X PUT -H "Content-Type: application/json" -d '{"value": 0.7}' http://localhost:8000/api/settings/brightness_cutoff_threshold` returns 200 with `{"value": 0.7}`; subsequent GET returns the same.
4. Default-path byte identity preserved: the "byte-identical when threshold==0" snapshot tests pass for both Hue and WLED.
5. Settings UI in both `SettingsPage` and `SettingsPanel` renders the slider, loads value on mount, persists on change.
</success_criteria>

<output>
After completion, create `.planning/quick/260516-kra-add-global-brightness-threshold-hue-wled/260516-kra-SUMMARY.md` describing: files changed, the gating equation (`bri < threshold` and `luma < threshold` both using Rec.709 weights), the byte-identity guarantee for `threshold == 0.0`, and one bullet on the `app.state` live-update mechanism (no stream restart needed).
</output>
