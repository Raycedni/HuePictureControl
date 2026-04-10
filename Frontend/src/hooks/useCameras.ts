import { useCallback, useEffect, useRef, useState } from 'react'
import { getCameras, type CamerasResponse } from '@/api/cameras'

const POLL_INTERVAL_MS = 5_000

export function useCameras() {
  const [data, setData] = useState<CamerasResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await getCameras()
      setData(result)
    } catch (e) {
      setError('Failed to load cameras')
      console.error('useCameras fetch error:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    pollRef.current = setInterval(refresh, POLL_INTERVAL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [refresh])

  return { data, loading, error, refresh }
}
