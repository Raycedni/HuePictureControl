# Phase 5: Gradient Device Support and Polish - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Deliver full per-segment independent control of gradient-capable devices (Festavia, Flux, Play Gradient Lightstrip), enforce the 20-channel Entertainment API limit, and add capture card disconnect retry. Builds on Phase 4's LightPanel drag-to-assign and Phase 3's streaming infrastructure.

</domain>

<decisions>
## Implementation Decisions

### 20-channel limit UX
- Soft warning — allow assignment beyond 20 channels, do NOT hard-prevent
- Always-visible channel counter: "X / 20 channels" displayed in the light panel header at all times
- Yellow/red warning banner above the canvas when total assigned channels exceed 20
- Banner message is a simple count: "22/20 channels assigned — bridge will ignore excess channels." No identification of which specific channels to remove — user decides what to trim
- Counter updates live as assignments change (no save-then-check)

### Segment display in light panel
- Claude's discretion — decide how gradient lights with multiple segments appear as assignable targets in the LightPanel during planning

### Segment assignment model
- Claude's discretion — decide cardinality rules (segment-to-region mapping) during planning
- Existing pattern: unassigned regions are ignored during streaming (Phase 4 decision) — apply same principle to unassigned segments

### Capture card reconnect
- Phase 5 roadmap overrides Phase 3's "stop entirely" behavior: add auto-retry with exponential backoff on capture card disconnect
- Claude's discretion on backoff parameters and UI feedback during retry

### Claude's Discretion
- Gradient device detection approach (CLIP v2 `gradient.pixel_count` vs `points_capable` vs channel enumeration)
- Entertainment config channel-to-light backward mapping implementation
- Per-segment channel ID resolution strategy
- Festavia/Flux segment count handling (empirical hardware validation required)
- Capture card reconnect backoff timing and retry limits
- How segment rows integrate with existing drag-to-assign flow

</decisions>

<specifics>
## Specific Ideas

- User chose soft warning over hard prevent because they may want to configure beyond 20 and trim later — the bridge silently drops excess, it doesn't error
- Always-visible counter chosen so users always know their channel budget regardless of setup size
- Banner above canvas (not status bar or inline) was chosen for prominence — hard to miss when over limit

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Backend/services/hue_client.py`: `list_lights()` (lines 102-148) fetches lights + device archetypes — extend to read `gradient.pixel_count` and `points_capable` from CLIP v2
- `Backend/services/hue_client.py`: `fetch_entertainment_config_channels()` (lines 169-200) returns channel_id + position — extend to map channel_id back to source light + segment index
- `Backend/services/streaming_service.py`: `_load_channel_map()` (lines 209-237) loads channel-to-mask mapping — already channel-granular, gradient segments just add more channels
- `Backend/services/streaming_service.py`: `_reconnect_loop()` (lines 315-352) for bridge reconnect with exponential backoff — reuse pattern for capture card reconnect
- `Frontend/src/components/LightPanel.tsx`: Drag-to-assign with `onDragStart` setting lightId/lightName via HTML5 dataTransfer — extend for per-segment drag items
- `Frontend/src/components/EditorCanvas.tsx`: `onDrop` handler resolves drag data and creates assignment — needs channel_id awareness for segments

### Established Patterns
- HTML5 dataTransfer drag-and-drop for light assignment (no library)
- `lightMap` built from `getLights()` on mount to resolve IDs to names
- Light interface: `{ id, name, type }` — extend with `segment_count` and `is_gradient`
- Backend `app.state` for shared service references
- Best-effort deactivation on cleanup (never raises)

### Integration Points
- Backend `GET /api/hue/lights` — extend response with gradient fields (segment_count, is_gradient)
- Backend light_assignments table — already stores `(region_id, channel_id, entertainment_config_id)`, channel_id maps to individual segments
- Frontend Light interface in `api/hue.ts` — add segment_count, is_gradient fields
- LightPanel renders one row per light — needs to render N rows for N-segment gradient lights
- EditorPage layout — add warning banner slot above canvas
- StatusBar or LightPanel header — add channel counter display

### Key Constraint
- Entertainment config channels already represent individual segments for gradient devices — a 7-segment Play Gradient appears as 7 separate channel entries. The mapping from channel_id to parent light + segment index is what's missing.

</code_context>

<deferred>
## Deferred Ideas

- Per-light color preview widgets showing current output color (v2 requirement AUI-04)
- Configurable color saturation boost / brightness scaling per light (v2 COLR-02)

</deferred>

---

*Phase: 05-gradient-device-support-and-polish*
*Context gathered: 2026-03-31*
