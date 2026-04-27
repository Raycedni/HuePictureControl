// Phase 17 D-17 / D-20 (UI follow-up): top-level Settings page.
//
// SettingsPanel is the modal variant launched from EditorPage's floating
// button. SettingsPage is the same content rendered as a full-page view
// for the Settings tab — discoverable from the main nav without entering
// the editor first. Both surfaces share WledDevicesPanel so behavior and
// data flow are identical.

import { WledDevicesPanel } from './WledDevicesPanel'

export function SettingsPage() {
  return (
    <div className="flex flex-col flex-1 min-h-0 p-4 text-left" data-testid="settings-page">
      <h2 className="text-sm font-semibold mb-3">Settings</h2>
      <div className="flex-1 flex flex-col md:flex-row gap-4 min-h-0">
        {/* D-20: Phase 19 paint canvas slot. */}
        <div
          className="hidden md:flex md:flex-[6] items-center justify-center border border-dashed border-white/[0.1] rounded text-xs text-muted-foreground min-h-[200px]"
          data-testid="paint-canvas-placeholder"
        >
          WLED strip paint canvas (Phase 19)
        </div>
        <div className="flex-1 md:flex-[4] overflow-auto">
          <WledDevicesPanel />
        </div>
      </div>
    </div>
  )
}
