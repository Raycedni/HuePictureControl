import { useRef, useState } from 'react'
import { Group, Line, Circle, Text } from 'react-konva'
import type Konva from 'konva'
import type { Region } from '@/api/regions'
import { useRegionStore } from '@/store/useRegionStore'
import { denormalize, normalize } from '@/utils/geometry'
import { updateRegion as updateRegionAPI } from '@/api/regions'

interface RegionPolygonProps {
  region: Region
  isSelected: boolean
  stageWidth: number
  stageHeight: number
  color?: string
  /** Display name of the assigned light (if any) */
  lightName?: string
}

export function RegionPolygon({
  region,
  isSelected,
  stageWidth,
  stageHeight,
  color,
  lightName,
}: RegionPolygonProps) {
  const setSelectedId = useRegionStore((s) => s.setSelectedId)
  const setDrawingMode = useRegionStore((s) => s.setDrawingMode)
  const updateRegionInStore = useRegionStore((s) => s.updateRegion)

  // Local pixel coordinates for immediate visual feedback
  const [localPoints, setLocalPoints] = useState<[number, number][]>(() =>
    denormalize(region.polygon as [number, number][], stageWidth, stageHeight),
  )

  // Keep local points in sync when region changes from outside (e.g., body drag)
  const prevRegionRef = useRef(region.polygon)
  if (region.polygon !== prevRegionRef.current) {
    prevRegionRef.current = region.polygon
    setLocalPoints(denormalize(region.polygon as [number, number][], stageWidth, stageHeight))
  }

  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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

  function handleGroupClick(e: Konva.KonvaEventObject<MouseEvent>) {
    e.cancelBubble = true
    setSelectedId(region.id)
    setDrawingMode('select')
  }

  function handleGroupDragEnd(e: Konva.KonvaEventObject<DragEvent>) {
    const dx = e.target.x()
    const dy = e.target.y()

    // Bake offset into points
    const newPoints: [number, number][] = localPoints.map(([x, y]) => [x + dx, y + dy])

    // Reset group position to avoid drift
    e.target.position({ x: 0, y: 0 })

    setLocalPoints(newPoints)
    scheduleSave(newPoints)
  }

  function handleVertexDragMove(index: number, e: Konva.KonvaEventObject<DragEvent>) {
    e.cancelBubble = true
    const newX = e.target.x()
    const newY = e.target.y()
    setLocalPoints((prev) => {
      const updated = [...prev]
      updated[index] = [newX, newY]
      return updated
    })
  }

  function handleVertexDragEnd(index: number, e: Konva.KonvaEventObject<DragEvent>) {
    e.cancelBubble = true
    const newX = e.target.x()
    const newY = e.target.y()
    const newPoints: [number, number][] = localPoints.map((pt, i) =>
      i === index ? [newX, newY] : pt,
    )
    setLocalPoints(newPoints)
    scheduleSave(newPoints)
  }

  // Compute centroid for label
  const cx = localPoints.reduce((sum, [x]) => sum + x, 0) / localPoints.length
  const cy = localPoints.reduce((sum, [, y]) => sum + y, 0) / localPoints.length

  const flatPoints = localPoints.flatMap(([x, y]) => [x, y])
  const fillColor = color ?? 'rgba(255,255,255,0.2)'

  return (
    <Group
      draggable={isSelected}
      onClick={handleGroupClick}
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
      {/* Show assigned light name when present, otherwise show region name in muted style */}
      {lightName ? (
        <Text
          x={cx - 40}
          y={cy - 8}
          width={80}
          text={lightName}
          fontSize={12}
          fill="yellow"
          align="center"
          listening={false}
        />
      ) : (
        <Text
          x={cx - 30}
          y={cy - 8}
          text={region.name}
          fontSize={12}
          fill="rgba(255,255,255,0.6)"
          listening={false}
        />
      )}
      {/* Vertex handles — only when selected */}
      {isSelected &&
        localPoints.map(([x, y], i) => (
          <Circle
            key={i}
            x={x}
            y={y}
            radius={6}
            fill="white"
            draggable
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
