---
phase: quick-260719-efy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - Backend/services/color_math.py
  - Backend/tests/test_color_math.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "correct_channels_rgb applies flat per-channel multiplicative gain to every pixel unconditionally (out = clip(arr * [gain_r, gain_g, gain_b], 0, 255))"
    - "gain_r == gain_g == gain_b == 1.0 returns the input unchanged (same object, zero cost)"
    - "A pure/near-pure green pixel's green channel IS scaled by gain_g (no longer dominant-channel invariant)"
    - "Extreme gains clip cleanly at 0 and 255"
    - "Docstring describes static/flat per-channel multiplicative hardware-tint compensation with no dominant-channel-invariance claims"
    - "Full backend test suite passes (no regressions in wiring/settings tests referencing color_correction_r/g/b)"
  artifacts:
    - path: "Backend/services/color_math.py"
      provides: "Reworked correct_channels_rgb (flat multiplicative) + updated docstring"
      contains: "def correct_channels_rgb"
    - path: "Backend/tests/test_color_math.py"
      provides: "Rewritten TestCorrectChannels asserting flat multiplicative behavior"
      contains: "class TestCorrectChannels"
  key_links:
    - from: "correct_channels_rgb"
      to: "streaming_coordinator.py call sites"
      via: "unchanged name/signature/settings keys"
      pattern: "correct_channels_rgb\\("
---

<objective>
Rework `correct_channels_rgb` in Backend/services/color_math.py from a relational
(dominant-channel-invariant) algorithm to a STATIC/flat per-channel multiplicative
gain applied to every pixel unconditionally. The user tested the relational version
on real hardware and it did not produce the desired effect; they want a
straightforward `out = clip(arr * [gain_r, gain_g, gain_b], 0, 255)`.

Purpose: Make the color_correction_r/g/b sliders act as a direct, intuitive
per-channel multiplier for hardware-tint compensation.
Output: Reworked function + docstring in color_math.py, rewritten TestCorrectChannels
in test_color_math.py, full backend suite green.

Scope is INTERNAL only — no rename, no re-wire. Function name, signature, settings
keys (`color_correction_r/g/b`), UI range (0.5-1.5), and all call sites in
streaming_coordinator.py stay EXACTLY as they are. No changes to
streaming_coordinator.py, database.py, routers/settings.py, main.py, or any frontend file.
</objective>

<execution_context>
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@CLAUDE.md

<interfaces>
<!-- Current signature (UNCHANGED by this task): -->
def correct_channels_rgb(
    rgb: np.ndarray, gain_r: float, gain_g: float, gain_b: float
) -> np.ndarray

<!-- Style reference for identity fast-path + numpy conventions (do NOT modify): -->
boost_saturation_rgb(rgb, boost)  # boost==0.0 returns rgb unchanged (same object);
                                  # uses np.asarray(rgb, np.float32) then
                                  # np.clip(out, 0.0, 255.0).astype(np.uint8)

<!-- Current correct_channels_rgb (the code to REPLACE), color_math.py ~lines 474-517:
     identity fast-path returns rgb unchanged; then
       arr = np.asarray(rgb, dtype=np.float32)
       mx  = arr.max(axis=-1, keepdims=True)
       gains = np.array([gain_r, gain_g, gain_b], dtype=np.float32)
       out = mx - (mx - arr) * gains           # <-- relational, replace this
       return np.clip(out, 0.0, 255.0).astype(np.uint8)
     NOTE: existing path uses .astype(np.uint8) (truncation, not rounding) —
     keep that convention so int() truncation behavior is predictable. -->
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rework correct_channels_rgb to flat per-channel multiplicative gain</name>
  <files>Backend/services/color_math.py</files>
  <behavior>
    - gain_r == gain_g == gain_b == 1.0 → return input unchanged (same object)
    - Otherwise: out = clip(arr * [gain_r, gain_g, gain_b], 0, 255), applied to
      EVERY channel of EVERY pixel regardless of which channel is the per-pixel max
    - Output dtype uint8 (truncation via .astype(np.uint8), matching existing convention)
    - Accepts (3,) and (N, 3) shapes (broadcasting over last axis)
  </behavior>
  <action>
Replace ONLY the body of `correct_channels_rgb` (color_math.py, currently ~lines
474-517). Keep the exact function name and signature
`correct_channels_rgb(rgb, gain_r, gain_g, gain_b) -> np.ndarray`.

New implementation:
1. Keep the identity fast-path unchanged:
   `if gain_r == 1.0 and gain_g == 1.0 and gain_b == 1.0: return rgb`
2. Replace the relational body with flat multiplicative scaling:
   ```python
   arr = np.asarray(rgb, dtype=np.float32)
   gains = np.array([gain_r, gain_g, gain_b], dtype=np.float32)
   out = arr * gains
   return np.clip(out, 0.0, 255.0).astype(np.uint8)
   ```
   Remove the `mx = arr.max(...)` line and the `out = mx - (mx - arr) * gains` line.

Rewrite the docstring to describe this as a STATIC/flat per-channel multiplicative
hardware-tint compensation knob. Requirements for the docstring:
- Describe each gain as a direct multiplier on its channel (red = arr[...,0]*gain_r, etc.),
  applied to every pixel unconditionally. 1.0 = identity per channel. Suggested UI
  range [0.5, 1.5].
- State that values are clipped to [0, 255] (so gains > 1.0 can saturate a channel).
- State the gain_r==gain_g==gain_b==1.0 identity contract (returns rgb unchanged, zero cost).
- REMOVE all dominant/max-channel invariance language: delete the "vibrant green stays
  vibrant green" claim, the "dominant channel is numerically unchanged" claim, and the
  "gain only affects non-dominant channels" framing — none of these hold anymore.
- Keep the note that this is a hardware-tint compensation knob (residual color rendering
  in the physical Hue/WLED lights), NOT a color-correctness fix.

Do NOT touch any other function in the file. Do NOT change imports.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -c "import numpy as np; from services.color_math import correct_channels_rgb as f; a=np.array([10,200,15],dtype=np.uint8); print(tuple(f(a,1.0,1.0,1.0))); print(tuple(f(a,1.0,0.5,1.0))); print(tuple(f(np.array([250,120,40],dtype=np.uint8),1.5,1.0,1.0)))"</automated>
  </verify>
  <done>correct_channels_rgb uses flat `arr * gains` scaling; identity fast-path preserved (same object); docstring rewritten with no dominant-channel-invariance claims. The verify snippet prints (10, 200, 15), (10, 100, 15), and (255, 120, 40).</done>
</task>

<task type="auto">
  <name>Task 2: Rewrite TestCorrectChannels for flat behavior and run full backend suite</name>
  <files>Backend/tests/test_color_math.py</files>
  <action>
Rewrite the `TestCorrectChannels` class (test_color_math.py, currently ~lines 599-642).
DELETE the tests that assert the old relational/dominant-preserving guarantees:
- `test_vibrant_green_stays_vibrant`
- `test_orange_green_is_corrected`
- `test_dominant_channel_invariant`
The `test_all_gains_one_is_identity`, `test_gray_pixels_unchanged`, and
`test_single_pixel_shape` tests need review — `test_all_gains_one_is_identity` (same-object
identity) still holds and can stay; `test_gray_pixels_unchanged` is now FALSE under flat
gains (gray IS scaled), so replace it. Keep `test_single_pixel_shape` (shape contract holds).

Write the class to assert flat multiplicative behavior. Include at minimum:
1. Identity: `correct_channels_rgb(arr, 1.0, 1.0, 1.0) is arr` (same object, zero cost).
2. Green IS scaled (no invariance): a near-pure green pixel `[10, 200, 15]` with
   gains `(1.0, 0.5, 1.0)` → green channel becomes 100 (i.e. `int(out[1]) == 100`),
   red==10, blue==15. This is the direct inverse of the deleted
   `test_vibrant_green_stays_vibrant` — assert green DID change.
3. Uniform application regardless of per-pixel max: for `[100, 200, 50]` with gains
   `(1.5, 1.0, 1.0)`, red (a NON-max channel) is scaled to 150 (`int(out[0]) == 150`),
   green (the max) unchanged at 200, blue unchanged at 50 — proving gains apply to every
   channel independent of which is dominant.
4. Clipping at 255: `[250, 120, 40]` with gains `(1.5, 1.0, 1.0)` → red clips to 255.
5. Clipping at 0 / scale-down: a gain of 0.5 on `[200, 0, 0]` → red 100, and confirm no
   negative/underflow (all channels >= 0). (gains are >= 0.5 in the UI so 0-clip is only
   reachable at exact-zero input; assert output stays in [0, 255] and dtype uint8.)
6. Output dtype is uint8 and single-pixel `(3,)` shape is preserved.

Use exact integer expected values (truncation via astype(uint8), so pick values that
divide/multiply cleanly: 200*0.5=100, 100*1.5=150, 250*1.5=375→clip 255).

Do NOT modify any other test class in the file. The `correct_channels_rgb` import at
the top of the file is already present — leave it.

After editing, run the FULL backend test suite (per CLAUDE.md) to confirm no regressions
in other files that reference color_correction_r/g/b (they test wiring/settings, not the
internal algorithm, so must still pass unchanged).
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_color_math.py::TestCorrectChannels -q && python -m pytest --tb=short -q</automated>
  </verify>
  <done>TestCorrectChannels asserts flat multiplicative behavior (green scaled, uniform-across-channels, clipping, identity, shape); all old relational assertions removed; `TestCorrectChannels` passes and the full backend suite (167+ tests) is green with zero regressions.</done>
</task>

</tasks>

<verification>
- correct_channels_rgb: identity at 1/1/1 returns same object; flat `arr * gains` clipped to [0,255] uint8 otherwise.
- Docstring contains no "vibrant green stays vibrant green" / dominant-invariance language.
- Full backend suite green: `python -m pytest` (all 167+ tests pass).
- No edits outside color_math.py and test_color_math.py (git diff shows only these two files).
</verification>

<success_criteria>
- `correct_channels_rgb` applies flat per-channel multiplicative gain to every pixel unconditionally.
- Identity fast-path (1.0/1.0/1.0 → same object) preserved.
- Docstring describes static/flat multiplicative hardware-tint compensation, no relational claims.
- `TestCorrectChannels` rewritten to assert flat behavior; old relational tests removed.
- Full backend test suite passes with no regressions.
- Function name, signature, settings keys, UI range, and streaming_coordinator.py call sites unchanged.
- NOT deployed (local implement + test only).
</success_criteria>

<output>
After completion, create `.planning/quick/260719-efy-rework-color-correction-from-relational-/260719-efy-SUMMARY.md`
</output>
