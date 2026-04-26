// Phase 17 D-17 / D-20: Settings panel hosts WLED device CRUD now and the
// Phase 19 paint canvas later. The dashed placeholder slot reserves the
// canvas area in the layout so Phase 19 can drop its component in without
// re-shaping the modal.

import { WledDevicesPanel } from './WledDevicesPanel'

interface Props {
  onClose: () => void
}

export function SettingsPanel({ onClose }: Props) {
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
          {/* D-20: Phase 19 paint canvas slot. Hidden on mobile so the
              device CRUD always fits; reappears at md+ alongside the
              device list. */}
          <div
            className="hidden md:flex md:flex-[6] items-center justify-center border border-dashed border-white/[0.1] rounded text-xs text-muted-foreground min-h-[200px]"
            data-testid="paint-canvas-placeholder"
          >
            WLED strip paint canvas (Phase 19)
          </div>
          <div className="flex-1 md:flex-[4]">
            <WledDevicesPanel />
          </div>
        </div>
      </div>
    </div>
  )
}
