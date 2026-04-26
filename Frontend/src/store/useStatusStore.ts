import { create } from 'zustand'

// Phase 17 D-16: per-device WLED health snapshot mirrored from the server's
// StatusBroadcaster._metrics["wled_devices"] payload. Stored but not rendered
// in Phase 17 — only the in_cooldown badge surfaces in the Settings panel.
export interface WledDeviceHealth {
  last_error: string | null
  last_success_at: string | null
  in_cooldown: boolean
}

interface StatusState {
  fps: number
  latency: number
  bridgeState: string
  error: string | null
  isStreaming: boolean
  activeConfigId: string | null // BFIX-02: entertainment_config_id the server is streaming (null when idle/error)
  activeDevicePath: string | null // BFIX-02: capture device_path the server is streaming (null when idle/error)
  // Phase 17 D-16: live WLED device health keyed by device id. Empty by
  // default; populated by useStatusWS from the WS payload.
  wledDevices: Record<string, WledDeviceHealth>
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
  wledDevices: {},

  setMetrics: (m) => set((state) => ({ ...state, ...m })),
}))
