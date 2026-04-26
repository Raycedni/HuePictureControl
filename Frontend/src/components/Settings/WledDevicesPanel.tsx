// Phase 17 D-17 / D-18: WLED device CRUD panel.
//
// Owns:
// - GET /api/wled/devices on mount + after every mutation (refresh()).
// - POST /api/wled/devices for manual IP entry and "Add" alongside scan
//   candidates. Branches on WledApiError.status so the user sees a
//   meaningful message for the documented Plan 07 error codes
//   (409 conflict, 422 validation, 502 unreachable).
// - DELETE /api/wled/devices/{id} (Remove button).
// - PUT /api/wled/devices/{id}/enabled (per-row enabled toggle, D-12).
// - POST /api/wled/scan (zeroconf candidates list, D-19).
//
// Reads useStatusStore.wledDevices for the live in_cooldown badge (D-16),
// so the panel reflects the per-device 30s cooldown state pushed via the
// /ws/status broadcast without an extra polling loop.

import { useCallback, useEffect, useState } from 'react'
import {
  addWledDevice,
  deleteWledDevice,
  getWledDevices,
  scanWledDevices,
  setWledDeviceEnabled,
  WledApiError,
  type WledDevice,
  type WledScanCandidate,
} from '@/api/wled'
import { useStatusStore } from '@/store/useStatusStore'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

export function WledDevicesPanel() {
  const [devices, setDevices] = useState<WledDevice[]>([])
  const [ip, setIp] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [candidates, setCandidates] = useState<WledScanCandidate[]>([])
  const wledDevices = useStatusStore((s) => s.wledDevices)

  const refresh = useCallback(async () => {
    try {
      const r = await getWledDevices()
      setDevices(r.devices)
    } catch (err) {
      setError((err as Error).message)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function handleAdd(explicitIp?: string) {
    const target = explicitIp ?? ip
    if (!target) return
    setError(null)
    setLoading(true)
    try {
      await addWledDevice(target)
      setIp('')
      await refresh()
    } catch (err) {
      if (err instanceof WledApiError) {
        if (err.status === 409) setError(`Already registered: ${target}`)
        else if (err.status === 422)
          setError('Invalid IP or device returned unexpected data')
        else if (err.status === 502) setError(`Unreachable: ${target}`)
        else setError(`Add failed (HTTP ${err.status})`)
      } else {
        setError((err as Error).message)
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleScan() {
    setError(null)
    setScanning(true)
    setCandidates([])
    try {
      const r = await scanWledDevices()
      setCandidates(r.candidates)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setScanning(false)
    }
  }

  async function handleRemove(id: string) {
    setError(null)
    try {
      await deleteWledDevice(id)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function handleToggleEnabled(id: string, enabled: boolean) {
    setError(null)
    try {
      await setWledDeviceEnabled(id, enabled)
      await refresh()
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="flex flex-col gap-3 text-left" data-testid="wled-devices-panel">
      <h3 className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
        WLED Devices
      </h3>

      <div className="flex gap-2">
        <input
          type="text"
          value={ip}
          onChange={(e) => setIp(e.target.value)}
          placeholder="192.168.1.50"
          aria-label="WLED device IP"
          data-testid="wled-ip-input"
          className="flex-1 bg-black/30 border border-white/[0.08] rounded px-2 py-1 text-sm"
        />
        <Button
          size="sm"
          onClick={() => void handleAdd()}
          disabled={loading || !ip}
          data-testid="wled-add-button"
        >
          Add
        </Button>
        <Button
          size="sm"
          onClick={() => void handleScan()}
          disabled={scanning}
          data-testid="wled-scan-button"
        >
          {scanning ? 'Scanning…' : 'Scan'}
        </Button>
      </div>

      {error && (
        <p role="alert" className="text-xs text-red-400">
          {error}
        </p>
      )}

      {candidates.length > 0 && (
        <div className="flex flex-col gap-1.5" data-testid="wled-candidates">
          <h4 className="text-[10px] font-semibold text-muted-foreground uppercase">
            Discovered
          </h4>
          {candidates.map((c) => (
            <div
              key={c.ip}
              className="flex items-center justify-between text-xs bg-black/20 rounded px-2 py-1"
            >
              <div>
                <span className="font-mono">{c.ip}</span> — {c.name}
              </div>
              <Button size="sm" onClick={() => void handleAdd(c.ip)}>
                Add
              </Button>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-col gap-2" data-testid="wled-device-list">
        {devices.length === 0 && (
          <p className="text-xs text-muted-foreground">No WLED devices registered.</p>
        )}
        {devices.map((d) => {
          const health = wledDevices[d.id]
          const inCooldown = health?.in_cooldown ?? false
          return (
            <div
              key={d.id}
              className="flex items-center justify-between gap-2 text-xs bg-black/20 rounded px-2 py-1.5"
              data-testid={`wled-row-${d.id}`}
            >
              <div className="flex-1 flex flex-col">
                <div className="flex items-center gap-1.5">
                  <span className="font-medium">{d.name}</span>
                  {d.connected ? (
                    <Badge variant="default" className="text-[9px] px-1 py-0">
                      Connected
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="text-[9px] px-1 py-0">
                      Offline
                    </Badge>
                  )}
                  {inCooldown && (
                    <Badge variant="destructive" className="text-[9px] px-1 py-0">
                      Cooldown
                    </Badge>
                  )}
                </div>
                <span className="font-mono text-muted-foreground">
                  {d.ip} · {d.led_count} LEDs
                </span>
              </div>
              <label className="flex items-center gap-1 text-[10px]">
                <input
                  type="checkbox"
                  checked={d.enabled}
                  onChange={(e) => void handleToggleEnabled(d.id, e.target.checked)}
                  data-testid={`wled-toggle-${d.id}`}
                  aria-label={`Enable ${d.name}`}
                />
                <span>Enabled</span>
              </label>
              <Button
                size="sm"
                variant="destructive"
                onClick={() => void handleRemove(d.id)}
                data-testid={`wled-remove-${d.id}`}
              >
                Remove
              </Button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
