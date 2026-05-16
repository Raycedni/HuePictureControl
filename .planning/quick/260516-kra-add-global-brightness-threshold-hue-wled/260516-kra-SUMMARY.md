---
phase: quick-260516-kra
plan: 01
subsystem: streaming, settings, ui
tags: [hue, wled, brightness, settings, render-path, live-update]
requires:
  - existing app.state.db / FastAPI lifespan
  - HueStreamer + WledStreamer (Phase 17 / 19.1 refactored sinks)
  - StreamingCoordinator (Phase 17 Plan 05) — owns sink construction
provides:
  - "GET/PUT /api/settings/brightness_cutoff_threshold (float in [0.0, 1.0])"
  - "Global per-frame gate: when threshold > 0 and region luma < threshold, Hue channel sends bri=0 and WLED zeros the channel's LED slice"
  - "Default-disabled (threshold == 0.0) is byte-identical to pre-feature output"
  - "Live update — changes take effect on next frame, no stream restart required"
affects:
  - Hue DTLS frame body (b_u16 = 0 for below-threshold channels)
  - WLED DRGB/DNRGB packet body (zeroed RGB triplets for below-threshold channel ranges)
  - Both Settings UI surfaces (full-page SettingsPage + modal SettingsPanel)
tech-stack:
  added:
    - "Pydantic BaseModel + manual JSON parsing in PUT handler (NaN-safe 422 path)"
  patterns:
    - "Settings KV table follows the existing CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE idiom used by bridge_config and known_cameras (not the PRAGMA user_version guard reserved for Phase 19.1 schema upgrades)"
    - "Streamers receive app_state via post-construction attribute set on the sink instance — preserves existing MagicMock injection in test_streaming_coordinator.py without breaking the constructor signature"
    - "Per-frame defensive read: getattr(self, '_app_state', None) inside render() so direct-instantiated streamers in unit tests stay byte-identical to today"
key-files:
  created:
    - Backend/routers/settings.py
    - Backend/tests/test_settings_router.py
    - Frontend/src/api/settings.ts
    - Frontend/src/components/Settings/BrightnessCutoffControl.tsx
    - Frontend/src/components/Settings/BrightnessCutoffControl.test.tsx
  modified:
    - Backend/database.py
    - Backend/main.py
    - Backend/services/streaming_coordinator.py
    - Backend/services/streaming_service.py
    - Backend/services/wled_streamer.py
    - Backend/tests/test_streaming_service.py
    - Backend/tests/test_wled_streamer.py
    - Frontend/src/components/Settings/SettingsPage.tsx
    - Frontend/src/components/Settings/SettingsPanel.tsx
decisions:
  - "PUT handler parses JSON body manually instead of using a Pydantic body-model parameter — necessary because FastAPI's default RequestValidationError handler re-serializes the offending input value into the 422 body, and a NaN value crashes the json encoder with 'Out of range float values are not JSON compliant: nan' (yields 500). Manual parsing rejects NaN/Inf with a fixed string detail that always JSON-encodes."
  - "Threshold is read once per frame inside render() via getattr defensive access — keeps direct-instantiated streamers in unit tests byte-identical to today, and lets PUT update app.state without a stream restart."
  - "WLED gating zeros the per-channel slice_arr BEFORE the intersect-and-clip write to colors[clip_lo:clip_hi] — keeps the surrounding slice math unchanged and means the `populated = True` flag still fires (so the packet emits with the zeroed bytes, turning the LEDs OFF rather than holding the previous frame)."
  - "Luma compute uses the SOURCE gradient (gradient.mean(axis=0)), not the resampled slice_arr — decision is per-region, O(N_region) not O(led_count). Matches the Rec.709 weights HueStreamer already uses."
  - "Settings KV table uses TEXT for value so future non-numeric settings (e.g. enums, JSON-encoded blobs) can share the same row without a migration."
metrics:
  duration: "~55 min"
  completed: "2026-05-16"
  tasks: 4
  files_touched: 14
  new_tests: 17  # 9 settings router + 3 hue gating + 3 wled gating + 0 (Task 4 verification only) + 4 vitest = 19 actually; counted below
---

# Quick Task 260516-kra: Global Brightness-Cutoff Threshold — Summary

A single global float (0.0–1.0, default 0.0) that, when > 0, forces individual lights to "off" whenever their assigned region's mean Rec.709 luma falls below the threshold. Default 0.0 is byte-identical to today's output. Setting persists in SQLite, surfaces in the Settings UI as a slider, and is read by both `HueStreamer.render` and `WledStreamer._render_one_device` once per frame so changes take effect without restarting the stream.

## Gating Equation

Both sinks use the same per-channel Rec.709 luma gating:

```
mean_rgb = gradient.mean(axis=0)             # (3,) — uint8 channel means
luma = (R*0.2126 + G*0.7152 + B*0.0722) / 255.0

if threshold > 0.0 and luma < threshold:
    # Hue:  bri = 0.0   → DTLS b_u16 = 0
    # WLED: slice_arr = np.zeros((range_len, 3), uint8) → packet body bytes are zero
elif (Hue only) bri < 0.01:
    bri = 0.01           # pre-existing dark-scene floor
```

When `threshold == 0.0` (the default) the gating branch never fires and the existing dark-scene floor (Hue) / passthrough (WLED) runs unchanged.

## Byte-Identity Guarantee for Default-Disabled Path

Pinned by two snapshot tests so a future refactor cannot drift the threshold==0.0 path:

- **Hue:** `test_render_default_byte_identical_for_canonical_frame` — fixture: 3 channels, RGB `(120,150,200) / (0,0,0) / (200,50,50)`, threshold 0.0. Pinned to exactly 146 hex chars (16 header + 36 entertainment_id + 21 channel record bytes).
- **WLED:** `test_render_zero_threshold_no_change` — fixture: 10 LEDs, RGB `(25,25,25)` (luma ≈ 0.098, would be cutoff for any threshold > 0.1), threshold 0.0. Verifies each LED triplet in the DRGB body is still `0x19 0x19 0x19`, NOT zero.

## Live Update — No Stream Restart Required

The streamers read `self._app_state.brightness_cutoff_threshold` once per `render()` call via `getattr` (defensive, so unit-test instantiations without `_app_state` still work). The PUT handler updates:

1. The persistent SQLite row (`INSERT ... ON CONFLICT DO UPDATE`).
2. `request.app.state.brightness_cutoff_threshold` — the same attribute the streamers read.

Because `StreamingCoordinator.__init__` propagates `app.state` to both `HueStreamer._app_state` and `WledStreamer._app_state` at startup (and Python attribute lookup is by-reference), mutating `app.state.brightness_cutoff_threshold` is observed on the NEXT frame by both sinks — no stream stop/start cycle needed.

## Files Changed

### Backend (created)

- `Backend/routers/settings.py` — `/api/settings/brightness_cutoff_threshold` GET/PUT with manual body parsing (NaN-safe 422 responses).
- `Backend/tests/test_settings_router.py` — 9 specs: default-zero, round-trip, boundaries (0.0 / 1.0), reject-above-one, reject-below-zero, reject-NaN, app.state live-update, upsert-overwrites.

### Backend (modified)

- `Backend/database.py` — new `settings` KV table + idempotent seed of `('brightness_cutoff_threshold', '0.0')` (CREATE-IF-NOT-EXISTS + INSERT-OR-IGNORE pattern, NOT under the Phase 19.1 PRAGMA user_version guard).
- `Backend/main.py` — hydrates `app.state.brightness_cutoff_threshold` from DB on startup; registers settings router; passes `app_state` kwarg to `StreamingCoordinator`.
- `Backend/services/streaming_coordinator.py` — new optional `app_state` kwarg; sets `self._hue._app_state = app_state` and `self._wled._app_state = app_state` after construction so MagicMock-injected streamers in tests still work (defensive try/except).
- `Backend/services/streaming_service.py` — per-frame threshold read at top of `HueStreamer.render`; gates `bri = 0.0` for below-threshold channels.
- `Backend/services/wled_streamer.py` — per-frame threshold read at top of `_render_one_device`; zeros per-channel `slice_arr` for below-threshold channels (uses source-gradient luma, not resampled slice).
- `Backend/tests/test_streaming_service.py` — 3 new Hue tests: zero-threshold-keeps-floor, above-threshold-zeros-bri-in-packet, default-byte-identical-snapshot.
- `Backend/tests/test_wled_streamer.py` — 3 new WLED tests: zero-threshold-no-change, above-threshold-zeros-led-slice, mixed-channel-only-dark-zeroed.

### Frontend (created)

- `Frontend/src/api/settings.ts` — typed client (`getBrightnessCutoff`, `putBrightnessCutoff`, `SettingsApiError`).
- `Frontend/src/components/Settings/BrightnessCutoffControl.tsx` — native `<input type="range">` + numeric readout + inline error caption; GET on mount, PUT on every change.
- `Frontend/src/components/Settings/BrightnessCutoffControl.test.tsx` — 4 vitest specs: render default 0.00, display loaded value, PUT body shape, error caption on 500.

### Frontend (modified)

- `Frontend/src/components/Settings/SettingsPage.tsx` — `<BrightnessCutoffControl />` mounted above the existing strip/devices container.
- `Frontend/src/components/Settings/SettingsPanel.tsx` — same component mounted at the top of the modal body so the full-page and modal surfaces show the same control.

## Commits

| Task | Hash    | Subject |
| ---- | ------- | ------- |
| 1    | f9eeb84 | feat(quick-260516-kra): add settings KV table + brightness cutoff router |
| 2    | c95d26e | feat(quick-260516-kra): gate Hue + WLED render paths on brightness cutoff |
| 3    | d550877 | feat(quick-260516-kra): brightness cutoff slider in Settings UI |
| 4    | —       | Verification-only (no source changes) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] PUT handler returned 500 instead of 422 for NaN body**
- **Found during:** Task 1 (test_put_rejects_nan).
- **Issue:** With a Pydantic `Field(..., ge=0.0, le=1.0)` body model and `field_validator` rejecting non-finite values, FastAPI's default `RequestValidationError` handler re-serializes the offending input into the 422 response body. The offending input is `NaN`, and `json.JSONEncoder` raises `ValueError: Out of range float values are not JSON compliant: nan`. Net effect: client receives 500, not 422.
- **Fix:** Switched the PUT handler to parse the raw body manually via `await request.body()` + `json.loads()`. The validation errors raise `HTTPException(422, detail="...")` with fixed-string details that always JSON-encode. Plan's `BrightnessCutoffPayload` model is therefore removed — the plan's spec is satisfied at the contract level (422 on NaN) while avoiding the FastAPI/Pydantic-v2 serialization corner case.
- **Files modified:** `Backend/routers/settings.py`
- **Commit:** f9eeb84

No other deviations — Tasks 2, 3, 4 executed exactly as planned.

## Verification Status

- **Task 1:** `test_settings_router.py` (9 specs) + `test_database.py` (36 specs total) → all pass.
- **Task 2:** `test_streaming_service.py` (28 specs incl. 3 new) + `test_wled_streamer.py` (18 specs incl. 3 new) → all pass.
- **Task 3:** `BrightnessCutoffControl.test.tsx` (4 specs) + `WledDevicesPanel.test.tsx` (7 specs) → all pass.
- **Task 4 (full preflight):**
  - Backend: 340 pass / 21 skipped / 0 fail (excluding `test_cameras_router.py` — 12 pre-existing failures documented in `.planning/phases/19.1-wled-segment-sync/deferred-items.md` under "Plan 01 (2026-05-14)", verified to be identical to the documented set).
  - Frontend: 116 pass / 20 todo / 0 fail.

## Pre-Existing Failures Confirmed Out of Scope

`Backend/tests/test_cameras_router.py` — 12 failures match the documented pre-existing set verbatim (`test_stable_identity_mode`, `test_known_cameras_updated_on_scan`, `test_reconnect_found`, etc.). These return 404 where 200 expected, suggesting a cameras router URL prefix mismatch. Pre-dates quick-task 260516-iqp and quick-task 260516-kra. Not caused by any change in this task — git-log diffs against `test_cameras_router.py` show no modifications in either quick task.

## Self-Check: PASSED

- **Files created:** verified all 5 new files exist at expected paths.
- **Files modified:** verified all 9 modifications via `git log -p HEAD~3..HEAD`.
- **Commits:** verified all 3 commits (`f9eeb84`, `c95d26e`, `d550877`) exist in `git log --oneline`.
- **Test counts:** backend +15 new pass (9 settings router + 3 Hue + 3 WLED), frontend +4 new pass.
- **Byte-identity:** Hue snapshot test pins exact 146-hex output for threshold==0.0; WLED test pins (25,25,25) triplets for low-luma gradient at threshold==0.0.
