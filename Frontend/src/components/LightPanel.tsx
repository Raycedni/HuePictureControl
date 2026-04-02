import { useEffect, useState } from 'react'
import { getLights, fetchConfigChannels, type Light, type ConfigChannel } from '@/api/hue'
import { fetchConfigs, startStreaming, stopStreaming, type Config } from '@/api/regions'
import { useStatusStore } from '@/store/useStatusStore'
import { useRegionStore } from '@/store/useRegionStore'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function LightPanel() {
  const [lights, setLights] = useState<Light[]>([])
  const [configs, setConfigs] = useState<Config[]>([])
  const [selectedConfigId, setSelectedConfigId] = useState<string>('')
  const [channels, setChannels] = useState<ConfigChannel[]>([])
  const [error, setError] = useState<string | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)

  const isStreaming = useStatusStore((s) => s.isStreaming)
  const regions = useRegionStore((s) => s.regions)

  useEffect(() => {
    getLights()
      .then(setLights)
      .catch((err) => {
        console.error('Failed to load lights:', err)
        setError('Failed to load lights')
      })

    fetchConfigs()
      .then((cfgs) => {
        setConfigs(cfgs)
        if (cfgs.length > 0 && !selectedConfigId) {
          setSelectedConfigId(cfgs[0].id)
        }
      })
      .catch((err) => {
        console.error('Failed to load configs:', err)
      })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!selectedConfigId) return
    fetchConfigChannels(selectedConfigId)
      .then(setChannels)
      .catch((err) => console.error('Failed to load channels:', err))
  }, [selectedConfigId])

  async function handleToggleStreaming() {
    setStreamError(null)
    try {
      if (isStreaming) {
        await stopStreaming()
      } else {
        if (!selectedConfigId) {
          setStreamError('Select a config first')
          return
        }
        await startStreaming(selectedConfigId)
      }
    } catch (err) {
      console.error('Streaming toggle failed:', err)
      setStreamError('Streaming action failed')
    }
  }

  // Build a map of light_id -> region name for "assigned" display
  const assignedMap: Record<string, string> = {}
  for (const region of regions) {
    if (region.light_id) {
      assignedMap[region.light_id] = region.name
    }
  }

  // Channel counter: count regions with any light assigned
  const assignedCount = regions.filter((r) => r.light_id !== null).length

  // Group channels by light_id
  const channelsByLight: Record<string, ConfigChannel[]> = {}
  for (const ch of channels) {
    if (!channelsByLight[ch.light_id]) {
      channelsByLight[ch.light_id] = []
    }
    channelsByLight[ch.light_id].push(ch)
  }

  // Build the set of light IDs that appear in channels
  const channelLightIds = new Set(Object.keys(channelsByLight))

  return (
    <div className="flex flex-col gap-3 p-3 border-l h-full">
      {/* Streaming section */}
      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-muted-foreground">Streaming</h2>

        {configs.length > 0 ? (
          <select
            className="text-xs border rounded px-2 py-1 bg-background text-foreground"
            value={selectedConfigId}
            onChange={(e) => setSelectedConfigId(e.target.value)}
            disabled={isStreaming}
          >
            {configs.map((cfg) => (
              <option key={cfg.id} value={cfg.id}>
                {cfg.name}
              </option>
            ))}
          </select>
        ) : (
          <p className="text-xs text-muted-foreground">No entertainment configs</p>
        )}

        <Button
          size="sm"
          variant={isStreaming ? 'destructive' : 'default'}
          onClick={handleToggleStreaming}
          className="w-full"
        >
          {isStreaming ? 'Stop' : 'Start'}
        </Button>

        {streamError && <p className="text-xs text-destructive">{streamError}</p>}
      </div>

      <div className="border-t" />

      {/* Lights section */}
      <div className="flex flex-col gap-2 min-h-0 flex-1">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-muted-foreground">Lights</h2>
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'text-xs font-mono',
                assignedCount > 20
                  ? 'text-red-500'
                  : assignedCount === 20
                    ? 'text-yellow-500'
                    : 'text-muted-foreground',
              )}
            >
              {assignedCount} / 20 channels
            </span>
            <Button
              size="sm"
              variant="outline"
              className="h-6 text-xs px-2"
              onClick={() => {
                setError(null)
                getLights()
                  .then(setLights)
                  .catch(() => setError('Failed to sync lights'))
                if (selectedConfigId) {
                  fetchConfigChannels(selectedConfigId)
                    .then(setChannels)
                    .catch((err) => console.error('Failed to reload channels:', err))
                }
              }}
            >
              Sync
            </Button>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">Drag a light onto a region to assign it.</p>

        {error && <p className="text-xs text-destructive">{error}</p>}

        <ScrollArea className="flex-1">
          <div className="flex flex-col gap-1">
            {lights.length === 0 && !error && (
              <p className="text-xs text-muted-foreground">Loading lights...</p>
            )}
            {lights.map((light) => {
              const lightChannels = channelsByLight[light.id]
              const isGradient = lightChannels && lightChannels.length > 1

              if (isGradient) {
                // Gradient light: show parent header + per-segment rows
                return (
                  <div key={light.id} className="flex flex-col gap-0.5">
                    {/* Gradient parent header — not draggable */}
                    <div className="flex items-center justify-between gap-1 rounded px-2 py-1 border bg-muted/30 select-none">
                      <span className="text-xs font-semibold truncate">{light.name}</span>
                      <Badge variant="secondary" className="text-[10px] shrink-0">
                        gradient
                      </Badge>
                    </div>
                    {/* Per-segment draggable rows */}
                    <div className="ml-3 border-l-2 border-primary/30 flex flex-col gap-0.5 pl-1">
                      {lightChannels
                        .sort((a, b) => a.segment_index - b.segment_index)
                        .map((channel) => {
                          const segAssignedTo = assignedMap[light.id]
                          return (
                            <div
                              key={channel.channel_id}
                              draggable
                              onDragStart={(e) => {
                                e.dataTransfer.setData('channelId', String(channel.channel_id))
                                e.dataTransfer.setData(
                                  'channelName',
                                  `${channel.light_name} - Seg ${channel.segment_index + 1}`,
                                )
                                e.dataTransfer.setData('lightId', channel.light_id)
                                e.dataTransfer.effectAllowed = 'copy'
                              }}
                              className="flex flex-col gap-0.5 rounded px-2 py-1 border cursor-grab active:opacity-60 hover:bg-accent select-none"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className="text-[11px] font-medium">
                                  Seg {channel.segment_index + 1}
                                </span>
                                <span className="text-[10px] text-muted-foreground font-mono">
                                  ch {channel.channel_id}
                                </span>
                              </div>
                              {segAssignedTo && (
                                <span className="text-[10px] text-muted-foreground">
                                  Assigned: {segAssignedTo}
                                </span>
                              )}
                            </div>
                          )
                        })}
                    </div>
                  </div>
                )
              }

              // Non-gradient light: render as single draggable item
              const assignedTo = assignedMap[light.id]
              // Find single channel for this light (if available in channels data)
              const singleChannel = lightChannels && lightChannels.length === 1 ? lightChannels[0] : null

              return (
                <div
                  key={light.id}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData('lightId', light.id)
                    e.dataTransfer.setData('lightName', light.name)
                    if (singleChannel) {
                      e.dataTransfer.setData('channelId', String(singleChannel.channel_id))
                      e.dataTransfer.setData('channelName', light.name)
                    }
                    e.dataTransfer.effectAllowed = 'copy'
                  }}
                  className="flex flex-col gap-0.5 rounded px-2 py-1.5 border cursor-grab active:opacity-60 hover:bg-accent select-none"
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-xs font-semibold truncate">{light.name}</span>
                    <div className="flex items-center gap-1 shrink-0">
                      {!channelLightIds.has(light.id) && (
                        <Badge variant="outline" className="text-[10px]">
                          {light.type}
                        </Badge>
                      )}
                      {channelLightIds.has(light.id) && (
                        <Badge variant="secondary" className="text-[10px]">
                          {light.type}
                        </Badge>
                      )}
                    </div>
                  </div>
                  {assignedTo && (
                    <span className="text-[10px] text-muted-foreground">
                      Assigned: {assignedTo}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </ScrollArea>
      </div>

      {/* Assigned regions summary */}
      {regions.some((r) => r.light_id) && (
        <>
          <div className="border-t" />
          <div className="flex flex-col gap-1">
            <h2 className="text-sm font-semibold text-muted-foreground">Assignments</h2>
            {regions
              .filter((r) => r.light_id)
              .map((r) => {
                const light = lights.find((l) => l.id === r.light_id)
                return (
                  <div key={r.id} className="flex items-center justify-between text-xs">
                    <span className="text-foreground truncate">{r.name}</span>
                    <span className="text-muted-foreground truncate ml-1">
                      {light?.name ?? r.light_id}
                    </span>
                  </div>
                )
              })}
          </div>
        </>
      )}
    </div>
  )
}
