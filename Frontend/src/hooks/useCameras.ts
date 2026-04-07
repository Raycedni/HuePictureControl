import { useEffect, useState } from 'react'
import { getCameras, type CamerasResponse } from '@/api/cameras'

export function useCameras() {
  const [data, setData] = useState<CamerasResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
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
  }

  useEffect(() => {
    refresh()
  }, [])

  return { data, loading, error, refresh }
}
