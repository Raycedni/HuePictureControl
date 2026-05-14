---
sketch: 002
name: zone-palette
question: "How are zone fills derived so adjacent zones read as distinct?"
winner: "A"
tags: [palette, color]
---

# Sketch 002: Zone Palette

## Design Question
CONTEXT.md D-09 forbids user-settable channel color. D-11 says the strip fill is "algorithmic and consistent with the rest of the UI brand (orange/amber base)". This sketch tests three derivation strategies against a 6-channel stress case (max likely density) and the typical 3-channel case.

## How to View
```
.planning\sketches\002-zone-palette\index.html
```

## Variants
- **A · Golden-Angle HSL** — `hsl((i * 137.508°) % 360, 60%, 60%)`. Maximum hue separation, full rainbow.
- **B · Amber Tonal Ramp** — Hue locked near brand (38°), step lightness 45→75 and saturation 90→60. Stays in family.
- **C · Brand + Cool Counterpoint** — Indexes alternate between a warm family (amber/orange/gold) and a cool family (slate/teal/periwinkle). Adjacent contrast guaranteed.

## What to Look For
- At 6 channels (TV Back Strip stress test), which still has adjacent contrast?
- Does the chip in the LightPanel row match the strip zone clearly enough to associate the two?
- Does the palette respect the brand or fight it? (A goes full rainbow; B stays inside; C balances.)
- Does Channel 1 = amber (variant C) feel intentional, or does it bias users into thinking Ch 1 is special?
- Test the "same-index-same-color across devices" property — Top/Mid/Bot on Lamp Strip reuses the first three colors. Does that read as consistent or confusing?

## Related decisions
- CONTEXT.md D-09 (no user-settable color), D-11 (algorithmic brand-aligned palette)
- CONTEXT.md "Specifics" (golden-angle HSL listed as natural option)
- Success criterion #3 (adjacent zones visually separated)
