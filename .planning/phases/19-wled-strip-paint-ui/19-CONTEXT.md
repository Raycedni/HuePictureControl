# Phase 19: WLED Strip Paint UI - Context

**Gathered:** 2026-05-14
**Status:** Ready for planning

<domain>
## Phase Boundary

The WLED tab gets a visual paint-on-strip editor that drops into the canvas slot Phase 17 reserved in `SettingsPage` / `SettingsPanel` (the `md:flex-[6]` `data-testid="paint-canvas-placeholder"` div). The phase delivers:

1. **Strip canvas** — one horizontal strip per registered WLED device, fit-to-width, with paint-to-create / drag-to-resize / select-to-edit interactions.
2. **Channel CRUD** — backend endpoints + DB writes to create / rename / resize / delete rows in `wled_channels`, cascading to `wled_light_assignments` on delete.
3. **LightPanel surfacing** — a new "WLED" section below "Lights" in `LightPanel`, grouped per device, with draggable channel rows that integrate with the existing `EditorCanvas` drop handler via an extended drag payload.
4. **Region properties panel (canvas side)** — a new surface that lets the user see the WLED channels assigned to a selected region and pick a per-assignment orientation (auto / horizontal / vertical, each direction-reversible).
5. **Orientation override in the streamer** — extend Phase 17's bbox-longest-axis sub-sample (D-10) to honor a per-assignment orientation enum, default `auto`.

Explicitly out of scope: HA control endpoints (Phase 18), polygon-path LED mapping (deferred from Phase 17), per-region polygon-axis sampling override beyond the per-assignment orientation control above, undo/redo, channel cloning between devices, mDNS-driven auto-discovery beyond what Phase 17 already shipped.

</domain>

<decisions>
## Implementation Decisions

### Paint interaction
- **D-01:** Drag-to-paint to create a new channel — mouse-down at start LED, drag across, release commits. Same mental model as `EditorCanvas` rectangle drawing (`handleMouseDown` / `handleMouseMove` / `handleMouseUp` in `Frontend/src/components/EditorCanvas.tsx`).
- **D-02:** Overlap **auto-splits** the existing zone. New range carves into the overlapped channel; remainder(s) keep the original channel's identity (id, name). Day-one experience: paint anywhere on the auto-seeded 'Strip' channel and the seed shrinks/splits to make room. No validation errors on overlap.
- **D-03:** Adjacent zone boundaries are resized via a **drag-handle on the strip** between the two zones. Dragging shifts the shared boundary — shrinking one channel and growing the other. Implies Konva (project already uses `react-konva` in `EditorCanvas`) or equivalent pointer-event-driven canvas; raw DOM is acceptable if simpler.
- **D-04:** Channel removal: select a zone, properties sidebar opens, Delete button removes it. The freed range collapses into whichever neighbor it abuts; if it abutted nothing (only at strip start/end with the seed already split out) it becomes unassigned space that subsequent paints can claim. Cascade to `wled_light_assignments` per success criterion #5.

### Strip rendering
- **D-05:** Visual unit is **zone-only rectangles** colored by the channel's derived render fill (D-09). No per-LED cells. Boundary between adjacent zones is the drag-handle (D-03).
- **D-06:** Long strips (up to 1200+ LEDs) **fit to width** of the canvas slot. Zones scale proportionally with their LED count. No horizontal scroll, no multi-row wrap. Per-LED precision is exposed via sidebar start/end inputs when a zone is selected.
- **D-07:** Strip is rendered as a **tall bar** (~40–60px). Channel name renders inline inside the zone rectangle when the zone is wide enough (planner picks the threshold, likely ~40px wide); narrower zones omit the inline label and rely on the properties sidebar.
- **D-08:** **Sparse axis labels** under the strip (e.g. 0, 50, 100, … or adapted to strip length) — a thin tick row that orients the user without requiring sidebar inspection.

### Channel naming + render color
- **D-09:** **No user-settable channel color.** Strip zone fills are derived at render time from a brand-aligned palette indexed by channel position. The original `wled_channels.color` column from Phase 17 D-07 is **left dormant** — UI ignores it, no migration. Mark as deprecated in code comments / docstring. No color picker is built. Rationale: Hue channels in `LightPanel` have no user-set color either; the UI brand palette handles "visual separation" (success criterion #3) without persisted user data.
- **D-10:** Channels are named **"Channel N"** automatically (numbered per device, monotonically incrementing — keep existing numbers stable on delete; never reuse a freed N). Name is editable in the properties sidebar when the zone is selected. Seed channel from Phase 17 D-09 keeps its `'Strip'` name until renamed.
- **D-11:** Render-fill palette for strip zones is **algorithmic and consistent with the rest of the UI brand** (orange/amber base). Exact formula is Claude's discretion — likely an HSL cycle anchored on the brand hue, or shaded variants of the brand color by channel index. Not persisted.

### LightPanel + multi-device
- **D-12:** New **'WLED' section in `LightPanel` below 'Lights'**, rendered with the existing section-header style. Channels are grouped per device (device name as sub-header → channel rows under it). Each channel row is `draggable`, mirroring the Hue per-channel rows. Render-fill chip from D-11 appears next to each row for visual matching with the painted strip.
- **D-13:** Drag payload **extends** the existing Hue contract — adds `wledChannelId` + `wledDeviceId` (plus `wledChannelName` for display) keys to `e.dataTransfer.setData(...)`. Existing Hue payload (`channelId / channelName / lightId / configId`) is untouched. `EditorCanvas.handleDrop` branches on presence of `wledChannelId` and calls a **new WLED-assignment API** that writes `wled_light_assignments(region_id, wled_channel_id, entertainment_config_id, orientation='auto')`. No reroute of the Hue path.
- **D-14:** **Separate counters** in the LightPanel header — keep the existing `N/20` chip for Hue (Entertainment-API channel limit), add a new `M` chip for WLED. WLED has no equivalent hard cap (UDP, per-device), so the WLED chip is a count only, no threshold colors.
- **D-15:** Settings paint slot **stacks all device strips vertically** with the device name as a header above each strip. The canvas slot scrolls vertically when total height exceeds the slot. No tabs, no dropdown selector — every device's painted state is visible at once.

### Orientation (per-assignment sub-sample axis)
- **D-16:** New column **`wled_light_assignments.orientation TEXT NOT NULL DEFAULT 'auto'`** added via a schema migration in Phase 19. Per-assignment scope: the same channel assigned to two different regions can have two different orientations. Phase 17's auto-seeded channel assignments (if any rows exist after a user has used the seed channel) backfill to `'auto'` via the `DEFAULT` clause — no explicit data migration step needed.
- **D-17:** Enum values for `orientation`: `auto`, `horizontal-LTR`, `horizontal-RTL`, `vertical-TTB`, `vertical-BTT`. `auto` resolves to the Phase 17 D-10 bbox-longest-axis behavior; the four explicit modes force both axis and direction.
- **D-18:** **Default `auto`** on every new assignment row — preserves the Phase 17 streaming behavior. User opts into an explicit axis only when needed.
- **D-19:** The orientation control surfaces in a **region properties panel on the canvas side**, not in the channel sidebar. Selecting a region (existing `useRegionStore.selectedId` pattern) opens a properties surface that lists each WLED channel assigned to that region, each row with a 5-option segmented control (auto / ← / → / ↑ / ↓ or equivalent icons). Exact placement of this surface (popover anchored to the selected region, inline expansion under `LightPanel.Assignments`, dedicated side panel) is Claude's discretion in planning — it must coexist with existing region selection without breaking the canvas drag-drop drop target.
- **D-20:** The backend sub-sample helper (`Backend/services/color_math.py` or wherever Phase 17 Plan 17-02 put it) is **extended to honor the orientation enum**: force the sampled axis to the bbox X or Y axis and force the direction of indexing when the enum is non-`auto`. `auto` keeps the longest-axis fallback unchanged.

### API additions (planner to refine shape)
- **D-21:** New endpoints under the existing `routers/wled.py`:
  - `GET /api/wled/devices/{device_id}/channels` — list channels for a device
  - `POST /api/wled/devices/{device_id}/channels` — create channel (body: `{name?, start_led, end_led}`); applies the overlap auto-split semantics from D-02
  - `PUT /api/wled/devices/{device_id}/channels/{channel_id}` — rename / resize / move boundary
  - `DELETE /api/wled/devices/{device_id}/channels/{channel_id}` — cascade to `wled_light_assignments`
  - `PUT /api/wled/assignments` — upsert `(region_id, wled_channel_id, entertainment_config_id, orientation)`. Mirrors the per-config scoping from Phase 17 D-08.
  - `PATCH /api/wled/assignments/{...}/orientation` — update orientation only (lighter call than a full upsert when the user just changes the segmented control). Optional — planner may fold into the upsert.
  - `DELETE /api/wled/assignments/...` — remove an assignment (driven by the canvas-side properties panel or LightPanel "Clear" action).
- **D-22:** Coordinator gradient contract from Phase 17 D-05 (`{region_id: gradient_array}`) is unchanged at the coordinator-to-sink boundary, but the gradient is now computed honoring per-assignment orientation. `N_region = max(channel_width for every assigned wled_channel)` continues to apply; the orientation flag affects axis + direction, not sample count.

### Claude's Discretion
- Konva vs raw DOM pointer-events for the strip canvas. Konva is established (`EditorCanvas` uses `react-konva`); reusing it is the natural call but a thin DOM implementation is acceptable if it's simpler for a 1D bar.
- Exact derived-fill formula (palette spacing, saturation/lightness, brand anchoring).
- Inline zone-label rendering threshold (probably ~40px wide before the label is hidden).
- Placement of the region properties panel (popover anchored to selected region, side panel, expansion of `LightPanel.Assignments`).
- Whether the seed `'Strip'` channel is auto-deleted when fully consumed by paint, or kept as a zero-width remnant. Cleanest behavior: delete when its `start_led > end_led` after a split, regenerate on next device-list refresh if no channels remain (preserves the Phase 17 D-09 invariant that every device always has at least one channel).
- Cascade semantics when a channel is deleted via the drag-handle resize collapsing it to zero width — likely treat as a delete with the same cascade to `wled_light_assignments`.
- Recompute of `N_region` (Phase 17 specifics) when assignments change mid-stream — likely on the next frame loop, not in-flight.
- Exact icons / glyphs for the orientation segmented control.
- Whether the LightPanel WLED counter shares the threshold-color rules of the Hue chip (D-14 says no — count only).
- Test strategy: Konva drag interactions in Vitest are notoriously fiddly; planner may need to choose between unit-testing the geometry/state logic in isolation and integration-testing through Playwright.

### Folded Todos
None — `STATE.md` lists no pending todos.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & Project
- `.planning/ROADMAP.md` §Phase 19 — five success criteria for WLED Strip Paint UI
- `.planning/ROADMAP.md` §Phase 17 — completed phase Phase 19 builds on (must not re-decide D-07/D-08/D-09/D-10/D-20)
- `.planning/milestones/v1.1-REQUIREMENTS.md` §WLED Strip Mapping — WMAP-01 through WMAP-05 definitions
- `.planning/PROJECT.md` §Active (v1.3) — Phase 19 line item
- `.planning/STATE.md` — current phase progress and milestone status

### Prior Phase Contexts (must-read)
- `.planning/phases/17-wled-backend-and-streaming/17-CONTEXT.md` — heavy must-read. Locks the `wled_channels` / `wled_light_assignments` data model (D-07), per-config scoping (D-08), seed channel (D-09), bbox-longest-axis sub-sample (D-10) that Phase 19 extends, paint-UI location in `SettingsPanel` (D-20), gradient contract from coordinator to sinks (D-05), `StatusBroadcaster` per-device health payload (D-16)
- `.planning/phases/16-zone-persistence-bug-fixes/16-CONTEXT.md` — `LightPanel` 3-tier zone selection + auto-save patterns Phase 19 must coexist with
- `.planning/phases/04-frontend-canvas-editor/04-CONTEXT.md` — Konva / react-konva conventions for the EditorCanvas; the strip canvas should follow the same conventions
- `.planning/phases/05-gradient-device-support-and-polish/05-CONTEXT.md` — Hue per-channel gradient semantics; reference for how WLED per-LED sub-sampling parallels them

### Project Convention / Research
- `CLAUDE.md` "Context: What Already Exists" — react-konva is the established canvas primitive (already noted: "Already the established canvas primitive. The strip UI is a horizontal canvas… Same pointer event model as the existing freeform region editor — no new library needed.")
- `CLAUDE.md` "Recommended Stack Additions" → Frontend table — explicit `react-konva` recommendation for the paint-on-strip selector

### Backend Files (modify)
- `Backend/database.py` — add `wled_light_assignments.orientation TEXT NOT NULL DEFAULT 'auto'` column to the existing CREATE TABLE block from Phase 17, plus an idempotent migration step (`ALTER TABLE ... ADD COLUMN` guarded by `PRAGMA table_info`)
- `Backend/routers/wled.py` — new channel CRUD endpoints (D-21) alongside the existing device CRUD / scan endpoints
- `Backend/services/streaming_coordinator.py` — `N_region` calculation continues to use channel widths; gradient request shape unchanged
- `Backend/services/wled_streamer.py` — applies the per-LED slice; orientation override comes from the sub-sample helper output, not from the streamer
- The Phase 17 sub-sample helper (file location set in Plan 17-02 — typically `Backend/services/color_math.py`) — extend with axis + direction overrides honoring D-17 enum

### Backend Files (new)
- Likely no new backend service files — paint UI maps onto existing wled_channels / wled_light_assignments tables + extends `routers/wled.py`. Planner may decide a dedicated `services/wled_channels.py` is worth extracting for the overlap-split logic in D-02 (likely worthwhile given the geometry complexity).

### Frontend Files (new/modify)
- `Frontend/src/components/Settings/SettingsPanel.tsx` and `Frontend/src/components/Settings/SettingsPage.tsx` — replace the `data-testid="paint-canvas-placeholder"` div with the new paint canvas component. Both surfaces share the same component (per Phase 17 SettingsPage.tsx docstring).
- New component: `Frontend/src/components/Settings/WledStripPainter.tsx` (or similar) — owns the Konva strip canvas, paint gesture, boundary handles, properties sidebar. Renders one strip per device per D-15.
- `Frontend/src/components/LightPanel.tsx` — add the WLED section (D-12) below the existing Lights section, plus the second counter (D-14). Add WLED-specific drag payload setup (D-13).
- `Frontend/src/components/EditorCanvas.tsx` — `handleDrop` branches on `wledChannelId` presence and calls a new WLED-assignment API. Existing Hue branch unchanged.
- New component: region properties panel (D-19) — exact form is Claude's discretion. Reads region selection from `useRegionStore`, lists WLED channels assigned to that region with orientation controls.
- `Frontend/src/api/wled.ts` — extend with channel CRUD client + assignment upsert/delete + orientation patch. Mirror the `WledApiError` pattern.
- `Frontend/src/store/useRegionStore.ts` — may need a `wledAssignments` field if region selection + orientation editing wants store-managed state, or pure local component state — planner's call.
- `Frontend/src/store/useStatusStore.ts` — no changes expected for Phase 19 (no new per-device status fields).
- Test files: `WledStripPainter.test.tsx`, extensions to `LightPanel.test.tsx` and `EditorCanvas.test.tsx` (if exists) for the new drop branch.

### External Docs
- [WLED UDP Realtime](https://kno.wled.ge/interfaces/udp-realtime/) — only relevant for orientation edge cases; DRGB/DNRGB byte order is fixed left-to-right and direction reversal is done in our sub-sample math, not in the protocol
- [react-konva docs](https://konvajs.org/docs/react/) — Stage / Layer / Rect / Line pointer events for the strip canvas

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `react-konva` Stage / Layer / Rect / Line (used in `Frontend/src/components/EditorCanvas.tsx`) — the strip canvas reuses the same primitives. Boundary drag-handles map naturally to draggable Line / Rect with `onDragMove` callbacks.
- Drag-and-drop API on `EditorCanvas` — drop handler reads `e.dataTransfer.getData(...)` and branches on which keys are present. Phase 19 adds a new branch for WLED.
- `Frontend/src/store/useRegionStore.ts` `selectedId` / `setSelectedId` — region selection state Phase 19 can hook into for the new region properties panel.
- `Frontend/src/components/ui/{Button,Badge}` — primitives consistent with Phase 17 WledDevicesPanel.
- `Backend/routers/wled.py` — error-handling and `WledApiError` pattern (409 conflict / 422 validation / 502 unreachable). New channel endpoints follow the same conventions.
- Phase 17 Plan 17-02 sub-sample helper (`sub_sample_gradient` or similar) — already exists; Phase 19 extends with orientation parameter.
- `LightPanel`'s grouped-rows pattern (light → segments) — directly applicable to WLED device → channels rendering.

### Established Patterns
- `react-konva` for canvas-style interactions; pointer events drive paint / drag handles
- Drag-source rows set `e.dataTransfer.setData(key, value)` and the drop handler reads by key; payload extension (not replacement) is the safe pattern (D-13)
- `CREATE TABLE IF NOT EXISTS` at startup in `database.py` for new schema; idempotent `ALTER TABLE ... ADD COLUMN` guarded by `PRAGMA table_info` for adding columns to existing tables (the orientation column add)
- Pydantic request/response models per router (see `routers/wled.py`, `routers/cameras.py`)
- Zustand store extension over new stores for shared frontend state
- Auto-save on change (Phase 10 D-05 / Phase 16 D-03) — apply to orientation segmented control and rename inputs
- `data-testid` selectors for unit tests (`zone-select`, `paint-canvas-placeholder`, `wled-add-button`, etc.) — pattern carries forward to all new paint UI elements

### Integration Points
- `Settings/SettingsPanel.tsx` and `Settings/SettingsPage.tsx` — the `flex-[6]` slot with `data-testid="paint-canvas-placeholder"` is the canonical mount point. Two surfaces, one new component.
- `LightPanel.tsx` — the WLED section sits between the existing Lights section and the Assignments section; the WLED counter chip sits next to the existing N/20 chip
- `EditorCanvas.handleDrop` — only file that changes for the canvas-side drop wiring; the branch on `wledChannelId` is additive
- `routers/wled.py` — channel endpoints live in the same router; `app.state.coordinator.set_wled_device_enabled` pattern is the reference for coordinator-aware channel updates if needed
- The region properties panel is a new surface — its placement determines whether it integrates with `EditorPage` (next to LightPanel), as a popover on the canvas, or as an expandable row inside `LightPanel.Assignments`

</code_context>

<specifics>
## Specific Ideas

- Drag-to-paint gesture mirrors `EditorCanvas.handleMouseDown/Move/Up` for rectangle drawing — same state machine, same Konva primitives.
- Boundary handle between adjacent zones is a thin draggable Konva `Line` (or `Rect`) anchored at the zone boundary's x-coordinate; `onDragMove` clamps to the neighboring zones' inner edges (min 1-LED width on either side).
- Strip aspect: 40–60px tall, fit-to-width, sparse axis ticks below — looks more like a video timeline editor than a literal LED strip. Trade-off accepted: less "literal" but readable for any strip length.
- LightPanel WLED section header style matches the existing `text-[11px] font-semibold text-muted-foreground uppercase tracking-wider` — consistent with "Zone" / "Camera" / "Lights".
- Each WLED device row in `LightPanel`'s WLED section is a sub-header (device name + LED count) with channel rows nested underneath, mirroring the Hue light → segments visual.
- Drag-source channel row in `LightPanel`: `draggable`, sets `wledChannelId`, `wledDeviceId`, `wledChannelName`, `entertainment_config_id`. The render-fill chip color is computed at render time (no DB lookup) so the LightPanel chip matches the strip zone fill by-position.
- Region properties panel (canvas side) lists assigned WLED channels with the same chip-color reference, plus a 5-button segmented control for orientation. "auto" is the default-selected button.
- Orientation icons: arrow glyphs (`→`, `←`, `↓`, `↑`) plus an "Auto" text option. Segmented control style consistent with shadcn/ui primitives the project already uses.
- Migration for the new column: `ALTER TABLE wled_light_assignments ADD COLUMN orientation TEXT NOT NULL DEFAULT 'auto'`, guarded by checking `PRAGMA table_info(wled_light_assignments)` for the column's absence so the change is idempotent across restarts.
- API for assignment upsert mirrors Phase 17's INSERT pattern in `routers/wled.py` — use `INSERT INTO wled_light_assignments(...) ON CONFLICT(region_id, wled_channel_id, entertainment_config_id) DO UPDATE SET orientation=excluded.orientation`.
- Auto-derived render-fill formula (Claude's discretion): one natural option is HSL with hue cycled by `(channel_index * 137.508°) mod 360` (golden-angle, well-separated colors) and saturation/lightness anchored to the project's brand-aligned tone. Alternative: shaded variants of the brand amber for a more cohesive but less distinct look.

</specifics>

<deferred>
## Deferred Ideas

- **User-picks-axis at the region level (not per-assignment)** — Phase 19 picks per-assignment; the simpler region-scoped variant is rejected as a v1 narrowing. Could be revisited if per-assignment proves to be too much UI for the common case.
- **Polygon-path LED mapping** — sampling along a region's perimeter or centerline instead of its bounding box. Phase 17 deferred; orientation override in Phase 19 mitigates the common "wrong axis" complaint. Revisit only if curved-region mapping still feels off.
- **Undo/redo on paint operations** — not in scope. The state is in the database; a wrong paint can be corrected by repainting or deleting.
- **Per-device default orientation setting** — cascade default to new channels on that device. Could simplify "I always mount strips vertically on this device" cases, but adds two levels of control. Defer until users ask.
- **WLED channel cloning across devices** — copy a strip's channel layout to another strip. Useful when wiring two identical-length strips, but rare.
- **User-settable channel colors** — explicitly rejected (D-09). No user data for a UI rendering concern.
- **Per-region cap on assigned WLED channels** — no hard cap currently exists; UI does not need to enforce one until a use case emerges.
- **Visualizing the per-assignment orientation arrow on the painted strip zone** — orientation is per-assignment; showing it on the strip (which is per-channel) would require either rendering it per-region the channel is assigned to (clutter) or omitting it (current choice). Indicator lives in region properties only.
- **Per-LED preview of the streaming color on the strip** — would visualize the actual streamed gradient during streaming. Useful for debugging but adds a WS payload + render path; defer to a possible Phase 20.
- **`wled_channels.color` removal migration** — left dormant in D-09; a future cleanup phase can drop the column.

### Reviewed Todos (not folded)
None — `STATE.md` lists no pending todos.

</deferred>

---

*Phase: 19-wled-strip-paint-ui*
*Context gathered: 2026-05-14*
