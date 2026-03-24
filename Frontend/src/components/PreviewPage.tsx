import { useEffect, useRef, useState } from 'react'
import {
  fetchConfigs,
  fetchRegions,
  startStreaming,
  stopStreaming,
  triggerAutoMap,
} from '../api/regions'
import type { Config, Region } from '../api/regions'

type StreamingState = 'idle' | 'streaming'

const OVERLAY_COLORS = [
  'rgba(255, 100, 100, 0.4)',
  'rgba(100, 200, 255, 0.4)',
  'rgba(100, 255, 150, 0.4)',
  'rgba(255, 220, 80, 0.4)',
  'rgba(200, 100, 255, 0.4)',
  'rgba(255, 160, 60, 0.4)',
  'rgba(80, 220, 220, 0.4)',
  'rgba(255, 100, 200, 0.4)',
]

export default function PreviewPage() {
  const [configs, setConfigs] = useState<Config[]>([])
  const [selectedConfigId, setSelectedConfigId] = useState<string>('')
  const [regions, setRegions] = useState<Region[]>([])
  const [streamingState, setStreamingState] = useState<StreamingState>('idle')
  const [autoMapStatus, setAutoMapStatus] = useState<string>('')
  const [autoMapError, setAutoMapError] = useState<string>('')
  const [streamError, setStreamError] = useState<string>('')
  const [imageError, setImageError] = useState(false)
  const [snapshotTs, setSnapshotTs] = useState<number>(Date.now())
  const [imgDimensions, setImgDimensions] = useState<{ width: number; height: number } | null>(null)

  const imgRef = useRef<HTMLImageElement>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Load configs on mount
  useEffect(() => {
    fetchConfigs()
      .then((cfgs) => {
        setConfigs(cfgs)
        if (cfgs.length > 0) setSelectedConfigId(cfgs[0].id)
      })
      .catch(() => {
        // Non-critical
      })
    // Load existing regions on mount
    fetchRegions()
      .then(setRegions)
      .catch(() => {
        // Non-critical
      })
  }, [])

  // Refresh snapshot every 2 seconds
  useEffect(() => {
    intervalRef.current = setInterval(() => {
      setSnapshotTs(Date.now())
    }, 2000)
    return () => {
      if (intervalRef.current !== null) clearInterval(intervalRef.current)
    }
  }, [])

  function handleImageLoad() {
    setImageError(false)
    if (imgRef.current) {
      setImgDimensions({
        width: imgRef.current.naturalWidth,
        height: imgRef.current.naturalHeight,
      })
    }
  }

  function handleImageError() {
    setImageError(true)
    setImgDimensions(null)
  }

  async function handleAutoMap() {
    if (!selectedConfigId) return
    setAutoMapStatus('')
    setAutoMapError('')
    try {
      const result = await triggerAutoMap(selectedConfigId)
      const msg = `${result.regions_created} region${result.regions_created !== 1 ? 's' : ''} created`
      setAutoMapStatus(result.warning ? `${msg} — Warning: ${result.warning}` : msg)
      const updated = await fetchRegions()
      setRegions(updated)
    } catch {
      setAutoMapError('Auto-map failed. Is a config selected?')
    }
  }

  async function handleStartStop() {
    setStreamError('')
    if (streamingState === 'idle') {
      if (!selectedConfigId) return
      try {
        await startStreaming(selectedConfigId)
        setStreamingState('streaming')
      } catch {
        setStreamError('Failed to start streaming.')
      }
    } else {
      try {
        await stopStreaming()
        setStreamingState('idle')
      } catch {
        setStreamError('Failed to stop streaming.')
      }
    }
  }

  const isStreaming = streamingState === 'streaming'
  const snapshotSrc = `/api/capture/snapshot?t=${snapshotTs}`

  // Compute overlay style from polygon (top-left and bottom-right corners)
  function getOverlayStyle(region: Region, colorIndex: number): React.CSSProperties {
    if (!imgRef.current || !imgDimensions || region.polygon.length < 2) return { display: 'none' }
    const renderedWidth = imgRef.current.clientWidth
    const renderedHeight = imgRef.current.clientHeight
    const [x1, y1] = region.polygon[0]
    const [x2, y2] = region.polygon[1]
    const left = Math.min(x1, x2) * renderedWidth
    const top = Math.min(y1, y2) * renderedHeight
    const width = Math.abs(x2 - x1) * renderedWidth
    const height = Math.abs(y2 - y1) * renderedHeight
    return {
      position: 'absolute',
      left: `${left}px`,
      top: `${top}px`,
      width: `${width}px`,
      height: `${height}px`,
      backgroundColor: OVERLAY_COLORS[colorIndex % OVERLAY_COLORS.length],
      border: '1px solid rgba(255,255,255,0.6)',
      boxSizing: 'border-box',
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'flex-start',
      overflow: 'hidden',
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>

      {/* Config selector row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
        <label htmlFor="config-select" style={{ fontWeight: 600 }}>
          Entertainment Config:
        </label>
        <select
          id="config-select"
          value={selectedConfigId}
          onChange={(e) => setSelectedConfigId(e.target.value)}
          disabled={isStreaming || configs.length === 0}
          style={{ padding: '0.3rem 0.5rem', minWidth: '180px' }}
        >
          {configs.length === 0 && <option value="">No configs available</option>}
          {configs.map((cfg) => (
            <option key={cfg.id} value={cfg.id}>
              {cfg.name} ({cfg.channel_count} ch)
            </option>
          ))}
        </select>
        <button
          onClick={handleAutoMap}
          disabled={isStreaming || !selectedConfigId}
          style={{ padding: '0.3rem 0.8rem' }}
        >
          Auto-Map
        </button>
        {autoMapStatus && (
          <span style={{ color: '#2a7' }}>{autoMapStatus}</span>
        )}
        {autoMapError && (
          <span style={{ color: '#c33' }}>{autoMapError}</span>
        )}
      </div>

      {/* Camera preview with region overlays */}
      <div style={{ position: 'relative', display: 'inline-block', maxWidth: '100%' }}>
        {imageError ? (
          <div
            style={{
              width: '640px',
              height: '360px',
              background: '#222',
              color: '#aaa',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: '4px',
              maxWidth: '100%',
            }}
          >
            No capture device
          </div>
        ) : (
          <img
            ref={imgRef}
            src={snapshotSrc}
            alt="Camera preview"
            onLoad={handleImageLoad}
            onError={handleImageError}
            style={{ display: 'block', maxWidth: '100%', borderRadius: '4px' }}
          />
        )}
        {/* Region overlays */}
        {!imageError && imgDimensions &&
          regions.map((region, idx) => (
            <div key={region.id} style={getOverlayStyle(region, idx)}>
              <span
                style={{
                  fontSize: '10px',
                  color: '#fff',
                  background: 'rgba(0,0,0,0.55)',
                  padding: '1px 3px',
                  borderRadius: '2px',
                  maxWidth: '100%',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {region.name}
              </span>
            </div>
          ))}
      </div>

      {/* Start/Stop toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <button
          onClick={handleStartStop}
          disabled={!selectedConfigId && !isStreaming}
          style={{
            padding: '0.5rem 1.5rem',
            fontWeight: 600,
            background: isStreaming ? '#c33' : '#2a7',
            color: '#fff',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
          }}
        >
          {isStreaming ? 'Stop Streaming' : 'Start Streaming'}
        </button>
        {streamingState === 'streaming' && (
          <span style={{ color: '#2a7' }}>Streaming...</span>
        )}
        {streamError && <span style={{ color: '#c33' }}>{streamError}</span>}
      </div>

    </div>
  )
}
