# Sketch Manifest

## Design Direction
Phase 19 ("WLED Strip Paint UI") sketches answer the visual questions left as "Claude's Discretion" in `.planning/phases/19-wled-strip-paint-ui/19-CONTEXT.md`. The aesthetic is anchored to the live app brand — dark `#0c0c14` ground, amber `#e8a000` accent, glass surfaces (white@4% on white@8% border), Geist Variable type, `text-[11px] uppercase tracking-wider` section headers. Sketches focus on structural and interaction questions rather than re-deriving the palette.

## Reference Points
- The running app (`Frontend/src/index.css`, `LightPanel.tsx`, `Settings/WledDevicesPanel.tsx`)
- Video timeline editors (Premiere/Resolve) — model for the horizontal strip + sparse-tick axis
- shadcn/ui — primitive idiom (Button, Badge) the project already uses

## Sketches

| # | Name | Design Question | Winner | Tags |
|---|------|----------------|--------|------|
| 001 | strip-canvas | What does the strip canvas look like across device counts and zone widths? | **A · Thin Timeline (40px)** | layout, canvas, settings |
| 002 | zone-palette | How are zone fills derived so adjacent zones read as distinct? | **A · Golden-Angle HSL** | palette, color |
| 003 | region-props-placement | Where does the per-assignment orientation control live? | _tbd_ | layout, panel, canvas |
