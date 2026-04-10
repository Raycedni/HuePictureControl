import { useEffect, useRef, useState } from 'react'
import {
  fetchConfigs,
  fetchRegions,
  startStreaming,
  stopStreaming,
  triggerAutoMap,
} from '../api/regions'
import type { Config, Region } from '../api/regions'
import { usePreviewWS } from '../hooks/usePreviewWS'
import { Button } from './ui/button'

type StreamingState = 'idle' | 'streaming'

const OVERLAY_COLORS = [
  'rgba(232, 160, 0, 0.35)',
  'rgba(100, 200, 255, 0.35)',
  'rgba(100, 255, 150, 0.35)',
  'rgba(168, 85, 247, 0.35)',
  'rgba(255, 100, 200, 0.35)',
  'rgba(255, 160, 60, 0.35)',
  'rgba(80, 220, 220, 0.35)',
  'rgba(59, 130, 246, 0.35)',
]

export default function PreviewPage() {
  const [configs, setConfigs] = useState<Config[]>([])
  const [selectedConfigId, setSelectedConfigId] = useState<string>('')
  const [regions, setRegions] = useState<Region[]>([])
  const [streamingState, setStreamingState] = useState<StreamingState>('idle')
  const [targetHz, setTargetHz] = useState<number>(50)
  const [autoMapStatus, setAutoMapStatus] = useState<string>('')
  const [autoMapError, setAutoMapError] = useState<string>('')
  const [streamError, setStreamError] = useState<string>('')
  const [imageError, setImageError] = useState(false)
  const [imgDimensions, setImgDimensions] = useState<{ width: number; height: number } | null>(null)

  const imgRef = useRef<HTMLImageElement>(null)
  const previewSrc = usePreviewWS(true)

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
        await startStreaming(selectedConfigId, targetHz)
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
      border: '1px solid rgba(255,255,255,0.2)',
      borderRadius: '4px',
      boxSizing: 'border-box',
      display: 'flex',
      alignItems: 'flex-end',
      justifyContent: 'flex-start',
      overflow: 'hidden',
    }
  }

  return (
    <div className="flex flex-col gap-4 p-5 max-w-4xl mx-auto w-full text-left">

      {/* Config selector row */}
      <div className="glass rounded-xl p-4 flex items-center gap-3 flex-wrap">
        <label htmlFor="config-select" className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Config
        </label>
        <select
          id="config-select"
          value={selectedConfigId}
          onChange={(e) => setSelectedConfigId(e.target.value)}
          disabled={isStreaming || configs.length === 0}
          className="min-w-[180px] text-sm"
        >
          {configs.length === 0 && <option value="">No configs available</option>}
          {configs.map((cfg) => (
            <option key={cfg.id} value={cfg.id}>
              {cfg.name} ({cfg.channel_count} ch)
            </option>
          ))}
        </select>
        <Button
          onClick={handleAutoMap}
          disabled={isStreaming || !selectedConfigId}
          variant="outline"
          size="sm"
          className="border-white/10"
        >
          Auto-Map
        </Button>
        {autoMapStatus && (
          <span className="text-xs text-green-400">{autoMapStatus}</span>
        )}
        {autoMapError && (
          <span className="text-xs text-red-400">{autoMapError}</span>
        )}
      </div>

      {/* Camera preview with region overlays */}
      <div className="relative inline-block max-w-full">
        {imageError ? (
          <div className="w-[640px] max-w-full aspect-video rounded-2xl glass flex items-center justify-center">
            <div className="text-center">
              <div className="w-10 h-10 mx-auto mb-2 rounded-full bg-white/5 flex items-center justify-center">
                <svg className="w-5 h-5 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 10.5l4.72-4.72a.75.75 0 011.28.53v11.38a.75.75 0 01-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25h-9A2.25 2.25 0 002.25 7.5v9a2.25 2.25 0 002.25 2.25z" />
                </svg>
              </div>
              <span className="text-sm text-muted-foreground">No capture device</span>
            </div>
          </div>
        ) : (
          <img
            ref={imgRef}
            src={previewSrc ?? ''}
            alt="Camera preview"
            onLoad={handleImageLoad}
            onError={handleImageError}
            className="block max-w-full rounded-2xl border border-white/[0.06]"
          />
        )}
        {/* Region overlays */}
        {!imageError && imgDimensions &&
          regions.map((region, idx) => (
            <div key={region.id} style={getOverlayStyle(region, idx)}>
              <span className="text-[10px] text-white bg-black/50 px-1.5 py-0.5 rounded max-w-full overflow-hidden text-ellipsis whitespace-nowrap backdrop-blur-sm">
                {region.name}
              </span>
            </div>
          ))}
      </div>

      {/* Start/Stop toggle + update rate */}
      <div className="glass rounded-xl p-4 flex items-center gap-4 flex-wrap">
        <Button
          onClick={handleStartStop}
          disabled={!selectedConfigId && !isStreaming}
          className={
            isStreaming
              ? 'bg-red-500/15 text-red-400 border-red-500/25 hover:bg-red-500/25'
              : 'bg-hue-orange/15 text-hue-amber border-hue-orange/25 hover:bg-hue-orange/25 hue-glow'
          }
        >
          {isStreaming ? 'Stop Streaming' : 'Start Streaming'}
        </Button>
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
            Update Rate
          </span>
          <input
            type="range"
            min={1}
            max={100}
            value={targetHz}
            onChange={(e) => setTargetHz(Number(e.target.value))}
            disabled={isStreaming}
            className="w-[120px]"
          />
          <span className="text-sm font-mono text-foreground min-w-[3.5rem]">{targetHz} Hz</span>
        </div>
        {streamingState === 'streaming' && (
          <span className="text-xs text-hue-amber flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-hue-orange animate-pulse" />
            Streaming
          </span>
        )}
        {streamError && <span className="text-xs text-red-400">{streamError}</span>}
      </div>

    </div>
  )
}
