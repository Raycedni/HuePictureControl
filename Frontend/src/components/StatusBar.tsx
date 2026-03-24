import { useStatusStore } from '../store/useStatusStore'
import { useStatusWS } from '../hooks/useStatusWS'
import { Badge } from './ui/badge'

export function StatusBar() {
  useStatusWS()

  const fps = useStatusStore((s) => s.fps)
  const latency = useStatusStore((s) => s.latency)
  const bridgeState = useStatusStore((s) => s.bridgeState)
  const error = useStatusStore((s) => s.error)
  const isStreaming = useStatusStore((s) => s.isStreaming)

  return (
    <div className="flex items-center justify-between px-4 py-1.5 border-t border-border bg-muted/40 text-sm text-muted-foreground h-10">
      <div className="flex items-center gap-2">
        <Badge
          variant={isStreaming ? 'default' : 'secondary'}
          className={isStreaming ? 'bg-green-600 text-white hover:bg-green-600' : ''}
        >
          {isStreaming ? 'Streaming' : 'Idle'}
        </Badge>
      </div>

      <div className="flex items-center gap-4">
        <span>
          FPS: <span className="font-medium text-foreground">{fps.toFixed(1)}</span>
        </span>
        <span>
          Latency: <span className="font-medium text-foreground">{latency}ms</span>
        </span>
      </div>

      <div className="flex items-center gap-2">
        <span>
          Bridge: <span className="font-medium text-foreground">{bridgeState}</span>
        </span>
        {error && (
          <span className="text-destructive font-medium">{error}</span>
        )}
      </div>
    </div>
  )
}
