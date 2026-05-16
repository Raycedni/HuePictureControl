import { useMemo, useState } from 'react'
import { Popover } from '@base-ui/react'

import { useRegionStore } from '@/store/useRegionStore'
import {
  patchRegionOrientation,
  type WledOrientation,
} from '@/api/wled'
import { segmentName, type WledSegment } from '@/utils/wled-segment'
import { channelColor } from '@/utils/wled-palette'

import { OrientationSegmentedControl } from './OrientationSegmentedControl'

interface Props {
  canvasWidth: number
  canvasHeight: number
  canvasContainerEl: HTMLElement | null
  selectedConfigId: string
  /**
   * Per-device segment cache keyed by device id. EditorCanvas loads this via
   * getWledDevices + listSegments (Plan 19.1-08) and passes it down. Each
   * `seg.seg_index` IS the palette index per D-09 — no sort-position resolver
   * needed. Chip color = `channelColor(a.seg_index)` for every assignment.
   */
  segsByDevice: Record<string, WledSegment[]>
}

/**
 * Region orientation popover — per-region narrowing (CONTEXT.md D-19/D-22).
 *
 * Renders ONE OrientationSegmentedControl per region (not per assignment) plus
 * a read-only list of the WLED segments assigned to that region. Anchored via
 * Base UI's virtual-anchor pattern to the selected region's screen-coord bbox.
 *
 * Phase 19.1 D-13: the assignment list is keyed by composite
 * `(wled_device_id, seg_index)` — `segmentName(seg)` resolves the display name
 * (with D-08 fallback), and `channelColor(seg_index)` paints the chip.
 */
export function RegionOrientationPopover({
  canvasWidth,
  canvasHeight,
  canvasContainerEl,
  selectedConfigId,
  segsByDevice,
}: Props) {
  const selectedId = useRegionStore((s) => s.selectedId)
  const regions = useRegionStore((s) => s.regions)
  const wledAssignments = useRegionStore((s) => s.wledAssignments)
  const setSelectedId = useRegionStore((s) => s.setSelectedId)
  const updateWledAssignmentOrientation = useRegionStore(
    (s) => s.updateWledAssignmentOrientation,
  )
  const [saveError, setSaveError] = useState<string | null>(null)

  const region = useMemo(
    () => regions.find((r) => r.id === selectedId) ?? null,
    [regions, selectedId],
  )
  const assignments = selectedId ? wledAssignments[selectedId] ?? [] : []

  // Per-region invariant: all assignments share the same orientation.
  const currentOrientation: WledOrientation =
    assignments[0]?.orientation ?? 'auto'

  const virtualAnchor = useMemo(() => {
    if (!region || !canvasContainerEl) return null
    return {
      getBoundingClientRect: (): DOMRect => {
        const canvasRect = canvasContainerEl.getBoundingClientRect()
        // Region.polygon is normalized [0..1]; convert to pixels then to screen coords.
        const pts = region.polygon as [number, number][]
        let minX = Infinity,
          minY = Infinity,
          maxX = -Infinity,
          maxY = -Infinity
        for (const [x, y] of pts) {
          const px = x * canvasWidth
          const py = y * canvasHeight
          if (px < minX) minX = px
          if (py < minY) minY = py
          if (px > maxX) maxX = px
          if (py > maxY) maxY = py
        }
        const left = canvasRect.left + minX
        const top = canvasRect.top + minY
        const width = maxX - minX
        const height = maxY - minY
        return new DOMRect(left, top, width, height)
      },
    }
  }, [region, canvasContainerEl, canvasWidth, canvasHeight])

  const open = selectedId !== null && region !== null

  async function handleOrientationChange(next: WledOrientation) {
    if (!selectedId || !selectedConfigId) return
    if (assignments.length === 0) return
    setSaveError(null)
    const prev = currentOrientation
    // Optimistic update.
    updateWledAssignmentOrientation(selectedId, next)
    try {
      await patchRegionOrientation(selectedId, selectedConfigId, next)
    } catch (err) {
      console.error('Failed to patch region orientation:', err)
      updateWledAssignmentOrientation(selectedId, prev)
      setSaveError("Couldn't save. Retry?")
    }
  }

  if (!virtualAnchor) return null

  return (
    <Popover.Root
      open={open}
      onOpenChange={() => {
        // Selection is owned by the canvas. The popover purely follows
        // selectedId — it does NOT clear it on outside-click, because Base UI
        // fires onOpenChange(false) for every click outside the popup
        // (including clicks landing on another region), which would race
        // RegionPolygon's onClick and clobber the new selection. The explicit
        // × button below calls setSelectedId(null) directly.
      }}
    >
      <Popover.Portal>
        <Popover.Positioner
          anchor={virtualAnchor}
          side="bottom"
          align="start"
          sideOffset={12}
          collisionPadding={8}
        >
          <Popover.Popup
            className="region-orientation-popover"
            style={{
              width: 280,
              background: 'rgba(20, 20, 35, 0.96)',
              border: '1px solid var(--glass-border)',
              borderRadius: 8,
              padding: 12,
              boxShadow:
                'rgba(0,0,0,0.5) 0 10px 30px -5px, rgba(0,0,0,0.3) 0 4px 10px -2px',
              backdropFilter: 'blur(12px)',
              zIndex: 50,
            }}
            data-testid="region-orientation-popover"
          >
            <Popover.Arrow
              style={{
                width: 12,
                height: 12,
                background: 'rgba(20,20,35,0.96)',
                borderLeft: '1px solid var(--glass-border)',
                borderTop: '1px solid var(--glass-border)',
                transform: 'rotate(45deg)',
              }}
            />

            <div className="flex items-center justify-between mb-3">
              <h4 className="text-sm font-semibold text-foreground">
                {region!.name}
                {assignments.length > 0 && (
                  <>
                    {' · '}
                    {assignments.length}{' '}
                    {assignments.length === 1 ? 'segment' : 'segments'}
                  </>
                )}
              </h4>
              <button
                type="button"
                aria-label="Close orientation panel"
                onClick={() => setSelectedId(null)}
                className="text-muted-foreground hover:text-foreground text-base leading-none"
              >
                ×
              </button>
            </div>

            {assignments.length === 0 ? (
              <p
                className="text-xs text-muted-foreground"
                data-testid="region-orientation-popover-empty"
              >
                Drag a segment from the LightPanel to add an assignment.
              </p>
            ) : (
              <>
                <p className="text-[10px] font-mono text-muted-foreground mb-1">
                  Sample axis
                </p>
                <OrientationSegmentedControl
                  value={currentOrientation}
                  onChange={handleOrientationChange}
                />

                {saveError && (
                  <p className="text-[10px] text-red-400 mt-1">{saveError}</p>
                )}

                <p className="text-[10px] font-mono text-muted-foreground mt-3 mb-1">
                  Segments in this region
                </p>
                <div className="flex flex-col gap-1">
                  {assignments.map((a) => {
                    // Phase 19.1 D-09: chip color is channelColor(seg_index)
                    // directly — seg_index IS the palette index, no per-device
                    // sort-position resolver needed. This guarantees parity
                    // with the LightPanel chip and the strip painter zone for
                    // the same (device_id, seg_index) pair.
                    const seg = (segsByDevice[a.wled_device_id] ?? []).find(
                      (s) => s.seg_index === a.seg_index,
                    )
                    const displayName = seg
                      ? segmentName(seg)
                      : `Segment ${a.seg_index}`
                    const compositeKey = `${a.wled_device_id}:${a.seg_index}`
                    return (
                      <div
                        key={compositeKey}
                        className="flex items-center gap-2 text-xs"
                      >
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ background: channelColor(a.seg_index) }}
                          data-testid={`region-orientation-popover-chip-${a.wled_device_id}-${a.seg_index}`}
                        />
                        <span className="truncate text-foreground/80">
                          {displayName}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </>
            )}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  )
}
