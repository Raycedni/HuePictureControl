import { create } from 'zustand'
import type { Region } from '../api/regions'
import type { WledAssignment } from '../api/wled'

interface RegionState {
  regions: Region[]
  selectedId: string | null
  drawingMode: 'select' | 'rectangle' | 'polygon'
  drawingPoints: [number, number][]
  wledAssignments: Record<string, WledAssignment[]>
  setRegions: (r: Region[]) => void
  addRegion: (r: Region) => void
  updateRegion: (id: string, patch: Partial<Region>) => void
  deleteRegion: (id: string) => void
  setSelectedId: (id: string | null) => void
  setDrawingMode: (m: RegionState['drawingMode']) => void
  appendPoint: (pt: [number, number]) => void
  clearDrawing: () => void
  setWledAssignments: (a: Record<string, WledAssignment[]>) => void
  updateWledAssignmentOrientation: (
    regionId: string,
    orientation: WledAssignment['orientation'],
  ) => void
}

export const useRegionStore = create<RegionState>((set) => ({
  regions: [],
  selectedId: null,
  drawingMode: 'select',
  drawingPoints: [],
  wledAssignments: {},

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

  setWledAssignments: (a) => set({ wledAssignments: a }),

  updateWledAssignmentOrientation: (regionId, orientation) =>
    set((state) => {
      const existing = state.wledAssignments[regionId] ?? []
      if (existing.length === 0) return state
      return {
        wledAssignments: {
          ...state.wledAssignments,
          [regionId]: existing.map((a) => ({ ...a, orientation })),
        },
      }
    }),
}))
