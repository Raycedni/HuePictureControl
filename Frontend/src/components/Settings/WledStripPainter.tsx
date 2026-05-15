// Phase 19.1 Plan 07: WledStripPainter is now a READ-ONLY segment visualizer.
//
// Phase 19's paint-gesture state machine (the paint reducer + Stage mousedown/
// move/up), boundary drag handles, and the channel-create commit callback have
// all been removed (D-06). The strip now renders one zone per WLED segment fetched via
// `listSegments(deviceId)` and refreshed on-demand via `refreshSegments(deviceId)`
// from a per-device Refresh button (D-03). A stale-badge surfaces below the
// device name when the cached segments' `refreshed_at` is more than 60 s old
// (D-04). Zone click selects the segment via `onSelectSegment(seg, deviceId)`.
//
// The Konva render block (Stage / Layer / Rect zones / TickMarks) and the
// ResizeObserver fit-to-width behavior survive verbatim from Phase 19.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Stage, Layer, Rect, Line, Text, Group } from 'react-konva'

import {
  getWledDevices,
  listSegments,
  refreshSegments,
  WledApiError,
  type WledDevice,
} from '@/api/wled'
import type { WledSegment } from '@/utils/wled-segment'
import { segmentName } from '@/utils/wled-segment'
import { channelColor } from '@/utils/wled-palette'
import { Button } from '@/components/ui/button'

const STRIP_HEIGHT = 40
const TICK_ROW_HEIGHT = 14
const STRIP_TO_TICKS_GAP = 4
const INLINE_LABEL_MIN_WIDTH = 40
const STALE_THRESHOLD_MS = 60_000

/** Linear LED → pixel mapping along the strip. Pure render helper. */
function ledToPixel(led: number, stripWidth: number, ledCount: number): number {
  return ledCount > 0 ? (led / ledCount) * stripWidth : 0
}

/**
 * Derive a stale-badge label from a segment list's `refreshed_at` timestamp.
 *
 * - returns `null` if there are no segments, no timestamp, or the timestamp is
 *   unparseable
 * - returns `'synced Ns ago'` if the cache is fresh (<60 s old)
 * - returns `'stale (Nm ago)'` if older than 60 s
 *
 * Exported only for tests; consumed inside the component below.
 */
function staleBadge(segs: WledSegment[] | undefined): string | null {
  if (!segs || segs.length === 0) return null
  const ts = segs[0]?.refreshed_at
  if (!ts) return null
  const ageMs = Date.now() - new Date(ts).getTime()
  if (Number.isNaN(ageMs)) return null
  if (ageMs < STALE_THRESHOLD_MS) {
    return `synced ${Math.max(1, Math.round(ageMs / 1000))}s ago`
  }
  return `stale (${Math.round(ageMs / 60_000)}m ago)`
}

export interface SelectedSeg {
  device_id: string
  seg_index: number
}

interface Props {
  selectedSeg: SelectedSeg | null
  onSelectSegment: (seg: WledSegment, deviceId: string) => void
}

interface DeviceBlock {
  device: WledDevice
  segments: WledSegment[]
}

export function WledStripPainter({ selectedSeg, onSelectSegment }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [stripWidth, setStripWidth] = useState(800)
  const [blocks, setBlocks] = useState<DeviceBlock[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // ResizeObserver - fit strips to container width (UI-SPEC §Spacing / Risks R4).
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? el.offsetWidth
      if (w > 0) setStripWidth(Math.floor(w))
    })
    ro.observe(el)
    setStripWidth(Math.floor(el.offsetWidth || 800))
    return () => ro.disconnect()
  }, [])

  // Load devices + cached segments. Pure cache read (D-18) — never contacts the
  // device. Per-device Refresh button below is the only path to /json/state.
  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const devicesResp = await getWledDevices()
      const devs = devicesResp.devices
      const newBlocks: DeviceBlock[] = []
      for (const d of devs) {
        try {
          const segResp = await listSegments(d.id)
          newBlocks.push({ device: d, segments: segResp.segments })
        } catch (segErr) {
          // D-04: an offline device with an empty cache should not block the
          // whole panel. Render an empty zone list — the stale-badge will
          // remain absent and the Refresh button gives the user a retry path.
          console.error(`Failed to load segments for ${d.id}:`, segErr)
          newBlocks.push({ device: d, segments: [] })
        }
      }
      setBlocks(newBlocks)
    } catch (err) {
      console.error('Failed to load WLED devices:', err)
      setError('Failed to load devices.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  // Per-device refresh handler — POSTs /segments/refresh and patches the
  // matching block on success; on failure, sets a per-device error message
  // and leaves the cached zones intact (D-04).
  const handleRefresh = useCallback(async (deviceId: string) => {
    setBlocks((prev) =>
      prev.map((b) =>
        b.device.id === deviceId ? { ...b, _refreshing: true } as DeviceBlock : b,
      ),
    )
    try {
      const resp = await refreshSegments(deviceId)
      setBlocks((prev) =>
        prev.map((b) =>
          b.device.id === deviceId ? { device: b.device, segments: resp.segments } : b,
        ),
      )
      setRefreshError((prev) => {
        const { [deviceId]: _omit, ...rest } = prev
        return rest
      })
    } catch (err) {
      const msg =
        err instanceof WledApiError ? `Refresh failed (${err.status})` : 'Refresh failed'
      setRefreshError((prev) => ({ ...prev, [deviceId]: msg }))
    } finally {
      setRefreshing((prev) => ({ ...prev, [deviceId]: false }))
    }
  }, [])

  // Refresh button busy/error state — colocated with the strip view so the
  // surrounding container layout stays simple.
  const [refreshing, setRefreshing] = useState<Record<string, boolean>>({})
  const [refreshError, setRefreshError] = useState<Record<string, string>>({})

  const onRefreshClick = useCallback(
    async (deviceId: string) => {
      setRefreshing((prev) => ({ ...prev, [deviceId]: true }))
      await handleRefresh(deviceId)
    },
    [handleRefresh],
  )

  if (loading) {
    return (
      <div
        ref={containerRef}
        className="w-full min-h-[200px] flex items-center justify-center text-xs text-muted-foreground"
        data-testid="wled-strip-painter-loading"
      >
        Loading devices...
      </div>
    )
  }
  if (error) {
    return (
      <div
        ref={containerRef}
        className="w-full text-xs text-red-400"
        data-testid="wled-strip-painter-error"
      >
        Failed to load WLED devices.
      </div>
    )
  }
  if (blocks.length === 0) {
    return (
      <div
        ref={containerRef}
        className="w-full min-h-[200px] flex flex-col items-center justify-center gap-1 text-center"
        data-testid="wled-strip-painter-empty"
      >
        <h3 className="text-xs font-semibold text-foreground">No WLED devices.</h3>
        <p className="text-xs text-muted-foreground">
          Add a device in the panel on the right to view segments.
        </p>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="w-full flex flex-col gap-4 overflow-y-auto"
      data-testid="wled-strip-painter"
    >
      {blocks.map((block) => (
        <DeviceStrip
          key={block.device.id}
          device={block.device}
          segments={block.segments}
          stripWidth={stripWidth}
          selectedSeg={selectedSeg}
          onSelectSegment={onSelectSegment}
          refreshing={refreshing[block.device.id] === true}
          refreshError={refreshError[block.device.id] ?? null}
          onRefresh={() => onRefreshClick(block.device.id)}
        />
      ))}
    </div>
  )
}

interface DeviceStripProps {
  device: WledDevice
  segments: WledSegment[]
  stripWidth: number
  selectedSeg: SelectedSeg | null
  onSelectSegment: (seg: WledSegment, deviceId: string) => void
  refreshing: boolean
  refreshError: string | null
  onRefresh: () => void
}

function DeviceStrip({
  device,
  segments,
  stripWidth,
  selectedSeg,
  onSelectSegment,
  refreshing,
  refreshError,
  onRefresh,
}: DeviceStripProps) {
  // Sort segments by start_led so adjacent zones render left-to-right.
  const sortedSegments = useMemo(
    () => [...segments].sort((a, b) => a.start_led - b.start_led),
    [segments],
  )

  const ledCount = device.led_count
  const tickPositions = useMemo(() => {
    // Sparse axis ticks: aim for ~5-7 labels across the strip.
    const step = ledCount <= 100 ? 25 : ledCount <= 500 ? 50 : 100
    const positions: number[] = []
    for (let led = 0; led <= ledCount; led += step) positions.push(led)
    if (positions[positions.length - 1] !== ledCount) positions.push(ledCount)
    return positions
  }, [ledCount])

  const totalHeight = STRIP_HEIGHT + STRIP_TO_TICKS_GAP + TICK_ROW_HEIGHT
  const badge = staleBadge(segments)

  return (
    <div className="flex flex-col gap-2" data-testid={`wled-strip-${device.id}`}>
      <div className="flex items-center gap-2">
        <div className="flex flex-col flex-1 min-w-0">
          <span className="text-xs font-semibold text-foreground truncate">{device.name}</span>
          <span className="text-[10px] text-muted-foreground font-mono">
            {device.ip} · {device.led_count} LEDs · {segments.length} segments
          </span>
          {badge && (
            <span
              className="text-[10px] text-muted-foreground"
              data-testid={`wled-stale-badge-${device.id}`}
            >
              {badge}
            </span>
          )}
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onRefresh}
          disabled={refreshing}
          data-testid={`wled-refresh-button-${device.id}`}
        >
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </Button>
      </div>
      {refreshError && (
        <p
          className="text-[11px] text-red-400"
          data-testid={`wled-refresh-error-${device.id}`}
        >
          {refreshError}
        </p>
      )}
      <Stage
        width={stripWidth}
        height={totalHeight}
        style={{ background: 'transparent' }}
      >
        <Layer>
          {/* Strip background */}
          <Rect
            x={0}
            y={0}
            width={stripWidth}
            height={STRIP_HEIGHT}
            fill="rgba(0,0,0,0.35)"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={1}
            cornerRadius={4}
            listening={false}
          />
          {/* Zones — one per segment, fill = channelColor(seg_index) per D-09 */}
          {sortedSegments.map((seg) => {
            const x = ledToPixel(seg.start_led, stripWidth, ledCount)
            const w = ledToPixel(seg.stop_led - seg.start_led + 1, stripWidth, ledCount)
            const isSelected =
              selectedSeg?.device_id === device.id &&
              selectedSeg?.seg_index === seg.seg_index
            return (
              <ZoneRect
                key={`${device.id}:${seg.seg_index}`}
                x={x}
                width={w}
                height={STRIP_HEIGHT}
                seg={seg}
                isSelected={isSelected}
                onClick={() => onSelectSegment(seg, device.id)}
                testId={`wled-seg-${device.id}-${seg.seg_index}`}
              />
            )
          })}
          {/* Axis ticks below the strip */}
          {tickPositions.map((led, i) => {
            const x = ledToPixel(led, stripWidth, ledCount)
            const y = STRIP_HEIGHT + STRIP_TO_TICKS_GAP
            return <TickMark key={`tick-${i}`} x={x} y={y} label={String(led)} />
          })}
        </Layer>
      </Stage>
    </div>
  )
}

interface ZoneRectProps {
  x: number
  width: number
  height: number
  seg: WledSegment
  isSelected: boolean
  onClick: () => void
  testId: string
}

function ZoneRect({ x, width, height, seg, isSelected, onClick, testId }: ZoneRectProps) {
  const fill = channelColor(seg.seg_index)
  const showLabel = width >= INLINE_LABEL_MIN_WIDTH
  return (
    <Group x={x} onClick={onClick} onTap={onClick}>
      {/* Render a sentinel <div> sibling so JSDOM-based tests (which stub the
          react-konva tree) can still find the zone by data-testid. The Konva
          renderer ignores unknown DOM nodes; the test mock passes children
          through directly so this <div> mounts as a peer of the Rect/Text. */}
      <ZoneTestSentinel testId={testId} />
      <Rect
        x={0}
        y={0}
        width={width}
        height={height}
        fill={fill}
        stroke={isSelected ? 'var(--accent)' : undefined}
        strokeWidth={isSelected ? 1 : 0}
        listening={true}
      />
      {showLabel && (
        <Text
          x={8}
          y={(height - 11) / 2}
          width={width - 16}
          text={segmentName(seg)}
          fontSize={11}
          fontStyle="500"
          fontFamily="Geist Variable, sans-serif"
          fill="rgba(0,0,0,0.78)"
          listening={false}
          ellipsis
        />
      )}
    </Group>
  )
}

/**
 * A zero-pixel sentinel element used purely so vitest tests can discover the
 * zone by `data-testid="wled-seg-{deviceId}-{segIndex}"`. In a real Konva
 * render this is mounted inside the Stage's `<canvas>` parent div but renders
 * nothing visible; in JSDOM-mocked tests (where react-konva is stubbed to a
 * pass-through fragment) it becomes a normal DOM node the testing-library
 * queries find.
 */
function ZoneTestSentinel({ testId }: { testId: string }) {
  return <span data-testid={testId} style={{ display: 'none' }} aria-hidden="true" />
}

interface TickMarkProps {
  x: number
  y: number
  label: string
}

function TickMark({ x, y, label }: TickMarkProps) {
  return (
    <Group>
      <Line
        points={[x, y, x, y + 4]}
        stroke="rgba(255,255,255,0.2)"
        strokeWidth={1}
        listening={false}
      />
      <Text
        x={x - 10}
        y={y + 5}
        width={20}
        text={label}
        fontSize={9}
        fontFamily="ui-monospace, Consolas, monospace"
        fill="rgba(255,255,255,0.35)"
        align="center"
        listening={false}
      />
    </Group>
  )
}
