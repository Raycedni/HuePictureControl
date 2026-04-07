# Phase 10: Frontend Camera Selector - Context

**Gathered:** 2026-04-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a per-zone camera dropdown selector to the editor UI's LightPanel sidebar, with an entertainment config (zone) selector above it. Selecting a camera persists the assignment immediately and switches the live preview to that camera's feed. The PreviewPage is NOT modified — camera selection is editor-only.

This phase does NOT change backend APIs (Phases 7-9 already deliver them), nor Docker device passthrough (Phase 11).

</domain>

<decisions>
## Implementation Decisions

### Dropdown Placement
- **D-01:** Camera dropdown lives in the LightPanel sidebar (right panel), NOT above the canvas or in the toolbar. Groups all configuration controls together.
- **D-02:** Entertainment config (zone) selector is added above the camera dropdown at the top of LightPanel. Order: Zone selector -> Camera selector -> Lights list.
- **D-03:** Camera selector appears only in the EditorPage (via LightPanel). PreviewPage is unchanged — it uses the zone's assigned camera automatically.

### Preview Switching
- **D-04:** Instant swap on camera change — close the old WebSocket, open new one with the new `?device=` param. The existing double-buffer pattern in EditorCanvas prevents blank flash (old frame stays visible until first new frame arrives, ~200-500ms gap).
- **D-05:** Camera assignment auto-saves immediately on dropdown change via `PUT /api/cameras/assignments/{config_id}`. No separate save button. Consistent with existing region auto-save pattern.

### Zone-Camera UX
- **D-06:** Switching entertainment config (zone) in the zone selector auto-updates the camera dropdown to show that zone's assigned camera (from `zone_health` data). Preview switches to that camera's feed.
- **D-07:** When a zone has no camera assigned, show "Select camera..." placeholder. No preview loads until a camera is explicitly picked. No auto-selection of first available camera.

### Camera Refresh
- **D-08:** Both a manual refresh button (icon next to camera dropdown) AND automatic re-scan when the dropdown is opened. Refresh button calls `GET /api/cameras` to re-scan devices. Satisfies DEVC-03 (on-demand refresh).

### Empty/Error States
- **D-09:** When no cameras are detected (`cameras_available: false`), show an inline warning banner above the canvas (similar to existing `identity_mode === 'degraded'` banner). Camera dropdown shows "No cameras" and is disabled. Editor remains usable for reviewing existing regions.
- **D-10:** When the assigned camera disconnects, show a "Disconnected" badge/indicator next to the camera dropdown. Canvas keeps the last received frame visible (frozen). User can pick a different camera or use the existing reconnect mechanism.

### Claude's Discretion
- Whether to use native `<select>` or a custom dropdown component for the camera/zone selectors
- How to fetch and cache the cameras list (new hook, inline fetch, or extend existing pattern)
- Exact styling of the disconnected badge and no-cameras banner
- Whether the zone selector filters the lights list to show only that zone's channels

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Codebase
- `Frontend/src/components/LightPanel.tsx` — Target component for camera + zone dropdowns; currently shows lights list only
- `Frontend/src/components/EditorCanvas.tsx` — Calls `usePreviewWS(true)` without device param; needs device wired through
- `Frontend/src/components/EditorPage.tsx` — Parent of LightPanel and EditorCanvas; already fetches `/api/cameras` for identity mode
- `Frontend/src/components/PreviewPage.tsx` — Has config selector pattern (native `<select>`) that can inform the editor's zone selector; NOT modified in this phase
- `Frontend/src/hooks/usePreviewWS.ts` — Already accepts optional `device` param (Phase 9); callers need to pass it
- `Frontend/src/api/hue.ts` — `getEntertainmentConfigs()` and `EntertainmentConfig` interface
- `Frontend/src/api/regions.ts` — `Region` interface with `camera_device: string | null` (Phase 9)
- `Frontend/src/store/useRegionStore.ts` — Zustand store for regions state
- `Frontend/src/components/ui/` — shadcn/ui components: badge, button, scroll-area, separator

### Backend API Surface (already implemented)
- `GET /api/cameras` — Returns `devices[]`, `identity_mode`, `cameras_available`, `zone_health` (Phases 7+9)
- `PUT /api/cameras/assignments/{config_id}` — Persist camera assignment per zone (Phase 7)
- `GET /api/hue/configs` — Entertainment configurations list
- `GET /ws/preview?device={path_or_stable_id}` — Preview WebSocket with required device param (Phase 9)

### Project Docs
- `.planning/REQUIREMENTS.md` — CMUI-01, CMUI-02, CMUI-03 requirements
- `.planning/ROADMAP.md` — Phase 10 success criteria
- `.planning/phases/07-device-enumeration-and-camera-assignment-schema/07-CONTEXT.md` — Device identity, camera assignment DB schema
- `.planning/phases/08-capture-registry/08-CONTEXT.md` — Capture registry lifecycle
- `.planning/phases/09-preview-routing-and-region-api/09-CONTEXT.md` — Preview WS routing, zone_health, usePreviewWS device param

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `usePreviewWS(enabled, device?)` — Hook ready for device param, just needs callers to wire it
- `getEntertainmentConfigs()` in `api/hue.ts` — Fetches configs, reusable for zone selector
- `EditorPage` already fetches `/api/cameras` — data fetching pattern exists
- Native `<select>` pattern in PreviewPage for config selector — can inform zone selector styling
- shadcn `Badge` component — could be used for disconnected indicator

### Established Patterns
- `useEffect` + `fetch` for data loading on mount (EditorPage, PreviewPage)
- Zustand for shared state (`useRegionStore`)
- Tailwind + `glass` class for panel styling
- Auto-save on change (region edits persist immediately via API)

### Integration Points
- `LightPanel.tsx` — Add zone selector and camera dropdown at top
- `EditorCanvas.tsx` — Pass `device` param to `usePreviewWS` call
- `EditorPage.tsx` — May need to lift camera/zone state to share between LightPanel and EditorCanvas
- State flow: EditorPage (or new store) holds selectedConfigId + selectedDevice -> passes to both LightPanel and EditorCanvas

</code_context>

<specifics>
## Specific Ideas

- Zone selector + camera dropdown in sidebar follows: Zone (top) -> Camera (middle) -> Lights (bottom)
- Camera dropdown should show device display_name and path (CMUI-02): e.g., "USB Capture Card (/dev/video0)"
- Both manual refresh button AND auto-refresh on dropdown open for camera list
- "Select camera..." placeholder when zone has no assignment — no preview until camera is picked
- Disconnected badge shows next to camera dropdown, last frame stays frozen on canvas
- Auto-save camera assignment on dropdown change — matches existing region auto-save pattern

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 10-frontend-camera-selector*
*Context gathered: 2026-04-07*
