import { useEffect, useRef, useState } from 'react'
import { DrawingToolbar } from './DrawingToolbar'
import { EditorCanvas, handleEditorDelete } from './EditorCanvas'
import { LightPanel } from './LightPanel'

export function EditorPage() {
  const containerRef = useRef<HTMLDivElement>(null)
  const [canvasWidth, setCanvasWidth] = useState(640)
  const canvasHeight = Math.round(canvasWidth * (3 / 4)) // 4:3 to match 640x480 capture

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        const w = Math.floor(entry.contentRect.width)
        setCanvasWidth(w)
      }
    })
    observer.observe(container)

    // Set initial size
    setCanvasWidth(Math.floor(container.clientWidth))

    return () => observer.disconnect()
  }, [])

  return (
    <div className="flex h-full min-h-0">
      {/* Left: canvas area ~70% */}
      <div className="flex flex-col flex-[7]">
        <DrawingToolbar onDelete={handleEditorDelete} />
        <div ref={containerRef} className="flex-1 overflow-hidden bg-black">
          <EditorCanvas
            width={canvasWidth}
            height={canvasHeight}
            onDeleteRequest={handleEditorDelete}
          />
        </div>
      </div>

      {/* Right: light panel ~30% */}
      <div className="flex flex-[3] min-h-0 overflow-hidden">
        <LightPanel />
      </div>
    </div>
  )
}
