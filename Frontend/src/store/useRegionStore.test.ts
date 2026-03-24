import { describe, it, expect, beforeEach } from 'vitest'
import { useRegionStore } from './useRegionStore'
import type { Region } from '../api/regions'

const makeRegion = (id: string): Region => ({
  id,
  name: `Region ${id}`,
  polygon: [[0, 0], [1, 0], [1, 1], [0, 1]],
  order_index: 0,
  light_id: null,
})

describe('useRegionStore', () => {
  beforeEach(() => {
    useRegionStore.setState({
      regions: [],
      selectedId: null,
      drawingMode: 'select',
      drawingPoints: [],
    })
  })

  it('setRegions replaces the entire array', () => {
    const r1 = makeRegion('1')
    const r2 = makeRegion('2')
    useRegionStore.getState().setRegions([r1, r2])
    expect(useRegionStore.getState().regions).toEqual([r1, r2])
    useRegionStore.getState().setRegions([r2])
    expect(useRegionStore.getState().regions).toEqual([r2])
  })

  it('addRegion appends to regions', () => {
    const r1 = makeRegion('1')
    const r2 = makeRegion('2')
    useRegionStore.getState().addRegion(r1)
    useRegionStore.getState().addRegion(r2)
    expect(useRegionStore.getState().regions).toHaveLength(2)
    expect(useRegionStore.getState().regions[1].id).toBe('2')
  })

  it('updateRegion patches matching region by id', () => {
    const r1 = makeRegion('1')
    useRegionStore.getState().setRegions([r1])
    useRegionStore.getState().updateRegion('1', { name: 'Updated' })
    expect(useRegionStore.getState().regions[0].name).toBe('Updated')
    expect(useRegionStore.getState().regions[0].id).toBe('1')
  })

  it('deleteRegion removes region by id', () => {
    const r1 = makeRegion('1')
    const r2 = makeRegion('2')
    useRegionStore.getState().setRegions([r1, r2])
    useRegionStore.getState().deleteRegion('1')
    expect(useRegionStore.getState().regions).toHaveLength(1)
    expect(useRegionStore.getState().regions[0].id).toBe('2')
  })

  it('setSelectedId updates selectedId', () => {
    useRegionStore.getState().setSelectedId('abc')
    expect(useRegionStore.getState().selectedId).toBe('abc')
    useRegionStore.getState().setSelectedId(null)
    expect(useRegionStore.getState().selectedId).toBeNull()
  })

  it('setDrawingMode updates drawingMode', () => {
    useRegionStore.getState().setDrawingMode('polygon')
    expect(useRegionStore.getState().drawingMode).toBe('polygon')
    useRegionStore.getState().setDrawingMode('select')
    expect(useRegionStore.getState().drawingMode).toBe('select')
  })

  it('appendPoint adds a point to drawingPoints', () => {
    useRegionStore.getState().appendPoint([10, 20])
    useRegionStore.getState().appendPoint([30, 40])
    expect(useRegionStore.getState().drawingPoints).toEqual([[10, 20], [30, 40]])
  })

  it('clearDrawing resets drawingPoints to empty array', () => {
    useRegionStore.getState().appendPoint([5, 5])
    useRegionStore.getState().clearDrawing()
    expect(useRegionStore.getState().drawingPoints).toEqual([])
  })
})
