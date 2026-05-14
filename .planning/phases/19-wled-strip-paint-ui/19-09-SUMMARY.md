---
phase: 19-wled-strip-paint-ui
plan: 09
subsystem: api
tags: [phase-19, wled, streaming-coordinator, orientation, color-math, wave-4]

requires:
  - phase: 19-04
    provides: sub_sample_gradient orientation parameter (Orientation literal + kwarg)
  - phase: 19-06
    provides: wled_channels service and wled_light_assignments rows in DB
  - phase: 19-08
    provides: PATCH /api/wled/regions/{rid}/orientation endpoint that writes orientation to wled_light_assignments

provides:
  - Per-region orientation resolution at stream start via MAX(wla.orientation) SQL aggregate
  - orientation kwarg propagated from region_plan into sub_sample_gradient at the frame loop call site
  - D-22 single-gradient-per-region contract preserved; HueStreamer and WledStreamer interfaces unchanged

affects: [streaming-coordinator, color-math, phase-19-e2e]

tech-stack:
  added: []
  patterns:
    - "Region plan tuple extended to 3-element (RegionMask, n_region, orientation_str) — orientation is region-scoped per D-16/D-22"
    - "COALESCE(MAX(wla.orientation), 'auto') pattern for per-region orientation resolution with Hue-only fallback"

key-files:
  created: []
  modified:
    - Backend/services/streaming_coordinator.py
    - Backend/tests/test_phase17_e2e.py
    - Backend/tests/test_streaming_coordinator.py

key-decisions:
  - "Used MAX(wla.orientation) in SQL aggregate; all wled_light_assignments rows for a given (region_id, config_id) carry the same orientation (enforced by PATCH endpoint from Plan 19-08), making MAX deterministic"
  - "COALESCE to 'auto' for Hue-only regions — preserves bit-for-bit Phase 17 behavior since sub_sample_gradient defaults to 'auto'"
  - "No change to HueStreamer, WledStreamer, or _load_wled_device_rows — orientation resolution is complete at the sub_sample_gradient call site; both sinks receive the already-resolved ndarray"

requirements-completed: [WMAP-01]

duration: 18min
completed: 2026-05-14
---

# Phase 19 Plan 09: Orientation Wire-up in StreamingCoordinator Summary

**Per-region orientation column flows end-to-end: DB wled_light_assignments -> _build_region_plan SQL aggregate -> 3-tuple region_plan -> sub_sample_gradient(orientation=) kwarg in frame loop**

## Performance

- **Duration:** 18 min
- **Started:** 2026-05-14T00:00:00Z
- **Completed:** 2026-05-14T00:18:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `_build_region_plan` SQL extended with `COALESCE(MAX(wla.orientation), 'auto') AS orientation`; plan tuple shape upgraded from `(RegionMask, int)` to `(RegionMask, int, str)`
- `_frame_loop` dict-comprehension updated to unpack the 3-tuple and pass `orientation=orientation` kwarg into `sub_sample_gradient`
- Phase 17 e2e regression (invariants 5, 14, 15) passes green; full backend suite 302 passed / 23 skipped

## SQL diff (`_build_region_plan`)

Before:
```sql
SELECT DISTINCT r.id AS region_id, r.polygon,
       COALESCE(MAX(wc.end_led - wc.start_led + 1), 1) AS n_region
FROM regions r ...
```

After:
```sql
SELECT DISTINCT r.id AS region_id, r.polygon,
       COALESCE(MAX(wc.end_led - wc.start_led + 1), 1) AS n_region,
       COALESCE(MAX(wla.orientation), 'auto') AS orientation
FROM regions r ...
```

## Call-site diff (`_frame_loop`)

Before:
```python
region_gradients: dict[str, np.ndarray] = {
    rid: sub_sample_gradient(frame, mask, n_region)
    for rid, (mask, n_region) in region_plan.items()
}
```

After:
```python
region_gradients: dict[str, np.ndarray] = {
    rid: sub_sample_gradient(frame, mask, n_region, orientation=orientation)
    for rid, (mask, n_region, orientation) in region_plan.items()
}
```

## HueStreamer / WledStreamer / _load_wled_device_rows diffs

All three are byte-identical to their pre-plan state. `git diff` on `streaming_service.py` and `wled_streamer.py` produces no output. `_load_wled_device_rows` SELECT still reads only `wc.id AS channel_id, wc.start_led, wc.end_led, wla.region_id` — no `wla.orientation` addition there.

## Task Commits

1. **Tasks 1 + 2: extend _build_region_plan + wire orientation kwarg in _frame_loop** - `352ff81` (feat)

## Files Created/Modified

- `Backend/services/streaming_coordinator.py` - SQL extended with orientation column; plan tuple 2→3 element; frame loop call site updated with orientation= kwarg
- `Backend/tests/test_phase17_e2e.py` - Added `orientation TEXT NOT NULL DEFAULT 'auto'` to inline wled_light_assignments DDL
- `Backend/tests/test_streaming_coordinator.py` - Updated 3 test fixtures: added "orientation" key to MagicMock row dicts; updated 2-tuple plan stubs to 3-tuples; updated unpack assertion to include orientation

## Decisions Made

- MAX(wla.orientation) is deterministic because the PATCH endpoint (Plan 19-08) writes the same orientation to every matching (region_id, config_id) row — per-region narrowing contract from CONTEXT.md D-16.
- COALESCE to 'auto' rather than a NULL check in Python — cleaner SQL, consistent with the existing COALESCE pattern already used for n_region.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test inline schema to include orientation column**
- **Found during:** Task 1 verification (Phase 17 e2e regression run)
- **Issue:** `test_phase17_e2e.py::_make_db_with_phase17_schema` created `wled_light_assignments` without the `orientation` column added in Plan 19-03; the new SQL query raised `no such column: wla.orientation`, causing the region plan to return empty and the streaming loop to send only the WledStreamer stop/blackout packet
- **Fix:** Added `orientation TEXT NOT NULL DEFAULT 'auto'` to the inline CREATE TABLE DDL in `_make_db_with_phase17_schema`
- **Files modified:** `Backend/tests/test_phase17_e2e.py`
- **Verification:** Phase 17 e2e — 2 passed in 3.19s
- **Committed in:** `352ff81`

**2. [Rule 1 - Bug] Updated test_streaming_coordinator.py mocks to 3-tuple shape**
- **Found during:** Task 2 verification (full backend suite run)
- **Issue:** Three tests in `test_streaming_coordinator.py` used MagicMock row dicts without `"orientation"` key and 2-tuple plan stubs `(mask, n_region)`; the new unpacking raised `KeyError: 'orientation'` and `not enough values to unpack`
- **Fix:** Added `"orientation": "auto"` to two MagicMock row side-effects; updated `_fake_plan` to return `(fake_region, 10, "auto")`; updated `mask, n_region = plan["rA"]` unpack to `mask, n_region, orientation = plan["rA"]` with `assert orientation == "auto"`
- **Files modified:** `Backend/tests/test_streaming_coordinator.py`
- **Verification:** 302 passed, 23 skipped
- **Committed in:** `352ff81`

---

**Total deviations:** 2 auto-fixed (both Rule 1 — test mocks not updated to match new 3-tuple plan shape and orientation column)
**Impact on plan:** Both fixes required for correctness. No scope creep — only affected test infrastructure for the files this plan modifies.

## Issues Encountered

None beyond the deviations documented above.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Orientation is now live end-to-end: DB column -> SQL aggregate -> region_plan -> sub_sample_gradient kwarg
- Phase 17 behavior preserved bit-for-bit for Hue-only regions (orientation='auto' produces identical output)
- Wave 5+ plans (frontend strip painter, paint reducer wiring) can proceed — the runtime now honors orientation data written by the PATCH endpoint

---
*Phase: 19-wled-strip-paint-ui*
*Completed: 2026-05-14*

## Self-Check: PASSED

- FOUND: `.planning/phases/19-wled-strip-paint-ui/19-09-SUMMARY.md`
- FOUND: commit `352ff81` (feat: orientation wire-up)
- FOUND: commit `0e21172` (docs: SUMMARY)
