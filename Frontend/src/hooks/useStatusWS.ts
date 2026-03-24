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
          const parsed = JSON.parse(ev.data as string) as Record<string, unknown>
          useStatusStore.getState().setMetrics(parsed)
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
