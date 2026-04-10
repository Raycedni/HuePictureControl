import { useStatusStore } from '../store/useStatusStore'
import { useStatusWS } from '../hooks/useStatusWS'

export function StatusBar() {
  useStatusWS()

  const fps = useStatusStore((s) => s.fps)
  const latency = useStatusStore((s) => s.latency)
  const bridgeState = useStatusStore((s) => s.bridgeState)
  const error = useStatusStore((s) => s.error)
  const isStreaming = useStatusStore((s) => s.isStreaming)

  return (
    <div className="flex items-center justify-between px-2 md:px-5 py-1.5 md:py-2 border-t border-white/[0.06] bg-white/[0.02] text-[10px] md:text-xs text-muted-foreground h-8 md:h-9 shrink-0 gap-2 overflow-x-auto">
      <div className="flex items-center gap-2 shrink-0">
        <span className={`flex items-center gap-1 md:gap-1.5 px-1.5 md:px-2 py-0.5 rounded-full text-[10px] md:text-[11px] font-medium ${
          isStreaming
            ? 'bg-hue-orange/15 text-hue-amber'
            : 'bg-white/5 text-muted-foreground'
        }`}>
          <span className={`w-1.5 h-1.5 rounded-full ${
            isStreaming ? 'bg-hue-orange animate-pulse shadow-[0_0_6px_rgba(232,160,0,0.5)]' : 'bg-white/20'
          }`} />
          {isStreaming ? 'Streaming' : 'Idle'}
        </span>
      </div>

      <div className="flex items-center gap-2 md:gap-4 shrink-0">
        <span>
          <span className="hidden sm:inline">FPS </span><span className="font-mono font-medium text-foreground">{fps.toFixed(1)}</span>
        </span>
        <span>
          <span className="hidden sm:inline">Latency </span><span className="font-mono font-medium text-foreground">{latency}ms</span>
        </span>
      </div>

      <div className="flex items-center gap-2 md:gap-3 shrink-0">
        <span className="hidden sm:inline">
          Bridge <span className="font-medium text-foreground">{bridgeState}</span>
        </span>
        {error && (
          <span className="text-red-400 font-medium truncate max-w-[120px] md:max-w-none">{error}</span>
        )}
      </div>
    </div>
  )
}
