import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent, act } from '@testing-library/react'
import React from 'react'
import { EditorCanvas } from './EditorCanvas'
import { useRegionStore } from '@/store/useRegionStore'

// -----------------------------------------------------------------------
// Mock react-konva — Stage forwards its ref so handleDrop can call
// setPointersPositions + getPointerPosition on the fake stage object.
// -----------------------------------------------------------------------
const mockStage = {
  setPointersPositions: vi.fn(),
  // Put the drop point inside the region polygon (the region covers [0,0]-[1,1]
  // normalised, so pixel [50,50] is inside for a 100×100 canvas).
  getPointerPosition: vi.fn().mockReturnValue({ x: 50, y: 50 }),
}

vi.mock('react-konva', () => ({
  Stage: React.forwardRef(
    (
      { children }: { children?: React.ReactNode },
      ref: React.Ref<typeof mockStage>,
    ) => {
      React.useImperativeHandle(ref, () => mockStage)
      return React.createElement('div', { 'data-testid': 'konva-stage' }, children)
    },
  ),
  Layer: ({ children }: { children?: React.ReactNode }) =>
    React.createElement('div', null, children),
  Group: ({ children }: { children?: React.ReactNode }) =>
    React.createElement('div', null, children),
  Image: () => null,
  Line: () => null,
  Circle: () => null,
  Text: () => null,
}))

// -----------------------------------------------------------------------
// Mock @/api/wled (Phase 19.1: composite-key shape per D-13)
// -----------------------------------------------------------------------
const mockUpsertWledAssignment = vi.fn().mockResolvedValue({
  region_id: 'region-1',
  wled_device_id: 'dev-1',
  seg_index: 0,
  entertainment_config_id: 'cfg-1',
  orientation: 'auto',
})
const mockListWledAssignments = vi.fn().mockResolvedValue({ assignments: [] })
const mockGetWledDevices = vi.fn().mockResolvedValue({ devices: [] })
const mockListSegments = vi.fn().mockResolvedValue({ segments: [] })
const mockPatchRegionOrientation = vi.fn().mockResolvedValue({ updated: 1 })

vi.mock('@/api/wled', () => ({
  upsertWledAssignment: (...args: unknown[]) => mockUpsertWledAssignment(...args),
  listWledAssignments: (...args: unknown[]) => mockListWledAssignments(...args),
  getWledDevices: (...args: unknown[]) => mockGetWledDevices(...args),
  listSegments: (...args: unknown[]) => mockListSegments(...args),
  patchRegionOrientation: (...args: unknown[]) => mockPatchRegionOrientation(...args),
}))

// -----------------------------------------------------------------------
// Mock @/api/regions
// -----------------------------------------------------------------------
const mockUpdateRegionAPI = vi.fn().mockResolvedValue({})
const mockFetchRegions = vi.fn().mockResolvedValue([])

vi.mock('@/api/regions', () => ({
  updateRegion: (...args: unknown[]) => mockUpdateRegionAPI(...args),
  fetchRegions: (...args: unknown[]) => mockFetchRegions(...args),
  createRegion: vi.fn(),
  deleteRegion: vi.fn(),
}))

// Mock hooks that depend on WebSockets / previews
vi.mock('@/hooks/usePreviewWS', () => ({
  usePreviewWS: () => null,
}))

// Stub RegionOrientationPopover — not needed for drop branch tests
vi.mock('./Editor/RegionOrientationPopover', () => ({
  RegionOrientationPopover: () => null,
}))

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------
function makeDropEvent(data: Record<string, string>): React.DragEvent<HTMLDivElement> {
  return {
    preventDefault: vi.fn(),
    dataTransfer: {
      getData: (key: string) => data[key] ?? '',
    },
  } as unknown as React.DragEvent<HTMLDivElement>
}

function seedRegion() {
  // Seed a region whose normalised polygon covers the whole canvas.
  // For a 100×100 canvas, pixel [50,50] is inside this polygon.
  useRegionStore.getState().setRegions([
    {
      id: 'region-1',
      name: 'Test Region',
      polygon: [
        [0, 0],
        [1, 0],
        [1, 1],
        [0, 1],
      ] as [number, number][],
      light_id: null,
      channel_id: null,
      entertainment_config_id: null,
    },
  ])
}

// -----------------------------------------------------------------------
// Tests
// -----------------------------------------------------------------------
describe('EditorCanvas.handleDrop — WLED branch (Phase 19.1 composite key)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset store between tests
    useRegionStore.getState().setRegions([])
    useRegionStore.getState().setSelectedId(null)
    useRegionStore.getState().setWledAssignments({})
    mockStage.getPointerPosition.mockReturnValue({ x: 50, y: 50 })
  })

  it('WLED drop: discriminates on wledDeviceId presence; POSTs composite-key body per D-13', async () => {
    seedRegion()
    const { container } = render(
      <EditorCanvas width={100} height={100} selectedConfigId="cfg-1" />,
    )
    const dropTarget = container.firstChild as HTMLElement
    const evt = makeDropEvent({
      wledDeviceId: 'dev-1',
      seg_index: '0',
      entertainment_config_id: 'cfg-1',
    })

    await act(async () => {
      fireEvent.drop(dropTarget, evt)
      // Give async handleDrop a tick to settle
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(mockUpsertWledAssignment).toHaveBeenCalledOnce()
    expect(mockUpsertWledAssignment).toHaveBeenCalledWith({
      region_id: 'region-1',
      wled_device_id: 'dev-1',
      seg_index: 0,
      entertainment_config_id: 'cfg-1',
    })
    // Hue branch must NOT have been called
    expect(mockUpdateRegionAPI).not.toHaveBeenCalled()
  })

  it('Hue drop preserved: payload without wledDeviceId still calls updateRegionAPI', async () => {
    seedRegion()
    const { container } = render(
      <EditorCanvas width={100} height={100} selectedConfigId="cfg-1" />,
    )
    const dropTarget = container.firstChild as HTMLElement
    const evt = makeDropEvent({
      channelId: '3',
      channelName: 'Center',
      lightId: 'light-42',
      configId: 'cfg-hue',
    })

    await act(async () => {
      fireEvent.drop(dropTarget, evt)
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(mockUpsertWledAssignment).not.toHaveBeenCalled()
    expect(mockUpdateRegionAPI).toHaveBeenCalledOnce()
  })

  it('WLED branch returns: payload with BOTH wledDeviceId and lightId only calls WLED handler', async () => {
    seedRegion()
    const { container } = render(
      <EditorCanvas width={100} height={100} selectedConfigId="cfg-1" />,
    )
    const dropTarget = container.firstChild as HTMLElement
    const evt = makeDropEvent({
      wledDeviceId: 'dev-1',
      seg_index: '0',
      entertainment_config_id: 'cfg-1',
      lightId: 'light-42',
      channelId: '3',
    })

    await act(async () => {
      fireEvent.drop(dropTarget, evt)
      await new Promise((r) => setTimeout(r, 0))
    })

    // WLED path runs; Hue path is guarded by the explicit return
    expect(mockUpsertWledAssignment).toHaveBeenCalledOnce()
    expect(mockUpdateRegionAPI).not.toHaveBeenCalled()
  })

  it('WLED drop: missing seg_index aborts without POST', async () => {
    seedRegion()
    const { container } = render(
      <EditorCanvas width={100} height={100} selectedConfigId="cfg-1" />,
    )
    const dropTarget = container.firstChild as HTMLElement
    const evt = makeDropEvent({
      wledDeviceId: 'dev-1',
      // seg_index intentionally missing
      entertainment_config_id: 'cfg-1',
    })

    await act(async () => {
      fireEvent.drop(dropTarget, evt)
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(mockUpsertWledAssignment).not.toHaveBeenCalled()
    expect(mockUpdateRegionAPI).not.toHaveBeenCalled()
  })

  it('WLED drop: missing entertainment_config_id aborts without POST', async () => {
    seedRegion()
    const { container } = render(
      <EditorCanvas width={100} height={100} selectedConfigId="cfg-1" />,
    )
    const dropTarget = container.firstChild as HTMLElement
    const evt = makeDropEvent({
      wledDeviceId: 'dev-1',
      seg_index: '0',
      // entertainment_config_id intentionally missing
    })

    await act(async () => {
      fireEvent.drop(dropTarget, evt)
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(mockUpsertWledAssignment).not.toHaveBeenCalled()
    expect(mockUpdateRegionAPI).not.toHaveBeenCalled()
  })

  it('No payload: handler exits without API calls when neither key is present', async () => {
    seedRegion()
    const { container } = render(
      <EditorCanvas width={100} height={100} selectedConfigId="cfg-1" />,
    )
    const dropTarget = container.firstChild as HTMLElement
    const evt = makeDropEvent({})

    await act(async () => {
      fireEvent.drop(dropTarget, evt)
      await new Promise((r) => setTimeout(r, 0))
    })

    expect(mockUpsertWledAssignment).not.toHaveBeenCalled()
    expect(mockUpdateRegionAPI).not.toHaveBeenCalled()
  })
})

describe('EditorCanvas — popover mount', () => {
  it.todo('renders RegionOrientationPopover as a sibling of Konva Stage')
})
