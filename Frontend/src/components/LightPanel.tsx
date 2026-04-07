import { useEffect, useMemo, useState } from 'react'
import { getLights, getEntertainmentConfigs, fetchConfigChannels, type Light, type ConfigChannel, type EntertainmentConfig } from '@/api/hue'
import { fetchRegions, startStreaming, stopStreaming, clearAllAssignments } from '@/api/regions'
import { putCameraAssignment, type CamerasResponse } from '@/api/cameras'
import { useStatusStore } from '@/store/useStatusStore'
import { useRegionStore } from '@/store/useRegionStore'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface LightPanelProps {
  selectedConfigId: string
  onConfigChange: (configId: string) => void
  selectedDevice: string | undefined
  onDeviceChange: (device: string | undefined) => void
  camerasData: CamerasResponse | null
  onCamerasRefresh: () => Promise<void>
}

export function LightPanel({
  selectedConfigId,
  onConfigChange,
  selectedDevice,
  onDeviceChange,
  camerasData,
  onCamerasRefresh,
}: LightPanelProps) {
  const [lights, setLights] = useState<Light[]>([])
  const [configs, setConfigs] = useState<EntertainmentConfig[]>([])
  const [channels, setChannels] = useState<ConfigChannel[]>([])
  const [error, setError] = useState<string | null>(null)
  const [streamError, setStreamError] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const isStreaming = useStatusStore((s) => s.isStreaming)
  const regions = useRegionStore((s) => s.regions)
  const setRegions = useRegionStore((s) => s.setRegions)

  useEffect(() => {
    getLights()
      .then(setLights)
      .catch((err) => {
        console.error('Failed to load lights:', err)
        setError('Failed to load lights')
      })

    getEntertainmentConfigs()
      .then((cfgs) => {
        setConfigs(cfgs)
        if (cfgs.length > 0 && !selectedConfigId) {
          onConfigChange(cfgs[0].id)
        }
      })
      .catch((err) => {
        console.error('Failed to load configs:', err)
      })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Zone-health-driven camera initialization — D-06
  useEffect(() => {
    if (!camerasData || !selectedConfigId) return
    const zoneEntry = camerasData.zone_health.find(
      (zh) => zh.entertainment_config_id === selectedConfigId
    )
    if (zoneEntry && zoneEntry.device_path) {
      onDeviceChange(zoneEntry.device_path)
    } else {
      onDeviceChange(undefined) // D-07: no auto-selection
    }
  }, [selectedConfigId, camerasData, onDeviceChange])

  useEffect(() => {
    if (!selectedConfigId) return
    fetchConfigChannels(selectedConfigId)
      .then(setChannels)
      .catch((err) => console.error('Failed to load channels:', err))
  }, [selectedConfigId])

  async function handleCameraChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const devicePath = e.target.value
    if (!devicePath) {
      onDeviceChange(undefined)
      return
    }
    const cam = camerasData?.devices.find((d) => d.device_path === devicePath)
    if (!cam) return
    onDeviceChange(cam.device_path)
    // Auto-save assignment (D-05) — use stable_id for PUT, device_path for WS
    if (selectedConfigId) {
      try {
        await putCameraAssignment(selectedConfigId, cam.stable_id, cam.display_name)
      } catch (err) {
        console.error('Failed to save camera assignment:', err)
      }
    }
  }

  // Compute disconnected state for the selected camera — D-10
  const selectedCameraDisconnected = (() => {
    if (!selectedDevice || !camerasData) return false
    const cam = camerasData.devices.find((d) => d.device_path === selectedDevice)
    return cam ? !cam.connected : false
  })()

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

  async function handleClearAssignments() {
    try {
      await clearAllAssignments()
      const updated = await fetchRegions()
      setRegions(updated)
    } catch (err) {
      console.error('Failed to clear assignments:', err)
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
    const key = ch.light_id ?? `unknown-${ch.channel_id}`
    if (!channelsByLight[key]) {
      channelsByLight[key] = []
    }
    channelsByLight[key].push(ch)
  }

  const filteredLights = useMemo(() => {
    if (!search.trim()) return lights
    const q = search.toLowerCase()
    return lights.filter((l) => l.name.toLowerCase().includes(q))
  }, [lights, search])

  return (
    <div className="flex flex-col gap-3 p-3 md:border-l border-white/[0.06] h-full overflow-hidden bg-white/[0.02] w-full">
      {/* Zone (entertainment config) selector — D-02: top of panel */}
      <div className="flex flex-col gap-2">
        <h2 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Zone</h2>
        {configs.length > 0 ? (
          <select
            className="text-xs rounded-lg px-2 py-1.5"
            value={selectedConfigId}
            onChange={(e) => onConfigChange(e.target.value)}
            disabled={isStreaming}
          >
            {configs.map((cfg) => (
              <option key={cfg.id} value={cfg.id}>{cfg.name}</option>
            ))}
          </select>
        ) : (
          <p className="text-xs text-muted-foreground">No entertainment configs</p>
        )}
      </div>

      <div className="h-px bg-white/[0.06]" />

      {/* Camera selector — D-01: in sidebar, D-02: below zone */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <h2 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Camera</h2>
            {selectedCameraDisconnected && (
              <Badge variant="destructive" className="text-[10px] px-1.5 py-0.5">
                Disconnected
              </Badge>
            )}
          </div>
          <button
            onClick={onCamerasRefresh}
            className="p-0.5 text-muted-foreground hover:text-foreground"
            title="Refresh camera list"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        </div>
        <select
          className="text-xs rounded-lg px-2 py-1.5"
          value={selectedDevice ?? ''}
          onChange={handleCameraChange}
          onFocus={onCamerasRefresh}
          disabled={!camerasData?.cameras_available}
        >
          {!camerasData?.cameras_available ? (
            <option value="">No cameras</option>
          ) : (
            <>
              <option value="">Select camera...</option>
              {camerasData.devices.filter((d) => d.connected).map((d) => (
                <option key={d.device_path} value={d.device_path}>
                  {d.display_name} ({d.device_path})
                </option>
              ))}
            </>
          )}
        </select>
      </div>

      <div className="h-px bg-white/[0.06]" />

      {/* Streaming section */}
      <div className="flex flex-col gap-2">
        <h2 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Streaming</h2>

        <Button
          size="sm"
          onClick={handleToggleStreaming}
          className={
            isStreaming
              ? 'w-full bg-red-500/15 text-red-400 border-red-500/25 hover:bg-red-500/25'
              : 'w-full bg-hue-orange/15 text-hue-amber border-hue-orange/25 hover:bg-hue-orange/25'
          }
        >
          {isStreaming ? 'Stop' : 'Start'}
        </Button>

        {streamError && <p className="text-xs text-red-400">{streamError}</p>}
      </div>

      <div className="h-px bg-white/[0.06]" />

      {/* Lights section */}
      <div className="flex flex-col gap-2 min-h-0 flex-1">
        <div className="flex items-center justify-between">
          <h2 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Lights</h2>
          <div className="flex items-center gap-2">
            <span
              className={cn(
                'text-[11px] font-mono',
                assignedCount > 20
                  ? 'text-red-400'
                  : assignedCount === 20
                    ? 'text-hue-amber'
                    : 'text-muted-foreground',
              )}
            >
              {assignedCount}/20
            </span>
            <Button
              size="xs"
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
              className="bg-white/[0.04] text-muted-foreground border-white/[0.08] hover:bg-white/[0.08] hover:text-foreground h-5 text-[10px] px-1.5"
            >
              Sync
            </Button>
          </div>
        </div>
        <p className="text-[11px] text-muted-foreground/60">Drag a channel onto a region to assign it.</p>

        <input
          type="text"
          placeholder="Search lights..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-7 text-xs w-full !rounded-lg !px-2.5"
        />

        {error && <p className="text-xs text-red-400">{error}</p>}

        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="flex flex-col gap-1">
            {lights.length === 0 && !error && (
              <p className="text-xs text-muted-foreground">Loading lights...</p>
            )}
            {filteredLights.map((light) => {
              const lightChannels = channelsByLight[light.id]
              const hasChannels = lightChannels && lightChannels.length > 0

              return (
                <div key={light.id} className="flex flex-col gap-0.5">
                  {/* Light header */}
                  <div className="flex items-center justify-between gap-1 rounded-lg px-2.5 py-1.5 bg-white/[0.03] border border-white/[0.06] select-none">
                    <span className="text-xs font-semibold truncate text-foreground">{light.name}</span>
                    <div className="flex items-center gap-1 shrink-0">
                      {hasChannels ? (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-hue-orange/10 text-hue-amber/80">
                          {lightChannels.length} ch
                        </span>
                      ) : (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/[0.04] text-muted-foreground/60">
                          not in config
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Per-channel draggable rows */}
                  {hasChannels && (
                    <div className="ml-3 border-l-2 border-hue-orange/20 flex flex-col gap-0.5 pl-1">
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
                                  `${light.name} [${channel.segment_index + 1}/${channel.segment_count}]`,
                                )
                                e.dataTransfer.setData('lightId', channel.light_id)
                                e.dataTransfer.setData('configId', selectedConfigId)
                                e.dataTransfer.effectAllowed = 'copy'
                              }}
                              className="flex flex-col gap-0.5 rounded-lg px-2.5 py-1.5 border border-white/[0.06] cursor-grab active:opacity-60 hover:bg-white/[0.04] select-none transition-colors"
                            >
                              <div className="flex items-center justify-between gap-1">
                                <span className="text-[11px] font-medium text-foreground/80">
                                  Seg {channel.segment_index + 1}/{channel.segment_count}
                                </span>
                                <span className="text-[10px] text-muted-foreground font-mono">
                                  ch {channel.channel_id}
                                </span>
                              </div>
                              {segAssignedTo && (
                                <span className="text-[10px] text-hue-amber/60">
                                  Assigned: {segAssignedTo}
                                </span>
                              )}
                            </div>
                          )
                        })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>

      {/* Assigned regions summary + clear button */}
      {regions.some((r) => r.light_id) && (
        <>
          <div className="h-px bg-white/[0.06]" />
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <h2 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Assignments</h2>
              <Button
                size="xs"
                onClick={handleClearAssignments}
                className="bg-white/[0.04] text-muted-foreground border-white/[0.08] hover:bg-red-500/10 hover:text-red-400 h-5 text-[10px] px-1.5"
              >
                Clear all
              </Button>
            </div>
            {regions
              .filter((r) => r.light_id)
              .map((r) => {
                const light = lights.find((l) => l.id === r.light_id)
                return (
                  <div key={r.id} className="flex items-center justify-between text-xs">
                    <span className="text-foreground/80 truncate">{r.name}</span>
                    <span className="text-hue-amber/50 truncate ml-1 text-[11px]">
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
