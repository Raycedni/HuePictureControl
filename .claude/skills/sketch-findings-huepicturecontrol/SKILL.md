---
name: sketch-findings-huepicturecontrol
description: Validated design decisions, CSS patterns, and visual direction from sketch experiments. Auto-loaded during UI implementation on HuePictureControl.
---

<context>
## Project: HuePictureControl

Aesthetic is anchored to the live app — dark `#0c0c14` ground, amber `#e8a000` accent, glass surfaces (white@4% on white@8% border), Geist Variable type, `text-[11px] uppercase tracking-wider` section headers. Sketch sessions answered visual questions left as "Claude's Discretion" in `.planning/phases/19-wled-strip-paint-ui/19-CONTEXT.md`, not the brand itself.

Reference points: the running app (`Frontend/src/index.css`, `LightPanel.tsx`, `Settings/WledDevicesPanel.tsx`), video timeline editors (Premiere/Resolve) for the strip cadence, shadcn/ui for primitive idiom (Button/Badge already in use).

Sketch sessions wrapped: 2026-05-14
</context>

<design_direction>
## Overall Direction

**Strip canvas = video-track cadence**, not a literal LED strip. 40px tall, in-strip boundary handles, sparse axis ticks below, fit-to-width, multiple devices stacked vertically. Zones are colored rectangles; no per-LED cells. Inline zone labels above ~13% of canvas width; everything else lives in the right-column sidebar.

**Zone colors = derived, not stored.** `hsl((index × 137.508°) % 360, 60%, 60%)` applied identically to strip zones and LightPanel chips. Brand color stays as chrome (selection outlines, accents, primary buttons); derived palette is reserved for data (zone fills, chips). Boundary crisp.

**Region orientation control = canvas popover.** Per-assignment orientation (auto / → / ← / ↓ / ↑) opens as a popover anchored to the selected region. Closes on outside-click or deselect. Auto-flip when near canvas edges. LightPanel `Assignments` section becomes a static reference list — control surface moves to the canvas where the region is.

**Spacing/typography/surfaces** follow the existing tokens — see `sources/themes/default.css` for the consolidated reference (mirrors `Frontend/src/index.css`).
</design_direction>

<findings_index>
## Design Areas

| Area | Reference | Key Decision |
|------|-----------|--------------|
| Canvas & Overlays | `references/canvas-and-overlays.md` | 40px strip + canvas popover for region props; shared `.handle` primitive for boundary + region resize handles |
| Zone Palette | `references/zone-palette.md` | `hsl((i × 137.508°) % 360, 60%, 60%)` — derived per-channel, not stored |

## Theme

Consolidated theme tokens at `sources/themes/default.css` mirror `Frontend/src/index.css`. The sketch theme is the source of truth for sketch primitives (`.section-header`, `.glass`, `.btn`, `.badge`, `.input`, `.handle`, `.popover` etc.) and stays in sync with the running app's CSS variables.

## Source Files

Full sketch HTML files preserved in `sources/` for complete context:
- `sources/001-strip-canvas/index.html` — strip canvas variants (A · Thin Timeline 40px wins, B/C preserved for comparison)
- `sources/002-zone-palette/index.html` — palette variants (A · Golden-Angle HSL wins)
- `sources/003-region-props-placement/index.html` — placement variants (A · Canvas Popover wins)
</findings_index>

<metadata>
## Processed Sketches

- 001-strip-canvas
- 002-zone-palette
- 003-region-props-placement
</metadata>
