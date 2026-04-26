// Phase 17 Plan 08: Typed REST client for /api/wled/* endpoints (D-17, D-18).
//
// Mirrors the conventions used by Frontend/src/api/cameras.ts and
// Frontend/src/api/hue.ts: typed exports, JSON bodies for mutations, and a
// dedicated error class so the UI can branch on HTTP status (409 conflict,
// 422 validation, 502 unreachable, etc.).

export interface WledDevice {
  id: string
  ip: string
  name: string
  led_count: number
  enabled: boolean
  created_at: string
  connected: boolean
  last_error: string | null
  last_success_at: string | null
}

export interface WledDevicesResponse {
  devices: WledDevice[]
}

export interface WledScanCandidate {
  ip: string
  name: string
}

export interface WledScanResponse {
  candidates: WledScanCandidate[]
}

/** Typed API error exposing HTTP status for UI branching. */
export class WledApiError extends Error {
  public status: number
  constructor(status: number, message?: string) {
    super(message ?? `HTTP ${status}`)
    this.name = 'WledApiError'
    this.status = status
  }
}

export async function getWledDevices(): Promise<WledDevicesResponse> {
  const res = await fetch('/api/wled/devices')
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

export async function addWledDevice(ip: string): Promise<WledDevice> {
  const res = await fetch('/api/wled/devices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ip }),
  })
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

export async function deleteWledDevice(id: string): Promise<void> {
  const res = await fetch(`/api/wled/devices/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new WledApiError(res.status)
}

export async function setWledDeviceEnabled(id: string, enabled: boolean): Promise<void> {
  const res = await fetch(`/api/wled/devices/${encodeURIComponent(id)}/enabled`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
  if (!res.ok) throw new WledApiError(res.status)
}

export async function scanWledDevices(): Promise<WledScanResponse> {
  const res = await fetch('/api/wled/scan', { method: 'POST' })
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}
