# Phase 19: WLED Strip Paint UI - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `19-CONTEXT.md` — this log preserves the alternatives considered.

**Date:** 2026-05-14
**Phase:** 19-wled-strip-paint-ui
**Areas discussed:** Paint interaction, Strip rendering & long strips, LightPanel + multi-device, Channel name + color, Orientation of painted regions

---

## Paint interaction

### Q1: How should the user create a new channel zone on the strip?

| Option | Description | Selected |
|--------|-------------|----------|
| Drag-to-paint (Recommended) | Mouse-down at start LED, drag across, release to commit. Mirrors EditorCanvas rectangle drawing. | ✓ |
| Click start, click end | Click first LED, click second LED, range commits. Easier for fine control on dense strips. | |
| Add button + sliders | Click 'Add channel', new zone appears with start/end sliders or numeric inputs. Most precise, least visual. | |

**User's choice:** Drag-to-paint
**Notes:** Aligned with the EditorCanvas rectangle-drawing pattern.

### Q2: What happens when the painted range overlaps an existing zone (e.g. the seed 'Strip' channel covering the full strip)?

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-split existing zone (Recommended) | New range created; existing zone is shrunk or split into two pieces to make room. | ✓ |
| Overwrite existing portion | New range wins; overlapped LEDs leave the old zone and join the new one. | |
| Forbid overlap (validation error) | User must paint inside unassigned space. | |

**User's choice:** Auto-split existing zone
**Notes:** Day-one experience: paint anywhere on the seed 'Strip' channel and get a new zone + remainders.

### Q3: How should adjacent zone boundaries be resized?

| Option | Description | Selected |
|--------|-------------|----------|
| Drag-handle on the strip (Recommended) | Vertical handle between two adjacent zones; drag left/right to shift the boundary. | ✓ |
| Sidebar with start/end inputs | Select a zone, sidebar shows numeric start/end LED inputs. | |
| Both — drag-handle + sidebar inputs | Drag handle for visual case, sidebar for fine control. | |

**User's choice:** Drag-handle on the strip
**Notes:** Matches success criterion #3 wording directly.

### Q4: How is a channel removed?

| Option | Description | Selected |
|--------|-------------|----------|
| Select zone + Delete button in sidebar/properties (Recommended) | Click a zone, properties panel appears with rename/recolor/delete. | ✓ |
| Right-click context menu on the zone | Right-click a zone → Delete. | |
| Dedicated channel list with row delete buttons | List below the strip with one row per channel; trash icon on each row. | |

**User's choice:** Select zone + Delete button in sidebar/properties
**Notes:** Same pattern as EditorCanvas region selection.

---

## Strip rendering & long strips

### Q1: What's the primary visual unit on the strip?

| Option | Description | Selected |
|--------|-------------|----------|
| Zone-only rectangles (Recommended) | One rectangle per painted channel, filling that LED range with the channel's display color. | ✓ |
| Per-LED cells | Each LED is one cell colored by its containing zone. | |
| Gradient bar with zone overlays | Horizontal bar with zones as semi-transparent overlays. | |

**User's choice:** Zone-only rectangles

### Q2: How should long strips (e.g. 1000+ LEDs) fit in the canvas slot?

| Option | Description | Selected |
|--------|-------------|----------|
| Fit-to-width, proportional zones (Recommended) | Strip always fits canvas width; zones scale proportionally. | ✓ |
| Horizontal scroll with fixed LED width | Each LED gets fixed minimum width; long strips become horizontally scrollable. | |
| Wrap to multiple rows | Strip wraps every N LEDs. | |

**User's choice:** Fit-to-width, proportional zones

### Q3: Strip height / aspect in the canvas slot?

| Option | Description | Selected |
|--------|-------------|----------|
| Tall bar with room for labels (Recommended) | Strip is 40–60px tall, room for inline zone labels. | ✓ |
| Thin literal strip (~10–16px) | Matches real-world appearance. Compact, labels must go in sidebar. | |
| Adaptive height based on strip length | Short strip: tall. Long strip: thin. | |

**User's choice:** Tall bar with room for labels

### Q4: Should the strip show LED index markers or labels?

| Option | Description | Selected |
|--------|-------------|----------|
| Hover-only tooltip (Recommended) | Hovering shows 'LED N' under cursor. | |
| Sparse axis labels (0, 50, 100…) | Tick row under the strip with LED indices at intervals. | ✓ |
| Per-zone count inline | Each zone shows its LED count or range inside the rectangle. | |

**User's choice:** Sparse axis labels (0, 50, 100…)

---

## LightPanel + multi-device

### Q1: Where do painted WLED channels appear in the LightPanel?

| Option | Description | Selected |
|--------|-------------|----------|
| Separate 'WLED' section below 'Lights' (Recommended) | New section header in LightPanel, grouped per device. | ✓ |
| Interleaved with Hue lights | Treat each WLED device as a 'light' with channels as 'segments'. | |
| Dedicated WLED panel/drawer | WLED channels in a separate side panel. | |

**User's choice:** Separate 'WLED' section below 'Lights'

### Q2: How should the drag payload distinguish WLED channels from Hue segments?

| Option | Description | Selected |
|--------|-------------|----------|
| New fields 'wledChannelId' + 'wledDeviceId' (Recommended) | Hue payload unchanged; WLED drags set distinct keys; handleDrop branches. | ✓ |
| Reuse 'channelId' with a 'channelKind' discriminator | Single channelId field plus channelKind: 'hue' \| 'wled'. | |
| Overload 'lightId' with a 'wled:' prefix | lightId becomes 'wled:<channel_id>'. Hacky string parsing. | |

**User's choice:** New fields 'wledChannelId' + 'wledDeviceId'

### Q3: Should WLED channel assignments count toward the 20/20 chip in LightPanel?

| Option | Description | Selected |
|--------|-------------|----------|
| Separate counters: Hue (N/20) + WLED (M) (Recommended) | Hue keeps its 20-channel limit visualization. WLED has no equivalent cap, shows count. | ✓ |
| Combined into one 20/20 chip | Total assignments — Hue + WLED — in one counter. | |
| Hide the chip entirely for WLED | Only Hue counter remains. | |

**User's choice:** Separate counters: Hue (N/20) + WLED (M)

### Q4: How should multiple WLED devices be presented in the Settings paint slot?

| Option | Description | Selected |
|--------|-------------|----------|
| Vertical stack — all strips visible (Recommended) | Each device's strip stacked top-to-bottom with device name above each. | ✓ |
| Tabs per device | One strip visible at a time; tabs to switch. | |
| Single strip + device dropdown | Strip + 'Editing: <device>' dropdown. | |

**User's choice:** Vertical stack — all strips visible

---

## Channel name + color

### Q1: How should a newly painted channel get its initial color?

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-palette, editable later (Recommended) | Paint commits with auto-assigned color; user can recolor in sidebar. | ✓ |
| Color picker prompts on paint commit | Drag-release opens a popover/modal with name + color. | |
| Auto-palette, immutable | Auto-assigned and never editable. | |

**User's choice:** Auto-palette, editable later
**Notes:** Subsequently rolled back by Q5 — user questioned why colors are needed at all, and the picker was dropped entirely.

### Q2: Which palette should auto-assignment use?

| Option | Description | Selected |
|--------|-------------|----------|
| HSL hue cycle (Recommended) | Cycle hue at fixed saturation/lightness. | |
| Fixed 12-color palette (tab-distinct) | Curated set of 12 highly-distinct colors. | |
| Match existing region/light colors | Reuse the brand palette from EditorPage / RegionPolygon. | ✓ |

**User's choice:** Match existing region/light colors
**Notes:** Interpreted as "use UI brand-aligned palette" rather than literally tracking the assigned region's color. Led to the discussion in Q5.

### Q3: How should a new channel be named?

| Option | Description | Selected |
|--------|-------------|----------|
| Auto 'Channel N', editable in sidebar (Recommended) | Auto 'Channel 1', 'Channel 2'… numbered per device. | ✓ |
| Required name input on paint commit | Paint opens quick input before zone is persisted. | |
| Auto 'LEDs 0–49' style by range, editable | Auto-name encodes the range itself. | |

**User's choice:** Auto 'Channel N', editable in sidebar

### Q4: What color-picker should the properties sidebar use?

**Question rejected by the user — pushed back with "why do we need a color picker?" and then "why do we need to set colors at all? The current lights dont use any static colors, why would WLED be any different?"**

**Resolution (Q5 below):** No color picker; no user-settable channel color. Strip zone fills are derived at render time from the brand palette. `wled_channels.color` column from Phase 17 left dormant.

### Q5 (replacement): What to do with the now-unused wled_channels.color column from Phase 17?

| Option | Description | Selected |
|--------|-------------|----------|
| Leave dormant — ignore in UI, no migration (Recommended) | Column stays with its default '#ffffff'. Nothing reads it. | ✓ |
| Drop the column in a Phase 19 migration | Schema migration removes the column. | |
| Keep it and persist auto-derived colors | Compute and write derived color on paint. | |

**User's choice:** Leave dormant — ignore in UI, no migration

---

## Orientation of painted regions (user-added area)

### Q1: Where does orientation live in the data model?

| Option | Description | Selected |
|--------|-------------|----------|
| Per channel — column on wled_channels (Recommended) | Orientation is intrinsic to the painted channel. | |
| Per assignment — column on wled_light_assignments | Orientation is per (channel, region) pair. | ✓ |
| Per region — column on regions table | All channels on a region inherit that region's orientation. | |

**User's choice:** Per assignment — column on wled_light_assignments

### Q2: What orientation values should be available?

| Option | Description | Selected |
|--------|-------------|----------|
| auto / horizontal / vertical, each direction-reversible (Recommended) | Four explicit modes + auto. | ✓ |
| auto / horizontal / vertical only | Three modes, no reverse. | |
| auto only + 'flip' toggle on top | Keep auto with a separate reverse boolean. | |

**User's choice:** auto / horizontal / vertical, each direction-reversible

### Q3: What's the default orientation when a new channel is painted?

| Option | Description | Selected |
|--------|-------------|----------|
| 'auto' (longest axis) — matches Phase 17 D-10 (Recommended) | New channels start in auto mode. | ✓ |
| Prompt on assignment (not on paint) | Surface a picker when channel is dragged onto a region. | |
| Inferred from region aspect ratio | Smart default based on region geometry. | |

**User's choice:** 'auto' (longest axis) — matches Phase 17 D-10

### Q4: Where does the orientation control live in the UI?

| Option | Description | Selected |
|--------|-------------|----------|
| Properties sidebar when zone selected (Recommended) | Same sidebar that holds rename/delete/start-end gets an orientation control. | ✓ |
| Small icon overlay on the painted zone | Each zone shows a small arrow icon; click to cycle. | |
| Per-device 'default orientation' + per-channel override | Two-level control hierarchy. | |

**User's choice:** Properties sidebar when zone selected

### Q5 (reconciliation): Where exactly does the per-assignment orientation control surface?

(Triggered because Q1 chose per-assignment scope but Q4 picked channel-properties sidebar — needed to reconcile where a per-region control lives.)

| Option | Description | Selected |
|--------|-------------|----------|
| Channel sidebar lists assignments + orientation per row (Recommended) | Select zone → sidebar shows name, range, list of regions it's assigned to with orientation per row. | |
| Region properties (canvas side) — per-channel orientation under the region | Select region on EditorCanvas → properties panel shows assigned WLED channels with orientation. | ✓ |
| Both surfaces show the same control, kept in sync | Channel sidebar AND region panel both render orientation. | |

**User's choice:** Region properties (canvas side) — per-channel orientation under the region
**Notes:** Introduces a new region-properties UI surface; exact placement (popover, side panel, expansion of LightPanel.Assignments) deferred to planning.

---

## Claude's Discretion

Areas deferred to research / planning:
- Konva vs raw DOM pointer-events for the strip canvas
- Derived render-fill palette formula (HSL cycle vs brand shades)
- Inline zone-label rendering threshold (~40px wide)
- Placement of the new region properties panel
- Whether the seed 'Strip' channel is auto-deleted when fully consumed
- Recompute timing of N_region when assignments change mid-stream
- Exact icons for the orientation segmented control
- Test strategy for Konva drag interactions

## Deferred Ideas

- User-picks-axis at the region-only level (rejected in favor of per-assignment)
- Polygon-path LED mapping (Phase 17 deferral, mitigated by orientation override)
- Undo/redo on paint operations
- Per-device default orientation setting
- WLED channel cloning across devices
- User-settable channel colors (explicitly rejected)
- Per-region cap on assigned WLED channels
- Orientation indicator on the painted strip zone (per-assignment scope makes this clutter-prone)
- Per-LED preview of the streaming color on the strip during streaming
- `wled_channels.color` removal migration (left dormant for a future cleanup phase)
