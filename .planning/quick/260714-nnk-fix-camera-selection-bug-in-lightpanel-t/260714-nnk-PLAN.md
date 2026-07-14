---
phase: quick-260714-nnk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - Frontend/src/components/EditorPage.tsx
  - Frontend/src/components/LightPanel.tsx
  - Frontend/src/components/LightPanel.test.tsx
autonomous: true
requirements: [BFIX-CAM-STABLEID]

must_haves:
  truths:
    - "Selecting a connected camera from the dropdown persists that camera's OWN stable_id (never a stale/disconnected device sharing the same device_path)"
    - "The camera dropdown lists only connected devices"
    - "The Disconnected badge reflects the connected/disconnected state of the actually-selected camera"
    - "Live preview WS still connects using a real device_path (resolved from the selected stable_id)"
    - "A regression test reproduces the device_path-collision scenario and passes"
  artifacts:
    - path: "Frontend/src/components/LightPanel.tsx"
      provides: "Camera selection keyed by stable_id end-to-end"
      contains: "d.stable_id === selectedDevice"
    - path: "Frontend/src/components/EditorPage.tsx"
      provides: "stable_id-based selection state + device_path resolution for the WS/preview flow"
    - path: "Frontend/src/components/LightPanel.test.tsx"
      provides: "Regression coverage for the device_path collision"
  key_links:
    - from: "Frontend/src/components/LightPanel.tsx <select value>"
      to: "camerasData.devices[].stable_id"
      via: "option value = d.stable_id"
      pattern: "value=\\{d\\.stable_id\\}"
    - from: "Frontend/src/components/EditorPage.tsx"
      to: "EditorCanvas device prop"
      via: "resolve device_path from selected stable_id at point of use"
      pattern: "stable_id === selectedDevice"
---

<objective>
Fix the camera selection bug in `LightPanel.tsx` where the selected camera is tracked by `device_path` instead of `stable_id`. Because `/api/cameras` can return multiple device records sharing the same `device_path` (one stale/disconnected + one live/connected, produced when a capture device is swapped on the same USB port), `Array.find(d => d.device_path === selectedDevice)` returns the FIRST match — which can be the wrong (stale, disconnected) record. This causes: wrong `stable_id` persisted to `camera_assignments`, wrong `stable_id` for `putLastZone`, and a false "Disconnected" badge on a connected camera.

Purpose: Track camera identity by the unique `stable_id` end-to-end (selection state, prop contract, `<select>` value, and all `.find()` lookups). Resolve `device_path` from `stable_id` only at the single point where a real `device_path` is required (the preview WebSocket).

Output: `LightPanel.tsx` + `EditorPage.tsx` refactored to a stable_id identity key, and a regression test in `LightPanel.test.tsx` reproducing the collision.
</objective>

<execution_context>
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/STATE.md

<interfaces>
<!-- Executor should use these directly — no codebase exploration needed. -->

From Frontend/src/api/cameras.ts:
```typescript
export interface CameraDevice {
  device_path: string
  stable_id: string          // UNIQUE identity key — use this for selection
  display_name: string
  connected: boolean
  last_seen_at: string | null
  last_entertainment_config_id: string | null
}

export interface ZoneHealth {
  entertainment_config_id: string
  camera_name: string
  camera_stable_id: string   // use this (NOT device_path) to set selection from zone_health
  connected: boolean
  device_path: string | null
}

export interface CamerasResponse {
  devices: CameraDevice[]
  identity_mode: string
  cameras_available: boolean
  zone_health: ZoneHealth[]
}

// PUT uses stable_id:
putCameraAssignment(configId, cameraStableId, cameraName): Promise<void>
putLastZone(stableId, entertainmentConfigId): Promise<void>
```

Downstream consumer that needs a REAL device_path (not stable_id):
- `EditorPage.tsx` passes `device={selectedDevice}` to `EditorCanvas`, which threads it to
  `usePreviewWS(enabled, device)`, which opens `ws://.../ws/preview?device=<device_path>`.
  The backend WS still expects a device_path. Resolve device_path from the selected
  stable_id in EditorPage before passing to EditorCanvas. Do NOT change EditorCanvas or
  usePreviewWS.

Selection state ownership: `EditorPage.tsx` owns
`const [selectedDevice, setSelectedDevice] = useState<string | undefined>(undefined)`
and passes `selectedDevice` / `onDeviceChange` to `LightPanel`. After this fix,
`selectedDevice` holds a stable_id.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Re-key camera selection from device_path to stable_id (LightPanel.tsx + EditorPage.tsx)</name>
  <files>Frontend/src/components/LightPanel.tsx, Frontend/src/components/EditorPage.tsx</files>
  <action>
Make `stable_id` the camera identity key threaded through the whole selection flow. The `selectedDevice` prop/state now holds a `stable_id`.

In `Frontend/src/components/LightPanel.tsx`:

1. `<select>` camera dropdown (~line 338-357): keep the `.filter((d) => d.connected)` (dropdown must list only connected devices). Change each `<option>` `value` from `d.device_path` to `d.stable_id` (~line 351). Keep `key={d.stable_id}` (now guaranteed unique). Keep the visible label text as `{d.display_name} ({d.device_path})` — only the option VALUE changes, not the display text.

2. `handleCameraChange` (~line 181-206): the `e.target.value` is now a stable_id — rename the local from `devicePath` to `stableId`. Look up via `camerasData?.devices.find((d) => d.stable_id === stableId)`. Call `onDeviceChange(cam.stable_id)` (not `cam.device_path`). Keep the existing `putCameraAssignment(selectedConfigId, cam.stable_id, cam.display_name)` call and the D-08 zone auto-switch logic unchanged (they already use `cam.stable_id` / `cam.last_entertainment_config_id`). Update the inline comment "use stable_id for PUT, device_path for WS" to reflect that selection is now stable_id and device_path is resolved at the WS call site in EditorPage.

3. `handleZoneChange` (~line 216): change `camerasData.devices.find((d) => d.device_path === selectedDevice)` to `d.stable_id === selectedDevice`. The subsequent `putLastZone(cam.stable_id, ...)` is unchanged.

4. `selectedCameraDisconnected` (~line 226-230): change `camerasData.devices.find((d) => d.device_path === selectedDevice)` to `d.stable_id === selectedDevice`.

5. Tier 2/3 zone pre-selection effect (~line 94-96): change `camerasData?.devices.find((d) => d.device_path === selectedDevice)` to `d.stable_id === selectedDevice`.

6. Zone-health-driven camera init effect (D-06, ~line 121-131): this currently sets selection from `zone_health` via `onDeviceChange(zoneEntry.device_path)`. Change it to use the stable id: guard on `zoneEntry.camera_stable_id` and call `onDeviceChange(zoneEntry.camera_stable_id)`; the `else` branch `onDeviceChange(undefined)` stays.

In `Frontend/src/components/EditorPage.tsx`:

7. Keep `const [selectedDevice, setSelectedDevice] = useState<string | undefined>(undefined)` (it now holds a stable_id). Before rendering `EditorCanvas`, resolve the real device_path from the selected stable_id at the point of use:
```tsx
const selectedDevicePath = cameras.data?.devices.find(
  (d) => d.stable_id === selectedDevice,
)?.device_path
```
Pass `device={selectedDevicePath}` to `<EditorCanvas>` (~line 100) instead of `device={selectedDevice}`. Do NOT modify `EditorCanvas` or `usePreviewWS` — they continue to receive/expect a device_path.

Do NOT touch `activeDevicePath` in `useStatusStore` / `useStatusWS` — that is the server-reported streaming device_path and is unrelated to the selection key.
  </action>
  <verify>
    <automated>cd Frontend && npx vitest run src/components/LightPanel.test.tsx</automated>
  </verify>
  <done>All `.find()` camera lookups in LightPanel.tsx match on `stable_id`; the dropdown option value is `d.stable_id`; the D-06 effect sets selection from `camera_stable_id`; EditorPage resolves device_path from the selected stable_id for EditorCanvas. Pre-existing camera-switch tests updated in Task 2 pass.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Update existing tests + add device_path-collision regression test</name>
  <files>Frontend/src/components/LightPanel.test.tsx</files>
  <behavior>
    - Existing tests that used `selectedDevice: '/dev/video0'` and fired `<select>` change events with `value: '/dev/video2'` now use stable_ids (`'usb-0403:6010-00000000'`, `'usb-1234:5678-00000001'`) and assert `onDeviceChange` is called with the stable_id.
    - NEW regression test "device_path collision resolves the connected device's stable_id": camerasData contains two devices sharing `device_path: '/dev/video0'` — one disconnected with the OLD stable_id (first in array) and one connected with the NEW stable_id (second). When the user selects the connected device from the dropdown, `putCameraAssignment` is called with the NEW (connected) stable_id, and `onDeviceChange` receives the NEW stable_id — never the stale first-match stable_id.
    - NEW assertion (badge): with the connected device (new stable_id) selected, the "Disconnected" badge is NOT shown; with the disconnected device (old stable_id) selected, it IS shown.
    - Dropdown lists only connected devices (the disconnected collision record is not rendered as an option).
  </behavior>
  <action>
Update `Frontend/src/components/LightPanel.test.tsx`:

1. Update `defaultProps.selectedDevice` from `'/dev/video0'` to the matching stable_id `'usb-0403:6010-00000000'`. Do the same for `wledDefaultProps.selectedDevice`.

2. In the D-08 camera-switch tests (~lines 189-243), the `fireEvent.change(cameraSelect, { target: { value: '/dev/video2' } })` calls must use the stable_id of the video2 device (`'usb-1234:5678-00000001'`), and the `onDeviceChange` assertions (e.g. `toHaveBeenCalledWith('/dev/video2')`) must expect that stable_id. The zone auto-switch assertions (`onConfigChange` with `config-2`) stay the same.

3. Leave the CMUI-02 test asserting option label text `"USB Capture Card (/dev/video0)"` unchanged — the visible label still contains device_path; only the option value changed.

4. Add a new `describe('device_path collision (BFIX-CAM-STABLEID)')` block with a fixture like:
```ts
const collisionCamerasData = {
  ...mockCamerasData,
  devices: [
    { device_path: '/dev/video0', stable_id: 'usb-OLD-disconnected',
      display_name: 'USB Video', connected: false, last_seen_at: null,
      last_entertainment_config_id: null },
    { device_path: '/dev/video0', stable_id: 'usb-NEW-connected',
      display_name: 'Elgato 4K S', connected: true, last_seen_at: null,
      last_entertainment_config_id: null },
  ],
  zone_health: [],
}
```
Tests in this block:
  - Selecting the connected device: render with `selectedConfigId: 'config-1'`, fire the camera `<select>` change with `value: 'usb-NEW-connected'`, then `await waitFor` that `putCameraAssignment` was called with `('config-1', 'usb-NEW-connected', 'Elgato 4K S')` and `onDeviceChange` with `'usb-NEW-connected'`. (Import `putCameraAssignment` from `@/api/cameras` in the test — it is already mocked.)
  - Dropdown lists only the connected device: assert the connected option label renders and the disconnected one does not (e.g. `screen.queryByText(/USB Video/)` is null while `Elgato 4K S` is present).
  - Badge correctness: render with `selectedDevice: 'usb-NEW-connected'` and assert `screen.queryByText('Disconnected')` is null; render with `selectedDevice: 'usb-OLD-disconnected'` and assert the badge IS present.

Query the camera `<select>` the same way the existing tests do (`screen.getAllByRole('combobox')[1]`, since the zone select is first). Reset streaming store state in a `beforeEach` if needed (mirror the existing `useStatusStore.setState({ isStreaming: false, activeConfigId: null })` pattern) so the camera select is enabled.
  </action>
  <verify>
    <automated>cd Frontend && npx vitest run src/components/LightPanel.test.tsx</automated>
  </verify>
  <done>All LightPanel tests pass, including the new collision block asserting the connected device's stable_id is persisted, only connected devices are listed, and the Disconnected badge tracks the selected device's real connection state.</done>
</task>

</tasks>

<verification>
Full frontend suite is green (no regressions in EditorPage/EditorCanvas/preview flow):
`cd Frontend && npx vitest run`
</verification>

<success_criteria>
- `LightPanel.tsx` and `EditorPage.tsx` key camera selection on `stable_id`; the only place a `device_path` is produced is resolved from the selected stable_id for the preview WS.
- Regression test reproduces the two-records-same-device_path scenario and proves the connected device's stable_id is used.
- `cd Frontend && npx vitest run` passes.
</success_criteria>

<output>
After completion, create `.planning/quick/260714-nnk-fix-camera-selection-bug-in-lightpanel-t/260714-nnk-SUMMARY.md`
</output>
