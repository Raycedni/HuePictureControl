---
phase: 19
slug: wled-strip-paint-ui
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-14
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Generated from RESEARCH.md `## Validation Architecture`. Orientation scope **narrowed to per-region** during plan-phase (see CONTEXT.md D-16/D-19/D-22); test rows below reflect the narrowed scope.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (Backend, `asyncio_mode=auto` via `Backend/pytest.ini`) + Vitest 4.1.x (Frontend) + Playwright 1.59.x (E2E pointer gestures — config to be installed in Wave 0) |
| **Config file** | `Backend/pytest.ini`, `Frontend/vitest.config.ts` (auto via `package.json`), `Frontend/playwright.config.ts` (NEW — Wave 0) |
| **Quick run command (backend)** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_channels.py tests/test_color_math.py tests/test_wled_router.py -x` |
| **Quick run command (frontend)** | `cd Frontend && npx vitest run src/components/Settings/wled-paint-reducer.test.ts src/utils/wled-palette.test.ts src/components/EditorCanvas.test.tsx` |
| **Full suite command (backend)** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |
| **Full suite command (frontend)** | `cd Frontend && npx vitest run` |
| **E2E command** | `cd Frontend && npx playwright test` |
| **Estimated runtime (quick combined)** | ~15 seconds |
| **Estimated runtime (full combined)** | ~90 seconds |

---

## Sampling Rate

- **After every task commit:** Run quick run command (backend or frontend depending on what changed).
- **After every plan wave:** Run full suite (both backend and frontend).
- **Before `/gsd-verify-work`:** Full suite must be green AND Playwright paint-gesture spec green AND manual UAT (paint a channel in browser, drag onto region, observe LED color update in live stream).
- **Max feedback latency (quick path):** 15 seconds.

---

## Per-Task Verification Map

| Req / Decision | Behavior | Test Type | Automated Command | File Status |
|----------------|----------|-----------|-------------------|-------------|
| WMAP-01 | Paint creates a channel — `POST /api/wled/devices/{id}/channels` with `{start_led: 10, end_led: 50}` inserts that range | integration | `pytest Backend/tests/test_wled_router.py::test_create_channel_basic -x` | ❌ Wave 0 |
| WMAP-01 | Paint over existing channel triggers overlap auto-split — cases A (no overlap, ignore), B (strict interior split → original keeps left, right half gets new id+name), C (exact match, no-op or swallow), D (crosses left only, left-trim), E (crosses right only, right-trim), F (multiple swallowed, deleted with cascade), G (boundary touch, no split) | unit | `pytest Backend/tests/test_wled_channels.py -x -k "overlap_split"` | ❌ Wave 0 |
| WMAP-01 | Channel-N invariant: `next_channel_n` increments monotonically per device, never reuses freed N's after delete | unit | `pytest Backend/tests/test_wled_channels.py::test_next_channel_name_monotonic -x` | ❌ Wave 0 |
| WMAP-01 | Paint gesture state machine (mousedown→move→up) — pure reducer | unit | `npx vitest run Frontend/src/components/Settings/wled-paint-reducer.test.ts` | ❌ Wave 0 |
| WMAP-01 | Paint pointer integration on actual Konva canvas | e2e | `npx playwright test Frontend/e2e/wled-paint.spec.ts -g "paint creates channel"` | ❌ Wave 0 |
| WMAP-02 | Painted channel appears in LightPanel WLED section (rendered + draggable) | unit (React) | `npx vitest run Frontend/src/components/LightPanel.test.tsx -t "WLED section"` | ❌ extend existing |
| WMAP-02 | Channel drag-source sets correct dataTransfer payload — `wledChannelId`, `wledDeviceId`, `wledChannelName`, `entertainment_config_id` (additive to existing Hue payload, no key collision) | unit (React) | `npx vitest run Frontend/src/components/LightPanel.test.tsx -t "WLED drag payload"` | ❌ extend existing |
| WMAP-03 | `channelColor(i)` produces correct golden-angle HSL hue per sketch-002 spec | unit | `npx vitest run Frontend/src/utils/wled-palette.test.ts` | ❌ Wave 0 |
| WMAP-03 | Adjacent zones in strip canvas have visually distinct fills (asserted via index-difference test) | unit | `npx vitest run Frontend/src/utils/wled-palette.test.ts -t "adjacent indices differ"` | ❌ Wave 0 |
| WMAP-04 | Boundary drag atomically updates two adjacent channels — `PUT /api/wled/devices/{id}/channels/boundary` writes both rows in one transaction | integration | `pytest Backend/tests/test_wled_router.py::test_boundary_resize_atomic -x` | ❌ Wave 0 |
| WMAP-04 | Boundary drag clamps to 1-LED minimum per side | unit | `npx vitest run Frontend/src/components/Settings/wled-paint-reducer.test.ts -t "boundary clamp"` | ❌ Wave 0 |
| WMAP-05 | `EditorCanvas.handleDrop` WLED branch calls `upsertAssignment` and refreshes regions | unit (React) | `npx vitest run Frontend/src/components/EditorCanvas.test.tsx -t "WLED drop"` | ❌ Wave 0 |
| WMAP-05 | Hue drop path is untouched after WLED branch added (regression guard) | unit (React) | `npx vitest run Frontend/src/components/EditorCanvas.test.tsx -t "Hue drop preserved"` | ❌ Wave 0 |
| Success #1 | Strip renders one canvas per registered WLED device, fit-to-width | e2e | `npx playwright test Frontend/e2e/wled-paint.spec.ts -g "fit-to-width per device"` | ❌ Wave 0 |
| Success #2 | Channels appear in LightPanel with distinct render-fill chips matching strip zone colors | unit (React) | `npx vitest run Frontend/src/components/LightPanel.test.tsx -t "WLED chip matches palette"` | ❌ extend existing |
| Success #3 | Boundary handle is visible between adjacent zones and drag-resizes them | e2e | `npx playwright test Frontend/e2e/wled-paint.spec.ts -g "boundary handle resize"` | ❌ Wave 0 |
| Success #4 | Painted channels + assignments + orientation persist across backend restart | integration | `pytest Backend/tests/test_phase19_e2e.py::test_persistence -x` | ❌ Wave 0 |
| Success #5 | Channel delete cascades to `wled_light_assignments` rows | integration | `pytest Backend/tests/test_wled_router.py::test_delete_channel_cascades -x` | ❌ Wave 0 |
| D-16 (per-region) | `PATCH /api/wled/regions/{region_id}/orientation?config={config_id}` writes the same orientation to ALL rows matching `(region_id, config_id)` in one statement | integration | `pytest Backend/tests/test_wled_router.py::test_patch_region_orientation_writes_all_rows -x` | ❌ Wave 0 |
| D-16 (migration) | Idempotent `ALTER TABLE ... ADD COLUMN orientation` on second init does not fail | unit | `pytest Backend/tests/test_database.py::test_init_db_idempotent_phase19 -x` | ❌ Wave 0 |
| D-16 (migration) | Idempotent `ALTER TABLE wled_devices ADD COLUMN next_channel_n` on second init does not fail | unit | `pytest Backend/tests/test_database.py::test_init_db_idempotent_next_channel_n -x` | ❌ Wave 0 |
| D-17 (`auto`) | `sub_sample_gradient` with `orientation='auto'` matches Phase 17 longest-axis behavior bit-for-bit | unit | `pytest Backend/tests/test_color_math.py::test_sub_sample_orientation_auto_matches_phase17 -x` | ❌ Wave 0 |
| D-17 (`horizontal-LTR`) | Forces axis to bbox X regardless of aspect; direction left→right | unit | `pytest Backend/tests/test_color_math.py::test_sub_sample_orientation_horizontal_ltr -x` | ❌ Wave 0 |
| D-17 (`horizontal-RTL`) | Forces axis to bbox X; reverses output array | unit | `pytest Backend/tests/test_color_math.py::test_sub_sample_orientation_horizontal_rtl -x` | ❌ Wave 0 |
| D-17 (`vertical-TTB`) | Forces axis to bbox Y; direction top→bottom | unit | `pytest Backend/tests/test_color_math.py::test_sub_sample_orientation_vertical_ttb -x` | ❌ Wave 0 |
| D-17 (`vertical-BTT`) | Forces axis to bbox Y; reverses output | unit | `pytest Backend/tests/test_color_math.py::test_sub_sample_orientation_vertical_btt -x` | ❌ Wave 0 |
| D-22 | Coordinator gradient dict shape stays literal `{region_id: ndarray}` — narrowed to per-region orientation, no nested dict | integration | `pytest Backend/tests/test_phase17_e2e.py -x` (regression — existing E2E must remain green) | ✅ extend |
| D-19 | Region orientation popover renders one segmented control per region (NOT per assignment); read-only list of assigned channels below | unit (React) | `npx vitest run Frontend/src/components/Editor/RegionOrientationPopover.test.tsx -t "per-region single control"` | ❌ Wave 0 |
| D-19 | Segmented-control click fires `PATCH /api/wled/regions/{region_id}/orientation` (region-scoped endpoint, not per-assignment) | unit (React) | `npx vitest run Frontend/src/components/Editor/OrientationSegmentedControl.test.tsx -t "patches region endpoint"` | ❌ Wave 0 |
| Drag-payload contract | Both Hue and WLED dataTransfer keys can coexist; WLED branch takes precedence with explicit `return` after handler | unit (React) | `npx vitest run Frontend/src/components/EditorCanvas.test.tsx -t "WLED branch returns"` | ❌ Wave 0 |
| Konva resize | Strip canvas re-renders when paint slot container width changes (ResizeObserver) | unit (React) | `npx vitest run Frontend/src/components/Settings/WledStripPainter.test.tsx -t "resize observer"` | ❌ Wave 0 |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `Backend/tests/test_wled_channels.py` — overlap-split cases A-G + `_next_channel_name` invariant tests
- [ ] `Backend/tests/test_phase19_e2e.py` — end-to-end paint→assign→stream→restart persistence smoke
- [ ] Extend `Backend/tests/test_color_math.py` with the 5 orientation enum parametrized tests
- [ ] Extend `Backend/tests/test_database.py` with second-init idempotency for both new columns
- [ ] Extend `Backend/tests/test_wled_router.py` with channel-CRUD + region-orientation PATCH tests
- [ ] `Frontend/src/components/Settings/wled-paint-reducer.test.ts` — paint state machine + boundary clamp
- [ ] `Frontend/src/utils/wled-palette.test.ts` — golden-angle assertions, adjacent-difference, AA-readable
- [ ] `Frontend/src/components/EditorCanvas.test.tsx` — drop-handler branch tests (NEW FILE)
- [ ] Extend `Frontend/src/components/LightPanel.test.tsx` with WLED section + drag-payload + counter-chip tests
- [ ] `Frontend/src/components/Editor/RegionOrientationPopover.test.tsx` — per-region single control + close triggers (NEW FILE)
- [ ] `Frontend/src/components/Editor/OrientationSegmentedControl.test.tsx` — patches region-scoped endpoint (NEW FILE)
- [ ] `Frontend/src/components/Settings/WledStripPainter.test.tsx` — ResizeObserver + Konva selection (NEW FILE — pure-state coverage; pointer integration deferred to Playwright)
- [ ] `Frontend/playwright.config.ts` — install `@playwright/test`, point at `localhost:8091` (NEW FILE)
- [ ] `Frontend/e2e/wled-paint.spec.ts` — paint gesture + boundary resize + fit-to-width per device specs (NEW FILE)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live LED color matches painted channel when streaming | WMAP-02 + Success #2 | Requires physical Hue Bridge + WLED device on LAN; no loopback fixture replicates true UDP sink rendering | Start backend, register WLED device, paint a channel, drag onto a screen region, start streaming, point the screen region at a known color (e.g. red browser tab), observe physical strip lights matching |
| Visual alignment of LightPanel chip color vs strip zone color | WMAP-03 + Success #2 | Pixel-perfect match across two surfaces is easier to confirm by eye than to encode | Open browser, register device, paint 5 channels, open EditorCanvas, expand LightPanel WLED section, eyeball: each chip color = corresponding strip zone color |
| Popover auto-flip near canvas edges | UI-SPEC `RegionOrientationPopover` anchor algorithm | Geometry of canvas + viewport interplay is hard to encode in a Vitest unit test | Move a region to the bottom-right corner of the canvas, select it, confirm the popover flips above and shifts left |
| Strip fit-to-width on browser resize | D-06 + Success #1 | ResizeObserver behavior in production layout | Resize browser window, watch the strip canvas width re-fit; zones should preserve their proportional widths |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s for quick path
- [ ] `nyquist_compliant: true` set in frontmatter once Wave 0 complete

**Approval:** pending
