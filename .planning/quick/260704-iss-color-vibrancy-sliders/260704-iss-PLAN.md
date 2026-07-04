---
phase: quick-260704-iss
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - Backend/services/color_math.py
  - Backend/tests/test_color_math.py
  - Backend/routers/settings.py
  - Backend/main.py
  - Backend/database.py
  - Backend/services/streaming_coordinator.py
  - Backend/tests/test_settings_router.py
  - Frontend/src/api/settings.ts
  - Frontend/src/components/Settings/SettingSlider.tsx
  - Frontend/src/components/Settings/SettingSlider.test.tsx
  - Frontend/src/components/Settings/SettingsPage.tsx
  - Frontend/src/components/Settings/SettingsPanel.tsx
autonomous: true
requirements: [QUICK-260704-iss]
must_haves:
  truths:
    - "Two new sliders (color vibrancy, saturation boost) appear in Settings next to the brightness cutoff slider, on both SettingsPage and SettingsPanel"
    - "At vibrancy 0.0 and boost 0.0 (defaults) the light output is byte-identical to current behavior — all existing backend and frontend tests pass unchanged"
    - "Raising color vibrancy suppresses white pixels in a region's color WITHOUT dimming it (weighted-mean chromaticity rescaled to unweighted-mean luma)"
    - "Raising saturation boost increases output saturation while HSV V (brightness) is unchanged"
    - "Both settings persist across restart (DB row) and apply mid-stream without a restart (app.state live-read per frame)"
  artifacts:
    - path: "Backend/services/color_math.py"
      provides: "vibrancy param on extract_region_color + sub_sample_gradient; boost_saturation_rgb helper"
      contains: "def boost_saturation_rgb"
    - path: "Backend/routers/settings.py"
      provides: "GET/PUT for color_vibrancy and saturation_boost"
      contains: "color_vibrancy"
    - path: "Backend/services/streaming_coordinator.py"
      provides: "per-frame read of vibrancy+boost, threaded into gradient compute + post-boost"
    - path: "Frontend/src/components/Settings/SettingSlider.tsx"
      provides: "reusable key-parameterized settings slider"
  key_links:
    - from: "streaming_coordinator.py frame loop"
      to: "sub_sample_gradient(..., vibrancy=...)"
      via: "vibrancy read from app_state per frame"
      pattern: "vibrancy="
    - from: "streaming_coordinator.py frame loop"
      to: "boost_saturation_rgb(gradient, boost)"
      via: "post-gradient boost before render"
      pattern: "boost_saturation_rgb"
    - from: "routers/settings.py PUT"
      to: "request.app.state.color_vibrancy / .saturation_boost"
      via: "live mirror after DB upsert"
      pattern: "app.state.color_vibrancy"
    - from: "SettingSlider.tsx"
      to: "/api/settings/{key}"
      via: "fetch on mount + PUT on change"
      pattern: "/api/settings/"
---

<objective>
Add two global vibrancy settings to fix "white pollution" in region color extraction. Small bright white elements (subtitles, HUD lines) inside a region currently desaturate the mean color sent to the LEDs.

- `color_vibrancy` (0.0–1.0, default 0.0): saturation-weighted region sampling that suppresses white pixels' chromaticity contribution while preserving brightness.
- `saturation_boost` (0.0–1.0, default 0.0): post-hoc output saturation boost that leaves brightness (HSV V) untouched.

Purpose: gradient-capable Hue devices and WLED strips render vivid, accurate colors even when a region contains bright white UI overlays.
Output: extended color math + settings KV wiring (replicating the existing `brightness_cutoff_threshold` pattern) + two Settings sliders.
</objective>

<execution_context>
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

# The feature replicates quick-task 260516-kra's brightness_cutoff_threshold
# wiring end-to-end. Study these before editing:
@Backend/routers/settings.py
@Backend/services/color_math.py
@Backend/services/streaming_coordinator.py
@Backend/tests/test_settings_router.py
@Frontend/src/components/Settings/BrightnessCutoffControl.tsx

<interfaces>
<!-- Contracts the executor needs — extracted from the codebase. No exploration required. -->

color_math.py functions to extend (Backend/services/color_math.py):
```python
def extract_region_color(frame: np.ndarray, region: RegionMask) -> tuple[int, int, int]:
    # Current: roi_frame = frame[y1:y2, x1:x2]; cv2.mean(roi_frame, mask=roi_mask) -> (r,g,b)
    # cv2.mean returns BGR; code returns (r_val, g, b) as ints.

def sub_sample_gradient(frame, region, n, orientation="auto") -> np.ndarray:
    # n<=1 short-circuits to extract_region_color.
    # n>1: per-slab cv2.mean loop over roi_frame; returns (n_effective, 3) uint8 RGB.
    # roi_frame = frame[region.y1:region.y2, region.x1:region.x2] (BGR)
    # slab_frame / slab_mask are column (axis_x) or row slices of roi_frame / region.roi_mask.
```

settings.py PUT validation pattern (Backend/routers/settings.py) — MUST replicate exactly:
```python
# Manual body parse (NOT a Pydantic body model) so NaN/Inf reject as a clean 422.
raw = await request.body(); body = json.loads(raw)   # -> 422 "invalid JSON body"
# require dict with "value"; reject bool; require int/float; require math.isfinite; require 0.0<=v<=1.0
# upsert: INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value
# await db.commit(); request.app.state.<field> = v   # live mirror
```

main.py startup hydrate (Backend/main.py ~L37-52) — mirror for both new keys:
```python
app.state.brightness_cutoff_threshold = 0.0
# SELECT value FROM settings WHERE key = 'brightness_cutoff_threshold'; float(row["value"]) on hit
# try/except so a stale DB image without the row still boots.
```

database.py seed (Backend/database.py ~L103-106):
```python
await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                 ("brightness_cutoff_threshold", "0.0"))
```

coordinator per-frame gradient build (Backend/services/streaming_coordinator.py _frame_loop):
```python
hue_gradients = { rid: sub_sample_gradient(frame, mask, 1, orientation=orientation)
                  for rid, (mask, n_region, orientation) in region_plan.items() }
# inside _wled_pipeline._compute(): sub_sample_gradient(current_frame, mask, n_region, orientation=orientation)
# self._app_state is available on the coordinator (may be None in tests).
```

Frontend api/settings.ts (Frontend/src/api/settings.ts): SettingsApiError + getBrightnessCutoff/putBrightnessCutoff already exist.
Both SettingsPage.tsx and SettingsPanel.tsx already mount <BrightnessCutoffControl /> (RESEARCH.md Pitfall 6: both surfaces must stay in sync).
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Color math — vibrancy-weighted sampling + saturation boost helper</name>
  <files>Backend/services/color_math.py, Backend/tests/test_color_math.py</files>
  <behavior>
    Backward-compat (the hard contract):
    - extract_region_color(frame, region) with no vibrancy arg == vibrancy 0.0 == the current cv2.mean fast path, bit-for-bit. All existing test_color_math.py tests pass UNCHANGED.
    - sub_sample_gradient(...) with vibrancy 0.0 keeps the exact current cv2.mean slab loop.
    Vibrancy (D-1):
    - Synthetic red frame with a white stripe: at vibrancy 0.0 the mean is the current desaturated pink; at vibrancy 1.0 the hue is near-pure red AND the Rec.709 luma equals the unweighted-mean luma. NOTE: use a NON-max red (e.g. RGB (200,0,0)) for the region so the "match unweighted luma" scale-up does not hit the 255 per-channel cap — a (255,0,0) region cannot brighten past 255 and the luma-equality assertion would then fail. Assert luma with pytest.approx tolerance.
    - Uniform saturated green frame (single color, no white): output is IDENTICAL at any vibrancy 0.0/0.5/1.0 and brightness is unchanged (all pixel weights equal -> weighted mean == unweighted mean).
    - Total-weight-zero fallback: an all-white (or all-gray) region at vibrancy 1.0 returns the plain unweighted mean (every S=0 -> every weight=0 -> guard falls back).
    Saturation boost (D-2):
    - boost_saturation_rgb(arr, 0.0) is identity: returns the input unchanged.
    - boost > 0 raises HSV S and leaves HSV V (== max channel / 255) unchanged; assert per-pixel max(R,G,B) is identical before/after. Pure-gray pixels (chroma 0) stay gray.
  </behavior>
  <action>
    In Backend/services/color_math.py:

    1. Add a private weight builder:
       `def _saturation_weights(roi_bgr: np.ndarray, alpha: float) -> np.ndarray:` computing per-pixel
       S = (max - min)/max on the float BGR ROI (S=0 where max==0), then w = (1-alpha) + alpha*(S*S).
       Return an (H,W) float32 array. This is computed ONCE per region ROI (perf constraint — see below).

    2. Add `def _weighted_region_mean(roi_bgr, mask, weights) -> tuple[int,int,int]:` implementing D-1
       brightness preservation:
       - select masked pixels (mask>0); if none, return (0,0,0).
       - unweighted_bgr = masked_pixels.mean(axis=0); weighted_bgr = sum(w*px)/sum(w).
       - if sum(w) < ~1e-6: use unweighted_bgr (total-weight-zero guard).
       - luma() uses Rec.709 on RGB order (BGR px -> R=idx2,G=idx1,B=idx0): 0.2126R+0.7152G+0.0722B.
       - scale = luma(unweighted)/luma(weighted) when luma(weighted) > 1e-6; CAP scale at 255/max(weighted_bgr)
         so NO channel overflows (this preserves hue by scaling all channels uniformly). Multiply weighted_bgr by scale, np.clip 0..255.
       - return RGB ints (idx2, idx1, idx0).

    3. Add `vibrancy: float = 0.0` param to `extract_region_color`. When vibrancy == 0.0 keep the EXACT
       current cv2.mean path (do NOT restructure it). When > 0.0: build weights on the cropped roi_frame via
       _saturation_weights and return _weighted_region_mean(roi_frame, region.roi_mask, weights).

    4. Add `vibrancy: float = 0.0` param to `sub_sample_gradient`. n<=1 branch forwards vibrancy to
       extract_region_color. n>1 branch: when vibrancy == 0.0 keep the current cv2.mean slab loop untouched.
       When > 0.0 compute the weight array ONCE over roi_frame (perf constraint: reuse across slabs), then per
       slab call _weighted_region_mean(slab_frame, slab_mask, weights_slab) where weights_slab is the same
       column/row slice used for slab_frame/slab_mask. Reverse handling (RTL/BTT) stays identical.

    5. Add `def boost_saturation_rgb(rgb: np.ndarray, boost: float) -> np.ndarray:` (D-2). If boost <= 0.0
       return `rgb` unchanged (identity — same object, zero cost). Else operate on float32: mx=max(axis=-1,keepdims),
       mn=min(...), chroma=mx-mn, S=where(mx>0, chroma/mx, 0), S'=S+boost*(1-S), ratio=where(S>1e-6, S'/S, 1.0),
       out = mx - (mx - arr)*ratio, clip 0..255, return uint8. Works for (N,3) and (3,) shapes. V (=mx) is
       untouched because the max channel has (mx-c)=0.

    Then add the tests in Backend/tests/test_color_math.py per <behavior> (new TestVibrancy + TestSaturationBoost
    classes; reuse the existing build_polygon_mask + numpy frame construction idioms already in the file).
    Do NOT touch routers/capture.py — preview stays raw mean (D-5); it never passes vibrancy so it is unaffected.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_color_math.py -x -q</automated>
  </verify>
  <done>New vibrancy + boost tests pass; ALL pre-existing test_color_math.py tests still pass (backward-compat contract); vibrancy=0.0 and boost=0.0 paths are byte-identical to current.</done>
</task>

<task type="auto">
  <name>Task 2: Settings KV wiring + coordinator live read (replicate brightness_cutoff)</name>
  <files>Backend/routers/settings.py, Backend/main.py, Backend/database.py, Backend/services/streaming_coordinator.py, Backend/tests/test_settings_router.py</files>
  <action>
    Replicate the `brightness_cutoff_threshold` pattern exactly (D-3) for two keys: `color_vibrancy`, `saturation_boost`.

    1. Backend/database.py (~L103-106): add two `INSERT OR IGNORE INTO settings (key,value) VALUES (?, ?)`
       seed rows for ("color_vibrancy","0.0") and ("saturation_boost","0.0"), immediately after the existing
       brightness_cutoff_threshold seed.

    2. Backend/routers/settings.py: add GET + PUT handlers for each new key mirroring get/put_brightness_cutoff
       verbatim (manual body parse; reject non-dict/missing "value"; reject bool; require int/float; require
       math.isfinite -> 422; require 0.0<=v<=1.0 -> 422; upsert; commit; mirror to request.app.state.color_vibrancy
       / .saturation_boost). Reuse a shared response model (a single `class SettingValueResponse(BaseModel): value: float`
       is fine) — endpoints: GET/PUT `/api/settings/color_vibrancy` and `/api/settings/saturation_boost`.

    3. Backend/main.py (~L37-52): hydrate both into app.state at startup, mirroring the brightness block —
       set default 0.0, SELECT the row, float() on hit, defensive try/except. Add app.state.color_vibrancy and
       app.state.saturation_boost.

    4. Backend/services/streaming_coordinator.py `_frame_loop`: read both from self._app_state ONCE per frame
       via a defensive getattr helper (mirror the sinks' getattr(app_state, key, 0.0) + try/except pattern;
       self._app_state may be None in tests -> defaults 0.0). Then:
       - pass `vibrancy=vibrancy` into BOTH sub_sample_gradient calls (the hue n=1 comprehension AND the
         _wled_pipeline._compute n=N_region comprehension).
       - apply `boost_saturation_rgb(gradient, boost)` to each gradient array AFTER sub_sample_gradient and
         BEFORE handing to the sink (D-2: applied to final per-region/per-LED RGB). Do this for both the
         hue_gradients dict and the wled_gradients dict. When boost==0.0 the helper is a zero-cost identity so
         the default path is unchanged. Import boost_saturation_rgb from services.color_math.

    5. Backend/tests/test_settings_router.py: add tests mirroring the brightness ones for BOTH new keys —
       GET default 0.0 on fresh DB, PUT round-trip, PUT boundary 0.0 and 1.0, reject >1.0 (422), reject <0.0 (422),
       reject NaN (422 via content=b'{"value": NaN}'), PUT updates app.state, PUT overwrites previous.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_settings_router.py tests/test_streaming_coordinator.py -q</automated>
  </verify>
  <done>GET returns 0.0 default and PUT persists + mirrors app.state for both keys; NaN/Inf/out-of-range return 422; coordinator threads vibrancy into sub_sample_gradient and applies boost before render; all coordinator tests still pass.</done>
</task>

<task type="auto">
  <name>Task 3: Frontend — two Settings sliders (reusable component)</name>
  <files>Frontend/src/api/settings.ts, Frontend/src/components/Settings/SettingSlider.tsx, Frontend/src/components/Settings/SettingSlider.test.tsx, Frontend/src/components/Settings/SettingsPage.tsx, Frontend/src/components/Settings/SettingsPanel.tsx</files>
  <action>
    D-4: two sliders next to the existing brightness cutoff slider, same fetch-on-mount / PUT-on-change pattern.
    Do NOT modify BrightnessCutoffControl.tsx or its test (keep them intact for backward-compat).

    1. Frontend/src/api/settings.ts: add generic `getSetting(key: string): Promise<{value:number}>` (GET
       `/api/settings/${key}`) and `putSetting(key: string, value: number): Promise<{value:number}>`
       (PUT same URL with JSON body {value}), reusing SettingsApiError. Leave existing getBrightnessCutoff/
       putBrightnessCutoff exports untouched.

    2. Create Frontend/src/components/Settings/SettingSlider.tsx: a generalized version of
       BrightnessCutoffControl parameterized by props `{ settingKey: string; label: string; description: string }`.
       Same structure: useState value/loaded/error, useEffect mount GET via getSetting(settingKey) with the
       cancelled-flag guard, persist via putSetting(settingKey, next) on change, MIN=0 MAX=1 STEP=0.01, native
       <input type="range">. Use STABLE data-testids derived from settingKey so tests can target each instance
       independently, e.g. `data-testid={`setting-slider-${settingKey}`}`, `setting-value-${settingKey}`,
       `setting-error-${settingKey}`.

    3. Mount two instances in BOTH SettingsPage.tsx and SettingsPanel.tsx, immediately adjacent to the existing
       <BrightnessCutoffControl /> (RESEARCH.md Pitfall 6: both surfaces stay in sync):
       - <SettingSlider settingKey="color_vibrancy" label="Color vibrancy (white suppression)"
         description="Suppresses bright white pixels (subtitles, HUD) so region colors stay vivid." />
       - <SettingSlider settingKey="saturation_boost" label="Saturation boost"
         description="Increases output color saturation. Brightness is unchanged." />

    4. Create Frontend/src/components/Settings/SettingSlider.test.tsx mirroring BrightnessCutoffControl.test.tsx
       (vi.stubGlobal fetch per test; unstubAllGlobals in afterEach): renders default 0.00 from GET on mount,
       displays loaded value, slider change triggers PUT to `/api/settings/${settingKey}` with new value, shows
       error caption when PUT fails. Parameterize with settingKey="color_vibrancy" (one representative instance).
  </action>
  <verify>
    <automated>cd Frontend && npx vitest run src/components/Settings/SettingSlider.test.tsx src/components/Settings/BrightnessCutoffControl.test.tsx</automated>
  </verify>
  <done>Two new sliders render on SettingsPage and SettingsPanel next to brightness cutoff; each fetches on mount and PUTs to its own /api/settings/{key} endpoint on change; new tests pass and the existing brightness-cutoff test still passes.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser → PUT /api/settings/* | Untrusted numeric slider value crosses into the settings KV store and live app.state |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-iss-01 | Tampering/DoS | PUT /api/settings/{color_vibrancy,saturation_boost} | mitigate | Replicate the brightness_cutoff manual-body-parse validation: reject non-numeric, bool, NaN/Inf (422), and clamp to [0.0,1.0] (422) BEFORE the DB upsert and app.state mirror. Prevents a poisoned value reaching the 60 Hz frame loop. |
| T-iss-02 | Spoofing/Auth | All /api/settings endpoints | accept | Web UI is unauthenticated by design (CLAUDE.md — local-network tool only); no PII, no secrets. Consistent with the existing brightness_cutoff endpoint. |
</threat_model>

<verification>
- Backend: `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` — all tests pass (167+ baseline plus new vibrancy/boost/settings tests).
- Frontend: `cd Frontend && npx vitest run` — all tests pass (30+ baseline plus SettingSlider tests).
- Backward-compat: with both settings at 0.0, color output is byte-identical to pre-change (vibrancy 0.0 keeps cv2.mean fast path; boost 0.0 is identity).
- Live update: PUT to either endpoint mutates app.state and takes effect on the next frame without a stream restart.
</verification>

<success_criteria>
- `color_vibrancy` and `saturation_boost` settings exist end-to-end: DB seed → GET/PUT router → app.state hydrate + live mirror → coordinator per-frame read → color_math.
- vibrancy>0 suppresses white pollution while preserving region luma; boost>0 raises saturation with V untouched.
- Two sliders visible on SettingsPage and SettingsPanel next to the brightness cutoff slider.
- Defaults (0.0/0.0) preserve current behavior; all existing backend + frontend tests pass unchanged.
- routers/capture.py (preview) untouched.
</success_criteria>

<output>
After completion, create `.planning/quick/260704-iss-color-vibrancy-sliders/260704-iss-SUMMARY.md`
</output>
