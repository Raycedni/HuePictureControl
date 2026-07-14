---
phase: 260714-png
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - Backend/services/color_math.py
  - Backend/routers/settings.py
  - Backend/tests/test_color_math.py
  - Backend/tests/test_settings_router.py
  - Frontend/src/components/Settings/SettingSlider.tsx
  - Frontend/src/components/Settings/SettingsPanel.tsx
  - Frontend/src/components/Settings/SettingsPage.tsx
  - Frontend/src/components/Settings/SettingSlider.test.tsx
autonomous: true
requirements: [SATBOOST-NEG]

must_haves:
  truths:
    - "boost_saturation_rgb desaturates when boost is negative (down to full grayscale at -1.0)"
    - "boost == 0.0 still returns the input array unchanged (same object, zero cost)"
    - "boost > 0.0 still raises saturation exactly as before (no behavior change)"
    - "PUT /api/settings/saturation_boost accepts values in [-1.0, 1.0]"
    - "PUT /api/settings for color_vibrancy, brightness_cutoff_threshold, hdr_input still reject negatives (range unchanged at [0.0, 1.0])"
    - "The saturation_boost slider in both Settings surfaces can be dragged to negative values"
    - "The color_vibrancy slider stays [0.0, 1.0] in both surfaces"
  artifacts:
    - path: "Backend/services/color_math.py"
      provides: "boost_saturation_rgb with symmetric negative-boost branch"
      contains: "s * (1.0 + boost)"
    - path: "Backend/routers/settings.py"
      provides: "_put_setting with per-setting (min_value, max_value) range"
      contains: "min_value"
    - path: "Frontend/src/components/Settings/SettingSlider.tsx"
      provides: "SettingSlider with optional min/max props"
      contains: "min ="
  key_links:
    - from: "Backend/routers/settings.py put_saturation_boost"
      to: "_put_setting range args"
      via: "passing (-1.0, 1.0)"
      pattern: "_put_setting\\(request, \"saturation_boost\", -1.0, 1.0\\)"
    - from: "SettingsPanel.tsx / SettingsPage.tsx saturation_boost slider"
      to: "SettingSlider min prop"
      via: "min={-1.0}"
      pattern: "min=\\{-1"
---

<objective>
Allow the `saturation_boost` setting to accept negative values in the range [-1.0, 1.0] so users can DESATURATE the output (useful for over-vibrant HDR content), not just boost saturation. This extends three shared generic layers (color math, settings validation, slider UI) without disturbing the other settings that ride on the same infrastructure.

Purpose: HDR content processed by the ambient-lighting pipeline comes out too vibrant; users need a way to pull saturation below the frame's natural level.

Output: Symmetric negative-boost math in `boost_saturation_rgb`, a per-setting range in `_put_setting`, optional `min`/`max` props on `SettingSlider`, wired `min={-1.0}` on both `saturation_boost` slider instances, and extended test coverage across backend + frontend.

CRITICAL SCOPE GUARD: Do NOT change `color_vibrancy` range or math. It shares the same `_put_setting` helper and `SettingSlider` component but must remain [0.0, 1.0]. Same for `brightness_cutoff_threshold` and `hdr_input`.
</objective>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Extracted from the codebase — use directly, no exploration needed. -->

From Backend/services/color_math.py (current boost_saturation_rgb, ~line 439):
```python
def boost_saturation_rgb(rgb: np.ndarray, boost: float) -> np.ndarray:
    if boost <= 0.0:
        return rgb
    arr = np.asarray(rgb, dtype=np.float32)
    mx = arr.max(axis=-1, keepdims=True)
    mn = arr.min(axis=-1, keepdims=True)
    chroma = mx - mn
    with np.errstate(invalid="ignore", divide="ignore"):
        s = np.where(mx > 0, chroma / mx, 0.0)
        s_new = s + boost * (1.0 - s)
        ratio = np.where(s > 1e-6, s_new / s, 1.0)
    out = mx - (mx - arr) * ratio
    return np.clip(out, 0.0, 255.0).astype(np.uint8)
```

From Backend/routers/settings.py (current _put_setting signature + range guard, ~line 56):
```python
async def _put_setting(request: Request, key: str) -> SettingValueResponse:
    ...
    if v < 0.0 or v > 1.0:
        raise HTTPException(status_code=422, detail="value must be in [0.0, 1.0]")
    ...
# All four route handlers call: await _put_setting(request, "<key>")
```

From Frontend/src/components/Settings/SettingSlider.tsx (module constants + Props, ~line 10):
```typescript
const STEP = 0.01
const MIN = 0.0
const MAX = 1.0

interface Props {
  settingKey: string
  label: string
  description: string
}
// <input ... min={MIN} max={MAX} step={STEP} ... />
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Negative-boost math + per-setting validation range (Backend)</name>
  <files>Backend/services/color_math.py, Backend/routers/settings.py, Backend/tests/test_color_math.py, Backend/tests/test_settings_router.py</files>
  <behavior>
    color_math.boost_saturation_rgb:
    - boost == 0.0 -> returns the SAME array object unchanged (identity fast path preserved; existing test asserts `result is arr`).
    - boost > 0.0 -> unchanged: s_new = s + boost*(1.0 - s); max channel (HSV V) numerically unchanged.
    - boost < 0.0 -> new: s_new = s * (1.0 + boost); at boost=-1.0 a saturated pixel becomes fully gray (all channels equal to the original max channel), at boost=-0.5 partially desaturated. Max channel (HSV V) still unchanged. No division-by-zero (uses the same `ratio = s_new/s where s>1e-6 else 1.0` guard).
    - Pure-gray pixels stay gray for ANY boost (positive OR negative).
    settings.py _put_setting:
    - saturation_boost PUT accepts -1.0..1.0 (inclusive); rejects < -1.0 and > 1.0 with 422.
    - color_vibrancy / brightness_cutoff_threshold / hdr_input still reject any negative value (default range [0.0, 1.0] unchanged) — regression guard.
    - 422 detail message reflects the ACTUAL allowed range for the setting (not a hardcoded "[0.0, 1.0]").
  </behavior>
  <action>
1. `Backend/services/color_math.py` — `boost_saturation_rgb(rgb, boost)`:
   - Change the fast-path guard from `if boost <= 0.0:` to `if boost == 0.0:` (identity, return `rgb` unchanged — keeps the `result is arr` contract for boost=0.0).
   - After computing `s` and BEFORE computing `s_new`, branch on the sign of `boost`:
     - `boost > 0.0`: keep existing `s_new = s + boost * (1.0 - s)`.
     - `boost < 0.0`: `s_new = s * (1.0 + boost)`.
     Implement with a scalar `if boost > 0.0: ... else: ...` (boost is a Python float scalar, not an array — a plain if/else is correct and clearest). Keep the `ratio = np.where(s > 1e-6, s_new / s, 1.0)` line and the `out = mx - (mx - arr) * ratio` line and the final `np.clip(out, 0.0, 255.0).astype(np.uint8)` EXACTLY as-is.
   - Update the docstring: document that `boost` ranges [-1.0, 1.0]; `0.0` = identity, `> 0.0` raises saturation (1.0 = full saturation S->1.0), `< 0.0` lowers saturation (-1.0 = full grayscale S->0.0). Keep the note that the max channel (HSV V) is preserved.

2. `Backend/routers/settings.py` — `_put_setting`:
   - Add two parameters with defaults: `async def _put_setting(request: Request, key: str, min_value: float = 0.0, max_value: float = 1.0)`.
   - Change the range guard to `if v < min_value or v > max_value:` and make the detail message reflect the range: `detail=f"value must be in [{min_value}, {max_value}]"`.
   - In `put_saturation_boost` ONLY, change the call to `return await _put_setting(request, "saturation_boost", -1.0, 1.0)`. Leave `put_brightness_cutoff`, `put_color_vibrancy`, `put_hdr_input` calling `_put_setting(request, "<key>")` unchanged (they inherit the [0.0, 1.0] default).

3. `Backend/tests/test_color_math.py` — extend class `TestSaturationBoost` with negative-boost cases:
   - `test_boost_negative_one_fully_desaturates`: a saturated pixel e.g. `[200, 50, 50]` at boost=-1.0 returns a gray pixel where all three channels equal the original max channel (200). Assert `boosted.max() == boosted.min()` per pixel and equals original max; dtype uint8.
   - `test_boost_negative_half_partially_desaturates`: e.g. `[200, 50, 50]` at boost=-0.5 has strictly lower saturation than the original but is not fully gray (min channel > original min, max channel == original max). Use the `_saturation` helper pattern already in the file.
   - `test_boost_negative_preserves_value`: max channel (HSV V) unchanged for negative boost, mirroring `test_boost_raises_saturation_leaves_value_unchanged`.
   - Confirm `test_boost_gray_pixels_stay_gray` still holds for negative boost (add an assertion or a param): pure gray unaffected at boost=-1.0.

4. `Backend/tests/test_settings_router.py` — adjust the shared parametrization + add saturation_boost negative cases:
   - REMOVE `"saturation_boost"` from the `@pytest.mark.parametrize("key", [...])` list on `test_new_setting_put_rejects_below_zero` (line ~208) so that test now covers only `["color_vibrancy", "hdr_input"]` (regression guard that the DEFAULT range still rejects negatives). Do NOT touch the other parametrized tests' key lists — `saturation_boost` must remain in `rejects_above_one` (1.5 is still invalid), `round_trip`, `boundary_zero`, `boundary_one`, `nan`, `updates_app_state`, `overwrites_previous_value`, and `get_returns_default_zero`.
   - ADD dedicated saturation_boost tests (not parametrized):
     - `test_saturation_boost_accepts_negative`: PUT `{"value": -0.5}` returns 200 and `{"value": -0.5}`.
     - `test_saturation_boost_accepts_boundary_negative_one`: PUT `{"value": -1.0}` returns 200.
     - `test_saturation_boost_rejects_below_negative_one`: PUT `{"value": -1.01}` returns 422.
     - `test_saturation_boost_rejects_above_one`: PUT `{"value": 1.01}` returns 422 (explicit upper-bound guard).
   Follow the existing `with _make_client() as client:` idiom used throughout the file.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_color_math.py tests/test_settings_router.py -q</automated>
  </verify>
  <done>All backend color_math + settings_router tests pass, including new negative-boost math cases and the saturation_boost [-1.0, 1.0] acceptance/rejection cases; color_vibrancy/brightness_cutoff_threshold/hdr_input still reject negatives.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Slider min/max props + wire saturation_boost to negative range (Frontend)</name>
  <files>Frontend/src/components/Settings/SettingSlider.tsx, Frontend/src/components/Settings/SettingsPanel.tsx, Frontend/src/components/Settings/SettingsPage.tsx, Frontend/src/components/Settings/SettingSlider.test.tsx</files>
  <behavior>
    - SettingSlider accepts optional `min` and `max` number props, defaulting to 0.0 and 1.0.
    - The rendered `<input type="range">` uses the prop values for its `min`/`max` attributes.
    - Existing color_vibrancy usage (no min/max passed) renders min=0 / max=1 unchanged.
    - saturation_boost slider in BOTH SettingsPanel and SettingsPage renders with min=-1.
  </behavior>
  <action>
1. `Frontend/src/components/Settings/SettingSlider.tsx`:
   - Add `min?: number` and `max?: number` to the `Props` interface.
   - Destructure with defaults in the component signature: `{ settingKey, label, description, min = 0.0, max = 1.0 }`.
   - Change the `<input>` attributes from `min={MIN} max={MAX}` to `min={min} max={max}`. Keep `step={STEP}`.
   - Remove the now-unused module-level `const MIN = 0.0` and `const MAX = 1.0` (keep `const STEP = 0.01` — a 0.01 step still works across [-1, 1]). If lint flags unused consts otherwise, deletion is required.

2. `Frontend/src/components/Settings/SettingsPanel.tsx`: on the `<SettingSlider settingKey="saturation_boost" ...>` instance, add `min={-1.0}`. Update its `description` to mention desaturation, e.g. "Adjusts output color saturation: negative desaturates, positive boosts. Brightness is unchanged." Do NOT add min/max to the `color_vibrancy` instance.

3. `Frontend/src/components/Settings/SettingsPage.tsx`: apply the IDENTICAL change to its `saturation_boost` `<SettingSlider>` instance — add `min={-1.0}` and the same updated description (Pitfall 6: both surfaces must stay in sync). Do NOT touch its `color_vibrancy` instance.

4. `Frontend/src/components/Settings/SettingSlider.test.tsx`:
   - Add a test verifying custom min/max props reach the rendered input, e.g. render with `min={-1}` and assert `(slider as HTMLInputElement).min === '-1'` and `.max === '1'`.
   - Add a test verifying the DEFAULT (no min/max passed) renders `.min === '0'` and `.max === '1'` (regression guard for color_vibrancy's untouched call site).
   - Existing tests must still pass unchanged.
  </action>
  <verify>
    <automated>cd Frontend && npx vitest run src/components/Settings/SettingSlider.test.tsx</automated>
  </verify>
  <done>SettingSlider exposes min/max props defaulting to 0/1; both saturation_boost slider instances render min=-1; color_vibrancy instances unchanged; new + existing frontend slider tests pass.</done>
</task>

</tasks>

<verification>
Full-suite regression per CLAUDE.md Autonomous Testing Checklist:
- Backend: `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` (167+ pass, no regressions)
- Frontend: `cd Frontend && npx vitest run` (30+ pass, no regressions)
</verification>

<success_criteria>
- `boost_saturation_rgb(arr, -1.0)` fully desaturates a color to gray (channels == original max); `boost=0.0` still returns the same object; `boost>0.0` unchanged.
- `PUT /api/settings/saturation_boost` accepts [-1.0, 1.0], rejects outside with 422 and an accurate range message.
- `color_vibrancy`, `brightness_cutoff_threshold`, `hdr_input` still reject negatives.
- Both `saturation_boost` slider instances allow dragging to negative values; `color_vibrancy` sliders unchanged at [0.0, 1.0].
- Full backend + frontend test suites pass.
</success_criteria>

<output>
After completion, create `.planning/quick/260714-png-allow-saturation-boost-setting-to-go-neg/260714-png-SUMMARY.md`
</output>
