// Phase 17 D-17 / D-20 (UI follow-up): top-level Settings page.
//
// SettingsPanel is the modal variant launched from EditorPage's floating
// button. SettingsPage is the same content rendered as a full-page view
// for the Settings tab — discoverable from the main nav without entering
// the editor first. Both surfaces share WledDevicesPanel so behavior and
// data flow are identical.
//
// Phase 19 Plan 10: placeholder replaced with WledStripPainter + WledChannelSidebar.

import { useState } from 'react'
import { WledDevicesPanel } from './WledDevicesPanel'
import { WledStripPainter } from './WledStripPainter'
import { WledChannelSidebar } from './WledChannelSidebar'

export function SettingsPage() {
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null)
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null)
  const [refreshTrigger, setRefreshTrigger] = useState(0)

  return (
    <div className="flex flex-col flex-1 min-h-0 p-4 text-left" data-testid="settings-page">
      <h2 className="text-sm font-semibold mb-3">Settings</h2>
      <div className="flex-1 flex flex-col md:flex-row gap-4 min-h-0">
        {/* Phase 19: paint canvas slot now hosts WledStripPainter + sidebar. */}
        <div className="hidden md:flex md:flex-[6] flex-col gap-3 min-h-[200px]">
          <WledStripPainter
            selectedChannelId={selectedChannelId}
            onSelectChannel={(cid, did) => {
              setSelectedChannelId(cid)
              setSelectedDeviceId(did)
            }}
            refreshTrigger={refreshTrigger}
          />
          <WledChannelSidebar
            selectedChannelId={selectedChannelId}
            selectedDeviceId={selectedDeviceId}
            onChange={() => setRefreshTrigger((n) => n + 1)}
            onClear={() => {
              setSelectedChannelId(null)
              setSelectedDeviceId(null)
            }}
          />
        </div>
        <div className="flex-1 md:flex-[4] overflow-auto">
          <WledDevicesPanel />
        </div>
      </div>
    </div>
  )
}
