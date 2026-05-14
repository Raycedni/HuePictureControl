# Sketch Wrap-Up Summary

**Date:** 2026-05-14
**Sketches processed:** 3
**Design areas:** Canvas & Overlays, Zone Palette
**Skill output:** `./.claude/skills/sketch-findings-huepicturecontrol/`

## Included Sketches

| # | Name | Winner | Design Area |
|---|------|--------|-------------|
| 001 | strip-canvas | A · Thin Timeline (40px) | Canvas & Overlays |
| 002 | zone-palette | A · Golden-Angle HSL | Zone Palette |
| 003 | region-props-placement | A · Canvas Popover | Canvas & Overlays |

## Excluded Sketches

| # | Name | Reason |
|---|------|--------|
| — | — | None — all three sketches included. |

## Design Direction

Phase 19's paint-on-strip UI lands as a video-track-cadence timeline editor anchored to the existing brand. The strip is the primary surface in the Settings paint slot; the orientation control comes to the user (popover on the canvas) rather than the user going to the control. Zone colors are derived from a deterministic golden-angle HSL formula — never stored, identical across strip zones and LightPanel chips.

## Key Decisions

- **Strip:** 40px tall, in-strip 2px boundary handle, sparse mono axis ticks below, vertical device stack in the Settings paint slot (`md:flex-[6]` slot in `SettingsPanel`/`SettingsPage`).
- **Zone label visibility:** inline name when zone wider than ~13% of canvas; narrow zones rely on the right-column "Selected channel" sidebar.
- **Palette:** `hsl((index × 137.508°) % 360, 60%, 60%)`. Per-device numbering means same indexes reuse colors across devices — intentional.
- **Region orientation popover:** 280px wide, anchored bottom-left to the selected region, auto-flip near canvas edges, closes on outside-click / region deselect / new selection / × button.
- **Segmented control:** `auto / → / ← / ↓ / ↑` (text + glyph, monospace, amber active state). Auto-save via `PATCH /api/wled/assignments/{...}/orientation`.
- **Brand vs derived:** brand color (`#e8a000`) is chrome — selection outlines, popover beak, segmented-control active state, primary buttons. Derived palette is data — zone fills, chips.
- **Shared `.handle` primitive** — boundary handles in the strip and the region-resize handles on the canvas share a single CSS utility.

## Rejected directions (preserved for context)

- **001-B (60px tall pill)** — primary surface but too dominant at 3+ devices stacked
- **001-C (stacked-rail tiles)** — read as grouped buttons rather than a continuous range
- **002-B (amber tonal ramp)** — in-brand but lost contrast past 5 channels
- **002-C (warm/cool alternation)** — brittle rule, needs hand-curated families
- **003-B (right-side drawer)** — permanent 280px tax even when no region selected
- **003-C (inline in LightPanel.Assignments)** — eye must leave canvas; scrolling at narrow widths

## Next steps

1. `/gsd-ui-phase 19` — bake these decisions into a formal UI-SPEC.md
2. `/gsd-plan-phase 19` — write Plan files referencing the spec + this skill

The sketch-findings skill is auto-routed from `CLAUDE.md` and will load when implementing the UI.
