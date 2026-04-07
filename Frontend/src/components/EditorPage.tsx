import { useEffect, useRef, useState } from 'react'
import { DrawingToolbar } from './DrawingToolbar'
import { EditorCanvas, handleEditorDelete } from './EditorCanvas'
import { LightPanel } from './LightPanel'
import { useRegionStore } from '@/store/useRegionStore'
import { useCameras } from '@/hooks/useCameras'

export function EditorPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [canvasDims, setCanvasDims] = useState({ width: 640, height: 360 })
  const [identityMode, setIdentityMode] = useState<string | null>(null)
  const [selectedConfigId, setSelectedConfigId] = useState<string>('')
  const [selectedDevice, setSelectedDevice] = useState<string | undefined>(undefined)
  const cameras = useCameras()

  const regions = useRegionStore((s) => s.regions)
  const assignedCount = regions.filter((r) => r.light_id !== null).length

  useEffect(() => {
    if (cameras.data) {
      setIdentityMode(cameras.data.identity_mode)
    }
  }, [cameras.data])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    function fitCanvas(containerW: number, containerH: number) {
      const w = Math.floor(containerW)
      const h = Math.floor(containerH)
      if (w <= 0 || h <= 0) return
      // Fit 16:9 within available space
      const byWidth = { width: w, height: Math.round(w * 9 / 16) }
      if (byWidth.height <= h) {
        setCanvasDims(byWidth)
      } else {
        // Height-constrained
        const fitW = Math.round(h * 16 / 9)
        setCanvasDims({ width: fitW, height: h })
      }
    }

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        fitCanvas(entry.contentRect.width, entry.contentRect.height)
      }
    })
    observer.observe(container)

    // Set initial size
    fitCanvas(container.clientWidth, container.clientHeight)

    return () => observer.disconnect()
  }, [])

  return (
    <div className="flex flex-col md:flex-row flex-1 min-h-0 text-left">
      {/* Left: canvas area ~70% */}
      <div className="flex flex-col flex-1 md:flex-[7] min-h-0">
        <DrawingToolbar onDelete={handleEditorDelete} />
        {identityMode === 'degraded' && (
          <div className="bg-amber-500/10 border border-amber-500/25 text-amber-400 text-xs px-3 py-2 text-center">
            Device identity is limited to capture card name. Devices may be misidentified if multiple identical cards are connected.
          </div>
        )}
        {cameras.data && !cameras.data.cameras_available && (
          <div className="bg-red-500/10 border border-red-500/25 text-red-400 text-xs px-3 py-2 text-center">
            No capture devices detected. Connect a USB capture card and click refresh.
          </div>
        )}
        {assignedCount > 20 && (
          <div className="bg-yellow-500/10 border border-yellow-500/30 text-yellow-600 dark:text-yellow-400 text-xs px-3 py-2 text-center">
            {assignedCount}/20 channels assigned — bridge will ignore excess channels.
          </div>
        )}
        <div ref={containerRef} className="flex-1 overflow-hidden min-h-[200px]">
          <EditorCanvas
            width={canvasDims.width}
            height={canvasDims.height}
            onDeleteRequest={handleEditorDelete}
            device={selectedDevice}
          />
        </div>
      </div>

      {/* Right (desktop) / Bottom (mobile): light panel */}
      <div className="flex md:flex-[3] min-h-0 overflow-hidden max-h-[40vh] md:max-h-none border-t md:border-t-0 border-white/[0.06]">
        <LightPanel
          selectedConfigId={selectedConfigId}
          onConfigChange={setSelectedConfigId}
          selectedDevice={selectedDevice}
          onDeviceChange={setSelectedDevice}
          camerasData={cameras.data}
          onCamerasRefresh={cameras.refresh}
        />
      </div>
    </div>
  )
}
