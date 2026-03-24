# Phase 4: Frontend Canvas Editor - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver a fully interactive web UI where users can draw polygon regions on a live camera preview and assign each region to a Hue light or gradient segment. Builds on Phase 3.1's auto-mapping and PreviewPage — adds Konva.js canvas with freeform drawing, vertex editing, and drag-to-assign light interaction.

</domain>

<decisions>
## Implementation Decisions

### Auto-map vs manual regions
- Auto-generated regions (from Phase 3.1) are fully editable — no distinction between auto and manual once created
- Re-running auto-map replaces ALL regions (auto and manual) — fresh start mental model
- Regions can exist without a light assignment — user draws first, assigns later
- Unassigned regions are ignored during streaming

### Canvas interaction model
- Two drawing modes: rectangle (click-drag) and freeform polygon (click-to-place vertices, click first vertex to close)
- Toolbar above canvas: [Rectangle] [Polygon] [Select] [Delete]
- Editing: click region to select (shows vertex handles), drag vertices to reshape, drag region body to move, Delete key or button to remove
- Region-to-light assignment: drag a light from the side panel onto a region on the canvas
- Each region shows the assigned light name as a small label inside it
- Auto-save on every change — no manual save button; every create/edit/delete/assign immediately persists to backend

### Live preview
- WebSocket binary JPEG at 10-15 fps for smooth live preview on the canvas
- Live sampled color overlay: each region polygon fills with the actual color being sent to its light (semi-transparent) — updates with each frame (UI-06)
- WebSocket preview only connects when editor tab is visible — disconnects when switching away
- Preview available without streaming active — camera feed shows even when not streaming to lights (backend needs preview-only mode)

### Page layout and navigation
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

</decisions>

<specifics>
## Specific Ideas

- Drag-to-assign from light panel to canvas region was specifically chosen over click-to-select + click-to-assign
- User wants both rectangle and freeform polygon drawing modes available via toolbar toggle
- Re-running auto-map is a "fresh start" — no protection for manual edits
- Preview without streaming means the capture device stays open for the camera feed even when DTLS is not active

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Frontend/src/components/PreviewPage.tsx`: 260 lines — config selector, auto-map trigger, snapshot display, region overlays, start/stop toggle. Phase 4 Editor reuses the API calls but replaces the canvas rendering with Konva.js
- `Frontend/src/api/regions.ts`: `fetchRegions`, `triggerAutoMap`, `startStreaming`, `stopStreaming`, typed `Region` and `Config` interfaces
- `Frontend/src/api/hue.ts`: `getLights()` — returns light id, name, type. Needed for the light panel
- `Frontend/src/components/PairingFlow.tsx`: Setup tab — stays as-is
- `Frontend/src/App.tsx`: Tab navigation with `useState<Page>` — extend to 3 tabs

### Established Patterns
- Plain React with `useState`/`useEffect` hooks (no state library yet — Zustand would be new)
- Inline styles throughout (no Tailwind yet — would be new)
- API client pattern: typed interfaces + fetch wrappers in `src/api/`
- Tab-based navigation via conditional rendering in App.tsx

### Integration Points
- Backend `GET /api/regions` / `POST /api/regions/auto-map` — region CRUD
- Backend `POST /api/capture/start` / `POST /api/capture/stop` — streaming control
- Backend `/ws/status` — status WebSocket (1 Hz heartbeat + state transitions)
- Backend needs NEW: `/ws/preview` — binary JPEG WebSocket at 10-15 fps for live canvas
- Backend needs NEW: region CRUD endpoints (`PUT /api/regions/{id}`, `DELETE /api/regions/{id}`) for canvas editing
- Backend needs NEW: light assignment endpoints or extend existing region API

</code_context>

<deferred>
## Deferred Ideas

- Per-light color preview widgets showing current output color (v2 requirement AUI-04)
- Preset region layouts / grid templates (v2 requirement AUI-01)
- Import/export configuration as JSON (v2 requirement AUI-02)

</deferred>

---

*Phase: 04-frontend-canvas-editor*
*Context gathered: 2026-03-24*
