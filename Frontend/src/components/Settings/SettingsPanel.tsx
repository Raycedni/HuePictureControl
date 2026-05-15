// Phase 17 D-17 / D-20: Settings panel hosts WLED device CRUD and the
// WLED strip view. Phase 19 used a paint canvas + sidebar with editable
// channels; Phase 19.1 Plan 07 turns the strip into a read-only segment
// visualizer (D-06) with a per-device Refresh button (D-03) and a
// metadata-only sidebar (D-07). Selection is lifted into one composite
// state shape: {device_id, seg_index} | null.

import { useState } from 'react'
import { WledDevicesPanel } from './WledDevicesPanel'
import { WledStripPainter } from './WledStripPainter'
import { WledChannelSidebar } from './WledChannelSidebar'

interface Props {
  onClose: () => void
}

export function SettingsPanel({ onClose }: Props) {
  const [selectedSeg, setSelectedSeg] = useState<
    { device_id: string; seg_index: number } | null
  >(null)

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-title"
    >
      <div className="relative bg-[#0f1115] border border-white/[0.08] rounded-lg w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <header className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
          <h2 id="settings-title" className="text-sm font-semibold">
            Settings
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings"
            className="text-muted-foreground hover:text-foreground text-lg leading-none"
          >
            ×
          </button>
        </header>
        <div className="flex-1 overflow-auto p-4 flex flex-col md:flex-row gap-4">
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
          <div className="flex-1 md:flex-[4]">
            <WledDevicesPanel />
          </div>
        </div>
      </div>
    </div>
  )
}
