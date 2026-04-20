import { useEffect } from 'react'
import { useStatusStore } from '../store/useStatusStore'

export function useStatusWS(): void {
  useEffect(() => {
    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let destroyed = false

    function connect() {
      if (destroyed) return

      ws = new WebSocket(`ws://${location.host}/ws/status`)

      ws.onmessage = (ev: MessageEvent) => {
        try {
          const raw = JSON.parse(ev.data as string) as Record<string, unknown>
          useStatusStore.getState().setMetrics({
            fps: typeof raw.fps === 'number' ? raw.fps : undefined,
            latency: typeof raw.latency_ms === 'number' ? raw.latency_ms : undefined,
            bridgeState: typeof raw.state === 'string' ? raw.state : undefined,
            isStreaming: raw.state === 'streaming',
            error: typeof raw.error === 'string' ? raw.error : null,
            // BFIX-02: tri-state parse — pass-through string, explicit null, or
            // undefined (omit) if the server didn't send the field. Preserves
            // the existing Partial<setMetrics> semantics so older payloads
            // don't clobber local state.
            activeConfigId:
              typeof raw.active_config_id === 'string'
                ? raw.active_config_id
                : raw.active_config_id === null
                  ? null
                  : undefined,
            activeDevicePath:
              typeof raw.active_device_path === 'string'
                ? raw.active_device_path
                : raw.active_device_path === null
                  ? null
                  : undefined,
          })
        } catch {
          // ignore malformed JSON
        }
      }

      ws.onclose = () => {
        if (!destroyed) {
          reconnectTimer = setTimeout(connect, 2000)
        }
      }

      ws.onerror = () => {
        ws?.close()
      }
    }

    connect()

    return () => {
      destroyed = true
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer)
      }
      ws?.close()
    }
  }, [])
}
