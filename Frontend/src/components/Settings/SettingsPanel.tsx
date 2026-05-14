// Phase 17 D-17 / D-20: Settings panel hosts WLED device CRUD now and the
// Phase 19 paint canvas. The placeholder slot reserved in Phase 17 has been
// replaced with WledStripPainter + WledChannelSidebar in Phase 19 Plan 10.

import { useState } from 'react'
import { WledDevicesPanel } from './WledDevicesPanel'
import { WledStripPainter } from './WledStripPainter'
import { WledChannelSidebar } from './WledChannelSidebar'

interface Props {
  onClose: () => void
}

export function SettingsPanel({ onClose }: Props) {
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null)
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null)
  const [refreshTrigger, setRefreshTrigger] = useState(0)

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
          <div className="flex-1 md:flex-[4]">
            <WledDevicesPanel />
          </div>
        </div>
      </div>
    </div>
  )
}
