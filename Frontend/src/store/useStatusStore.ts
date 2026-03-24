import { create } from 'zustand'

interface StatusState {
  fps: number
  latency: number
  bridgeState: string
  error: string | null
  isStreaming: boolean
  setMetrics: (m: Partial<Omit<StatusState, 'setMetrics'>>) => void
}

export const useStatusStore = create<StatusState>((set) => ({
  fps: 0,
  latency: 0,
  bridgeState: 'unknown',
  error: null,
  isStreaming: false,

  setMetrics: (m) => set((state) => ({ ...state, ...m })),
}))
