import { useRef, useState, useEffect } from 'react'
import { Group, Line, Circle, Text } from 'react-konva'
import type Konva from 'konva'
import type { Region } from '@/api/regions'
import { useRegionStore } from '@/store/useRegionStore'
import { denormalize, normalize } from '@/utils/geometry'
import { updateRegion as updateRegionAPI } from '@/api/regions'
import type { WledSegment } from '@/api/wled'

interface RegionPolygonProps {
  region: Region
  isSelected: boolean
  stageWidth: number
  stageHeight: number
  color?: string
  segsByDevice?: Record<string, WledSegment[]>
}

export function RegionPolygon({
  region,
  isSelected,
  stageWidth,
  stageHeight,
  color,
  segsByDevice,
}: RegionPolygonProps) {
  const setSelectedId = useRegionStore((s) => s.setSelectedId)
  const setDrawingMode = useRegionStore((s) => s.setDrawingMode)
  const updateRegionInStore = useRegionStore((s) => s.updateRegion)
  const assignments = useRegionStore((s) => s.wledAssignments[region.id]) ?? []

  // Local pixel coordinates for immediate visual feedback
  const [localPoints, setLocalPoints] = useState<[number, number][]>(() =>
    denormalize(region.polygon as [number, number][], stageWidth, stageHeight),
  )

  // Keep local points in sync when region changes OR stage dimensions change
  const prevRegionRef = useRef(region.polygon)
  const prevDimsRef = useRef({ w: stageWidth, h: stageHeight })
  if (
    region.polygon !== prevRegionRef.current ||
    stageWidth !== prevDimsRef.current.w ||
    stageHeight !== prevDimsRef.current.h
  ) {
    prevRegionRef.current = region.polygon
    prevDimsRef.current = { w: stageWidth, h: stageHeight }
    setLocalPoints(denormalize(region.polygon as [number, number][], stageWidth, stageHeight))
  }

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const ctrlHeldRef = useRef(false)
  const dragStartPointsRef = useRef<[number, number][] | null>(null)

  useEffect(() => {
    const down = (e: KeyboardEvent) => { if (e.key === 'Control') ctrlHeldRef.current = true }
    const up = (e: KeyboardEvent) => { if (e.key === 'Control') ctrlHeldRef.current = false }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up) }
  }, [])

  function scheduleSave(newPoints: [number, number][]) {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(async () => {
      const normalized = normalize(newPoints, stageWidth, stageHeight)
      try {
        await updateRegionAPI(region.id, { polygon: normalized })
        updateRegionInStore(region.id, { polygon: normalized })
      } catch (err) {
        console.error('Failed to save region:', err)
      }
    }, 400)
  }

  /** Clamp a set of points so the entire polygon stays within [0, stageWidth] x [0, stageHeight] */
  function clampPoints(pts: [number, number][]): [number, number][] {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const [x, y] of pts) {
      if (x < minX) minX = x
      if (y < minY) minY = y
      if (x > maxX) maxX = x
      if (y > maxY) maxY = y
    }
    let dx = 0, dy = 0
    if (minX < 0) dx = -minX
    else if (maxX > stageWidth) dx = stageWidth - maxX
    if (minY < 0) dy = -minY
    else if (maxY > stageHeight) dy = stageHeight - maxY
    if (dx === 0 && dy === 0) return pts
    return pts.map(([x, y]) => [x + dx, y + dy])
  }

  function handleGroupClick(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    e.cancelBubble = true
    setSelectedId(region.id)
    setDrawingMode('select')
  }

  /** Collect snap edges (x and y values) from all other regions */
  function getSnapEdges(): { xs: number[]; ys: number[] } {
    const allRegions = useRegionStore.getState().regions
    const xs: number[] = []
    const ys: number[] = []
    for (const r of allRegions) {
      if (r.id === region.id) continue
      const pts = denormalize(r.polygon as [number, number][], stageWidth, stageHeight)
      for (const [x, y] of pts) {
        xs.push(x)
        ys.push(y)
      }
    }
    // Also add canvas edges
    xs.push(0, stageWidth)
    ys.push(0, stageHeight)
    return { xs, ys }
  }

  const SNAP_THRESHOLD = 8

  /** Constrain group drag so the polygon never leaves the canvas; snap when Ctrl held */
  function handleGroupDragBound(pos: { x: number; y: number }) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const [x, y] of localPoints) {
      if (x < minX) minX = x
      if (y < minY) minY = y
      if (x > maxX) maxX = x
      if (y > maxY) maxY = y
    }

    let x = Math.min(Math.max(pos.x, -minX), stageWidth - maxX)
    let y = Math.min(Math.max(pos.y, -minY), stageHeight - maxY)

    // Snap edges to other zones when Ctrl is held
    if (ctrlHeldRef.current) {
      const { xs, ys } = getSnapEdges()
      // Check each edge of this polygon (shifted by drag offset) against snap targets
      const myEdgesX = [minX + x, maxX + x]
      const myEdgesY = [minY + y, maxY + y]

      let bestSnapX = Infinity
      for (const ex of myEdgesX) {
        for (const sx of xs) {
          const d = sx - ex
          if (Math.abs(d) < Math.abs(bestSnapX) && Math.abs(d) < SNAP_THRESHOLD) {
            bestSnapX = d
          }
        }
      }
      if (bestSnapX !== Infinity) x += bestSnapX

      let bestSnapY = Infinity
      for (const ey of myEdgesY) {
        for (const sy of ys) {
          const d = sy - ey
          if (Math.abs(d) < Math.abs(bestSnapY) && Math.abs(d) < SNAP_THRESHOLD) {
            bestSnapY = d
          }
        }
      }
      if (bestSnapY !== Infinity) y += bestSnapY

      // Re-clamp after snap
      x = Math.min(Math.max(x, -minX), stageWidth - maxX)
      y = Math.min(Math.max(y, -minY), stageHeight - maxY)
    }

    return { x, y }
  }

  function handleGroupDragEnd(e: Konva.KonvaEventObject<DragEvent>) {
    const dx = e.target.x()
    const dy = e.target.y()

    // Bake offset into points and clamp to bounds
    const shifted: [number, number][] = localPoints.map(([x, y]) => [x + dx, y + dy])
    const newPoints = clampPoints(shifted)

    // Reset group position to avoid drift
    e.target.position({ x: 0, y: 0 })

    setLocalPoints(newPoints)
    scheduleSave(newPoints)
  }

  function handleVertexDragStart(_index: number) {
    dragStartPointsRef.current = localPoints.map(([x, y]) => [x, y] as [number, number])
  }

  function applyRectConstraint(
    index: number,
    newX: number,
    newY: number,
    base: [number, number][],
  ): [number, number][] {
    if (base.length !== 4 || ctrlHeldRef.current) {
      // Free-form: only move the dragged vertex
      const updated = [...base]
      updated[index] = [newX, newY]
      return updated
    }
    // Rectangle constraint: winding is TL(0), TR(1), BR(2), BL(3)
    // Adjacent vertices share an edge — determine horizontal vs vertical by
    // checking which coordinate was closer in the original rectangle.
    const prev = (index + 3) % 4
    const next = (index + 1) % 4
    const updated: [number, number][] = base.map(([x, y]) => [x, y])
    updated[index] = [newX, newY]

    const orig = dragStartPointsRef.current ?? base
    // prev-index edge: if they shared similar X, it's a vertical edge → sync X; else sync Y
    if (Math.abs(orig[prev][0] - orig[index][0]) < Math.abs(orig[prev][1] - orig[index][1])) {
      updated[prev] = [newX, updated[prev][1]]
    } else {
      updated[prev] = [updated[prev][0], newY]
    }
    // index-next edge: same logic
    if (Math.abs(orig[next][0] - orig[index][0]) < Math.abs(orig[next][1] - orig[index][1])) {
      updated[next] = [newX, updated[next][1]]
    } else {
      updated[next] = [updated[next][0], newY]
    }
    return updated
  }

  function clampVertex(x: number, y: number): [number, number] {
    return [Math.min(Math.max(x, 0), stageWidth), Math.min(Math.max(y, 0), stageHeight)]
  }

  function handleVertexDragMove(index: number, e: Konva.KonvaEventObject<DragEvent>) {
    e.cancelBubble = true
    const [newX, newY] = clampVertex(e.target.x(), e.target.y())
    e.target.position({ x: newX, y: newY })
    setLocalPoints((prev) => applyRectConstraint(index, newX, newY, prev))
  }

  function handleVertexDragEnd(index: number, e: Konva.KonvaEventObject<DragEvent>) {
    e.cancelBubble = true
    const [newX, newY] = clampVertex(e.target.x(), e.target.y())
    const newPoints = applyRectConstraint(index, newX, newY, localPoints)
    setLocalPoints(newPoints)
    scheduleSave(newPoints)
    dragStartPointsRef.current = null
  }

  // Compute centroid for label
  const cx = localPoints.reduce((sum, [x]) => sum + x, 0) / localPoints.length
  const cy = localPoints.reduce((sum, [, y]) => sum + y, 0) / localPoints.length

  const flatPoints = localPoints.flatMap(([x, y]) => [x, y])
  const fillColor = color ?? 'rgba(255,255,255,0.2)'
  // Larger handles on touch devices
  const isTouchDevice = typeof window !== 'undefined' && ('ontouchstart' in window || navigator.maxTouchPoints > 0)
  const handleRadius = isTouchDevice ? 12 : 6

  // LED-split dividers — mirrors Backend/services/color_math.py sub_sample_gradient:
  // sample centers at t=i/(N-1) along the bbox-longest axis (or the explicit
  // orientation). Boundary between LED i and i+1 sits at the midpoint
  // t=(i+0.5)/(N-1), giving N-1 divider lines for an N-LED segment.
  let dividerLines: Array<[number, number, number, number]> = []
  if (assignments.length > 0 && segsByDevice) {
    let n = 0
    for (const a of assignments) {
      const seg = (segsByDevice[a.wled_device_id] ?? []).find(
        (s) => s.seg_index === a.seg_index,
      )
      if (!seg) continue
      const len = seg.stop_led - seg.start_led + 1
      if (len > n) n = len
    }
    if (n >= 2) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
      for (const [x, y] of localPoints) {
        if (x < minX) minX = x
        if (y < minY) minY = y
        if (x > maxX) maxX = x
        if (y > maxY) maxY = y
      }
      const w = maxX - minX
      const h = maxY - minY
      const orientation = assignments[0]?.orientation ?? 'auto'
      const axisX =
        orientation === 'horizontal-LTR' || orientation === 'horizontal-RTL'
          ? true
          : orientation === 'vertical-TTB' || orientation === 'vertical-BTT'
            ? false
            : w >= h
      for (let i = 0; i < n - 1; i++) {
        const t = (i + 0.5) / (n - 1)
        if (axisX) {
          const x = minX + t * w
          dividerLines.push([x, minY, x, maxY])
        } else {
          const y = minY + t * h
          dividerLines.push([minX, y, maxX, y])
        }
      }
    }
  }

  return (
    <Group
      draggable={isSelected}
      onClick={handleGroupClick}
      onTap={handleGroupClick}
      dragBoundFunc={handleGroupDragBound}
      onDragEnd={handleGroupDragEnd}
    >
      <Line
        points={flatPoints}
        closed
        fill={fillColor}
        stroke="white"
        strokeWidth={2}
        listening
      />
      {dividerLines.length > 0 && (
        <Group
          listening={false}
          clipFunc={(ctx) => {
            if (localPoints.length === 0) return
            ctx.beginPath()
            ctx.moveTo(localPoints[0][0], localPoints[0][1])
            for (let i = 1; i < localPoints.length; i++) {
              ctx.lineTo(localPoints[i][0], localPoints[i][1])
            }
            ctx.closePath()
          }}
        >
          {dividerLines.map(([x1, y1, x2, y2], i) => (
            <Line
              key={i}
              points={[x1, y1, x2, y2]}
              stroke="rgba(255,255,255,0.7)"
              strokeWidth={1}
              listening={false}
            />
          ))}
        </Group>
      )}
      <Text
        x={cx - 50}
        y={cy - 8}
        width={100}
        text={region.name}
        fontSize={12}
        fill={region.light_id ? 'yellow' : 'rgba(255,255,255,0.6)'}
        align="center"
        listening={false}
      />
      {/* Vertex handles — only when selected */}
      {isSelected &&
        localPoints.map(([x, y], i) => (
          <Circle
            key={i}
            x={x}
            y={y}
            radius={handleRadius}
            fill="white"
            draggable
            onDragStart={() => handleVertexDragStart(i)}
            onDragMove={(e) => handleVertexDragMove(i, e)}
            onDragEnd={(e) => handleVertexDragEnd(i, e)}
            onClick={(e) => {
              e.cancelBubble = true
            }}
          />
        ))}
    </Group>
  )
}
