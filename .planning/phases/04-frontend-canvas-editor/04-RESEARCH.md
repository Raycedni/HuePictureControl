# Phase 4: Frontend Canvas Editor - Research

**Researched:** 2026-03-24
**Domain:** React canvas UI — Konva.js polygon editor, Zustand state, shadcn/ui + Tailwind CSS v4, WebSocket live preview
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Auto-generated regions (from Phase 3.1) are fully editable — no distinction between auto and manual once created
- Re-running auto-map replaces ALL regions (auto and manual) — fresh start mental model
- Regions can exist without a light assignment — user draws first, assigns later
- Unassigned regions are ignored during streaming
- Two drawing modes: rectangle (click-drag) and freeform polygon (click-to-place vertices, click first vertex to close)
- Toolbar above canvas: [Rectangle] [Polygon] [Select] [Delete]
- Editing: click region to select (shows vertex handles), drag vertices to reshape, drag region body to move, Delete key or button to remove
- Region-to-light assignment: drag a light from the side panel onto a region on the canvas
- Each region shows the assigned light name as a small label inside it
- Auto-save on every change — no manual save button; every create/edit/delete/assign immediately persists to backend
- WebSocket binary JPEG at 10-15 fps for smooth live preview on the canvas
- Live sampled color overlay: each region polygon fills with the actual color being sent to its light (semi-transparent) — updates with each frame (UI-06)
- WebSocket preview only connects when editor tab is visible — disconnects when switching away
- Preview available without streaming active — camera feed shows even when not streaming to lights (backend needs preview-only mode)
- Three tabs: Setup | Preview | Editor
- PreviewPage (Phase 3.1) stays as the simple auto-map view
- Editor is the full Konva.js canvas with drawing tools and light assignment
- Layout: canvas left (~70% width), light panel right (~30%), status bar at bottom
- Status bar is global — visible on all tabs, always shows streaming state, FPS, latency
- Toolbar strip above canvas: drawing mode toggles

### Claude's Discretion
- Konva.js layer architecture (preview layer, region layer, selection handles layer)
- Zustand store structure and state management approach
- shadcn/ui + Tailwind CSS v4 integration details
- WebSocket reconnection logic for preview stream
- Debounce strategy for auto-save during vertex dragging
- Exact toolbar and panel component hierarchy

### Deferred Ideas (OUT OF SCOPE)
- Per-light color preview widgets showing current output color (v2 requirement AUI-04)
- Preset region layouts / grid templates (v2 requirement AUI-01)
- Import/export configuration as JSON (v2 requirement AUI-02)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| REGN-01 | User can draw freeform polygon regions on a camera snapshot in the web UI | Konva.js `Line` with `closed: true` + click-to-place vertex pattern |
| REGN-02 | User can edit existing regions (move vertices, drag region, delete) | Konva `Circle` anchors at vertices + `Group` draggable for body; `hitFunc` for hit areas |
| REGN-03 | User can assign each region to a Hue light or gradient segment channel | HTML5 dragstart from side panel + `stage.setPointersPositions(e)` / `getPointerPosition()` |
| REGN-04 | Region coordinates stored as normalized [0..1] values | Already complete; divide pixel coords by Stage width/height before storing |
| REGN-05 | Region-to-light mappings persist across restarts | Already complete via SQLite; new CRUD endpoints needed |
| REGN-06 | Live camera preview available in the web UI via WebSocket | `/ws/preview` backend endpoint; `URL.createObjectURL(blob)` → `use-image` hook in Konva |
| UI-01 | Web UI accessible without authentication on the local network | No auth required (no changes) |
| UI-03 | Global start/stop toggle controls the capture and streaming loop | Extend existing `startStreaming`/`stopStreaming` API calls; keep in global status bar |
| UI-04 | Real-time status display shows FPS, latency, bridge connection state, and errors | `/ws/status` WebSocket already exists; status bar component consuming it |
| UI-05 | Light discovery panel shows all available lights with their type and segment count | `GET /api/hue/lights` exists; `LightResponse` has id/name/type (segment count needs backend extension) |
| UI-06 | Region canvas shows semi-transparent color overlay indicating what each region is "seeing" | Backend streams sampled RGB per region via `/ws/preview` frame metadata or separate channel; Konva `Line` fill updated per frame |
</phase_requirements>

---

## Summary

Phase 4 replaces the existing `<img>` snapshot polling with a full Konva.js canvas editor, adds Zustand for cross-component state, and introduces shadcn/ui + Tailwind CSS v4 for a consistent design system. The core interaction model is a three-layer Konva Stage: a live JPEG preview layer updated from a WebSocket binary stream at 10–15 fps, a region polygon layer with interactive vertex handles and drag-to-move, and a transient drawing-in-progress layer. Light assignment uses native HTML5 drag-and-drop from the side panel onto the Konva Stage, resolved to canvas coordinates via `stage.setPointersPositions(e)` + `getPointerPosition()`.

The backend requires three new additions: a `/ws/preview` WebSocket endpoint that pushes binary JPEG frames from `LatestFrameCapture` in a loop (separate from the DTLS streaming path), new REST endpoints for region CRUD (`PUT /api/regions/{id}`, `DELETE /api/regions/{id}`, `POST /api/regions` for manual creation) with a `light_id` field, and extension of the `LightResponse` model to include `segment_count`. The existing `light_assignments` table and `regions` table already exist and can support these additions with minimal migration.

The biggest execution risk is the vertex-anchor + region-body drag interaction in Konva: both require `draggable` on different nodes, and hit area overlap causes event confusion. The verified pattern wraps each polygon in a `Group` (body drag), adds `Circle` anchor nodes for vertex drag, and uses `hitFunc` on the polygon fill to expand its hit area. Auto-save during vertex drag must be debounced (300–500 ms after `dragend`) to avoid hammering the backend on every pixel move.

**Primary recommendation:** Install `react-konva@^19.2.3 konva zustand use-image` first; scaffold the three-layer Stage with a static test polygon before wiring any WebSocket or API calls. This validates the interaction model before adding complexity.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react-konva | ^19.2.3 | React bindings for Konva.js canvas | Version matches React 19 peer dep; official react-konva versioning mirrors React major |
| konva | ^9.x | Canvas rendering, shape primitives, drag/drop | Underlies react-konva; direct usage needed for image loading patterns |
| zustand | ^5.0.12 | Cross-component state (regions, selection, drawing mode) | Minimal boilerplate, `useSyncExternalStore` backend, no provider required |
| tailwindcss | ^4.x | Utility CSS | CSS-first config (`@import "tailwindcss"`), no `tailwind.config.js` |
| @tailwindcss/vite | ^4.x | Vite plugin for Tailwind v4 | Required for Vite projects using Tailwind v4 |
| shadcn/ui | latest CLI | Headless component primitives (Button, Badge, etc.) | Already updated for Tailwind v4 + React 19; generated into `src/components/ui/` |
| use-image | ^1.x | React hook for loading image URLs into Konva Image | Official konvajs companion; handles async load + re-render |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tw-animate-css | latest | CSS animations for shadcn/ui | Replaces deprecated `tailwindcss-animate` in Tailwind v4 new projects |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| react-konva | Fabric.js, plain Canvas API | Fabric.js has larger bundle; plain Canvas requires full React lifecycle management |
| Zustand | React Context + useReducer | Context causes full subtree re-renders on every state change; unacceptable at 10–15 fps update rate |
| shadcn/ui | Radix UI bare | shadcn gives styled defaults; saves time on Toolbar, Badge, Panel layout |
| HTML5 DnD for light assign | @dnd-kit | HTML5 DnD is sufficient for the one drag direction (panel → canvas); @dnd-kit adds 10 KB for no gain |

**Installation:**
```bash
npm install react-konva konva zustand use-image
npm install tailwindcss @tailwindcss/vite
npx shadcn@latest init
npx shadcn@latest add button badge separator scroll-area
```

---

## Architecture Patterns

### Recommended Project Structure
```
Frontend/src/
├── api/
│   ├── regions.ts        # existing + new CRUD (createRegion, updateRegion, deleteRegion, assignLight)
│   └── hue.ts            # existing (getLights already present)
├── components/
│   ├── ui/               # shadcn-generated components (button, badge, etc.)
│   ├── PairingFlow.tsx   # unchanged
│   ├── PreviewPage.tsx   # unchanged (Phase 3.1)
│   ├── StatusBar.tsx     # NEW: global WS status consumer
│   ├── EditorPage.tsx    # NEW: layout shell (canvas 70% + panel 30%)
│   ├── EditorCanvas.tsx  # NEW: Konva Stage + all three layers
│   ├── DrawingToolbar.tsx# NEW: mode buttons above canvas
│   └── LightPanel.tsx    # NEW: draggable light list
├── store/
│   ├── useRegionStore.ts # Zustand: regions[], selectedId, drawingMode
│   └── useStatusStore.ts # Zustand: fps, latency, bridgeState from /ws/status
├── hooks/
│   ├── usePreviewWS.ts   # manages /ws/preview connection lifecycle
│   └── useStatusWS.ts    # manages /ws/status connection lifecycle
└── App.tsx               # extend to 3 tabs, add StatusBar below tabs
```

### Pattern 1: Three-Layer Konva Stage
**What:** Separate layers by update frequency — preview updates at 10–15 fps, regions update on user interaction, handles/cursor layer updates on selection.
**When to use:** Always. Max 3–5 layers in Konva; more degrades performance.

```typescript
// Source: https://konvajs.org/docs/performance/Layer_Management.html
<Stage width={canvasW} height={canvasH}>
  {/* Layer 0: live JPEG preview — redraws every WS frame */}
  <Layer listening={false}>
    <Image image={previewImage} width={canvasW} height={canvasH} />
  </Layer>

  {/* Layer 1: region polygons + color overlays — redraws on region change */}
  <Layer>
    {regions.map(r => <RegionPolygon key={r.id} region={r} />)}
    {drawingInProgress && <DrawingPreview points={currentPoints} />}
  </Layer>

  {/* Layer 2: vertex anchors for selected region — redraws on drag */}
  <Layer>
    {selectedRegion && <VertexHandles region={selectedRegion} />}
  </Layer>
</Stage>
```

**CRITICAL:** Set `listening={false}` on the preview layer — it never needs events and this avoids hit-detection cost on the highest-frequency layer.

### Pattern 2: Polygon Drawing — Click-to-Place Vertices
**What:** Each click on the Stage in "polygon" mode appends a vertex. Clicking within ~10px of the first vertex closes the polygon.

```typescript
// Source: https://konvajs.org/docs/shapes/Line_-_Polygon.html
// In-progress line (open)
<Line points={flatPoints} stroke="white" strokeWidth={2} dash={[4, 4]} />
// First vertex close-target indicator
<Circle x={firstPt.x} y={firstPt.y} radius={8} fill="rgba(255,255,255,0.5)" />

// Stage onClick handler (polygon mode)
function handleStageClick(e: KonvaEventObject<MouseEvent>) {
  const pos = stageRef.current!.getPointerPosition()!
  if (isNearFirst(pos, currentPoints[0], 10)) {
    commitPolygon(currentPoints)   // normalize and save
  } else {
    setCurrentPoints(prev => [...prev, pos])
  }
}
```

### Pattern 3: Vertex Anchor + Body Drag (the tricky one)
**What:** Each selected region renders as a Konva `Group` (draggable for body) with a `Line` (closed polygon fill) and `Circle` anchors at each vertex.

```typescript
// Source: https://konvajs.org/docs/sandbox/Modify_Curves_with_Anchor_Points.html
// and community patterns from https://github.com/definite2/kanva-draggable-polygon
function RegionPolygon({ region, onUpdate }) {
  const [pts, setPts] = useState(denormalize(region.polygon, stageW, stageH))

  return (
    <Group
      draggable
      onDragEnd={e => {
        const dx = e.target.x(), dy = e.target.y()
        const moved = pts.map(([x, y]) => [x + dx, y + dy])
        e.target.position({ x: 0, y: 0 })
        setPts(moved)
        onUpdate(normalize(moved, stageW, stageH))
      }}
    >
      <Line
        points={pts.flat()}
        closed
        fill={assignedColor ?? 'rgba(255,255,255,0.2)'}
        stroke="white"
        strokeWidth={2}
        hitFunc={(ctx, shape) => {
          // expand hit area by 4px on each side
          ctx.beginPath()
          ctx.rect(-4, -4, shape.width() + 8, shape.height() + 8)
          ctx.closePath()
          ctx.fillStrokeShape(shape)
        }}
      />
      {isSelected && pts.map(([x, y], i) => (
        <Circle key={i} x={x} y={y} radius={6} fill="white" draggable
          onDragMove={e => {
            const next = [...pts]
            next[i] = [e.target.x(), e.target.y()]
            setPts(next)
          }}
          onDragEnd={() => onUpdate(normalize(pts, stageW, stageH))}
        />
      ))}
    </Group>
  )
}
```

**Key insight:** After `Group` drag ends, reset `e.target.position({ x: 0, y: 0 })` and bake the offset into the point coordinates. Otherwise Group position accumulates independently of the points array.

### Pattern 4: WebSocket Binary JPEG → Konva Image
**What:** WebSocket receives binary JPEG, creates an `ObjectURL`, feeds it to a stateful `<Image>` via `use-image`-style loading.

```typescript
// Source: https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/binaryType
// and https://konvajs.org/docs/react/Images.html
function usePreviewWS(enabled: boolean) {
  const [imgSrc, setImgSrc] = useState<string | null>(null)
  const prevUrl = useRef<string | null>(null)

  useEffect(() => {
    if (!enabled) return
    const ws = new WebSocket(`ws://${location.host}/ws/preview`)
    ws.binaryType = 'blob'
    ws.onmessage = (e) => {
      const url = URL.createObjectURL(e.data as Blob)
      setImgSrc(url)
      if (prevUrl.current) URL.revokeObjectURL(prevUrl.current)  // prevent memory leak
      prevUrl.current = url
    }
    return () => { ws.close(); if (prevUrl.current) URL.revokeObjectURL(prevUrl.current) }
  }, [enabled])

  return imgSrc
}

// In EditorCanvas:
const [previewImage] = useImage(imgSrc ?? '')
// <Image image={previewImage} width={canvasW} height={canvasH} />
```

### Pattern 5: Light Drag-to-Assign (HTML5 DnD to Konva)
**What:** Drag a light row from the panel (HTML element). Drop on the Stage (Konva canvas element). Resolve to canvas coordinates via Konva's pointer API.

```typescript
// Source: https://konvajs.org/docs/react/Drop_Image.html
// LightPanel row:
<div draggable onDragStart={e => e.dataTransfer.setData('lightId', light.id)}>
  {light.name}
</div>

// Wrapping div around <Stage>:
<div
  onDragOver={e => e.preventDefault()}
  onDrop={e => {
    e.preventDefault()
    const lightId = e.dataTransfer.getData('lightId')
    stageRef.current!.setPointersPositions(e)
    const pos = stageRef.current!.getPointerPosition()!
    const hit = findRegionAt(pos, regions)   // point-in-polygon test
    if (hit) assignLight(hit.id, lightId)
  }}
>
  <Stage ref={stageRef} ...>
```

**CRITICAL:** `stage.setPointersPositions(e)` MUST be called before `getPointerPosition()` when the event originates from a DOM drag (not a Konva event). Without it, pointer position is stale.

### Pattern 6: Debounced Auto-Save During Drag
**What:** Debounce backend persistence calls by 400 ms on `dragend` events; apply immediately on `dragend` completion but not during `dragmove`.

```typescript
// Source: https://github.com/pmndrs/zustand (discussions/696 on transient updates)
const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

function scheduleSave(region: Region) {
  if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
  saveTimeoutRef.current = setTimeout(() => updateRegionAPI(region), 400)
}

// Call scheduleSave on dragEnd (not dragMove)
```

### Pattern 7: Zustand Store Design
**What:** Two focused stores. `useRegionStore` owns the editable canvas state. `useStatusStore` owns the live streaming metrics from `/ws/status`.

```typescript
// Source: https://tkdodo.eu/blog/working-with-zustand
interface RegionStore {
  regions: Region[]
  selectedId: string | null
  drawingMode: 'select' | 'rectangle' | 'polygon'
  drawingPoints: [number, number][]
  // actions
  setRegions: (r: Region[]) => void
  addRegion: (r: Region) => void
  updateRegion: (id: string, patch: Partial<Region>) => void
  deleteRegion: (id: string) => void
  setSelectedId: (id: string | null) => void
  setDrawingMode: (m: RegionStore['drawingMode']) => void
  appendPoint: (pt: [number, number]) => void
  commitDrawing: () => void
}

interface StatusStore {
  fps: number
  latency: number
  bridgeState: string
  error: string | null
  setMetrics: (m: Partial<StatusStore>) => void
}
```

Expose atomic selectors, not object slices, to avoid spurious re-renders:
```typescript
const selectedId = useRegionStore(s => s.selectedId)   // stable string
const regions = useRegionStore(s => s.regions)          // array — subscribe carefully
```

### Anti-Patterns to Avoid
- **Calling `layer.draw()` manually in react-konva:** react-konva manages redraws automatically via React reconciliation. Only manual Konva imperative code needs explicit `layer.draw()`.
- **Storing pixel coordinates in the Zustand store:** Always store normalized [0..1]. Convert to pixels inside the canvas component, convert back on save.
- **Creating more than 3 Konva layers:** Konva documentation says max 3–5 layers. Adding a fourth for every interaction type degrades performance.
- **Not revoking ObjectURLs from WebSocket frames:** Each `URL.createObjectURL(blob)` holds a memory reference. Revoke the previous URL on every new frame.
- **Forgetting `e.target.position({x:0, y:0})` after Group drag:** Without this reset, Group position accumulates separately from the points array, causing misalignment on subsequent drags.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Canvas rendering | Custom canvas2d component | react-konva | Layer management, hit detection, event system — 1000+ lines of complexity |
| Image URL loading in Konva | Custom useEffect image loader | `use-image` hook | Handles race conditions, reloads, SSR safely |
| CSS component primitives | Custom styled div components | shadcn/ui | Accessible, Tailwind v4-ready, matches project requirement for consistent UI |
| Point-in-polygon hit test | Custom winding number algorithm | Konva's built-in hit detection via `getIntersection()` or `findOne()` | Konva already has canvas-based hit detection per shape |
| WebSocket reconnection logic | Custom exponential backoff | Simple `onclose` → `setTimeout` reconnect | Overkill for a local-network tool; simple retry is sufficient |

**Key insight:** Konva's hit detection works on the rendered canvas pixels — polygon hit detection is a solved problem inside Konva shapes, not something to implement separately.

---

## Common Pitfalls

### Pitfall 1: Group Position Drift After Drag
**What goes wrong:** After dragging a polygon Group, vertex circles appear displaced from the polygon line because the Group's `(x, y)` offset accumulates independently.
**Why it happens:** Konva stores Group position as a transform offset. Dragging the Group changes `group.x()` and `group.y()`, but child node coordinates haven't changed.
**How to avoid:** In `onDragEnd`, read `e.target.x()` and `e.target.y()`, bake the offset into the points array, then call `e.target.position({ x: 0, y: 0 })`.
**Warning signs:** Vertex anchors drift visually after first drag.

### Pitfall 2: Vertex Click Intercepted by Region Body
**What goes wrong:** Clicking a vertex anchor Circle triggers the underlying Line's `onClick` first (deselection or region click), making vertex selection unreliable.
**Why it happens:** Both the Line and Circle are listening for events. The Circle sits on top but both fire.
**How to avoid:** Use `e.cancelBubble = true` (or `e.evt.stopPropagation()`) in Circle event handlers to prevent the event from propagating to the parent Group or Line.
**Warning signs:** Selection flickers when clicking near vertices.

### Pitfall 3: Stale Pointer Position on HTML5 Drop
**What goes wrong:** `stage.getPointerPosition()` returns the position from the last mouse event, not the drop position.
**Why it happens:** HTML5 `drop` events are DOM events, not Konva events. Konva hasn't updated its internal pointer state.
**How to avoid:** Always call `stage.setPointersPositions(e)` before `getPointerPosition()` when handling DOM drag events.
**Warning signs:** Dropped lights always assign to wrong region, or always assign to the same region.

### Pitfall 4: ObjectURL Memory Leak
**What goes wrong:** Memory usage grows at ~5 KB/frame × 10 fps = ~50 KB/s from Blob URLs that are never revoked.
**Why it happens:** Each `URL.createObjectURL()` registers a reference in the browser until explicitly revoked.
**How to avoid:** Track the previous URL in a `useRef`, revoke it before creating a new one on every WS message.
**Warning signs:** Browser memory climbs continuously while editor is open.

### Pitfall 5: Tailwind v4 CSS-First Config
**What goes wrong:** Developer adds `tailwind.config.js` expecting it to work as in v3. Configuration silently has no effect.
**Why it happens:** Tailwind v4 is entirely CSS-first. Config file is not read.
**How to avoid:** All theme customization goes in the CSS file under `@theme`. Run `npx shadcn@latest init` which sets this up correctly.
**Warning signs:** Custom colors or spacing values don't apply to shadcn components.

### Pitfall 6: Preview WebSocket Connects on All Tabs
**What goes wrong:** Camera frames stream even when user is on Setup or Preview tab, wasting bandwidth and backend resources.
**Why it happens:** WebSocket is opened in a global effect not tied to tab visibility.
**How to avoid:** Pass `enabled` flag to `usePreviewWS` based on active tab. Open WS connection only when `page === 'editor'`.
**Warning signs:** Backend logs show `/ws/preview` connection from the start, not just when editor tab is selected.

### Pitfall 7: react-konva and React 19 Version Mismatch
**What goes wrong:** npm install fails with peer dependency error or canvas doesn't render.
**Why it happens:** react-konva versions 18.x require React 18; version 19.x requires React 19.
**How to avoid:** Install `react-konva@^19.2.3` — the major version mirrors React's major version. This project uses React 19.2.4.
**Warning signs:** `npm install` shows peer dependency conflict for react version.

---

## Code Examples

Verified patterns from official sources:

### Closed Polygon Shape
```typescript
// Source: https://konvajs.org/docs/shapes/Line_-_Polygon.html
<Line
  points={[73, 192, 73, 160, 340, 23, 500, 109, 499, 139, 342, 93]}
  fill="rgba(100, 200, 255, 0.3)"
  stroke="white"
  strokeWidth={2}
  closed={true}
/>
```

### Konva Image from URL (use-image pattern)
```typescript
// Source: https://konvajs.org/docs/react/Images.html
import useImage from 'use-image'

function LivePreview({ src }: { src: string }) {
  const [image] = useImage(src)
  return <Image image={image} width={640} height={480} />
}
```

### HTML5 Drop onto Konva Stage
```typescript
// Source: https://konvajs.org/docs/react/Drop_Image.html (adapted for light assign)
<div
  onDragOver={e => e.preventDefault()}
  onDrop={e => {
    e.preventDefault()
    stageRef.current!.setPointersPositions(e)  // REQUIRED before getPointerPosition
    const pos = stageRef.current!.getPointerPosition()!
    // ... find region at pos, assign light
  }}
>
  <Stage ref={stageRef} ... />
</div>
```

### Zustand Store (minimal)
```typescript
// Source: https://github.com/pmndrs/zustand
import { create } from 'zustand'

const useRegionStore = create<RegionStore>((set) => ({
  regions: [],
  selectedId: null,
  drawingMode: 'select',
  setRegions: (regions) => set({ regions }),
  updateRegion: (id, patch) =>
    set(s => ({ regions: s.regions.map(r => r.id === id ? { ...r, ...patch } : r) })),
  deleteRegion: (id) =>
    set(s => ({ regions: s.regions.filter(r => r.id !== id) })),
}))
```

### shadcn/ui Init (Vite + Tailwind v4)
```bash
# Source: https://ui.shadcn.com/docs/installation/vite
npx shadcn@latest init -t vite
# Handles: @tailwindcss/vite plugin, path aliases, components.json
```

---

## Backend New Endpoints Required

These are NOT frontend research — they are backend gaps discovered during frontend research.

| Endpoint | Method | Purpose | Notes |
|----------|--------|---------|-------|
| `POST /api/regions` | POST | Create a manually drawn region | Returns `{id, name, polygon, order_index}` |
| `PUT /api/regions/{id}` | PUT | Update polygon coords + light assignment | Body: `{polygon?, light_id?, name?}` |
| `DELETE /api/regions/{id}` | DELETE | Remove a region | Returns 204 |
| `/ws/preview` | WebSocket | Push binary JPEG frames at 10–15 fps | Reads from `LatestFrameCapture`; runs independently of DTLS streaming |

The `light_id` field needs to be added to the `regions` table (nullable FK or plain text). The `LightResponse` model needs a `segment_count` field for the light panel (UI-05 requires "type and segment count").

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `tailwind.config.js` | CSS-first `@theme` in `.css` | Tailwind v4 (2024) | No JS config file; all theming in CSS |
| `tailwindcss-animate` | `tw-animate-css` | shadcn/ui + Tailwind v4 migration | Different import, same animation classes |
| `forwardRef` on shadcn components | Direct prop access, `data-slot` attrs | React 19 / shadcn update 2024–25 | Simpler component APIs, direct styling |
| Snapshot polling (`setInterval`) | WebSocket binary JPEG | This phase | 10–15 fps vs ~0.5 fps, low latency |

**Deprecated/outdated:**
- `tailwindcss-animate`: Replaced by `tw-animate-css` in new Tailwind v4 projects
- Tailwind v3 `@layer base` + HSL variables: Now uses `@theme inline` + OKLCH

---

## Open Questions

1. **`segment_count` on `LightResponse`**
   - What we know: Current `LightResponse` has `id`, `name`, `type` only. UI-05 requires segment count.
   - What's unclear: Whether `list_lights` in `hue_client.py` already fetches segment data from the bridge API.
   - Recommendation: Check `Backend/services/hue_client.py` `list_lights` implementation during planning. If segment data is in the API response, add `segment_count` to `LightResponse`; otherwise default to `1` for non-gradient lights.

2. **UI-06 sampled color overlay delivery mechanism**
   - What we know: User wants region polygons filled with the actual color being sent to the light (semi-transparent, updated per frame).
   - What's unclear: How does the frontend receive per-region RGB values? Options: (a) embed in `/ws/preview` message as JSON header before JPEG bytes, (b) separate `/ws/colors` endpoint, (c) include in `/ws/status` at 1 Hz (too slow).
   - Recommendation: Simplest approach — embed a JSON prefix before the JPEG binary in `/ws/preview` frames (e.g., `{colors: {regionId: [r,g,b]}}` as a text frame, followed by binary JPEG). Keep as separate text + binary messages on same WebSocket.

3. **Rectangle drawing mode implementation**
   - What we know: User wants both rectangle and polygon modes. Rectangle is click-drag.
   - What's unclear: Whether to implement rectangle as a special 4-vertex polygon (simplest) or as a separate `Konva.Rect` shape.
   - Recommendation: Implement as 4-vertex polygon (normalized corners). Consistent data model, no special cases downstream.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest 4.x + @testing-library/react 16.x |
| Config file | `Frontend/vitest.config.ts` (exists) |
| Quick run command | `cd Frontend && npm test` |
| Full suite command | `cd Frontend && npm test` |

Backend tests: pytest with asyncio_mode=auto — `cd Backend && pytest`

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REGN-01 | Polygon drawing state machine (click-to-append, close-on-first) | unit | `npm test -- useRegionStore` | ❌ Wave 0 |
| REGN-02 | Vertex drag normalizes coordinates correctly | unit | `npm test -- useRegionStore` | ❌ Wave 0 |
| REGN-03 | Light assign updates region store | unit | `npm test -- useRegionStore` | ❌ Wave 0 |
| REGN-04 | Normalize/denormalize round-trips | unit | `npm test -- geometry` | ❌ Wave 0 |
| REGN-06 | Preview WS hook connects only when enabled | unit | `npm test -- usePreviewWS` | ❌ Wave 0 |
| UI-03 | Start/stop toggle calls correct API | unit | `npm test -- EditorPage` | ❌ Wave 0 |
| UI-04 | Status store updates from WS message | unit | `npm test -- useStatusStore` | ❌ Wave 0 |
| UI-05 | Light panel renders lights from API | unit | `npm test -- LightPanel` | ❌ Wave 0 |
| Backend: PUT /api/regions/{id} | Updates polygon + light assignment in DB | unit | `cd Backend && pytest tests/test_regions_router.py` | ❌ Wave 0 |
| Backend: DELETE /api/regions/{id} | Removes region row | unit | `cd Backend && pytest tests/test_regions_router.py` | ❌ Wave 0 |
| Backend: /ws/preview | Sends binary JPEG frames | unit | `cd Backend && pytest tests/test_preview_ws.py` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd Frontend && npm test` + `cd Backend && pytest tests/test_regions_router.py -x`
- **Per wave merge:** `cd Frontend && npm test && cd Backend && pytest`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `Frontend/src/store/useRegionStore.test.ts` — covers REGN-01, REGN-02, REGN-03
- [ ] `Frontend/src/store/useStatusStore.test.ts` — covers UI-04
- [ ] `Frontend/src/hooks/usePreviewWS.test.ts` — covers REGN-06
- [ ] `Frontend/src/utils/geometry.test.ts` — covers REGN-04 (normalize/denormalize)
- [ ] `Backend/tests/test_preview_ws.py` — covers /ws/preview binary streaming
- [ ] `Backend/tests/test_regions_router.py` — extend existing file (PUT, DELETE, POST)
- [ ] Zustand install: `cd Frontend && npm install zustand` — if not yet installed

---

## Sources

### Primary (HIGH confidence)
- [konvajs.org/docs/react](https://konvajs.org/docs/react/index.html) — Stage/Layer/Shape setup, use-image pattern, DnD with canvas
- [konvajs.org/docs/performance/Layer_Management](https://konvajs.org/docs/performance/Layer_Management.html) — 3-layer architecture, listening(false)
- [konvajs.org/docs/shapes/Line_-_Polygon](https://konvajs.org/docs/shapes/Line_-_Polygon.html) — `closed: true` polygon API
- [konvajs.org/docs/react/Drop_Image](https://konvajs.org/docs/react/Drop_Image.html) — `setPointersPositions` + `getPointerPosition` for HTML5 drop
- [konvajs.org/docs/sandbox/Drop_DOM_Element](https://konvajs.org/docs/sandbox/Drop_DOM_Element.html) — DOM drag to canvas pattern
- [ui.shadcn.com/docs/tailwind-v4](https://ui.shadcn.com/docs/tailwind-v4) — shadcn Tailwind v4 migration, `@theme inline`, OKLCH, React 19 forwardRef removal
- [ui.shadcn.com/docs/installation/vite](https://ui.shadcn.com/docs/installation/vite) — `npx shadcn@latest init -t vite`
- [github.com/pmndrs/zustand releases](https://github.com/pmndrs/zustand/releases) — v5.0.12 latest stable
- [tkdodo.eu/blog/working-with-zustand](https://tkdodo.eu/blog/working-with-zustand) — atomic selectors, separate actions, small stores
- [MDN WebSocket.binaryType](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/binaryType) — `arraybuffer` vs `blob`, ObjectURL pattern
- Existing codebase: `Frontend/package.json` — React 19.2.4, Vite 8.x, Vitest 4.x
- Existing codebase: `Backend/routers/regions.py`, `Backend/database.py` — current schema gaps

### Secondary (MEDIUM confidence)
- [npmjs.com/package/react-konva](https://www.npmjs.com/package/react-konva) — v19.2.3 latest, peer dep React ^19
- [github.com/konvajs/use-image](https://github.com/konvajs/use-image) — maintained through 2025, React 19 compatible
- WebSearch verified: shadcn/ui all components updated for Tailwind v4 + React 19; `tw-animate-css` replaces `tailwindcss-animate`

### Tertiary (LOW confidence)
- Community pattern for Group position reset after drag (multiple GitHub discussions, not in official docs) — validate by prototyping

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — npm versions verified via search, official docs checked for compatibility
- Architecture: HIGH — layer pattern from official docs; store pattern from official Zustand blog
- Pitfalls: MEDIUM — Group position drift and vertex event bubbling from community sources; WebSocket memory leak from MDN
- Backend gaps: HIGH — identified by direct inspection of existing codebase

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (30 days — stack is stable; shadcn moves fast but CLI handles updates)
