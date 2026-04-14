# Phase 10: Frontend Camera Selector - Research

**Researched:** 2026-04-07
**Domain:** React 19 / TypeScript UI — state lifting, dropdown wiring, WebSocket device switching
**Confidence:** HIGH

## Summary

Phase 10 is a pure frontend wiring task. The backend APIs are already fully implemented (Phases 7–9). The preview WebSocket hook already accepts an optional `device` parameter. The only work is: lift `selectedConfigId` state from LightPanel to EditorPage, add a camera dropdown below the zone selector in LightPanel, pass the selected device path to EditorCanvas, and call `PUT /api/cameras/assignments/{config_id}` on change. No new libraries are needed. No backend changes are needed.

The key structural challenge is **state lifting**: `selectedConfigId` and `selectedDevice` are currently isolated inside LightPanel, but EditorCanvas (a sibling) needs to consume `selectedDevice` to wire it into `usePreviewWS`. The cleanest solution given the existing Zustand + prop-drilling pattern is to lift both values into EditorPage as local state and pass them down as props. A dedicated Zustand slice is not warranted — these are transient UI-navigation values, not persistent data.

The live preview switch already works correctly: `usePreviewWS` re-runs its effect when `device` changes (the dependency array includes `device`), closes the old WebSocket, and opens a new one. The double-buffer pattern in EditorCanvas prevents blank flashes during the transition. No additional animation or buffering logic is required.

**Primary recommendation:** Lift selectedConfigId + selectedDevice to EditorPage state, add camera API call (useCameras hook pattern), add camera dropdown to LightPanel with auto-save on change.

## Project Constraints (from CLAUDE.md)

- Python 3.12 pinned — not relevant to this phase (frontend only)
- No third-party Hue wrapper libraries — not applicable
- No auth on web UI — already satisfied
- Autonomous testing checklist: `npx vitest run` must pass (30+ tests) before and after changes
- Docker for full-stack verification; Playwright MCP for visual verification at http://localhost:8091

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Camera dropdown lives in the LightPanel sidebar (right panel), NOT above the canvas or in the toolbar.
- **D-02:** Zone selector (entertainment config) goes above camera dropdown at the top of LightPanel. Order: Zone selector -> Camera selector -> Lights list.
- **D-03:** Camera selector appears only in the EditorPage (via LightPanel). PreviewPage is unchanged.
- **D-04:** Instant preview swap on camera change — close old WebSocket, open new with new `?device=` param. Double-buffer pattern already handles blank flash.
- **D-05:** Camera assignment auto-saves immediately on dropdown change via `PUT /api/cameras/assignments/{config_id}`. No separate save button.
- **D-06:** Switching entertainment config (zone) auto-updates the camera dropdown to show that zone's assigned camera (from `zone_health` data). Preview switches to that camera's feed.
- **D-07:** When a zone has no camera assigned, show "Select camera..." placeholder. No preview loads until a camera is explicitly picked. No auto-selection of first available camera.
- **D-08:** Both a manual refresh button (icon next to camera dropdown) AND automatic re-scan when the dropdown is opened. Refresh button calls `GET /api/cameras`.
- **D-09:** When no cameras detected (`cameras_available: false`), show inline warning banner above the canvas. Camera dropdown shows "No cameras" and is disabled.
- **D-10:** When the assigned camera disconnects, show a "Disconnected" badge next to the camera dropdown. Canvas keeps last frame frozen. User can pick a different camera.

### Claude's Discretion

- Whether to use native `<select>` or a custom dropdown component for the camera/zone selectors
- How to fetch and cache the cameras list (new hook, inline fetch, or extend existing pattern)
- Exact styling of the disconnected badge and no-cameras banner
- Whether the zone selector filters the lights list to show only that zone's channels

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CMUI-01 | Camera dropdown selector per entertainment zone in the editor UI | LightPanel.tsx is the target; zone selector needs to be added above camera dropdown |
| CMUI-02 | Dropdown shows device name and path for each available camera | GET /api/cameras returns `display_name` + `device_path` per CameraDevice; format as "USB Capture Card (/dev/video0)" |
| CMUI-03 | Live preview updates immediately when camera selection changes | usePreviewWS already has device param; re-runs effect on device change; double-buffer prevents blank flash |
</phase_requirements>

## Standard Stack

### Core (already installed — no new packages needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React 19 | 19.x | UI rendering | Already in use |
| Zustand | existing | Shared state | Already in use (`useRegionStore`, `useStatusStore`) |
| shadcn/ui Badge | existing | Disconnected indicator | Already in `src/components/ui/badge.tsx` |
| shadcn/ui Button | existing | Refresh button | Already in `src/components/ui/button.tsx` |
| Tailwind CSS | existing | Styling | Already in use |

### No New Dependencies

This phase requires zero new npm packages. All components, hooks, and API patterns are already present in the codebase.

**Installation:** None required.

## Architecture Patterns

### Recommended Project Structure Changes

```
Frontend/src/
├── components/
│   ├── EditorPage.tsx       # MODIFIED: lift selectedConfigId + selectedDevice state here
│   ├── EditorCanvas.tsx     # MODIFIED: accept device?: string prop, pass to usePreviewWS
│   └── LightPanel.tsx       # MODIFIED: add zone + camera selectors at top; accept/emit props
├── api/
│   └── cameras.ts           # NEW: typed fetch wrappers for GET /api/cameras and PUT /api/cameras/assignments/{id}
└── hooks/
    └── useCameras.ts        # NEW: fetch hook returning cameras list + loading/error state
```

### Pattern 1: State Lifting to EditorPage

**What:** EditorPage holds `selectedConfigId: string` and `selectedDevice: string | undefined`. Both are passed as props to LightPanel and EditorCanvas.

**When to use:** When two sibling components (LightPanel, EditorCanvas) need to share the same value and neither is a natural parent of the other.

**Current state:** `selectedConfigId` lives inside LightPanel local state. EditorCanvas calls `usePreviewWS(true)` with no device arg. The hook stays disconnected when device is undefined (confirmed in `usePreviewWS.ts` line 10: `if (!enabled || !device) { ... setImgSrc(null); return }`).

**Example:**
```typescript
// EditorPage.tsx — lifted state
const [selectedConfigId, setSelectedConfigId] = useState<string>('')
const [selectedDevice, setSelectedDevice] = useState<string | undefined>(undefined)

// Pass down
<LightPanel
  selectedConfigId={selectedConfigId}
  onConfigChange={setSelectedConfigId}
  selectedDevice={selectedDevice}
  onDeviceChange={setSelectedDevice}
/>
<EditorCanvas
  width={canvasDims.width}
  height={canvasDims.height}
  onDeleteRequest={handleEditorDelete}
  device={selectedDevice}
/>
```

### Pattern 2: useCameras Hook

**What:** A simple data-fetching hook that calls `GET /api/cameras` and returns typed results.

**When to use:** Whenever camera list is needed (LightPanel needs it for dropdown).

**Example:**
```typescript
// hooks/useCameras.ts
export function useCameras() {
  const [data, setData] = useState<CamerasResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    try {
      const res = await fetch('/api/cameras')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e) {
      setError('Failed to load cameras')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [])
  return { data, loading, error, refresh }
}
```

### Pattern 3: Auto-save Camera Assignment

**What:** On dropdown `onChange`, immediately call `PUT /api/cameras/assignments/{config_id}` with the selected camera's `stable_id` and `display_name`. No confirmation or save button.

**When to use:** Matches the existing region auto-save pattern (region edits persist immediately via API).

**The PUT body shape** (from `cameras.py` `AssignmentRequest`):
```typescript
// api/cameras.ts
export async function putCameraAssignment(
  configId: string,
  cameraStableId: string,
  cameraName: string,
): Promise<void> {
  const res = await fetch(`/api/cameras/assignments/${configId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ camera_stable_id: cameraStableId, camera_name: cameraName }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}
```

### Pattern 4: Zone-Health Initialization

**What:** When the user first loads the editor (or switches zones), pre-select the camera that is already assigned to that zone. `GET /api/cameras` returns `zone_health[]` which includes `entertainment_config_id`, `camera_stable_id`, `connected`, and `device_path`.

**When to use:** On initial load and whenever `selectedConfigId` changes.

**Logic:**
```typescript
// When selectedConfigId changes, look up zone_health to find assigned camera
useEffect(() => {
  if (!camerasData || !selectedConfigId) return
  const zoneEntry = camerasData.zone_health.find(
    zh => zh.entertainment_config_id === selectedConfigId
  )
  if (zoneEntry && zoneEntry.device_path) {
    setSelectedDevice(zoneEntry.device_path)
  } else {
    setSelectedDevice(undefined) // D-07: no auto-selection
  }
}, [selectedConfigId, camerasData])
```

### Pattern 5: Disconnected Badge (D-10)

**What:** After selecting a device, cross-reference `camerasData.devices` to check `connected` flag for the selected `stable_id`. If `connected === false`, show Badge next to dropdown.

**Available component:** `Frontend/src/components/ui/badge.tsx` is already installed.

### Pattern 6: No-Cameras Banner (D-09)

**What:** When `camerasData.cameras_available === false`, show inline warning above the canvas in EditorPage. Pattern matches the existing `identityMode === 'degraded'` banner already in EditorPage (lines 61-64).

**Example (EditorPage.tsx pattern already used):**
```tsx
{!camerasData?.cameras_available && (
  <div className="bg-red-500/10 border border-red-500/25 text-red-400 text-xs px-3 py-2 text-center">
    No capture devices detected. Connect a USB capture card and click refresh.
  </div>
)}
```

### Pattern 7: Dropdown Auto-Refresh on Open

**What:** D-08 requires `GET /api/cameras` to fire when the dropdown is opened (in addition to the manual refresh button). For a native `<select>`, use `onFocus` or `onMouseDown` to trigger `refresh()` from `useCameras`.

**Note on native `<select>` vs custom:** The existing codebase uses native `<select>` elements throughout (LightPanel zone selector, PreviewPage config selector). Consistency favors native `<select>`. Custom dropdowns add complexity with no functional gain for this use case. Recommendation: use native `<select>` for both zone and camera selectors.

### Anti-Patterns to Avoid

- **Calling `GET /api/cameras` on every render:** Use a hook with explicit `refresh()` — call it on mount + on user action, not in the render path.
- **Storing `selectedDevice` inside LightPanel:** EditorCanvas is a sibling and needs it — keep state in EditorPage.
- **Auto-selecting first camera:** D-07 explicitly forbids this. When `zone_health` has no entry for the selected config, `selectedDevice` must be `undefined`.
- **Using `stable_id` as the WebSocket `?device=` param:** The preview WS endpoint accepts the device path (e.g., `/dev/video0`), not the stable_id. Use `device_path` from the cameras list. Confirmed in `usePreviewWS.ts`: it constructs `?device=${encodeURIComponent(device!)}` and the backend routes by path.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebSocket device switching | Custom reconnect manager | Existing `usePreviewWS` hook — change `device` prop, effect re-runs | Already implemented with cleanup, reconnect timer, URL revocation |
| Disconnected badge | Custom status component | shadcn `Badge` in `ui/badge.tsx` | Already installed, matches design system |
| Camera list fetch | Raw fetch in component body | `useCameras` hook pattern | Separates fetch lifecycle from render, enables `refresh()` call from multiple trigger points |
| Assignment persistence | Optimistic update + sync | Immediate PUT on change (fire-and-forget with error logging) | Matches existing region auto-save pattern; no undo needed |

**Key insight:** The only "new" code in this phase is glue. Every primitive (WebSocket hook, API fetch pattern, badge component, banner pattern, auto-save) already exists in the codebase.

## Common Pitfalls

### Pitfall 1: usePreviewWS disconnects when device is undefined

**What goes wrong:** `usePreviewWS(true)` with no device arg will never open a WebSocket (hook returns `null` early). If EditorCanvas doesn't pass the device prop, the canvas stays dark forever.

**Why it happens:** Phase 9 changed the hook signature to require `device` for routing. The hook disconnects intentionally when `device` is undefined.

**How to avoid:** Wire `device` prop from EditorPage state all the way to `usePreviewWS(enabled, device)` in EditorCanvas. The EditorCanvas prop interface needs `device?: string` added.

**Warning signs:** Canvas shows black/placeholder, no WS connections in browser DevTools.

### Pitfall 2: Zone selector and streaming config selector are currently the same element

**What goes wrong:** LightPanel currently has a `<select>` for entertainment config that is also used to drive the `startStreaming()` call. If you add a second zone selector at the top of LightPanel for camera assignment purposes, you'll have two sources of truth for `selectedConfigId`.

**Why it happens:** The existing zone select is inside LightPanel's local state, tightly coupled to streaming controls.

**How to avoid:** After lifting `selectedConfigId` to EditorPage, remove the local `selectedConfigId` state from LightPanel and use the prop version everywhere (streaming start, channel fetch, camera assignment).

**Warning signs:** Streaming starts with a different config than the camera dropdown shows.

### Pitfall 3: Stable ID vs device path confusion

**What goes wrong:** `PUT /api/cameras/assignments/{config_id}` body requires `camera_stable_id` (e.g., `usb-0403:6010-00000000`). The `?device=` WebSocket param requires `device_path` (e.g., `/dev/video0`). Mixing them causes 404s from the assignment endpoint or failed WS connections.

**Why it happens:** The cameras API returns both fields; it's easy to pass the wrong one to the wrong destination.

**How to avoid:** When the user selects a camera, store the full `CameraDevice` object (or both fields separately): use `stable_id` for `PUT /api/cameras/assignments`, use `device_path` for `setSelectedDevice` (WS param).

**Warning signs:** Assignment PUT returns 404 ("stable_id not found"), or WS connection fails silently.

### Pitfall 4: usePreviewWS test breaks after device param becomes required

**What goes wrong:** `usePreviewWS.test.ts` line 41 calls `renderHook(() => usePreviewWS(true))` with no device arg. After Phase 9, the hook already requires device — but the test still passes because the hook silently disconnects when device is undefined. If the test asserts a WS connection was opened, it will fail.

**Why it happens:** The test was written before the device param was mandatory.

**How to avoid:** Update `usePreviewWS.test.ts` to pass a device string: `usePreviewWS(true, '/dev/video0')`. The mock WS URL assertion on line 43 (`toContain('/ws/preview')`) will then also need to check for the device query param.

**Warning signs:** `npx vitest run` fails on `usePreviewWS.test.ts` after EditorCanvas changes.

### Pitfall 5: "Select camera..." placeholder with value=""

**What goes wrong:** Sending `camera_stable_id: ""` to the PUT endpoint returns 404 (empty string is not in known_cameras). Calling `setSelectedDevice(undefined)` must NOT trigger a PUT.

**Why it happens:** `onChange` fires when the placeholder option is selected.

**How to avoid:** Guard the auto-save handler: `if (!selectedCameraStableId) return`.

## Code Examples

Verified patterns from existing codebase:

### CameraDevice TypeScript interface (from cameras.py Pydantic model)
```typescript
// api/cameras.ts — NEW FILE
export interface CameraDevice {
  device_path: string
  stable_id: string
  display_name: string
  connected: boolean
  last_seen_at: string | null
}

export interface ZoneHealth {
  entertainment_config_id: string
  camera_name: string
  camera_stable_id: string
  connected: boolean
  device_path: string | null
}

export interface CamerasResponse {
  devices: CameraDevice[]
  identity_mode: string  // "stable" | "degraded"
  cameras_available: boolean
  zone_health: ZoneHealth[]
}

export async function getCameras(): Promise<CamerasResponse> {
  const res = await fetch('/api/cameras')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function putCameraAssignment(
  configId: string,
  cameraStableId: string,
  cameraName: string,
): Promise<void> {
  const res = await fetch(`/api/cameras/assignments/${configId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ camera_stable_id: cameraStableId, camera_name: cameraName }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}
```

### Camera dropdown label format (CMUI-02)
```typescript
// Display format: "USB Capture Card (/dev/video0)"
const label = `${device.display_name} (${device.device_path})`
```

### EditorCanvas — adding device prop
```typescript
// EditorCanvas.tsx
export interface EditorCanvasProps {
  width: number
  height: number
  onDeleteRequest?: () => void
  device?: string  // ADD THIS
}

export function EditorCanvas({ width, height, onDeleteRequest, device }: EditorCanvasProps) {
  const imgSrc = usePreviewWS(true, device)  // WIRE device HERE
  // ... rest unchanged
}
```

### Badge usage for disconnected state
```typescript
// Source: Frontend/src/components/ui/badge.tsx (already installed)
import { Badge } from '@/components/ui/badge'

// In LightPanel camera section:
{isDisconnected && (
  <Badge variant="destructive" className="text-[10px] px-1.5 py-0.5">
    Disconnected
  </Badge>
)}
```

### Refresh button icon (no new icon library needed — inline SVG)
```tsx
<button
  onClick={refresh}
  className="p-0.5 text-muted-foreground hover:text-foreground"
  title="Refresh camera list"
>
  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
  </svg>
</button>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `usePreviewWS(true)` no device | `usePreviewWS(true, device?)` — disconnects when device=undefined | Phase 9 | EditorCanvas must now pass device |
| Global single capture device | CaptureRegistry keyed by device path | Phase 8 | Preview WS routes by device_path param |
| No zone_health in API | `GET /api/cameras` includes `zone_health[]` | Phase 9 | Frontend can pre-select assigned camera per zone |
| No camera assignments table | `camera_assignments` table with `PUT /api/cameras/assignments/{id}` | Phase 7 | Frontend saves assignments immediately |

## Open Questions

1. **Does `usePreviewWS.test.ts` already fail on device=undefined?**
   - What we know: The test calls `usePreviewWS(true)` (no device). Since Phase 9, the hook exits early when device is undefined and no WS is opened. The test asserts `instances.toHaveLength(1)` — this will fail.
   - What's unclear: Whether Phase 9 updated this test already or left it broken.
   - Recommendation: Run `npx vitest run` before any changes to establish baseline. Fix test in Wave 0 if it's already failing.

2. **Does the zone selector in LightPanel need to control streaming?**
   - What we know: The current zone `<select>` in LightPanel drives both `fetchConfigChannels` and the `startStreaming()` call.
   - What's unclear: After lifting to EditorPage, whether the streaming toggle should use `selectedConfigId` from EditorPage props or have its own local override.
   - Recommendation: Use the lifted prop everywhere. The streaming config and the camera assignment config should always be the same zone. This is the correct behavior (D-06).

## Environment Availability

Step 2.6: SKIPPED — this phase is purely frontend code changes. No external tool dependencies beyond the existing Docker stack and Node 20+ (already confirmed in use).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest + @testing-library/react |
| Config file | `Frontend/vitest.config.ts` |
| Quick run command | `cd Frontend && npx vitest run` |
| Full suite command | `cd Frontend && npx vitest run` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CMUI-01 | Camera dropdown renders in LightPanel with zone selector above it | unit | `cd Frontend && npx vitest run --reporter=verbose src/components/LightPanel.test.tsx` | ❌ Wave 0 |
| CMUI-02 | Dropdown option text matches "display_name (device_path)" format | unit | `cd Frontend && npx vitest run --reporter=verbose src/components/LightPanel.test.tsx` | ❌ Wave 0 |
| CMUI-03 | Changing device prop on EditorCanvas changes usePreviewWS device param | unit | `cd Frontend && npx vitest run --reporter=verbose src/hooks/usePreviewWS.test.ts` | ✅ (needs update) |

### Sampling Rate
- **Per task commit:** `cd Frontend && npx vitest run`
- **Per wave merge:** `cd Frontend && npx vitest run`
- **Phase gate:** Full vitest suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `Frontend/src/components/LightPanel.test.tsx` — covers CMUI-01, CMUI-02 (zone and camera dropdown rendering, option format)
- [ ] `Frontend/src/api/cameras.test.ts` — covers `getCameras()` and `putCameraAssignment()` fetch wrappers
- [ ] Update `Frontend/src/hooks/usePreviewWS.test.ts` — pass `device` arg to `renderHook(() => usePreviewWS(true, '/dev/video0'))` to fix baseline failure

## Sources

### Primary (HIGH confidence)
- `Frontend/src/hooks/usePreviewWS.ts` — read directly; device param and disconnect-on-undefined behavior confirmed
- `Frontend/src/components/LightPanel.tsx` — read directly; current state, no device integration
- `Frontend/src/components/EditorCanvas.tsx` — read directly; `usePreviewWS(true)` call with no device
- `Frontend/src/components/EditorPage.tsx` — read directly; state to be lifted from here
- `Backend/routers/cameras.py` — read directly; CameraDevice/ZoneHealth schema, PUT body shape confirmed
- `Frontend/src/api/regions.ts` — read directly; auto-save pattern (updateRegion)
- `Frontend/src/components/ui/badge.tsx` — confirmed exists; shadcn Badge available

### Secondary (MEDIUM confidence)
- `Frontend/src/hooks/usePreviewWS.test.ts` — existing test needs update; device param not yet passed

### Tertiary (LOW confidence)
- None — all findings from direct codebase inspection

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all verified by direct file inspection
- Architecture: HIGH — state lifting pattern confirmed by existing component structure
- Pitfalls: HIGH — all confirmed by reading actual code (stable_id vs device_path distinction from cameras.py, device=undefined behavior from usePreviewWS.ts)

**Research date:** 2026-04-07
**Valid until:** 2026-05-07 (stable codebase — no external dependencies to become stale)
