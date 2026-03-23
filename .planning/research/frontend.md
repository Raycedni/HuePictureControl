# Frontend Research: HuePictureControl

**Domain:** Real-time ambient lighting config UI with canvas region drawing
**Researched:** 2026-03-23
**Overall confidence:** MEDIUM-HIGH

---

## 1. Framework Comparison: React vs Vue vs Svelte

### Evaluation Criteria

For this project the critical axes are:
- Canvas library ecosystem (does react-konva/vue-konva/svelte-konva exist and is it maintained?)
- Real-time WebSocket rendering performance
- State management story for region-to-light mappings
- Ecosystem maturity (TypeScript support, tooling, community size)

### React

**Canvas:** `react-konva` (19.2.3, published ~3 weeks ago as of research date) is the first-class Konva binding. Largest community of canvas annotation tutorials; multiple polygon annotation examples exist. All Konva shapes and events are exposed declaratively.

**Real-time:** React's Virtual DOM introduces overhead per frame, but for this use case the hot path is drawing JPEG frames to a raw `<canvas>` element — React is not in that loop at all. WebSocket handlers update React state for region data and color readbacks; this happens at 1-5 Hz, not 30 fps, so VDOM overhead is irrelevant.

**State management:** Zustand is the 2025 default for medium-complexity apps. A single store holding `{ regions: Region[], lights: Light[], mappings: Mapping[] }` is straightforward. No boilerplate; ~0.8 KB.

**Ecosystem:** Largest ecosystem of any framework. shadcn/ui + Tailwind v4 provides a production-quality panel/sidebar/list component set with zero design work. TypeScript support is first-class. Vite + React template is the canonical starting point.

**Weaknesses:** Bundle size (~156 KB for React itself) is larger than Svelte; irrelevant for a desktop config UI served locally.

**Confidence:** HIGH — well-documented, validated across annotation tool use case specifically.

### Svelte 5

**Canvas:** `svelte-konva` is a first-class, officially maintained Konva binding. It was rewritten for Svelte 5 runes as of 2024-2025 and is runes-only. Works with SvelteKit (with SSR caveat: must lazy-import).

**Real-time:** Svelte compiles to direct DOM mutations, no VDOM. Benchmark advantage over React is real (3x smaller bundles, ~60% faster renders) but this is the wrong problem to optimize for: rendering a MJPEG stream is a canvas draw-call problem, not a framework reactivity problem.

**State management:** Svelte 5 runes (`$state`, `$derived`) replace stores. For a config UI with a moderate number of entities, runes are elegant but the ecosystem of patterns is younger than React's. No equivalent of Zustand devtools for debugging mapping state.

**Ecosystem:** Smaller community than React. UI component library story is weaker: Svelte-specific shadcn ports exist but are less complete. Most Hue / smart-home UI tutorials target React.

**Confidence:** MEDIUM — svelte-konva is healthy, but fewer annotation-tool reference implementations exist for Svelte.

### Vue 3

**Canvas:** `vue-konva` is the official Konva binding for Vue; maintained, but weekly downloads are lower than `react-konva`. Vue 3 Composition API + Konva works.

**State management:** Pinia is the Vue 3 standard, well-suited to this shape of data.

**Ecosystem:** Strong, but the canvas annotation tutorial ecosystem is thinner than React's. No shadcn equivalent with the same coverage.

**Confidence:** MEDIUM — viable but offers no advantage over React for this project.

### Decision

**Recommendation: React + TypeScript**

Rationale:
1. `react-konva` has the densest set of working polygon/annotation examples, including exact patterns needed (polygon draw, drag anchor points, image underlay). This reduces implementation risk.
2. The real-time performance advantage of Svelte is irrelevant here: the 30 fps canvas draw loop bypasses framework rendering entirely.
3. `shadcn/ui` + Tailwind v4 delivers a polished panel/sidebar/list UI for the light-assignment interface with minimal work.
4. Zustand gives a clean, debuggable state model for the region-to-light mapping graph.
5. Vite + React is the de-facto standard toolchain; the ecosystem assumes it.

---

## 2. Canvas Library: Konva.js

### Candidates Evaluated

| Library | Best For | Polygon Draw | Drag/Resize | Image Underlay | Framework Bindings | Maintenance |
|---------|----------|-------------|-------------|----------------|-------------------|-------------|
| **Konva.js** | Interactive 2D editors, annotation tools | Yes (Line + closed) | Built-in (Transformer) | Yes (Image node) | React, Vue, Svelte, Solid | Actively maintained, ~877K weekly downloads |
| **Fabric.js** | Document/design editors, SVG export | Yes (Polygon) | Built-in | Yes | React wrapper exists | Active, but API is more opinionated |
| **Paper.js** | Mathematical vector art, path algorithms | Yes | Limited | Possible | No first-class bindings | Low activity recently |
| **Raw Canvas API** | Full control, zero overhead | Manual | Manual | `drawImage()` | N/A | N/A |

### Why Konva.js is the Right Choice

**Polygon drawing:** `Konva.Line` with `closed: true` is the standard pattern. Anchor points are rendered as draggable `Konva.Circle` nodes. Tutorials for interactive polygon editors in React with full draw/drag/resize cycles are abundant and current (2025).

**Transformer:** `Konva.Transformer` provides selection handles, resize, and rotation on any node group without custom code.

**Layering:** Konva uses a scene graph with explicit layers. The recommended architecture for this project:
- Layer 0: MJPEG camera frame (updated via `Konva.Image` from an offscreen canvas or `drawImage`)
- Layer 1: Region polygons with color overlays (semi-transparent fills showing sampled color)
- Layer 2: Selection handles and UI chrome

**Color overlay:** Each region polygon can have a semi-transparent fill updated at ~5 Hz from the backend's color samples. `polygon.fill('rgba(r, g, b, 0.4)')` is a one-liner.

**react-konva API:**
```tsx
<Stage width={width} height={height}>
  <Layer>
    <KonvaImage image={videoFrame} />
  </Layer>
  <Layer>
    {regions.map(r => (
      <Line key={r.id} points={r.points} closed fill={r.sampledColor} stroke="white" />
    ))}
  </Layer>
</Stage>
```

**Fabric.js was considered and rejected** for this use case because:
- Its object model is heavier (full object serialization on every mutation)
- The react wrapper (`react-fabric`) is less maintained than `react-konva`
- Fabric's architecture is designed around a single active-object selection model, which fights against a multi-region annotation workflow

**Paper.js was rejected** because:
- It has no first-class React bindings
- Maintenance is low
- Its strength (mathematical path operations) is not needed here

**Confidence:** HIGH — Konva is clearly the standard choice for image/video annotation tools on the web.

---

## 3. Camera Feed Streaming: Approach Comparison

### Options

| Approach | Latency | Complexity | Backend Work | Browser Support | Notes |
|----------|---------|------------|--------------|-----------------|-------|
| **WebSocket + JPEG frames** | 50–200 ms (LAN) | Low | Low | All | Binary frames pushed as ArrayBuffer; drawn to canvas with `createImageBitmap` |
| **MJPEG HTTP stream** | 100–500 ms | Very Low | Minimal | All | `<img src="http://...stream">` or multipart HTTP; simplest possible backend |
| **WebRTC** | < 100 ms (sub-250 ms) | High | High (STUN/ICE/signaling) | All modern | Overkill for a local LAN tool |
| **Server-Sent Events + snapshots** | 200–1000 ms | Low | Low | All | Not binary-friendly; worse than WebSocket for frames |
| **HLS/DASH** | 2–10 s | Medium | Medium | All | Designed for VOD/broadcast, not config UIs |

### Recommendation: WebSocket + JPEG Frames

For a local-network ambient lighting config tool, WebSocket JPEG streaming is the right tradeoff:

- **Latency:** On a LAN, 16–50 ms is achievable. Combined with browser VSYNC the user sees ~32–50 ms total visual lag, imperceptible for a config UI.
- **Backend simplicity:** A Python WebSocket server (FastAPI + WebSockets or `websockets` library) encodes frames as JPEG bytes and pushes them. No signaling server, no ICE/STUN complexity.
- **Frontend rendering:**
  ```typescript
  ws.onmessage = async (event) => {
    const blob = new Blob([event.data], { type: 'image/jpeg' });
    const bitmap = await createImageBitmap(blob);
    konvaImage.image(bitmap);
    layer.batchDraw();
  };
  ```
  `createImageBitmap` is hardware-accelerated in modern browsers and does not block the main thread.

- **Why not MJPEG HTTP:** A plain `<img>` MJPEG stream cannot easily be drawn to a canvas (browser renders only first frame in some implementations). WebSocket gives explicit per-frame control needed to draw frames into the Konva layer.

- **Why not WebRTC:** This is a local single-user config tool, not a broadcast. WebRTC setup complexity (signaling, ICE, STUN/TURN) is not justified. The latency advantage (~50 ms vs ~200 ms) is irrelevant for dragging polygon vertices.

**Performance tips:**
- Decode frames with `createImageBitmap()` (async, off main thread decode path in Chrome/Firefox)
- Keep camera feed on its own Konva layer, call `layer.batchDraw()` only when a new frame arrives
- Drop incoming frames if the previous decode is still in flight (don't queue frames)
- Target 10–15 fps for the preview; the ambient lighting updates do not need 30 fps

**Confidence:** HIGH

---

## 4. UI Patterns for Light Mapping

### Panel Layout

Split the UI into two panels:

```
┌─────────────────────────────────┬──────────────────────┐
│  Camera feed + drawn regions    │  Light list panel    │
│  (Konva canvas)                 │                      │
│                                 │  [HueLight A]  ●     │
│  [Toolbar: draw / select / del] │  [HueLight B]  ●     │
│                                 │  [Segment 1/3] ●     │
│  ┌──region overlay──┐           │                      │
│  │ color: #3a8ef2   │           │  Mappings:           │
│  │ → HueLight A     │           │  Region 1 → Light A  │
│  └──────────────────┘           │  Region 2 → Light B  │
└─────────────────────────────────┴──────────────────────┘
```

### Assignment Interaction

**Recommended pattern: Click-to-assign (preferred over drag-and-drop)**

For a technical config UI, click-to-assign is more reliable and accessible than drag-and-drop onto canvas regions:
1. User draws a region on the canvas
2. Region appears selected (highlighted border)
3. User clicks a light in the light list panel
4. Mapping is created; the region fill updates immediately to the light's current color

**Alternative: Drag-from-list-to-canvas** — dragging a light card onto a canvas polygon. This works with the HTML5 Drag and Drop API + Konva event listeners but adds complexity. Only worth implementing if the assignment workflow is discovered to be awkward during early testing.

**Real-time color preview:**
- Each region polygon fill is updated with the sampled average color from the backend
- Use `rgba(r, g, b, 0.35)` semi-transparent fill so the camera feed is still visible underneath
- Update at ~5 Hz (every 200 ms); no need to match camera feed frame rate

### State Shape (Zustand)

```typescript
interface Region {
  id: string;
  points: number[];        // flat [x0,y0,x1,y1,...] in canvas coords
  normalizedPoints: number[]; // [0..1] relative to feed dimensions
  assignedLightId: string | null;
  sampledColor: string;    // "rgba(r,g,b,0.35)"
}

interface Light {
  id: string;
  name: string;
  type: 'bulb' | 'gradient_segment';
  currentColor: string;
  reachable: boolean;
}

interface AppStore {
  regions: Region[];
  lights: Light[];
  selectedRegionId: string | null;
  // Actions
  addRegion: (points: number[]) => void;
  updateRegionColor: (id: string, color: string) => void;
  assignLight: (regionId: string, lightId: string) => void;
  deleteRegion: (id: string) => void;
}
```

**Confidence:** MEDIUM — based on standard annotation tool patterns; specific interaction flow needs validation during implementation.

---

## 5. Build Tooling

### Recommendation: Vite

Vite is the unambiguous standard for new React/TypeScript projects as of 2025. Create React App is deprecated. Vite offers:
- Native ES module dev server (near-instant startup)
- esbuild-powered TypeScript compilation
- HMR that preserves canvas/Konva state during edits
- Production builds with Rollup + tree-shaking

**Bootstrap:**
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install konva react-konva zustand
npm install -D tailwindcss @tailwindcss/vite
```

**shadcn/ui** (optional but recommended for the light list panel):
```bash
npx shadcn@latest init
npx shadcn@latest add card badge scroll-area button
```

**Confidence:** HIGH

---

## 6. Recommended Stack Summary

| Layer | Choice | Version | Rationale |
|-------|--------|---------|-----------|
| Framework | React | 19.x | Largest canvas annotation ecosystem; shadcn/ui available |
| Language | TypeScript | 5.x | Type safety for Region/Light/Mapping data model |
| Build tool | Vite | 6.x | Industry standard; instant HMR |
| Canvas | Konva.js + react-konva | 9.x / 19.x | Scene graph, Transformer, image underlay, polygon draw |
| State | Zustand | 5.x | Simple, debuggable, no boilerplate |
| UI components | shadcn/ui + Tailwind CSS | v4 | Panel/list/badge components for light assignment UI |
| Streaming | WebSocket JPEG frames | — | Low complexity, LAN latency acceptable |
| Frame decode | `createImageBitmap` API | — | Hardware-accelerated, non-blocking |

---

## 7. Architecture Notes

### Canvas Rendering Architecture

The camera feed and region overlays should use separate Konva layers. The feed layer is updated on every WebSocket frame. The region layer is updated only when region data changes (user draws, edits, or the backend sends a new color sample). This keeps region re-renders decoupled from the 10–15 fps frame loop.

```
WebSocket (binary JPEG) ---> createImageBitmap ---> Konva.Image (Layer 0)
                                                         |
Backend color updates (5 Hz) ---> Zustand store ---> Region fills (Layer 1)
User mouse events ---> Konva event handlers ---> Polygon point state (Layer 1)
```

### Coordinate Normalization

Regions should store their points in normalized coordinates `[0..1]` relative to the displayed canvas dimensions, not pixel coordinates. This makes the config portable across display resolutions and allows the backend to use the same coordinates against the raw camera frame (which may be a different resolution than the canvas display size).

Convert on draw: `normalizedPoint * canvasWidth`.
Convert on save: `pixelPoint / canvasWidth`.

### Pitfall: Konva Image Node and Video Frames

Konva's `Image` node does not auto-update when its image source changes. After writing a new `ImageBitmap` to the node, `layer.batchDraw()` must be called explicitly. Using `layer.draw()` in a tight loop will cause frame drops; `batchDraw()` coalesces calls within an animation frame.

---

## 8. Open Questions / Flags for Later Phases

- **WebSocket vs REST for config persistence:** Should region/mapping config be saved via a REST endpoint or pushed over the same WebSocket? Recommend REST for simplicity.
- **Camera resolution:** Higher resolution feeds increase WebSocket bandwidth. Need to benchmark JPEG quality vs bandwidth vs decode latency at target resolution.
- **Hue API discovery:** Konva region drawing is frontend-only; the light discovery and Hue Bridge API integration is a backend concern. The frontend only needs the list of lights + current colors.
- **Multi-user:** Not in scope, but if two browser tabs open simultaneously, the Zustand store is per-tab. The backend needs to be the source of truth for mappings.

---

## Sources

- [Konva.js vs Fabric.js — DEV Community](https://dev.to/xingjian_hu_123dc779cbcac/konvajs-vs-fabricjs-in-depth-technical-comparison-and-use-case-analysis-3k7l)
- [Konva vs Fabric — GitHub Issue #637](https://github.com/konvajs/konva/issues/637)
- [react-konva — GitHub](https://github.com/konvajs/react-konva)
- [svelte-konva — GitHub](https://github.com/konvajs/svelte-konva)
- [Konva Polygon Tutorial](https://konvajs.org/docs/shapes/Line_-_Polygon.html)
- [Konva Image Annotation Sandbox](https://konvajs.org/docs/sandbox/Image_Labeling.html)
- [How to Build an Interactive Polygon Editor with react-konva](https://medium.com/@imamrasheedatahmad1993/how-to-build-an-interactive-polygon-editor-in-react-using-react-konva-1b085e0b04de)
- [Bounding Polygon Annotation Tool with react-konva](https://devmuscle.com/blog/react-konva-image-annotation)
- [WebRTC vs WebSocket Latency Comparison](https://www.videosdk.live/developer-hub/websocket/which-is-better-and-when-to-use-it-webrtc-or-websocket)
- [MotionJpeg Latency Test — GitHub](https://github.com/iimachines/MotionJpegLatencyTest)
- [Manipulating video using canvas — MDN](https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API/Manipulating_video_using_canvas)
- [Offscreen Canvas API for real-time rendering](https://webrtc.ventures/2022/02/offscreen-canvas-api/)
- [Zustand vs Jotai — State Management in 2025](https://dev.to/hijazi313/state-management-in-2025-when-to-use-context-redux-zustand-or-jotai-2d2k)
- [Svelte 5 vs React 19 — 2025 benchmarks](https://jsgurujobs.com/blog/svelte-5-vs-react-19-vs-vue-4-the-2025-framework-war-nobody-expected-performance-benchmarks)
- [Vite Getting Started](https://vite.dev/guide/)
- [shadcn/ui](https://ui.shadcn.com/)
- [Ranking JavaScript Canvas Frameworks Feb 2026 — Medium](https://drabstract.medium.com/ranking-javascript-canvas-frameworks-3c3e407ab7d8)
