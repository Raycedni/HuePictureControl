---
sketch: 003
name: region-props-placement
question: "Where does the per-assignment orientation control live?"
winner: "A"
tags: [layout, panel, canvas]
---

# Sketch 003: Region Properties Placement

## Design Question
CONTEXT.md D-19 says the per-assignment orientation control (auto / → / ← / ↓ / ↑) "must coexist with existing region selection without breaking the canvas drag-drop drop target" and explicitly lists three viable placements as Claude's discretion. This sketch builds all three with the EditorPage in the background (canvas + region + LightPanel) so the spatial relationship is visible.

## How to View
```
.planning\sketches\003-region-props-placement\index.html
```

## Variants
- **A · Canvas Popover** — Anchored to the selected region. Opens on select, closes on outside click / deselect. Spatially tied to the region; risks edge collisions and obscuring underlying frame.
- **B · Right-Side Drawer** — Dedicated 280px panel between canvas and LightPanel. Persistent layout. Room for future region-level metadata. Costs ~280px of canvas width permanently.
- **C · Inline in LightPanel** — Lives inside the existing `Assignments` section that already exists in `LightPanel.tsx`. No new surface. Spatially disconnected from the canvas; user's eye must travel.

## What to Look For
- Which placement keeps the user's attention closest to the region they're editing?
- Does any variant break the existing canvas drag-drop drop target (per D-19's constraint)?
- How does each handle the empty-state (no region selected)?
- Variant A: popover at the bottom of the canvas — does it collide with edges?
- Variant B: with three vertical columns (canvas | drawer | LightPanel), does the canvas feel cramped?
- Variant C: scroll behaviour — when LightPanel is tall, can users find the Assignments section after selecting a region?
- Variant C is the lowest-cost implementation (extends an existing section). Does it lose enough UX to be worth the extra component?

## Related decisions
- CONTEXT.md D-16, D-17, D-18 (orientation enum, default `auto`, per-assignment scope)
- CONTEXT.md D-19 (placement is Claude's discretion, three options listed)
- Phase 16 patterns: `useRegionStore.selectedId` is the selection source
