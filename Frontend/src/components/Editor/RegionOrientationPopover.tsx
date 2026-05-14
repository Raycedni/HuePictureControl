import { useMemo, useState } from 'react'
import { Popover } from '@base-ui/react'

import { useRegionStore } from '@/store/useRegionStore'
import {
  patchRegionOrientation,
  type WledChannel,
  type WledOrientation,
} from '@/api/wled'
import { channelColor } from '@/utils/wled-palette'

import { OrientationSegmentedControl } from './OrientationSegmentedControl'

interface Props {
  canvasWidth: number
  canvasHeight: number
  canvasContainerEl: HTMLElement | null
  selectedConfigId: string
  /**
   * Per-device channel map keyed by device id. EditorCanvas already loads this
   * via getWledDevices + listWledChannels (see Plan 19-11 pattern) and passes
   * it down. Channels in each device's list MUST be sorted by start_led
   * ascending — the sorted index in that list IS the per-device channel_index
   * passed to channelColor(), which guarantees chip parity with the
   * LightPanel and the strip painter (UI-SPEC §Color line 95).
   */
  channelsByDevice: Record<string, WledChannel[]>
}

/**
 * Region orientation popover - per-region narrowing (CONTEXT.md D-19/D-22).
 *
 * Renders ONE OrientationSegmentedControl per region (not per assignment) plus
 * a read-only list of the WLED channels assigned to that region. Anchored via
 * Base UI's virtual-anchor pattern to the selected region's screen-coord bbox.
 *
 * Chip color is computed via channelColor(per-device channel_index) — the
 * SAME formula the LightPanel and the strip painter use. This guarantees the
 * UI-SPEC §Color line 95 contract: identical input across all three surfaces.
 */
export function RegionOrientationPopover({
  canvasWidth,
  canvasHeight,
  canvasContainerEl,
  selectedConfigId,
  channelsByDevice,
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

  // -------------------------------------------------------------------------
  // Per-device channel_index resolver (UI-SPEC §Color line 95 contract).
  //
  // Builds Record<wled_channel_id, channel_index> where channel_index is the
  // channel's position in its OWN device's start_led-sorted channel list —
  // identical to the formula LightPanel.tsx applies (Plan 19-11). This
  // guarantees that for any channel C:
  //   popover chip color === LightPanel chip color === strip painter zone fill
  // -------------------------------------------------------------------------
  const deviceChannelIndexById = useMemo(() => {
    const out: Record<string, number> = {}
    for (const channels of Object.values(channelsByDevice)) {
      const sorted = channels.slice().sort((a, b) => a.start_led - b.start_led)
      sorted.forEach((ch, idx) => {
        out[ch.id] = idx
      })
    }
    return out
  }, [channelsByDevice])

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
      onOpenChange={(o) => {
        if (!o) setSelectedId(null)
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
                    {assignments.length === 1 ? 'channel' : 'channels'}
                  </>
                )}
              </h4>
              <Popover.Close
                aria-label="Close orientation panel"
                className="text-muted-foreground hover:text-foreground text-base leading-none"
              >
                ×
              </Popover.Close>
            </div>

            {assignments.length === 0 ? (
              <p
                className="text-xs text-muted-foreground"
                data-testid="region-orientation-popover-empty"
              >
                Drag a channel from the LightPanel to add an assignment.
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
                  Channels in this region
                </p>
                <div className="flex flex-col gap-1">
                  {assignments.map((a) => {
                    // UI-SPEC §Color line 95: chip color uses the channel's
                    // per-device channel_index (its position in its OWN
                    // device's start_led-sorted channel list) — NOT the
                    // in-region position. This guarantees the popover chip
                    // color matches the LightPanel chip and the strip
                    // painter zone for the same channel.
                    const deviceChannelIndex =
                      deviceChannelIndexById[a.wled_channel_id] ?? 0
                    // Try to surface the channel's human-readable name from
                    // channelsByDevice; fall back to the id if not found.
                    const channelName =
                      Object.values(channelsByDevice)
                        .flat()
                        .find((c) => c.id === a.wled_channel_id)?.name ??
                      a.wled_channel_id
                    return (
                      <div
                        key={a.wled_channel_id}
                        className="flex items-center gap-2 text-xs"
                      >
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ background: channelColor(deviceChannelIndex) }}
                          data-testid={`region-orientation-popover-chip-${a.wled_channel_id}`}
                        />
                        <span className="truncate text-foreground/80">
                          {channelName}
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
