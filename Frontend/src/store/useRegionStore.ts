import { create } from 'zustand'
import type { Region } from '../api/regions'

interface RegionState {
  regions: Region[]
  selectedId: string | null
  drawingMode: 'select' | 'rectangle' | 'polygon'
  drawingPoints: [number, number][]
  setRegions: (r: Region[]) => void
  addRegion: (r: Region) => void
  updateRegion: (id: string, patch: Partial<Region>) => void
  deleteRegion: (id: string) => void
  setSelectedId: (id: string | null) => void
  setDrawingMode: (m: RegionState['drawingMode']) => void
  appendPoint: (pt: [number, number]) => void
  clearDrawing: () => void
}

export const useRegionStore = create<RegionState>((set) => ({
  regions: [],
  selectedId: null,
  drawingMode: 'select',
  drawingPoints: [],

  setRegions: (r) => set({ regions: r }),

  addRegion: (r) =>
    set((state) => ({ regions: [...state.regions, r] })),

  updateRegion: (id, patch) =>
    set((state) => ({
      regions: state.regions.map((region) =>
        region.id === id ? { ...region, ...patch } : region,
      ),
    })),

  deleteRegion: (id) =>
    set((state) => ({
      regions: state.regions.filter((region) => region.id !== id),
    })),

  setSelectedId: (id) => set({ selectedId: id }),

  setDrawingMode: (m) => set({ drawingMode: m }),

  appendPoint: (pt) =>
    set((state) => ({ drawingPoints: [...state.drawingPoints, pt] })),

  clearDrawing: () => set({ drawingPoints: [] }),
}))
