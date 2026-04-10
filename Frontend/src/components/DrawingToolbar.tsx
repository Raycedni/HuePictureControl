import { Button } from '@/components/ui/button'
import { useRegionStore } from '@/store/useRegionStore'
import { deleteAllRegions } from '@/api/regions'

interface DrawingToolbarProps {
  onDelete: () => void
}

export function DrawingToolbar({ onDelete }: DrawingToolbarProps) {
  const drawingMode = useRegionStore((s) => s.drawingMode)
  const setDrawingMode = useRegionStore((s) => s.setDrawingMode)
  const setRegions = useRegionStore((s) => s.setRegions)
  const setSelectedId = useRegionStore((s) => s.setSelectedId)

  async function handleClearAll() {
    try {
      await deleteAllRegions()
      setRegions([])
      setSelectedId(null)
    } catch (err) {
      console.error('Failed to clear regions:', err)
    }
  }

  const modeBtn = (_mode: string, active: boolean) =>
    active
      ? 'bg-hue-orange/15 text-hue-amber border-hue-orange/30 hover:bg-hue-orange/20'
      : 'bg-white/[0.03] text-muted-foreground border-white/[0.08] hover:bg-white/[0.06] hover:text-foreground'

  return (
    <div className="flex flex-wrap gap-1.5 px-3 py-2 border-b border-white/[0.06] bg-white/[0.02]">
      <Button
        className={modeBtn('rectangle', drawingMode === 'rectangle')}
        size="sm"
        onClick={() => setDrawingMode('rectangle')}
      >
        Rectangle
      </Button>
      <Button
        className={modeBtn('polygon', drawingMode === 'polygon')}
        size="sm"
        onClick={() => setDrawingMode('polygon')}
      >
        Polygon
      </Button>
      <Button
        className={modeBtn('select', drawingMode === 'select')}
        size="sm"
        onClick={() => setDrawingMode('select')}
      >
        Select
      </Button>
      <div className="w-px bg-white/[0.08] mx-1" />
      <Button
        variant="outline"
        size="sm"
        onClick={onDelete}
        className="border-white/[0.08] text-muted-foreground hover:text-foreground"
      >
        Delete
      </Button>
      <Button
        size="sm"
        onClick={handleClearAll}
        className="bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500/20"
      >
        Clear All
      </Button>
    </div>
  )
}
