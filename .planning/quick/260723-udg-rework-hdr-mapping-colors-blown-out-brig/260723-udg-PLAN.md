---
phase: quick-260723-udg
plan: 01
type: tdd
wave: 1
depends_on: []
files_modified:
  - Backend/services/color_math.py
  - Backend/tests/test_color_math.py
autonomous: true
requirements: [QUICK-260723-UDG]
must_haves:
  truths:
    - "Bright saturated orange HDR input maps to an orange light color (R > G > B), never green/yellow-white"
    - "Brown (dark orange) HDR input keeps its R:G:B channel ratios instead of shifting to red"
    - "SDR-range HDR content (below the tone-map knee) passes through with channel ratios exactly preserved"
    - "Highlights compress smoothly toward white without per-channel clipping artifacts"
  artifacts:
    - path: "Backend/services/color_math.py"
      provides: "Hue-preserving max-RGB tone map + hue-preserving BT.709 gamut compression in _finish_linear_bt2020_to_srgb"
      contains: "_tone_map_max_rgb"
    - path: "Backend/tests/test_color_math.py"
      provides: "Behavior tests proving hue stability and ratio preservation"
      contains: "TestHuePreservingToneMap"
  key_links:
    - from: "Backend/services/color_math.py:extract_region_color (hdr=True)"
      to: "_finish_linear_bt2020_to_srgb"
      via: "single-call finish after linear-light averaging"
      pattern: "_finish_linear_bt2020_to_srgb\\(lin_"
    - from: "Backend/services/color_math.py:hdr10_to_srgb"
      to: "_finish_linear_bt2020_to_srgb"
      via: "composition LUT -> finish"
      pattern: "_finish_linear_bt2020_to_srgb\\(rel\\)"
---

<objective>
Rework the HDR10 finishing stage (`_finish_linear_bt2020_to_srgb`) from per-channel extended-Reinhard tone mapping to a hue-preserving pipeline: scalar max-RGB tone map (uniform per-sample scaling) followed by hue-preserving gamut compression toward the achromatic axis instead of per-channel clipping.

Purpose: The current per-channel Reinhard destroys channel ratios on bright colors — bright orange collapses to near-white yellow (which `saturation_boost` then rotates toward green), diffuse white maps to ~0.5 (midtone crush users compensate for by blowing out brightness), and per-channel clipping after the BT.2020→BT.709 matrix rotates brown into red. All three reported symptoms trace to this one function.

Output: A reworked `_finish_linear_bt2020_to_srgb` (same signature, same callers, zero wiring changes) with two new testable private helpers, plus a rewritten/extended HDR test suite proving hue stability.
</objective>

<execution_context>
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@Backend/services/color_math.py
@Backend/tests/test_color_math.py

<interfaces>
Current function under rework (Backend/services/color_math.py, ~line 811):

```python
def _finish_linear_bt2020_to_srgb(rel: np.ndarray) -> np.ndarray:
    """(N,3) or (3,) float32 RGB linear light (1.0 == diffuse white) -> uint8 sRGB."""
```

Defective section (line ~834-841): per-channel extended Reinhard
`toned = arr * (1.0 + arr / (white * white)) / (1.0 + arr)` with
`white = 10000.0 / HDR_REF_WHITE_NITS` (~49.26), followed by
`rel709 = toned @ _BT2020_TO_BT709.T`, `np.maximum(rel709, 0.0)`,
sRGB OETF, `np.clip(srgb, 0.0, 1.0)`.

Callers (all keep working unchanged — signature is preserved):
- `extract_region_color` hdr=True path: `_finish_linear_bt2020_to_srgb(lin_rgb)` on a (3,) mean
- `sub_sample_gradient` hdr=True path: `_finish_linear_bt2020_to_srgb(lin_means)` on an (n,3) buffer
- `hdr10_to_srgb`: `_finish_linear_bt2020_to_srgb(_LINEAR_LUT[arr])`

Module constants that stay untouched: `_LINEAR_LUT`, `HDR_REF_WHITE_NITS`,
`_BT2020_TO_BT709`, all PQ constants.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Replace per-channel Reinhard with hue-preserving max-RGB tone map + gamut compression (tests first)</name>
  <files>Backend/services/color_math.py, Backend/tests/test_color_math.py</files>
  <behavior>
    Write these tests FIRST in a new `TestHuePreservingToneMap` class in Backend/tests/test_color_math.py (RED commit), driving the two new private helpers plus the reworked finish. Import `_finish_linear_bt2020_to_srgb`, `_tone_map_max_rgb`, `_compress_to_gamut_709` directly.

    - Ratio preservation through the tone map: for a bright linear BT.2020 sample `[40.0, 13.0, 2.0]`, `_tone_map_max_rgb` output has R/G and R/B ratios equal to the input ratios within 1e-4 relative tolerance (uniform scaling), and max channel <= 1.0.
    - Sub-knee passthrough: a linear sample with max channel below the knee constant (e.g. `[0.5, 0.25, 0.1]`) is returned by `_tone_map_max_rgb` bit-identically (no compression below the knee).
    - Midtone crush fixed: diffuse-white linear input `[1.0, 1.0, 1.0]` tone-maps to a max channel > 0.85 (old code produced ~0.5).
    - Monotonicity: for the same chromaticity `[2,1,0.2] * k` at k = 1, 4, 16, output max channel via `_tone_map_max_rgb` is non-decreasing in k and all <= 1.0.
    - Saturation survives highlights: full finish of very bright saturated orange linear `[40.0, 13.0, 2.0]` yields uint8 output with r > g > b AND HSV-style saturation (max-min)/max >= 0.5 — proving no collapse to near-white (the root cause of the green shift after saturation_boost).
    - Brown stays brown: full finish of `[0.35, 0.18, 0.06]` (dark orange / brown, sub-knee) yields r > g > b with r/g output byte ratio within 15% of the sRGB-encoded expectation of the un-tone-mapped input — no red shift from channel crush.
    - Hue-preserving gamut compression: `_compress_to_gamut_709` on a BT.2020->709 out-of-gamut sample with a negative channel (e.g. `[-0.1, 0.8, 0.2]`) returns all channels in [0,1], keeps G as the dominant channel, and preserves Rec.709 luma within 1e-3 (compression is a lerp toward the achromatic axis, not a clip).
    - In-gamut passthrough: `_compress_to_gamut_709` on `[0.5, 0.3, 0.1]` returns it unchanged.
    - Black safety: `_finish_linear_bt2020_to_srgb(np.zeros(3, dtype=np.float32))` returns `[0, 0, 0]` uint8, no NaN/warnings.
    - Shape/dtype contracts: (3,) in -> (3,) uint8 out; (N,3) in -> (N,3) uint8 out (mirrors existing TestHdr10ToSrgb shape tests).

    Existing tests that MUST still pass unchanged: all of TestHdr10ToSrgb (neutral gray stays neutral, saturated orange stays r > g > b, black stays black, bright white stays neutral, shapes), all of TestLinearLut, all of TestHdrLinearAveraging (linear-averaging semantics are untouched — only the finishing curve changes). Do NOT weaken any existing assertion.
  </behavior>
  <action>
    After the RED commit, rework Backend/services/color_math.py (GREEN commit):

    1. Add module constant `_TONE_KNEE = np.float32(0.75)` next to `HDR_REF_WHITE_NITS` with a one-line comment (linear-light knee below which the tone map is identity; SDR-range content passes through untouched).

    2. Add `_tone_map_max_rgb(rel: np.ndarray) -> np.ndarray` (private, operates on (N,3) float32 linear BT.2020 RGB, returns same shape float32). Per sample: m = max(R,G,B). Scalar shoulder curve f: f(m) = m for m <= _TONE_KNEE; f(m) = 1 - (1 - k) * exp(-(m - k) / (1 - k)) for m > k where k = _TONE_KNEE — C1-continuous exponential shoulder (f(k) = k, f'(k) = 1, asymptote 1.0), so HDR white (~49.26) lands just under 1.0. Apply UNIFORM per-sample scale = f(m)/m to all three channels (guard m < 1e-6 -> scale 1.0, sample stays black). This preserves hue AND saturation exactly and guarantees every channel <= 1.0 before the primaries matrix. Vectorize with np.where — no Python loop.

    3. Add `_compress_to_gamut_709(rel709: np.ndarray) -> np.ndarray` (private, (N,3) float32 in [roughly -0.3..1.2] -> (N,3) float32 in [0,1]). Per sample: Y = Rec.709 luma (reuse the 0.2126/0.7152/0.0722 coefficients already in the module as _REC709_LUMA, but note _REC709_LUMA is float64 — cast appropriately). For samples with any channel outside [0,1], lerp toward the achromatic axis: rgb' = Y + (rgb - Y) * s with the largest s in [0,1] such that all channels land in [0,1]; per channel the feasible s is Y/(Y-c) when c < 0 and (1-Y)/(c-Y) when c > 1, s = min over offending channels clipped to [0,1]. Guard degenerate Y (Y <= 0 or Y >= 1): fall back to plain np.clip for that sample. Finish with a safety np.clip(rgb', 0.0, 1.0) for float round-off. In-gamut samples pass through untouched. Vectorized; suppress divide warnings with np.errstate as boost_saturation_rgb does.

    4. Rework `_finish_linear_bt2020_to_srgb` body to: (a) `toned = _tone_map_max_rgb(arr)`, (b) `rel709 = toned @ _BT2020_TO_BT709.T` (unchanged), (c) `rel709 = _compress_to_gamut_709(rel709)` replacing the bare `np.maximum(rel709, 0.0)`, (d) sRGB OETF encode + final clip + uint8 round (unchanged). Keep the (3,)/(N,3) single-row squeeze logic and signature byte-identical.

    5. Update the docstrings of `_finish_linear_bt2020_to_srgb` and the module-level HDR comment block (the v1/v2 narrative around line 732-765) with a short v3 paragraph (quick-task 260723-udg): per-channel Reinhard rotated hue and collapsed saturation on highlights (orange->green via saturation_boost, brown->red via channel crush + clip); v3 tone-maps the max-RGB scalar with a knee+exponential shoulder and gamut-compresses toward the achromatic axis, preserving hue end-to-end. Do NOT put implementation code in comments elsewhere; do NOT touch `_LINEAR_LUT`, `hdr10_to_srgb`'s composition, `extract_region_color`, `sub_sample_gradient`, or any hdr=False path.

    Keep _TONE_KNEE a module constant (no new settings key/UI) — this is Claude's-discretion scope control; the existing hdr_input toggle remains the only user-facing switch.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_color_math.py -x -q</automated>
  </verify>
  <done>New TestHuePreservingToneMap tests pass; all pre-existing TestHdr10ToSrgb, TestLinearLut, TestHdrLinearAveraging tests pass without modification; RED and GREEN commits exist (test(quick-260723-udg): ... then feat(quick-260723-udg): ...).</done>
</task>

<task type="auto">
  <name>Task 2: Full-suite regression — prove hdr=False paths and all sinks are untouched</name>
  <files>Backend/services/color_math.py</files>
  <action>
    Run the complete backend suite (167+ tests) to prove the rework leaked nowhere: streaming_coordinator reads `hdr_input` per frame and forwards `hdr=` into sub_sample_gradient, so test_streaming_coordinator / test_color_math SDR-path parity tests must all pass. Confirm via grep that `_finish_linear_bt2020_to_srgb` still has exactly the same three call sites (extract_region_color hdr path, sub_sample_gradient hdr path, hdr10_to_srgb) and that no hdr=False code path changed — `git diff` on Backend/services/color_math.py must show edits only inside the HDR section (the two new helpers, _TONE_KNEE, the finish body, and comments). If any non-HDR hunk appears, revert it. No frontend changes in this task.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest -q</automated>
  </verify>
  <done>Full backend suite green; git diff confined to the HDR section of color_math.py plus test file; no changes to streaming_coordinator.py, routers, or Frontend.</done>
</task>

</tasks>

<verification>
- `python -m pytest Backend/tests/test_color_math.py -q` — all color-math tests green including new TestHuePreservingToneMap.
- `python -m pytest -q` in Backend — full suite green (167+).
- <human-check>On real hardware after deploy (via .claude/vm-exec.sh per memory — pull, restart hpc-backend): play HDR content with bright orange (fire/sunset) and brown (wood/skin) scenes with hdr_input=1. Lights should show orange as orange (not green/yellow-white) and brown as warm dark orange (not red), with highlights bright but not blown out. Existing saturation_boost/color_correction settings may need re-tuning downward since colors no longer collapse to white.</human-check>
</verification>

<success_criteria>
- Per-channel Reinhard removed; tone mapping is a uniform per-sample scale driven by max(R,G,B) with knee + exponential shoulder.
- Post-matrix negative/overflow handling is hue-preserving lerp toward the achromatic axis, not per-channel clip.
- Channel-ratio preservation proven by automated test (1e-4 tolerance through the tone map).
- Diffuse white (linear 1.0) maps above 0.85 instead of ~0.5 — midtone crush eliminated.
- All pre-existing HDR and SDR-parity tests pass without weakened assertions.
</success_criteria>

<output>
Create `.planning/quick/260723-udg-rework-hdr-mapping-colors-blown-out-brig/260723-udg-SUMMARY.md` when done.
</output>
