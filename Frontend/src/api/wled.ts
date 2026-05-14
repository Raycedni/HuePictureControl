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

// ---------------------------------------------------------------------------
// Phase 19 — Channel CRUD + Assignment + Region orientation
// ---------------------------------------------------------------------------

/** Per-region orientation enum for the sub-sample axis (D-17). */
export type WledOrientation =
  | 'auto'
  | 'horizontal-LTR'
  | 'horizontal-RTL'
  | 'vertical-TTB'
  | 'vertical-BTT'

export interface WledChannel {
  id: string
  device_id: string
  name: string
  start_led: number
  end_led: number
}

export interface WledChannelsResponse {
  channels: WledChannel[]
}

export interface WledAssignment {
  region_id: string
  wled_channel_id: string
  entertainment_config_id: string
  orientation: WledOrientation
}

/** List all channels for a WLED device, ordered by start_led ASC. */
export async function listWledChannels(
  deviceId: string,
): Promise<WledChannelsResponse> {
  const res = await fetch(
    `/api/wled/devices/${encodeURIComponent(deviceId)}/channels`,
  )
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

/** Create a channel — backend applies overlap auto-split (D-02). */
export async function createWledChannel(
  deviceId: string,
  body: { start_led: number; end_led: number; name?: string },
): Promise<WledChannel> {
  const res = await fetch(
    `/api/wled/devices/${encodeURIComponent(deviceId)}/channels`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

/** Rename and/or resize a single channel (partial PUT — all fields optional). */
export async function updateWledChannel(
  deviceId: string,
  channelId: string,
  body: { name?: string; start_led?: number; end_led?: number },
): Promise<WledChannel> {
  const res = await fetch(
    `/api/wled/devices/${encodeURIComponent(deviceId)}/channels/${encodeURIComponent(channelId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

/**
 * Atomically move the shared boundary between two adjacent channels.
 * Fires once on drag end — NEVER per onDragMove (RESEARCH.md §Boundary
 * Drag-Handle Resize commit cadence).
 */
export async function resizeWledChannelBoundary(
  deviceId: string,
  body: {
    left_channel_id: string
    right_channel_id: string
    boundary: number
  },
): Promise<{ ok: true }> {
  const res = await fetch(
    `/api/wled/devices/${encodeURIComponent(deviceId)}/channels/boundary`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

/** Delete a channel — cascades to wled_light_assignments (D-04, Success #5). */
export async function deleteWledChannel(
  deviceId: string,
  channelId: string,
): Promise<void> {
  const res = await fetch(
    `/api/wled/devices/${encodeURIComponent(deviceId)}/channels/${encodeURIComponent(channelId)}`,
    { method: 'DELETE' },
  )
  if (!res.ok) throw new WledApiError(res.status)
}

/**
 * Upsert a region→channel assignment for a specific config (D-21).
 * New assignments inherit the region's current orientation; existing rows
 * keep their orientation unchanged unless `orientation` is in the body.
 */
export async function upsertWledAssignment(body: {
  region_id: string
  wled_channel_id: string
  entertainment_config_id: string
  orientation?: WledOrientation
}): Promise<WledAssignment> {
  const res = await fetch('/api/wled/assignments', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

/** Remove a region→channel assignment for a specific config (D-21). */
export async function deleteWledAssignment(body: {
  region_id: string
  wled_channel_id: string
  entertainment_config_id: string
}): Promise<void> {
  const res = await fetch('/api/wled/assignments', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new WledApiError(res.status)
}

/**
 * Region-scoped orientation update (CONTEXT.md per-region narrowing 2026-05-14).
 *
 * Writes the same orientation value to EVERY wled_light_assignments row that
 * matches (region_id, entertainment_config_id) — one statement on the
 * backend. Returns the number of rows updated for optimistic-UI verification.
 */
export async function patchRegionOrientation(
  regionId: string,
  configId: string,
  orientation: WledOrientation,
): Promise<{ updated: number }> {
  const url =
    `/api/wled/regions/${encodeURIComponent(regionId)}/orientation` +
    `?config=${encodeURIComponent(configId)}`
  const res = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ orientation }),
  })
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

/** List all WLED assignments scoped to a config — used to hydrate useRegionStore.wledAssignments. */
export async function listWledAssignments(
  configId: string,
): Promise<{ assignments: WledAssignment[] }> {
  // The router exposes this via `GET /api/wled/assignments?config={cid}`.
  const url = `/api/wled/assignments?config=${encodeURIComponent(configId)}`
  const res = await fetch(url)
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}
