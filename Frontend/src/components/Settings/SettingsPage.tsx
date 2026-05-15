// Phase 17 D-17 / D-20 (UI follow-up): top-level Settings page.
//
// SettingsPanel is the modal variant launched from EditorPage's floating
// button. SettingsPage is the same content rendered as a full-page view
// for the Settings tab — discoverable from the main nav without entering
// the editor first. Both surfaces share WledDevicesPanel so behavior and
// data flow are identical.
//
// Phase 19.1 Plan 07: strip is now a read-only segment visualizer (D-06)
// with a per-device Refresh button (D-03); sidebar is a read-only metadata
// panel (D-07). Selection lives in a composite {device_id, seg_index}
// shape lifted from the strip into the page. SettingsPanel.tsx mirrors
// this same wiring (RESEARCH.md Pitfall 6: both surfaces must stay in sync).

import { useState } from 'react'
import { WledDevicesPanel } from './WledDevicesPanel'
import { WledStripPainter } from './WledStripPainter'
import { WledChannelSidebar } from './WledChannelSidebar'

export function SettingsPage() {
  const [selectedSeg, setSelectedSeg] = useState<
    { device_id: string; seg_index: number } | null
  >(null)

  return (
    <div className="flex flex-col flex-1 min-h-0 p-4 text-left" data-testid="settings-page">
      <h2 className="text-sm font-semibold mb-3">Settings</h2>
      <div className="flex-1 flex flex-col md:flex-row gap-4 min-h-0">
        {/* Phase 19.1: paint canvas slot now hosts the read-only strip view + metadata sidebar. */}
        <div className="hidden md:flex md:flex-[6] flex-col gap-3 min-h-[200px]">
          <WledStripPainter
            selectedSeg={selectedSeg}
            onSelectSegment={(seg, deviceId) =>
              setSelectedSeg({ device_id: deviceId, seg_index: seg.seg_index })
            }
          />
          <WledChannelSidebar
            selectedSeg={selectedSeg}
            onClear={() => setSelectedSeg(null)}
          />
        </div>
        <div className="flex-1 md:flex-[4] overflow-auto">
          <WledDevicesPanel />
        </div>
      </div>
    </div>
  )
}
