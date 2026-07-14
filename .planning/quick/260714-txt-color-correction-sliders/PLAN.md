---
phase: 260714-txt
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - Backend/services/color_math.py
  - Backend/tests/test_color_math.py
  - Backend/database.py
  - Backend/routers/settings.py
  - Backend/main.py
  - Backend/tests/test_settings_router.py
  - Backend/services/streaming_coordinator.py
  - Backend/tests/test_streaming_coordinator.py
  - Frontend/src/components/Settings/SettingsPanel.tsx
  - Frontend/src/components/Settings/SettingsPage.tsx
autonomous: true
requirements: [COLORCORRECT-RGB]

must_haves:
  truths:
    - "A pure/near-pure green pixel (e.g. [10,250,15]) is left unchanged by a hard gain_g correction, because green is that pixel's dominant channel (vibrant green stays vibrant green)."
    - "An orange-ish mixed pixel (green non-dominant, e.g. [250,120,40]) IS corrected by the same gain_g setting — its green channel is pulled down."
    - "gain_r=gain_g=gain_b=1.0 is a byte-identical no-op (same contract boost_saturation_rgb documents for boost=0.0)."
    - "correct_channels_rgb never touches a pixel's dominant (max) channel for any gain values."
    - "GET/PUT /api/settings/color_correction_{r,g,b} round-trip in [0.5, 1.5]; values outside are rejected 422; default is 1.0."
    - "The three correction gains are read once per frame and applied AFTER boost_saturation_rgb to BOTH the Hue path and the WLED path, from the same shared gradient (once per region, not per sink)."
    - "The /ws/preview path is uncorrected (unchanged) — correction only affects light output."
    - "Three color-correction sliders (R, G, B), default 1.0, range 0.5–1.5, appear in both Settings surfaces with live PUT-on-change."
  artifacts:
    - path: "Backend/services/color_math.py"
      provides: "correct_channels_rgb(rgb, gain_r, gain_g, gain_b) — relational per-channel correction generalizing boost_saturation_rgb"
      contains: "def correct_channels_rgb"
    - path: "Backend/routers/settings.py"
      provides: "GET/PUT handlers for color_correction_r/g/b with [0.5, 1.5] range and 1.0 default"
      contains: "color_correction_r"
    - path: "Backend/database.py"
      provides: "INSERT OR IGNORE seed of the three keys at value '1.0'"
      contains: "color_correction_r"
    - path: "Backend/services/streaming_coordinator.py"
      provides: "per-frame read of the three gains + correct_channels_rgb applied after boost in both hue_gradients and _wled_pipeline"
      contains: "correct_channels_rgb"
  key_links:
    - from: "Backend/services/streaming_coordinator.py _frame_loop"
      to: "correct_channels_rgb"
      via: "applied after boost_saturation_rgb in the hue_gradients comprehension"
      pattern: "correct_channels_rgb\\("
    - from: "Backend/routers/settings.py put_color_correction_r"
      to: "_put_setting range args"
      via: "passing (0.5, 1.5)"
      pattern: "_put_setting\\(request, \"color_correction_r\", 0.5, 1.5\\)"
    - from: "SettingsPanel.tsx / SettingsPage.tsx"
      to: "SettingSlider color_correction_* instances"
      via: "min={0.5} max={1.5}"
      pattern: "settingKey=\"color_correction_"
---

<objective>
Add three global color-correction gains — `color_correction_r`, `color_correction_g`, `color_correction_b` (default 1.0 each) — so the user can manually fine-tune the R/G/B balance of the light output and compensate for a residual color-rendering characteristic in their physical Hue/WLED hardware. A just-closed debug session (`.planning/debug/hdr10-color-hue-shift.md`) confirmed the computed colors are correct end-to-end; the tint is downstream in the lights themselves, so this is a deliberate output-side adjustment, not a bug fix.

Purpose: give the user a hardware-tint knob without discoloring already-correct colors of other hues.

Output: a new relational `correct_channels_rgb` pure function in `color_math.py` (generalizing `boost_saturation_rgb`), three persisted live settings wired exactly like `saturation_boost`, the correction applied per-frame after saturation boost on the shared gradient for both sinks, and three sliders in both Settings surfaces.

CRITICAL DESIGN CONSTRAINT — the correction MUST be relational/proportional, never a flat `channel * gain` multiplier. A flat multiplier would also discolor genuinely-correct pure colors of other hues (a slider that reduces green to fix an orange tint would also dim a real vibrant green). The correct approach copies the structural property `boost_saturation_rgb` already has: only NON-dominant (non-max) channels are adjusted; each pixel's max channel is always left exactly unchanged. For a pixel where green IS the max (a real vibrant green), gain_g cannot touch it — that is precisely the "vibrant green stays vibrant green" guarantee. This dual property (dominant-channel invariance + correction of the same channel where it is non-dominant) is the actual spec and must be proven by a dedicated test.

SCOPE GUARD: Do NOT touch `hdr_input`, the PQ/BT.2020 HDR pipeline, `capture_v4l2.py`, or the `/ws/preview` path. Do NOT change `saturation_boost`, `color_vibrancy`, or `brightness_cutoff_threshold` ranges/math — the new keys ride the SAME shared `_put_setting` / `SettingSlider` infrastructure but must not disturb the existing settings.

TDD MODE IS OFF for this project (`config.json: "tdd_mode": false`). Plan tasks as implementation-then-test (or combined in one task), consistent with how the `saturation_boost` quick task (260714-png) was executed — NOT strict RED/GREEN cycles. `tdd="true"` on a task here just means "make the test expectations explicit up front," not that tests must be committed failing first.
</objective>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Extracted from the codebase — use directly, no exploration needed. -->

From Backend/services/color_math.py — the TEMPLATE to generalize (boost_saturation_rgb, ~line 439).
Note its key structural trick: `out = mx - (mx - arr) * ratio` leaves the max channel unchanged automatically because `(mx - mx) == 0`:
```python
def boost_saturation_rgb(rgb: np.ndarray, boost: float) -> np.ndarray:
    if boost == 0.0:
        return rgb
    arr = np.asarray(rgb, dtype=np.float32)
    mx = arr.max(axis=-1, keepdims=True)
    mn = arr.min(axis=-1, keepdims=True)
    chroma = mx - mn
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(mx > 0, chroma / mx, 0.0)
        if boost > 0.0:
            s_new = s + boost * (1.0 - s)
        else:
            s_new = s * (1.0 + boost)
        ratio = np.where(s > 1e-6, s_new / s, 1.0)
    out = mx - (mx - arr) * ratio
    return np.clip(out, 0.0, 255.0).astype(np.uint8)
```

From Backend/routers/settings.py — the shared helpers (~line 41, ~line 56). `_put_setting` already takes (min_value, max_value); `_get_setting` currently hardcodes a 0.0 missing-row default:
```python
async def _get_setting(request: Request, key: str) -> SettingValueResponse:
    ...
    if row is None:
        return SettingValueResponse(value=0.0)   # will need a per-key default for 1.0
    ...

async def _put_setting(request, key, min_value=0.0, max_value=1.0) -> SettingValueResponse:
    ...
    if v < min_value or v > max_value:
        raise HTTPException(status_code=422, detail=f"value must be in [{min_value}, {max_value}]")
    ...
    setattr(request.app.state, key, v)   # live update read by the coordinator next frame
```
Existing route pair pattern to mirror (saturation_boost, ~line 129):
```python
@router.get("/saturation_boost", response_model=SettingValueResponse)
async def get_saturation_boost(request): return await _get_setting(request, "saturation_boost")
@router.put("/saturation_boost", response_model=SettingValueResponse)
async def put_saturation_boost(request): return await _put_setting(request, "saturation_boost", -1.0, 1.0)
```

From Backend/database.py — the idempotent seed pattern (~line 109). New keys seed at "1.0" (identity), NOT "0.0":
```python
await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ("saturation_boost", "0.0"))
```

From Backend/main.py — the live-hydration block (~line 60). New keys default 1.0 in app.state:
```python
app.state.color_vibrancy = 0.0
app.state.saturation_boost = 0.0
app.state.hdr_input = 0.0
# ... SELECT key,value FROM settings WHERE key IN (...) -> setattr(app.state, key, float(value))
```

From Backend/services/streaming_coordinator.py — per-frame settings read + the TWO apply sites (~line 610-666).
`_read_live_setting(key, default)` already accepts a default; USE 1.0 for the gains so a missing attr is identity, not a destructive 0.0:
```python
vibrancy = self._read_live_setting("color_vibrancy")   # default 0.0
boost = self._read_live_setting("saturation_boost")    # default 0.0
# Hue path:
hue_gradients = {
    rid: boost_saturation_rgb(sub_sample_gradient(frame, mask, 1, orientation=orientation,
                                                  vibrancy=vibrancy, hdr=hdr), boost)
    for rid, (mask, n_region, orientation) in region_plan.items()
}
# WLED path (inside _wled_pipeline._compute):
result[rid] = boost_saturation_rgb(g, bst)
```
Import at module top (~line 30):
```python
from services.color_math import (boost_saturation_rgb, build_polygon_mask, sub_sample_gradient)
```

From Frontend/src/components/Settings/SettingSlider.tsx — ALREADY supports optional `min`/`max` props (default 0.0/1.0), STEP=0.01, PUT-on-change. No component change needed; just add three instances with `min={0.5} max={1.5}`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: correct_channels_rgb relational correction + unit tests (Backend pure function)</name>
  <files>Backend/services/color_math.py, Backend/tests/test_color_math.py</files>
  <behavior>
    correct_channels_rgb(rgb, gain_r, gain_g, gain_b):
    - gain_r == gain_g == gain_b == 1.0 -> returns the SAME array object unchanged (identity fast path, byte-identical no-op — mirror boost_saturation_rgb's `if boost == 0.0: return rgb` contract; assert `result is arr`).
    - For any gains: each pixel's dominant (max) channel is numerically unchanged, because out = mx - (mx - c)*g and (mx - mx)*g == 0.
    - gain_c > 1.0 pulls a NON-max channel c further from mx (more corrected-down); gain_c < 1.0 pulls it toward mx (boosted up). Direction: out_c = mx - (mx - c) * gain_c.
    - Accepts (N,3) and (3,) shapes; returns uint8; clips to [0,255]. Fully vectorized (no Python per-pixel loop), same style as boost_saturation_rgb.
    - "Vibrant green stays vibrant green" (THE spec, dual test):
      * Pure/near-pure green [10, 250, 15] with gain_r=1.0, gain_g=1.5 (green pushed hard in the reduce direction), gain_b=1.0 -> green channel (index 1) is unchanged (== 250), because green is dominant.
      * Orange-ish [250, 120, 40] (green NON-dominant) with the SAME gain_g=1.5 -> green channel IS reduced (out_g == 250 - (250-120)*1.5 == 55, well below 120).
    - Pure-gray pixels ([128,128,128]) unchanged for any gains (all channels == mx -> all deltas 0).
  </behavior>
  <action>
1. `Backend/services/color_math.py` — add `correct_channels_rgb(rgb, gain_r, gain_g, gain_b)` directly AFTER `boost_saturation_rgb` (share the section, it's the template):
   - Fast path: `if gain_r == 1.0 and gain_g == 1.0 and gain_b == 1.0: return rgb` (identity, same-object, zero cost — matches boost_saturation_rgb's boost==0.0 contract).
   - `arr = np.asarray(rgb, dtype=np.float32)`.
   - `mx = arr.max(axis=-1, keepdims=True)` (per-pixel dominant channel, exactly like boost_saturation_rgb line 460).
   - `gains = np.array([gain_r, gain_g, gain_b], dtype=np.float32)` — a (3,) vector that broadcasts across the last axis for both (N,3) and (3,) input, replacing boost_saturation_rgb's scalar/per-pixel `ratio`.
   - `out = mx - (mx - arr) * gains` — identical structure to boost_saturation_rgb's `out = mx - (mx - arr) * ratio`; the max channel is left exactly unchanged because its `(mx - c)` term is 0.
   - `return np.clip(out, 0.0, 255.0).astype(np.uint8)`.
   - Docstring: explain gains default 1.0 = identity, suggested UI range 0.5–1.5; gain>1 pulls non-max channel further from the dominant channel (corrects it down), gain<1 pulls it toward the dominant channel (boosts it up); the per-pixel dominant channel is invariant for all gains (this is the "vibrant green stays vibrant green" property). Reference quick-task 260714-txt.

2. `Backend/tests/test_color_math.py` — add a new `class TestCorrectChannels` (place after `TestSaturationBoost`, ~line 591), importing `correct_channels_rgb` alongside the existing color_math imports at the top of the file. Tests:
   - `test_all_gains_one_is_identity`: `arr = np.array([[200,100,50],[128,128,128]], dtype=np.uint8)`; `correct_channels_rgb(arr, 1.0, 1.0, 1.0) is arr` (same-object no-op).
   - `test_vibrant_green_stays_vibrant` (THE spec): `px = np.array([10, 250, 15], dtype=np.uint8)`; `out = correct_channels_rgb(px, 1.0, 1.5, 1.0)`; assert `int(out[1]) == 250` (green unchanged because it is dominant); dtype uint8.
   - `test_orange_green_is_corrected` (THE spec, paired): `px = np.array([250, 120, 40], dtype=np.uint8)`; `out = correct_channels_rgb(px, 1.0, 1.5, 1.0)`; assert `int(out[1]) < 120` and `int(out[0]) == 250` (red dominant, unchanged). Optionally assert `int(out[1]) == 55` for the exact formula value.
   - `test_dominant_channel_invariant`: for a batch `[[200,100,50],[10,10,200]]` with arbitrary gains e.g. (1.3, 0.7, 1.5), assert `(out.max(axis=-1) == arr.max(axis=-1)).all()` — the per-pixel max is preserved.
   - `test_gray_pixels_unchanged`: `[[128,128,128],[0,0,0],[255,255,255]]` with gains (1.5, 0.5, 1.5) returns the input unchanged.
   - `test_single_pixel_shape`: `correct_channels_rgb(np.array([200,50,50], dtype=np.uint8), 1.2, 1.0, 1.0).shape == (3,)`.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_color_math.py -q</automated>
  </verify>
  <done>correct_channels_rgb exists, is a byte-identical no-op at all-1.0 gains, preserves each pixel's dominant channel, corrects the SAME channel where it is non-dominant, and all new TestCorrectChannels tests pass (including the dual vibrant-green / corrected-orange spec).</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Persist + expose color_correction_r/g/b settings (DB seed, API, hydration) + settings tests</name>
  <files>Backend/database.py, Backend/routers/settings.py, Backend/main.py, Backend/tests/test_settings_router.py</files>
  <behavior>
    - init_db seeds ('color_correction_r','1.0'), ('color_correction_g','1.0'), ('color_correction_b','1.0') via INSERT OR IGNORE (default identity = 1.0, NOT 0.0).
    - GET /api/settings/color_correction_{r,g,b} returns 1.0 on a fresh seeded DB (and 1.0 as the missing-row fallback default).
    - PUT accepts [0.5, 1.5] inclusive; rejects < 0.5 and > 1.5 with 422; rejects NaN/Infinity 422; updates the DB row AND app.state.<key> live.
    - main.py hydrates app.state.color_correction_{r,g,b} = 1.0 on startup then overwrites from the DB.
    - Existing saturation_boost/color_vibrancy/hdr_input/brightness ranges + tests are untouched.
  </behavior>
  <action>
1. `Backend/database.py` — after the `hdr_input` seed (~line 119-122), add three `INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)` calls seeding `color_correction_r`, `color_correction_g`, `color_correction_b` each at `"1.0"`. Add a short comment referencing quick-task 260714-txt (mirror the existing seed comments). Note: value "1.0" not "0.0" — 1.0 is the identity/no-correction default.

2. `Backend/routers/settings.py`:
   - Extend `_get_setting` with an optional `default: float = 0.0` param; change the `if row is None:` branch and the parse-failure `except` branch to `return SettingValueResponse(value=default)` so the color_correction getters can return 1.0 when a row is missing. Existing callers pass no default -> unchanged 0.0 behavior.
   - Add three GET + three PUT route pairs mirroring the saturation_boost pair. GET handlers call `_get_setting(request, "color_correction_r", 1.0)` (and _g, _b). PUT handlers call `_put_setting(request, "color_correction_r", 0.5, 1.5)` (and _g, _b). Update the module docstring's endpoint list to mention the three new keys and their [0.5, 1.5] range.

3. `Backend/main.py` — in the hydration block (~line 60-77): set `app.state.color_correction_r = 1.0` (and _g, _b) before the SELECT, then extend the `SELECT ... WHERE key IN (...)` list to include the three new keys so they hydrate from the DB with the same setattr loop. Keep defaults at 1.0.

4. `Backend/tests/test_settings_router.py` — mirror the existing parametrized settings tests for the three new keys, but with the [0.5, 1.5] range and 1.0 default (do NOT add them to the existing `["color_vibrancy","saturation_boost","hdr_input"]` parametrize lists — those assert a 0.0 default and [0.0,1.0] range). Add a dedicated block (mirror the `saturation_boost` extended-range block at ~line 252):
     - `@pytest.mark.parametrize("key", ["color_correction_r","color_correction_g","color_correction_b"])` tests:
       - `test_color_correction_get_returns_default_one_on_fresh_db`: GET returns `{"value": 1.0}` (seeded default).
       - `test_color_correction_put_round_trip`: PUT `{"value": 1.2}` -> 200 + `{"value": 1.2}`, GET echoes 1.2.
       - `test_color_correction_accepts_boundary_low`: PUT `{"value": 0.5}` -> 200.
       - `test_color_correction_accepts_boundary_high`: PUT `{"value": 1.5}` -> 200.
       - `test_color_correction_rejects_below_min`: PUT `{"value": 0.49}` -> 422.
       - `test_color_correction_rejects_above_max`: PUT `{"value": 1.51}` -> 422.
       - `test_color_correction_rejects_nan`: PUT `{"value": float("nan")}` sent as raw JSON `{"value": NaN}` -> 422 (follow the existing NaN test idiom in the file).
       - `test_color_correction_put_updates_app_state`: PUT then assert `client.app.state.<key> == <value>` (mirror `test_new_setting_put_updates_app_state`).
   Use the existing `with _make_client() as client:` idiom throughout.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_settings_router.py -q</automated>
  </verify>
  <done>The three keys seed at 1.0, GET/PUT round-trip in [0.5, 1.5] with 1.0 default, reject out-of-range + NaN with 422, update app.state live, and hydrate on startup; existing settings tests still pass unchanged.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Apply correction per-frame in the coordinator (both sinks) + frontend sliders + tests</name>
  <files>Backend/services/streaming_coordinator.py, Backend/tests/test_streaming_coordinator.py, Frontend/src/components/Settings/SettingsPanel.tsx, Frontend/src/components/Settings/SettingsPage.tsx</files>
  <behavior>
    - The coordinator reads gain_r/gain_g/gain_b once per frame via `_read_live_setting("color_correction_r", 1.0)` etc. (DEFAULT 1.0 — a missing attr must be identity, never 0.0).
    - correct_channels_rgb is applied AFTER boost_saturation_rgb, on the SAME shared gradient, in BOTH the Hue path (hue_gradients comprehension) and the WLED path (_wled_pipeline._compute) — identical effect on both sinks, applied once per region not per sink.
    - At all-1.0 gains the fan-out output is byte-identical to pre-feature behavior (identity).
    - /ws/preview is NOT affected (preview_ws.py calls backend.get_jpeg() and never touches color_math — leave it untouched; do not add correction there).
    - Both Settings surfaces show three sliders (color_correction_r/g/b), default 1.0, min 0.5, max 1.5, live PUT-on-change via the existing SettingSlider component.
  </behavior>
  <action>
1. `Backend/services/streaming_coordinator.py`:
   - Add `correct_channels_rgb` to the `from services.color_math import (...)` block at module top (~line 30).
   - In `_frame_loop`, right after `boost = self._read_live_setting("saturation_boost")` (~line 617), add:
     `gain_r = self._read_live_setting("color_correction_r", 1.0)` / `gain_g = ... "color_correction_g", 1.0` / `gain_b = ... "color_correction_b", 1.0`. Comment: quick-task 260714-txt — per-frame live read, default 1.0 = identity.
   - Hue path (~line 639): wrap the existing `boost_saturation_rgb(sub_sample_gradient(...), boost)` in `correct_channels_rgb(..., gain_r, gain_g, gain_b)` so it is applied AFTER the boost.
   - WLED path: extend the `_wled_pipeline` closure signature to capture the gains (add `gr=gain_r, gg=gain_g, gb=gain_b` to its default-arg binding, mirroring how `bst=boost` is captured ~line 650), and in `_compute` change `result[rid] = boost_saturation_rgb(g, bst)` to `result[rid] = correct_channels_rgb(boost_saturation_rgb(g, bst), gr, gg, gb)`.
   - Do NOT duplicate the correction anywhere else and do NOT change the preview path.

2. `Backend/tests/test_streaming_coordinator.py` — add a test that the correction gains reach the shared gradient for both sinks. Mirror `test_frame_loop_passes_region_gradients_to_hue_render` (~line 235): build the same one-region DB + a mock hue and a mock wled, set `app_state` (a simple object / SimpleNamespace) with `color_correction_g = 1.5` and the other two gains + saturation_boost/color_vibrancy/hdr_input at identity, pass it via `app_state=` to StreamingCoordinator, run a few frames, and assert the gradient handed to `mock_hue.render` differs from the same region's gradient computed WITHOUT correction (or simpler: assert that with a hard non-identity gain the rendered gradient's green channel is reduced relative to an all-1.0 baseline run). Keep it lightweight — one assertion that a non-identity gain measurably changes the fanned-out gradient is enough to lock the wiring. Reuse the existing helpers (`make_mock_capture`, `_MockRegistry`, `_solid_blue_frame`, `_make_mock_hue`) in the file.

3. `Frontend/src/components/Settings/SettingsPanel.tsx` — after the `hdr_input` SettingToggle (~line 67-71), add three `<SettingSlider>` instances:
   ```tsx
   <SettingSlider settingKey="color_correction_r" label="Color correction — Red"
     description="Fine-tunes red output to compensate for your lights' color rendering. 1.00 = no change. Only affects non-dominant channels, so pure colors stay pure."
     min={0.5} max={1.5} />
   <SettingSlider settingKey="color_correction_g" label="Color correction — Green"
     description="Fine-tunes green output to compensate for your lights' color rendering. 1.00 = no change. Only affects non-dominant channels, so pure colors stay pure."
     min={0.5} max={1.5} />
   <SettingSlider settingKey="color_correction_b" label="Color correction — Blue"
     description="Fine-tunes blue output to compensate for your lights' color rendering. 1.00 = no change. Only affects non-dominant channels, so pure colors stay pure."
     min={0.5} max={1.5} />
   ```
   Update the surrounding comment block to reference quick-task 260714-txt.

4. `Frontend/src/components/Settings/SettingsPage.tsx` — apply the IDENTICAL three-slider addition after its `hdr_input` SettingToggle (~line 50-54), so both surfaces stay in sync (RESEARCH.md Pitfall 6 pattern the existing sliders follow). Do NOT touch any other slider instance.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_streaming_coordinator.py -q && cd ../Frontend && npx vitest run</automated>
  </verify>
  <done>The coordinator reads the three gains per frame and applies correct_channels_rgb after boost on the shared gradient for both Hue and WLED; a non-identity gain measurably changes the fanned-out gradient (test passes); preview path untouched; both Settings surfaces render three 0.5–1.5 sliders defaulting to 1.0; full frontend suite passes.</done>
</task>

</tasks>

<verification>
Full-suite regression per CLAUDE.md Autonomous Testing Checklist:
- Backend: `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` (167+ pass, no regressions)
- Frontend: `cd Frontend && npx vitest run` (30+ pass, no regressions)
- Optional visual check: launch the app, open Settings, confirm three color-correction sliders default to 1.00 and drag across 0.5–1.5.
</verification>

<success_criteria>
- `correct_channels_rgb(arr, 1.0, 1.0, 1.0)` is a same-object byte-identical no-op; any gains leave each pixel's dominant channel unchanged.
- Dual spec proven: pure green [10,250,15] with gain_g=1.5 keeps green at 250; orange [250,120,40] with the same gain_g=1.5 has green reduced.
- `GET/PUT /api/settings/color_correction_{r,g,b}` round-trip in [0.5, 1.5], default 1.0, reject out-of-range + NaN with 422, update app.state live, hydrate on startup.
- The correction is applied once per shared gradient after saturation boost and reaches BOTH the Hue and WLED sinks; `/ws/preview` is unaffected.
- Three sliders (R, G, B) appear in both Settings surfaces, default 1.00, range 0.5–1.5, live PUT-on-change.
- `hdr_input`, the HDR pipeline, `capture_v4l2.py`, and the other settings' ranges/math are untouched. Full backend + frontend suites pass.
</success_criteria>

<output>
After completion, create `.planning/quick/260714-txt-color-correction-sliders/260714-txt-SUMMARY.md`
</output>
