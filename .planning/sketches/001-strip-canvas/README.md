---
sketch: 001
name: strip-canvas
question: "What does the strip canvas look like across device counts and zone widths?"
winner: "A"
tags: [layout, canvas, settings]
---

# Sketch 001: Strip Canvas

## Design Question
CONTEXT.md decides the strip is fit-to-width, no per-LED cells, and rendered as a tall bar with sparse axis ticks. It leaves "tall bar (~40–60px)" as a range and inline-label threshold as Claude's discretion. This sketch tests how three different strip-rendering models read with realistic device counts (2 devices, mixed channel widths, one narrow zone, one unassigned span).

## How to View
```
.planning\sketches\001-strip-canvas\index.html
```

## Variants
- **A · Thin Timeline (40px)** — Video-track cadence. Inline labels only when wide; small zones go label-less and rely on the selected-channel sidebar.
- **B · Tall Pill (60px)** — Strip as primary object. Name + LED range inline above ~80px wide; clips to name-only when narrower.
- **C · Stacked Rail** — Zones become tiles floating above a thin rail. Empty rail = unassigned LEDs visible at a glance. Floating boundary pill instead of in-strip handle.

## What to Look For
- Which density makes 3+ channels readable without sidebar trips?
- How does each variant handle the narrow zone (Ch 3, 6% wide)?
- How does each handle multiple devices stacked vertically (C-D-15: all devices visible at once)?
- Does C's unassigned-LED visualisation justify the extra visual machinery?
- Which boundary-handle treatment (in-strip line vs floating pill) communicates "draggable" best?

## Related decisions
- CONTEXT.md D-05, D-06, D-07 (zone-only rendering, fit-to-width, tall bar)
- CONTEXT.md D-08 (sparse axis labels)
- CONTEXT.md D-15 (all device strips visible at once, vertical scroll)
- CONTEXT.md "Claude's Discretion" (inline-label threshold)
