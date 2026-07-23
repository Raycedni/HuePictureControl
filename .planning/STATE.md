---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Wireless Input
status: milestone_complete
stopped_at: Completed 19.1-09-PLAN.md
last_updated: "2026-05-16T11:29:39.763Z"
last_activity: 2026-05-16
progress:
  total_phases: 11
  completed_phases: 10
  total_plans: 52
  completed_plans: 51
  percent: 91
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-14)

**Core value:** Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.
**Current focus:** Phase 19.1 — wled-segment-sync

## Current Position

Phase: 19.1
Plan: Not started
Status: Milestone complete
Last activity: 2026-07-23 - Completed quick task 260723-udg: Rework HDR mapping to hue-preserving tone map + gamut compression

## Performance Metrics

**Velocity:**

- Total plans completed: 22 (Phase 16 full)
- Average duration: ~30 min / plan
- Total execution time: ~1.5 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 16 | 3 | ~1.5h | ~30 min |
| 17 | 9 | - | - |
| 19.1 | 10 | - | - |

**Recent Trend:**

- Last 5 plans: 16-01 (backend DB + router), 16-02 (broadcaster + streaming service), 16-03 (frontend store + LightPanel)
- Trend: steady; Phase 16 executed cleanly across both backend and frontend

*Updated after each plan completion*
| Phase 19.1 P01 | 25min | 2 tasks | 5 files |
| Phase 19.1 P02 | 24min | 2 tasks | 4 files |
| Phase 19.1 P03 | 12min | 1 tasks | 1 files |
| Phase 19.1 P04 | 20min | 2 tasks | 3 files |
| Phase 19.1 P05 | 31min | 2 tasks | 4 files |
| Phase Phase 19.1 PP06 | 6min | 3 tasks | 5 files |
| Phase 19.1 P07 | 8min | 3 tasks | 6 files |
| Phase Phase 19.1 PP08 | 7min | 3 tasks tasks | 5 files files |
| Phase 19.1 P09 | 12min | 2 tasks tasks | 6 files files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [16-03]: LightPanel uses a 3-tier zone selection cascade (streaming > camera-persisted > configs[0]) with guard-clause early returns inside a single useEffect
- [16-03]: Stale-persisted configs fall back silently AND overwrite the dangling row via putLastZone (Claude's Discretion per 16-CONTEXT.md)
- [16-03]: W2 closure — pre-selection is read-only; verified by explicit `not.toHaveBeenCalled()` negative assertion
- [16-03]: W3 closure — zone `<select>` carries data-testid="zone-select"; tests use findByTestId/getByTestId instead of index-based querySelectorAll
- [v1.3 roadmap]: WLED streaming uses stdlib socket (UDP) — no new library; DRGB for <=490 LEDs, DNRGB for >490 (auto-selected by WledService)
- [v1.3 roadmap]: WLED device registration uses existing httpx to fetch /json/info from device IP before persisting
- [v1.3 roadmap]: WLED channels use shared channel abstraction — painted ranges appear in light panel alongside Hue segments, same drag-drop assignment
- [v1.3 roadmap]: HA endpoints are unauthenticated thin adapters over the existing StreamingCoordinator — no new auth layer
- [v1.3 roadmap]: Phase 16 (bug fixes) runs first as warm-up — independent of WLED, unblocks clean state for WLED testing
- [19.1-01] Wave 0 stubs use double-gated skip (pytest.importorskip + hasattr) for fetch_wled_state because services.wled_client already exists but the new function does not
- [19.1-01] Pre-existing 12 test_cameras_router.py failures logged to deferred-items.md as out-of-scope (verified pre-existing via git-stash diff)
- [19.1-02] fetch_wled_state IGNORES seg.id and uses array index as canonical seg_index (D-11) per WLED docs + firmware 0.14 issue #3041
- [19.1-02] EXCLUSIVE WLED seg.stop is converted to INCLUSIVE stop_led at the parse boundary so downstream consumers stay on Phase 19's inclusive-both-ends gradient math (D-22)
- [19.1-02] Schema migration uses PRAGMA user_version one-shot guard (PHASE_19_1_USER_VERSION=1) — atomic, no extra table, bump LAST so partial failures re-fire on next boot
- [19.1-02] orientation column baked into new wled_light_assignments CREATE; Phase 19 next_channel_n ALTER preserved as harmless dormant column per D-10 Claude's Discretion
- [19.1-03] reconcile_segments cascades via NOT IN sub-SELECT against freshly-written cache inside one transaction — simpler than diff-by-set, robust to duplicate seg_index, and naturally handles N->0 because empty cache means every assignment for the device is in the NOT IN set
- [19.1-03] reconcile_segments has zero network I/O — caller (Plan 04 router) owns fetch_wled_state plus httpx/ValueError -> HTTP translation; keeps the unit tests httpx-free and the transaction window tight
- [19.1-04] Two-fetch atomic registration before any DB write: /json/info + /json/state in one try-block ensures /json/state failure leaves zero wled_devices rows (D-02); proven by test_register_device_rolls_back_on_state_failure
- [19.1-04] reconcile_segments runs AFTER device-row commit (not inside same transaction) — reconcile owns its own commit; on brand-new device the cache is empty so it is just an INSERT batch; reconcile-failure post-commit yields empty cache, which D-04 frontend handles as stale-badge offline
- [19.1-04] PATCH /regions/{id}/orientation keeps Phase 19 query-param 'config' shape (not body) for binary-compat with the existing frontend until Plan 06+ rewrites it; SQL filter (region_id, entertainment_config_id) unchanged across the D-13 rename
- [19.1-05] id = str(seg_index) emitted at coordinator boundary — preserves WledStreamer.start channel-dict contract with zero edits to wled_streamer.py
- [19.1-05] Static-source assertion test via inspect.getsource(module) pins the SQL structural invariant (no wled_channels, must JOIN wled_seg_cache) regardless of future formatting changes
- [19.1-05] SQL-routing test mocks updated from FROM wled_channels to FROM wled_seg_cache rather than deleted — prevents silent always-pass tests under the new code path
- [19.1-06] segmentName(seg) D-08 fallback helper landed as single-function module (Frontend/src/utils/wled-segment.ts) mirroring wled-palette.ts shape — WledSegment interface co-located so downstream Wave 4 components import one typed surface
- [19.1-06] api/wled.ts rewritten end-to-end: channel-CRUD client fns removed (D-10), refreshSegments + listSegments added (D-17/D-18), upsertWledAssignment + deleteWledAssignment bodies reshaped to D-13 composite key; WledApiError + WledOrientation + device CRUD preserved byte-for-byte
- [19.1-06] patchRegionOrientation signature preserved verbatim from Phase 19 (?config= query param + {orientation} body) rather than rewritten to the plan's reference body shape — keeps binary-compat with Plan 04's backend deviation
- [19.1-06] useRegionStore.ts required zero body changes — WledAssignment reshape inside api/wled.ts propagates through 'import type' transparently; all 8 store tests still pass without edits
- [19.1-07] WledStripPainter rewritten as a read-only segment visualizer; paint reducer + Stage pointer handlers + BoundaryHandle subcomponent + createWledChannel/resizeWledChannelBoundary calls all removed per D-06; ledToPixel inlined to drop the wled-paint-reducer dependency Plan 09 will delete
- [19.1-07] Per-device Refresh button + stale-badge added to the strip per D-03/D-04; refreshing/refreshError state lives in WledStripPainter (records keyed by device_id) so DeviceStrip stays a pure renderer
- [19.1-07] ZoneTestSentinel hidden-span pattern: Konva renders zones to a single canvas, hiding them from testing-library, so each Group mounts a zero-pixel <span data-testid> peer that becomes a discoverable DOM node in JSDOM-mocked tests where react-konva is stubbed to a fragment pass-through
- [19.1-07] WledChannelSidebar rewritten as a read-only metadata <dl> panel per D-07; all <input> fields, name/start/end draft state, saveField+blur callbacks, and Delete button removed; optional Clear-selection button kept (UI-only, doesn't mutate data)
- [19.1-07] SettingsPanel + SettingsPage rewired in the same diff per RESEARCH.md Pitfall 6; lifted state reshape (selectedChannelId, selectedDeviceId) -> selectedSeg:{device_id, seg_index}|null; refreshTrigger counter + onChange callback dropped (no mutation flows through these containers anymore)
- [19.1-08] LightPanel.tsx, EditorCanvas.tsx, RegionOrientationPopover.tsx rewired to D-13 composite (wled_device_id, seg_index) key; drag payload sets wledDeviceId + seg_index + wledSegName + entertainment_config_id; EditorCanvas discriminator changes from wledChannelId presence to wledDeviceId presence with Number.isFinite guard on seg_index
- [19.1-08] Popover deviceChannelIndexById useMemo deleted entirely per D-09 — seg_index IS the palette index, so channelColor(a.seg_index) is a direct render-time call with zero per-device sort-position resolver
- [19.1-08] JSDOM normalizes hsl(h,s%,l%) to rgb(r,g,b) when reading element.style.background — chip-color tests use pairwise inequality (two seg_index values produce different rgb strings) instead of literal hsl(...) string compare; same D-09 semantic guarantee, JSDOM-stable
- [19.1-09] All Phase 19 paint-era artifacts hard-deleted (5 files, 44,202 bytes); zero surviving importers in production code per repository-wide grep audit. DROP TABLE upgrade guards in database.py preserved (D-20).
- [19.1-09] Frontend/e2e/wled-paint.spec.ts replaced by wled-segments.spec.ts with 3 specs: refresh-stub smoke + fit-to-width + D-13 composite drag-payload (synthetic dispatchEvent harness, not Playwright dragAndDrop). V3' boundary-after-change stays manual UAT (Plan 10) per CONTEXT.md D-23.

### Pending Todos

None yet.

### Roadmap Evolution

- Phase 3.1 inserted after Phase 3: Auto-Mapping from Entertainment Config — auto-generate screen regions from channel positions before building manual canvas editor (user decision 2026-03-24)
- v1.3 Phases 16-19 added 2026-04-14: Zone persistence fixes, WLED backend+streaming, HA control endpoints, WLED strip paint UI
- v1.1 archived 2026-04-14: 5 phases, 10 plans, 7 requirements left unchecked (known gaps)
- Phase 16 closed 2026-04-20: 3 plans, BFIX-01 + BFIX-02 shipped
- Phase 19 closed 2026-05-14: 13 plans, 5/5 success criteria PASSED. Manual UAT V1–V4 deferred to 19.1.
- Phase 19.1 inserted after Phase 19: WLED Segment Sync (URGENT) — channels auto-queried from WLED `/json/state seg[]` instead of paint-managed, redesign decided 2026-05-14 during Phase 19 Wave 7 checkpoint

### Blockers/Concerns

(None — Phase 16 clean close; ready for Phase 17 kickoff)

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260516-iqp | Tier 1 real-time light sync performance pass: batched DTLS, vectorized WLED build, parallel sink render | 2026-05-16 | 48f6482 | [260516-iqp-tier-1-real-time-light-sync-performance-](./quick/260516-iqp-tier-1-real-time-light-sync-performance-/) |
| 260516-kra | Add global brightness threshold (Hue+WLED) — per-region luma cutoff, default 0.0 disabled | 2026-05-16 | d550877 | [260516-kra-add-global-brightness-threshold-hue-wled](./quick/260516-kra-add-global-brightness-threshold-hue-wled/) |
| 260704-iss | Color vibrancy + saturation boost sliders — saturation-weighted sampling fixes white pollution, brightness-preserving | 2026-07-04 | 5984d66 | [260704-iss-color-vibrancy-sliders](./quick/260704-iss-color-vibrancy-sliders/) |
| 260704-w88 | HDR input toggle — HDR10 (BT.2020+PQ) → sRGB conversion on sampled region colors before saturation boost and rgb_to_xy | 2026-07-04 | ea5ce0f | [260704-w88-add-hdr-input-toggle-convert-sampled-reg](./quick/260704-w88-add-hdr-input-toggle-convert-sampled-reg/) |
| 260704-wy5 | HDR pipeline v2 — limited-range expansion + PQ→linear LUT per-pixel BEFORE averaging (linear-light region means, MS2130 fix) | 2026-07-04 | 4fde109 | [260704-wy5-hdr-pipeline-v2-linear-light-averaging-l](./quick/260704-wy5-hdr-pipeline-v2-linear-light-averaging-l/) |
| 260714-nnk | Fix camera selection bug in LightPanel.tsx — re-keyed selection from non-unique device_path to stable_id after Elgato 4K S capture card swap exposed a device_path collision (stale + live records sharing /dev/video0) | 2026-07-14 | 22712b6 | [260714-nnk-fix-camera-selection-bug-in-lightpanel-t](./quick/260714-nnk-fix-camera-selection-bug-in-lightpanel-t/) |
| 260714-o9r | Fix V4L2 capture format-mismatch — Elgato 4K S negotiates MJPEG successfully but actually delivers raw YUYV payload (cv2.imdecode silently failed forever); added content-sniffed decode path with YUYV fallback + re-encode for /ws/preview | 2026-07-14 | 6bdf8ee | [260714-o9r-fix-v4l2-capture-elgato-4k-s-negotiates-](./quick/260714-o9r-fix-v4l2-capture-elgato-4k-s-negotiates-/) |
| 260714-ong | Fix v4l2_format struct offset bug — width/height/pixelformat read/written 4 bytes too early in _setup_device (missing 8-byte union alignment padding after `type`), which broke 260714-o9r's YUYV fallback in production; named offset constants added to prevent recurrence | 2026-07-14 | 2f1ec85 | [260714-ong-fix-v4l2-format-struct-offset-bug-in-cap](./quick/260714-ong-fix-v4l2-format-struct-offset-bug-in-cap/) |
| 260714-png | Allow saturation_boost to go negative (-1.0 to 1.0) — symmetric desaturation formula (s*(1+boost) below 0) so over-vibrant HDR content can be toned down; color_vibrancy/brightness_cutoff_threshold/hdr_input stay [0.0, 1.0] | 2026-07-14 | 82f3e42 | [260714-png-allow-saturation-boost-setting-to-go-neg](./quick/260714-png-allow-saturation-boost-setting-to-go-neg/) |
| 260714-pzk | Scope brightness_cutoff_threshold to Hue only — removed the matching luma-gating block from WledStreamer._render_one_device (WLED now always renders its real computed color); streaming_service.py (Hue) left byte-identical | 2026-07-14 | 783706a | [260714-pzk-scope-brightness-cutoff-threshold-to-hue](./quick/260714-pzk-scope-brightness-cutoff-threshold-to-hue/) |
| 260714-txt | Add color_correction_r/g/b sliders (default 1.0, range [0.5,1.5]) — relational correct_channels_rgb generalizes boost_saturation_rgb's dominant-channel invariance to 3 independent gains; applied after saturation boost on the shared gradient for both Hue and WLED sinks | 2026-07-14 | 2616e7a | [260714-txt-color-correction-sliders](./quick/260714-txt-color-correction-sliders/) |
| 260719-efy | Rework correct_channels_rgb from relational to static flat per-channel gain — out = clip(arr * [gain_r,gain_g,gain_b], 0, 255) applied to every pixel unconditionally (dominant-channel invariance dropped after it failed the user's hardware test); identity fast-path preserved, signature/settings keys/wiring unchanged; TestCorrectChannels rewritten for flat behavior | 2026-07-19 | 18e2027 | [260719-efy-rework-color-correction-from-relational-](./quick/260719-efy-rework-color-correction-from-relational-/) |
| 260723-udg | Rework HDR mapping — replaced per-channel extended-Reinhard finish with hue-preserving pipeline (_tone_map_max_rgb uniform scale with knee 0.75 + exponential shoulder, _compress_to_gamut_709 luma-preserving lerp toward achromatic axis); fixes blown-out midtones (diffuse white ~0.5→~0.91), orange→green and brown→red hue rotation; hdr=False paths byte-identical | 2026-07-23 | 19847cf | [260723-udg-rework-hdr-mapping-colors-blown-out-brig](./quick/260723-udg-rework-hdr-mapping-colors-blown-out-brig/) |

## Session Continuity

Last session: 2026-05-15T19:44:54.914Z
Stopped at: Completed 19.1-09-PLAN.md
Resume file: None

**Planned Phase:** 19.1 (WLED Segment Sync) — 10 plans — 2026-05-14T17:38:50.370Z
