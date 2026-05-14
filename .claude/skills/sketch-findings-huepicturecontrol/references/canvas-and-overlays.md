# Canvas & Overlays

Layout patterns for any new canvas-style surface (the WLED paint strip in Settings, and the per-region orientation popover on the EditorCanvas). Both share the same primitives — pointer-driven canvas + glass-surface overlay + amber accent on selection.

## Design Decisions

### Strip canvas (Settings paint slot) — Sketch 001

| Decision | Value | Rationale |
|---|---|---|
| Height | **40px** | Tested 40 (thin timeline), 60 (tall pill), 52 (stacked rail). 40px gives video-track cadence — primary surface stays compact, ticks legible directly underneath, fits multiple devices stacked. |
| Surface | `background: rgba(0,0,0,0.35); border-radius: 4px; border: 1px solid rgba(255,255,255,0.06)` | Inset feel — strip is a "track" that zones live inside, not a floating object. |
| Zone fill | Derived (see `zone-palette.md`) | No user color picker. |
| Zone label | Inline name above ~80px wide (~13% of the canvas width with the test fixture); `.zone.narrow { padding: 0 }` removes label. Selected zone always shows in the right-column sidebar regardless of width. |
| Zone label color | `rgba(0,0,0,0.78)` — dark text on the colored fills. High enough contrast on every palette index tested. |
| Boundary handle | 2px vertical line, `rgba(255,255,255,0.45)`, height 70% of strip, hover → `var(--accent)` and 90% height. **Lives inside the strip**, not floating above. |
| Selected outline | `1px solid var(--accent)`, `outline-offset: -1px`, `z-index: 2` so the outline stays on top of neighbors. |
| Axis ticks | Below the strip, 14px tall row, `rgba(255,255,255,0.2)` 1×4px tick + `font-family: var(--mono)` 9px label. Sparse — 0/50/100/150/200/250/300 for a 300-LED strip. |
| Device stack | Vertical, device name (12px, `var(--text-h)`) + meta (10px mono, `rgba(255,255,255,0.4)`) above each strip. Slot scrolls vertically when total height exceeds the slot. |
| Sidebar (right column of Settings) | `WledDevicesPanel` keeps the existing device CRUD up top; below it a "Selected channel" group with name input, start/end LED inputs (mono), delete button. |

### Region orientation popover (EditorCanvas) — Sketch 003

| Decision | Value | Rationale |
|---|---|---|
| Trigger | Region selection via `useRegionStore.selectedId` | Existing pattern from Phase 16. |
| Anchor | Bottom-left of the selected region, offset 12px down | Tested against drawer + inline-LightPanel alternatives. Popover keeps the user's attention on the canvas. |
| Width | 280px | Matches the LightPanel column width on the right — visual consistency. |
| Surface | `background: rgba(20,20,35,0.96); border: 1px solid var(--glass-border); border-radius: 8px; padding: 12px; box-shadow: var(--shadow-lg); backdrop-filter: blur(12px)` | Heavier than glass surfaces elsewhere because it floats above content and must remain readable over varied backgrounds. |
| Pointer | 12×12 rotated square, top edge, 24px from popover left — standard popover beak. |
| Close triggers | (1) outside click, (2) region deselect, (3) selecting a different region, (4) explicit × button in popover header. |
| Edge handling | **Auto-flip required**: anchor below-left → if region bottom would push the popover off-screen, flip above. Same for left/right edges. Implementation can hand off to a popover positioning lib if Frontend already has one, otherwise plain bounding-box math. |
| Empty state | If selected region has no WLED assignments: show "Drag a channel from the LightPanel to add an assignment." in the popover, no segmented controls. |
| Content per assignment | Chip + channel name + device name on row 1; `ori-label` + 5-button segmented control on row 2. One block per assignment, separated by 8px gap. |

### Orientation segmented control (shared by popover)

| Decision | Value |
|---|---|
| Surface | `background: rgba(0,0,0,0.3); border: 1px solid var(--glass-border); border-radius: 4px; padding: 2px` |
| Button labels | `auto`, `→`, `←`, `↓`, `↑` (text + glyphs, monospace font) |
| Active state | `background: var(--accent-bg); color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent-border)` |
| Hover (inactive) | `color: var(--text-h); background: rgba(255,255,255,0.04)` |
| Default selection | `auto` (matches D-18 default) |
| Persists | On-click upsert via `PATCH /api/wled/assignments/{...}/orientation` (auto-save pattern from Phase 16) |

## CSS Patterns

### Strip + zones (sketch 001-A)
```css
.strip {
  position: relative;
  height: 40px;
  background: rgba(0,0,0,0.35);
  border-radius: 4px;
  border: 1px solid rgba(255,255,255,0.06);
  overflow: visible; /* handles extend above/below */
}
.strip .zone {
  position: absolute; top: 0; bottom: 0;
  display: flex; align-items: center; padding: 0 8px;
  font-size: 11px; font-weight: 500;
  color: rgba(0,0,0,0.78);
  cursor: pointer; user-select: none;
  border-right: 1px solid rgba(0,0,0,0.25);
}
.strip .zone:hover  { filter: brightness(1.08); }
.strip .zone.selected { outline: 1px solid var(--accent); outline-offset: -1px; z-index: 2; }
.strip .zone.narrow { padding: 0; /* label hidden via DOM, not CSS */ }
```

### Boundary handle (shared utility — extract to a CSS class)
```css
.handle {
  position: absolute;
  top: 50%;
  width: 8px;
  height: calc(100% + 12px);
  transform: translate(-50%, -50%);
  cursor: ew-resize;
  display: flex; align-items: center; justify-content: center;
}
.handle::before {
  content: '';
  width: 2px;
  height: 70%;
  background: rgba(255,255,255,0.45);
  border-radius: 1px;
  box-shadow: 0 0 0 1px rgba(0,0,0,0.4);
}
.handle:hover::before { background: var(--accent); height: 90%; }
```

### Axis ticks
```css
.ticks {
  position: relative; height: 14px; margin-top: 4px;
  font-size: 9px; color: rgba(255,255,255,0.35); font-family: var(--mono);
}
.ticks .tick { position: absolute; top: 0; transform: translateX(-50%); }
.ticks .tick::before {
  content: ''; display: block; width: 1px; height: 4px;
  background: rgba(255,255,255,0.2); margin: 0 auto 2px;
}
```

### Popover (sketch 003-A)
```css
.popover {
  position: absolute;
  width: 280px;
  background: rgba(20, 20, 35, 0.96);
  border: 1px solid var(--glass-border);
  border-radius: 8px;
  padding: 12px;
  box-shadow: rgba(0,0,0,0.5) 0 10px 30px -5px, rgba(0,0,0,0.3) 0 4px 10px -2px;
  backdrop-filter: blur(12px);
  z-index: 50;
}
.popover::before {
  content: '';
  position: absolute; top: -7px; left: 24px;
  width: 12px; height: 12px;
  background: rgba(20,20,35,0.96);
  border-left: 1px solid var(--glass-border);
  border-top: 1px solid var(--glass-border);
  transform: rotate(45deg);
}
```

### Orientation segmented control
```css
.ori-control {
  display: flex; gap: 2px;
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--glass-border);
  border-radius: 4px;
  padding: 2px;
}
.ori-btn {
  flex: 1;
  background: transparent; border: 0;
  color: rgba(255,255,255,0.55);
  font-family: var(--mono); font-size: 11px;
  padding: 4px 0;
  border-radius: 3px;
  cursor: pointer;
  transition: all 100ms;
  line-height: 1;
}
.ori-btn:hover { color: var(--text-h); background: rgba(255,255,255,0.04); }
.ori-btn.active {
  background: var(--accent-bg);
  color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent-border);
}
```

## HTML Structures

### Strip block (per WLED device)
```html
<div class="device-block">
  <div class="device-head">
    <span class="device-name">TV Back Strip</span>
    <span class="device-meta">192.168.1.42 · 300 LEDs · 3 channels</span>
  </div>
  <div class="strip">
    <div class="zone selected" style="left:0%; width:23%; background:hsl(0,60%,60%);">Channel 1</div>
    <div class="zone"          style="left:23%; width:40%; background:hsl(137.5,60%,60%);">Channel 2</div>
    <div class="zone narrow"   style="left:63%; width:6%;  background:hsl(275,60%,60%);"></div>
    <div class="zone"          style="left:69%; width:31%; background:hsl(52.5,60%,60%);">Strip</div>
    <div class="handle" style="left:23%;"></div>
    <div class="handle" style="left:63%;"></div>
    <div class="handle" style="left:69%;"></div>
  </div>
  <div class="ticks">
    <span class="tick" style="left:0%;">0</span>
    <span class="tick" style="left:33.3%;">100</span>
    <span class="tick" style="left:66.6%;">200</span>
    <span class="tick" style="left:100%;">300</span>
  </div>
</div>
```

### Popover (per selected region)
```html
<div class="popover" style="top:calc(38% + 36% + 12px); left:42%;">
  <h4>
    <span><span style="color:var(--accent);">center</span> · 2 channels</span>
    <button class="close">×</button>
  </h4>
  <div class="lp-assignment">
    <div class="row1">
      <span class="chip" style="background:hsl(0,60%,60%);"></span>
      <span class="nm">Channel 1</span>
      <span class="dev">TV Back Strip</span>
    </div>
    <div class="ori-label">Sample axis · LEDs 0–69</div>
    <div class="ori-control">
      <button class="ori-btn active">auto</button>
      <button class="ori-btn">→</button>
      <button class="ori-btn">←</button>
      <button class="ori-btn">↓</button>
      <button class="ori-btn">↑</button>
    </div>
  </div>
</div>
```

## What to Avoid

| Tried in | Why rejected |
|---|---|
| **001-B (60px tall pill)** | Strip felt too dominant — vertical real-estate consumed when stacking 3+ devices. Inline labels were nice but didn't justify the extra height. |
| **001-C (stacked rail with floating boundary pills)** | Zones-as-tiles started reading as grouped buttons rather than a continuous range. Empty rail visualizes unassigned LEDs but that's a marginal benefit for a perpetual cost. |
| **003-B (dedicated right-side drawer)** | Permanent ~280px of canvas width regardless of selection state. Three columns (canvas / drawer / LightPanel) felt cramped at typical window widths. |
| **003-C (inline in LightPanel.Assignments)** | Eye has to leave the canvas to find the orientation control. Disconnected spatially. At narrower windows the LightPanel scrolls — selecting a region required scrolling to find the right Assignments row. |
| **Per-LED rendering** (rejected before sketching, CONTEXT.md D-05) | Zone-only rectangles are the correct unit. Per-LED cells fight the up-to-1200-LED fit-to-width constraint. |

## Origin
Synthesized from sketches: 001 (strip-canvas), 003 (region-props-placement)
Source files: `sources/001-strip-canvas/index.html`, `sources/003-region-props-placement/index.html`
Shared theme: `sources/themes/default.css`
