import { create } from 'zustand'

interface StatusState {
  fps: number
  latency: number
  bridgeState: string
  error: string | null
  isStreaming: boolean
  activeConfigId: string | null // BFIX-02: entertainment_config_id the server is streaming (null when idle/error)
  activeDevicePath: string | null // BFIX-02: capture device_path the server is streaming (null when idle/error)
  setMetrics: (m: Partial<Omit<StatusState, 'setMetrics'>>) => void
}

export const useStatusStore = create<StatusState>((set) => ({
  fps: 0,
  latency: 0,
  bridgeState: 'unknown',
  error: null,
  isStreaming: false,
  activeConfigId: null,
  activeDevicePath: null,

  setMetrics: (m) => set((state) => ({ ...state, ...m })),
}))
