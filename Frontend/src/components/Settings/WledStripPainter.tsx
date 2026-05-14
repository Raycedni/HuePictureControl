import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import type Konva from 'konva'
import { Stage, Layer, Rect, Line, Text } from 'react-konva'

import {
  getWledDevices,
  listWledChannels,
  createWledChannel,
  resizeWledChannelBoundary,
  type WledDevice,
  type WledChannel,
} from '@/api/wled'
import { channelColor } from '@/utils/wled-palette'
import {
  paintReducer,
  pixelToLed,
  ledToPixel,
  clampBoundary,
} from './wled-paint-reducer'

const STRIP_HEIGHT = 40
const TICK_ROW_HEIGHT = 14
const STRIP_TO_TICKS_GAP = 4
const BLOCK_GAP = 16
const HANDLE_HIT_WIDTH = 8
const INLINE_LABEL_MIN_WIDTH = 40

interface Props {
  selectedChannelId: string | null
  onSelectChannel: (channelId: string | null, deviceId: string | null) => void
  refreshTrigger?: number
}

interface DeviceBlock {
  device: WledDevice
  channels: WledChannel[]
}

export function WledStripPainter({
  selectedChannelId,
  onSelectChannel,
  refreshTrigger,
}: Props) {
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

  // Load devices + channels.
  const reload = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const devicesResp = await getWledDevices()
      const devs = devicesResp.devices
      const newBlocks: DeviceBlock[] = []
      for (const d of devs) {
        const chResp = await listWledChannels(d.id)
        newBlocks.push({ device: d, channels: chResp.channels })
      }
      setBlocks(newBlocks)
    } catch (err) {
      console.error('Failed to load WLED devices/channels:', err)
      setError('Failed to load devices.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload, refreshTrigger])

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
          Add a device in the panel on the right to start painting channels.
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
          channels={block.channels}
          stripWidth={stripWidth}
          selectedChannelId={selectedChannelId}
          onSelectChannel={(cid) => onSelectChannel(cid, block.device.id)}
          onReload={reload}
        />
      ))}
    </div>
  )
}

interface DeviceStripProps {
  device: WledDevice
  channels: WledChannel[]
  stripWidth: number
  selectedChannelId: string | null
  onSelectChannel: (channelId: string | null) => void
  onReload: () => Promise<void>
}

function DeviceStrip({
  device,
  channels,
  stripWidth,
  selectedChannelId,
  onSelectChannel,
  onReload,
}: DeviceStripProps) {
  const stageRef = useRef<Konva.Stage>(null)
  const [paintState, dispatch] = useReducer(paintReducer, { phase: 'idle' })

  // Sort channels by start_led for ordering and boundary handle placement.
  const sortedChannels = useMemo(
    () => [...channels].sort((a, b) => a.start_led - b.start_led),
    [channels],
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

  function getPointerLed(): number | null {
    const stage = stageRef.current
    if (!stage) return null
    const pos = stage.getPointerPosition()
    if (!pos) return null
    return pixelToLed(pos.x, stripWidth, ledCount)
  }

  function handleStageMouseDown(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    // Only paint on the background — clicks on zones are handled by the Rect's onClick.
    if (e.target !== e.target.getStage()) return
    const led = getPointerLed()
    if (led === null) return
    dispatch({ type: 'mousedown', led })
    e.cancelBubble = true
  }

  function handleStageMouseMove(_e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (paintState.phase !== 'painting') return
    const led = getPointerLed()
    if (led === null) return
    dispatch({ type: 'mousemove', led })
  }

  async function handleStageMouseUp(_e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (paintState.phase !== 'painting') return
    const led = getPointerLed()
    if (led === null) {
      dispatch({ type: 'cancel' })
      return
    }
    dispatch({
      type: 'mouseup',
      led,
      commit: async (start, end) => {
        try {
          await createWledChannel(device.id, { start_led: start, end_led: end })
          await onReload()
        } catch (err) {
          console.error('Failed to create WLED channel:', err)
        }
      },
    })
  }

  function handleZoneClick(channel: WledChannel) {
    onSelectChannel(channel.id)
  }

  async function handleBoundaryDragEnd(
    leftCh: WledChannel,
    rightCh: WledChannel,
    pixelX: number,
  ) {
    const desired = pixelToLed(pixelX, stripWidth, ledCount)
    const boundary = clampBoundary(desired, leftCh.start_led, rightCh.end_led)
    if (boundary === rightCh.start_led) return // no change
    try {
      await resizeWledChannelBoundary(device.id, {
        left_channel_id: leftCh.id,
        right_channel_id: rightCh.id,
        boundary,
      })
      await onReload()
    } catch (err) {
      console.error('Failed to resize boundary:', err)
      await onReload() // snap back on failure
    }
  }

  const totalHeight = STRIP_HEIGHT + STRIP_TO_TICKS_GAP + TICK_ROW_HEIGHT

  // Suppress unused variable lint — BLOCK_GAP used for layout documentation.
  void BLOCK_GAP

  return (
    <div className="flex flex-col gap-2" data-testid={`wled-strip-${device.id}`}>
      <div className="flex flex-col">
        <span className="text-xs font-semibold text-foreground">{device.name}</span>
        <span className="text-[10px] text-muted-foreground font-mono">
          {device.ip} · {device.led_count} LEDs · {channels.length} channels
        </span>
      </div>
      <Stage
        ref={stageRef}
        width={stripWidth}
        height={totalHeight}
        onMouseDown={handleStageMouseDown}
        onMouseMove={handleStageMouseMove}
        onMouseUp={handleStageMouseUp}
        onTouchStart={handleStageMouseDown}
        onTouchMove={handleStageMouseMove}
        onTouchEnd={handleStageMouseUp}
        style={{ background: 'transparent', touchAction: 'none' }}
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
          {/* Zones */}
          {sortedChannels.map((ch, idx) => {
            const x = ledToPixel(ch.start_led, stripWidth, ledCount)
            const w = ledToPixel(ch.end_led - ch.start_led + 1, stripWidth, ledCount)
            const isSelected = ch.id === selectedChannelId
            return (
              <ZoneRect
                key={ch.id}
                x={x}
                width={w}
                height={STRIP_HEIGHT}
                channel={ch}
                channelIndex={idx}
                isSelected={isSelected}
                onClick={() => handleZoneClick(ch)}
              />
            )
          })}
          {/* In-progress paint preview */}
          {paintState.phase === 'painting' && (
            <Rect
              x={ledToPixel(
                Math.min(paintState.startLed, paintState.currentLed),
                stripWidth,
                ledCount,
              )}
              y={0}
              width={ledToPixel(
                Math.abs(paintState.currentLed - paintState.startLed) + 1,
                stripWidth,
                ledCount,
              )}
              height={STRIP_HEIGHT}
              fill={channelColor(sortedChannels.length)}
              opacity={0.5}
              listening={false}
            />
          )}
          {/* Boundary handles - one per adjacent pair */}
          {sortedChannels.slice(0, -1).map((leftCh, i) => {
            const rightCh = sortedChannels[i + 1]
            if (leftCh.end_led + 1 !== rightCh.start_led) return null
            const x = ledToPixel(rightCh.start_led, stripWidth, ledCount)
            return (
              <BoundaryHandle
                key={`bnd-${leftCh.id}-${rightCh.id}`}
                x={x}
                stripHeight={STRIP_HEIGHT}
                onDragEnd={(newX) => handleBoundaryDragEnd(leftCh, rightCh, newX)}
              />
            )
          })}
          {/* Axis ticks below the strip */}
          {tickPositions.map((led, i) => {
            const x = ledToPixel(led, stripWidth, ledCount)
            const y = STRIP_HEIGHT + STRIP_TO_TICKS_GAP
            return (
              <TickMark key={`tick-${i}`} x={x} y={y} label={String(led)} />
            )
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
  channel: WledChannel
  channelIndex: number
  isSelected: boolean
  onClick: () => void
}

function ZoneRect({
  x, width, height, channel, channelIndex, isSelected, onClick,
}: ZoneRectProps) {
  const fill = channelColor(channelIndex)
  const showLabel = width >= INLINE_LABEL_MIN_WIDTH
  return (
    <>
      <Rect
        x={x}
        y={0}
        width={width}
        height={height}
        fill={fill}
        stroke={isSelected ? 'var(--accent)' : undefined}
        strokeWidth={isSelected ? 1 : 0}
        onClick={onClick}
        onTap={onClick}
        listening={true}
      />
      {showLabel && (
        <Text
          x={x + 8}
          y={(height - 11) / 2}
          width={width - 16}
          text={channel.name}
          fontSize={11}
          fontStyle="500"
          fontFamily="Geist Variable, sans-serif"
          fill="rgba(0,0,0,0.78)"
          listening={false}
          ellipsis
        />
      )}
    </>
  )
}

interface BoundaryHandleProps {
  x: number
  stripHeight: number
  onDragEnd: (newX: number) => void
}

function BoundaryHandle({ x, stripHeight, onDragEnd }: BoundaryHandleProps) {
  const [hovered, setHovered] = useState(false)
  const lineHeight = hovered ? stripHeight * 0.9 : stripHeight * 0.7
  const top = (stripHeight - lineHeight) / 2
  return (
    <>
      {/* Invisible hit zone */}
      <Rect
        x={x - HANDLE_HIT_WIDTH / 2}
        y={0}
        width={HANDLE_HIT_WIDTH}
        height={stripHeight}
        draggable
        dragBoundFunc={(pos) => ({ x: pos.x, y: 0 })}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onDragEnd={(e) => onDragEnd(e.target.x() + HANDLE_HIT_WIDTH / 2)}
        fill="transparent"
        style={{ cursor: 'ew-resize' } as never}
      />
      {/* Visible line (non-interactive) */}
      <Line
        points={[x, top, x, top + lineHeight]}
        stroke={hovered ? 'var(--accent)' : 'rgba(255,255,255,0.45)'}
        strokeWidth={2}
        listening={false}
      />
    </>
  )
}

interface TickMarkProps {
  x: number
  y: number
  label: string
}

function TickMark({ x, y, label }: TickMarkProps) {
  return (
    <>
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
    </>
  )
}
