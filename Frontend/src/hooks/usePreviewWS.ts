import { useEffect, useRef, useState } from 'react'

export function usePreviewWS(enabled: boolean): string | null {
  const [imgSrc, setImgSrc] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const prevUrlRef = useRef<string | null>(null)

  useEffect(() => {
    if (!enabled) {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (prevUrlRef.current) {
        URL.revokeObjectURL(prevUrlRef.current)
        prevUrlRef.current = null
      }
      setImgSrc(null)
      return
    }

    const ws = new WebSocket(`ws://${location.host}/ws/preview`)
    ws.binaryType = 'blob'
    wsRef.current = ws

    ws.onmessage = (ev: MessageEvent) => {
      const blob = ev.data as Blob
      const url = URL.createObjectURL(blob)

      if (prevUrlRef.current) {
        URL.revokeObjectURL(prevUrlRef.current)
      }
      prevUrlRef.current = url
      setImgSrc(url)
    }

    return () => {
      ws.close()
      wsRef.current = null
      if (prevUrlRef.current) {
        URL.revokeObjectURL(prevUrlRef.current)
        prevUrlRef.current = null
      }
    }
  }, [enabled])

  return imgSrc
}
