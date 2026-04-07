import { useEffect, useRef, useState } from 'react'
import { Stage, Layer, Image as KonvaImage, Line, Circle } from 'react-konva'
import type Konva from 'konva'
import { usePreviewWS } from '@/hooks/usePreviewWS'
import { useRegionStore } from '@/store/useRegionStore'
import { normalize, denormalize, pointInPolygon, polygonArea } from '@/utils/geometry'
import { createRegion, deleteRegion as deleteRegionAPI, fetchRegions, updateRegion as updateRegionAPI } from '@/api/regions'
import { RegionPolygon } from './RegionPolygon'

export interface EditorCanvasProps {
  width: number
  height: number
  /** Called by keyboard shortcuts and toolbar delete — wired from EditorPage */
  onDeleteRequest?: () => void
  device?: string
}

export function EditorCanvas({ width, height, onDeleteRequest, device }: EditorCanvasProps) {
  const imgSrc = usePreviewWS(true, device)

  // Double-buffer: keep previous image visible while new one loads to prevent flicker
  const [previewImage, setPreviewImage] = useState<HTMLImageElement | null>(null)
  const loadingImgRef = useRef<HTMLImageElement | null>(null)

  useEffect(() => {
    if (!imgSrc) return
    const img = new window.Image()
    loadingImgRef.current = img
    img.onload = () => {
      // Only update if this is still the latest requested image
      if (loadingImgRef.current === img) {
        setPreviewImage(img)
      }
    }
    img.src = imgSrc
    return () => {
      // Cancel pending load to prevent stale callbacks after unmount
      if (loadingImgRef.current === img) {
        img.onload = null
        img.src = ''
        loadingImgRef.current = null
      }
    }
  }, [imgSrc])

  const stageRef = useRef<Konva.Stage>(null)

  const regions = useRegionStore((s) => s.regions)
  const selectedId = useRegionStore((s) => s.selectedId)
  const drawingMode = useRegionStore((s) => s.drawingMode)
  const drawingPoints = useRegionStore((s) => s.drawingPoints)
  const setRegions = useRegionStore((s) => s.setRegions)
  const addRegion = useRegionStore((s) => s.addRegion)
  const setSelectedId = useRegionStore((s) => s.setSelectedId)
  const appendPoint = useRegionStore((s) => s.appendPoint)
  const clearDrawing = useRegionStore((s) => s.clearDrawing)
  const updateRegionInStore = useRegionStore((s) => s.updateRegion)

  // Rectangle drawing state
  const [rectStart, setRectStart] = useState<[number, number] | null>(null)
  const [rectPreview, setRectPreview] = useState<[number, number][] | null>(null)

  // Minimum region area from backend settings
  const [minRegionArea, setMinRegionArea] = useState(0.001)

  // Load regions, lights, and settings on mount
  useEffect(() => {
    fetchRegions().then(setRegions).catch(console.error)
    fetch('/api/regions/settings')
      .then((r) => r.json())
      .then((s: { min_region_area: number }) => setMinRegionArea(s.min_region_area))
      .catch(console.error)
  }, [setRegions])


  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Delete' || e.key === 'Backspace') {
        onDeleteRequest?.()
      } else if (e.key === 'Escape') {
        clearDrawing()
        setRectStart(null)
        setRectPreview(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onDeleteRequest, clearDrawing])

  async function commitPolygon(pixelPoints: [number, number][]) {
    if (pixelPoints.length < 3) return
    const normalized = normalize(pixelPoints, width, height)
    if (polygonArea(normalized) < minRegionArea) {
      console.warn('Region too small, ignoring')
      clearDrawing()
      return
    }
    const regionCount = useRegionStore.getState().regions.length
    try {
      const region = await createRegion({
        name: `Region ${regionCount + 1}`,
        polygon: normalized,
      })
      addRegion(region)
    } catch (err) {
      console.error('Failed to create region:', err)
    }
    clearDrawing()
  }

  function getPointerPos(): [number, number] | null {
    const stage = stageRef.current
    if (!stage) return null
    const pos = stage.getPointerPosition()
    if (!pos) return null
    // Clamp to canvas bounds
    return [Math.min(Math.max(pos.x, 0), width), Math.min(Math.max(pos.y, 0), height)]
  }

  function handleStageClick(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    // Deselect on empty stage click
    if (e.target === e.target.getStage()) {
      setSelectedId(null)
    }

    if (drawingMode === 'polygon') {
      const pos = getPointerPos()
      if (!pos) return

      if (drawingPoints.length >= 3) {
        const [fx, fy] = drawingPoints[0]
        const dist = Math.hypot(pos[0] - fx, pos[1] - fy)
        if (dist < 10) {
          // Close polygon
          commitPolygon(drawingPoints)
          return
        }
      }
      appendPoint(pos)
    }
  }

  function handleMouseDown(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (drawingMode !== 'rectangle') return
    const pos = getPointerPos()
    if (!pos) return
    setRectStart(pos)
    setRectPreview(null)
    e.cancelBubble = true
  }

  function handleMouseMove(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (drawingMode !== 'rectangle' || !rectStart) return
    const pos = getPointerPos()
    if (!pos) return
    const [sx, sy] = rectStart
    const [ex, ey] = pos
    setRectPreview([
      [sx, sy],
      [ex, sy],
      [ex, ey],
      [sx, ey],
    ])
    e.cancelBubble = true
  }

  async function handleMouseUp(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (drawingMode !== 'rectangle' || !rectStart) return
    const pos = getPointerPos()
    if (!pos) return
    const [sx, sy] = rectStart
    const [ex, ey] = pos
    const pts: [number, number][] = [
      [sx, sy],
      [ex, sy],
      [ex, ey],
      [sx, ey],
    ]
    setRectStart(null)
    setRectPreview(null)
    await commitPolygon(pts)
    e.cancelBubble = true
  }

  const drawingLinePoints = drawingPoints.flatMap(([x, y]) => [x, y])
  const previewLinePoints = (rectPreview ?? []).flatMap(([x, y]) => [x, y])

  async function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault()
    const channelId = e.dataTransfer.getData('channelId')
    const channelName = e.dataTransfer.getData('channelName')
    const lightId = e.dataTransfer.getData('lightId')
    const configId = e.dataTransfer.getData('configId')

    if (!channelId && !lightId) return

    const stage = stageRef.current
    if (!stage) return

    // Update Konva pointer position from the DOM drag event
    stage.setPointersPositions(e)
    const pos = stage.getPointerPosition()
    if (!pos) return

    // Find which region contains the drop point (in pixel space)
    const currentRegions = useRegionStore.getState().regions
    const hit = currentRegions.find((region) => {
      const pixelPolygon = denormalize(region.polygon as [number, number][], width, height)
      return pointInPolygon([pos.x, pos.y], pixelPolygon)
    })

    if (!hit) return

    const assignLightId = lightId || null
    if (!assignLightId) return

    try {
      const update: Parameters<typeof updateRegionAPI>[1] = {
        light_id: assignLightId,
        name: channelName || hit.name,
      }
      if (channelId && configId) {
        update.channel_id = Number(channelId)
        update.entertainment_config_id = configId
      }
      await updateRegionAPI(hit.id, update)
      updateRegionInStore(hit.id, { light_id: assignLightId, name: update.name })
    } catch (err) {
      console.error('Failed to assign light to region:', err)
    }
  }

  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
      style={{ background: '#000', display: 'inline-block', touchAction: 'none' }}
    >
      <Stage
        ref={stageRef}
        width={width}
        height={height}
        onClick={handleStageClick}
        onTap={handleStageClick}
        onMouseDown={handleMouseDown}
        onTouchStart={handleMouseDown}
        onMouseMove={handleMouseMove}
        onTouchMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onTouchEnd={handleMouseUp}
      >
        {/* Layer 0: preview — no interaction */}
        <Layer listening={false}>
          {previewImage && (
            <KonvaImage image={previewImage} width={width} height={height} />
          )}
        </Layer>

        {/* Layer 1: regions + drawing-in-progress */}
        <Layer>
          {regions.map((region) => (
            <RegionPolygon
              key={region.id}
              region={region}
              isSelected={region.id === selectedId}
              stageWidth={width}
              stageHeight={height}
            />
          ))}

          {/* Polygon drawing in progress */}
          {drawingMode === 'polygon' && drawingPoints.length > 0 && (
            <>
              <Line
                points={drawingLinePoints}
                stroke="white"
                strokeWidth={2}
                dash={[6, 4]}
                listening={false}
              />
              {/* First point close-target indicator */}
              {drawingPoints.length >= 3 && (
                <Circle
                  x={drawingPoints[0][0]}
                  y={drawingPoints[0][1]}
                  radius={8}
                  stroke="yellow"
                  strokeWidth={2}
                  fill="rgba(255,255,0,0.3)"
                  listening={false}
                />
              )}
            </>
          )}

          {/* Rectangle preview */}
          {drawingMode === 'rectangle' && rectPreview && (
            <Line
              points={previewLinePoints}
              closed
              stroke="white"
              strokeWidth={2}
              dash={[6, 4]}
              listening={false}
            />
          )}
        </Layer>
      </Stage>
    </div>
  )
}

/**
 * Standalone delete handler — can be called from EditorPage toolbar or keyboard shortcut.
 */
export async function handleEditorDelete(): Promise<void> {
  const id = useRegionStore.getState().selectedId
  if (!id) return
  try {
    await deleteRegionAPI(id)
    useRegionStore.getState().deleteRegion(id)
    useRegionStore.getState().setSelectedId(null)
  } catch (err) {
    console.error('Failed to delete region:', err)
  }
}
