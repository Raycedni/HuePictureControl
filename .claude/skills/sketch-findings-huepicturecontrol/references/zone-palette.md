# Zone Palette

Color derivation for WLED zone fills (strip canvas) and LightPanel chips. **Algorithmic, deterministic, no persisted user color data** — see CONTEXT.md D-09, D-11.

## Design Decisions

### Formula

```js
function channelColor(index) {
  const hue = (index * 137.508) % 360;  // golden-angle spacing
  return `hsl(${hue}, 60%, 60%)`;
}
```

- **`index`** — per-device channel index, monotonically incrementing per CONTEXT.md D-10 (never reused on delete).
- **Hue step `137.508°`** — golden-angle constant. Guarantees adjacent indexes are maximally separated in hue space; same family doesn't repeat until index 12+.
- **Saturation `60%`** — bright enough to read on the dark `#0c0c14` ground, muted enough that fills don't fight the amber brand chrome (accent stays as the "primary" hue in the app).
- **Lightness `60%`** — high enough that `rgba(0,0,0,0.78)` zone-label text remains AA-readable on every index.

### Color values (first 12 indexes)

| idx | hue | hex (approx) | role |
|---|---|---|---|
| 0 | 0° | `#d97070` | red |
| 1 | 137.5° | `#7ad97a` | green |
| 2 | 275° | `#9c70d9` | violet |
| 3 | 52.5° | `#d9c870` | yellow |
| 4 | 190° | `#70c8d9` | cyan |
| 5 | 327.5° | `#d970a9` | magenta |
| 6 | 105° | `#a4d970` | lime |
| 7 | 242.5° | `#7080d9` | indigo |
| 8 | 20° | `#d99670` | orange |
| 9 | 157.5° | `#70d9af` | mint |
| 10 | 295° | `#bf70d9` | purple |
| 11 | 72.5° | `#cad970` | chartreuse |

### Per-device numbering, identical colors across devices

CONTEXT.md D-10 numbers channels **per device** (not globally), so Top/Mid/Bot on a second strip will reuse colors 0/1/2 from the first strip. **This is intentional** — channels are grouped under their device in LightPanel (D-12), so the visual repetition reads as "same index" within a device-grouped section rather than as collision.

### Chip + zone consistency

The LightPanel chip and the strip zone fill **must call the same `channelColor()` function with the same `(device_id, channel_index)` input** so they remain in sync without DB round-trip. Don't store the resolved color anywhere.

| Surface | Element | Color source |
|---|---|---|
| Settings paint canvas | `.zone` `background` | `channelColor(idx)` at render time |
| LightPanel | `.lp-row .chip` | same |
| Region popover | `.lp-assignment .chip` | same |

### Brand vs derived: division of labor

| Brand color (`var(--accent)`, `#e8a000`) is used for | Derived palette is used for |
|---|---|
| Selection outlines, popover beak, segmented-control active state, primary buttons, section accents, brand chip in LightPanel header | **Only** zone fills + matching chips |

The brand is the chrome; derived colors are the data. Keep the boundary crisp.

## CSS / TSX patterns

### Inline style (sketch idiom — fine for prototypes)
```html
<div class="zone" style="background:hsl(0,60%,60%);">Channel 1</div>
```

### React/TS pattern (recommended for the real implementation)
```tsx
// src/utils/wled-palette.ts
export function channelColor(index: number): string {
  const hue = (index * 137.508) % 360;
  return `hsl(${hue}, 60%, 60%)`;
}

// usage
<div
  className="zone"
  style={{ background: channelColor(channel.index) }}
>
  {channel.name}
</div>
```

### CSS custom-property pattern (alternative — if you want named tokens)
```css
.zone[data-idx="0"]  { background: hsl(0,     60%, 60%); }
.zone[data-idx="1"]  { background: hsl(137.5, 60%, 60%); }
/* … through 11, then wrap */
```
Drop this approach in favor of the inline-style or the helper-function approach unless the project already uses data-attribute palette patterns.

## What to Avoid

| Tried in | Why rejected |
|---|---|
| **002-B (amber tonal ramp)** | Stayed beautifully in-brand but ran out of headroom past 5 channels. Adjacent zones at indexes 4–5 became hard to distinguish. The TV Back Strip stress case (6 channels) lost contrast at the right end. |
| **002-C (warm/cool alternation)** | Adjacent contrast was strong (guaranteed by family alternation) and Channel 1 = amber felt intentional, but the rule isn't mathematically clean — needs hand-curated 5–10 colors per family or a generator. Brittle. |
| **User-settable colors** (rejected before sketching, CONTEXT.md D-09) | UI rendering concern, not user data. No precedent in the existing Hue panel either. |
| **`wled_channels.color` column persistence** (deprecated, CONTEXT.md D-09) | Phase 17 created the column; Phase 19 leaves it dormant. UI ignores it. A future cleanup phase can drop it. |
| **Storing the resolved color in state** | `channelColor()` is pure — recompute on render. Saves a DB column and stays in sync if the formula ever evolves. |

## Origin
Synthesized from sketch: 002 (zone-palette)
Source file: `sources/002-zone-palette/index.html`
Shared theme: `sources/themes/default.css`
