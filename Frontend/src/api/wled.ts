// Phase 19.1 Plan 06: Typed REST client for /api/wled/* endpoints.
//
// Mirrors the conventions used by Frontend/src/api/cameras.ts and
// Frontend/src/api/hue.ts: typed exports, JSON bodies for mutations, and a
// dedicated error class so the UI can branch on HTTP status (409 conflict,
// 422 validation, 502 unreachable, etc.).
//
// Phase 19.1 changes (vs Phase 19):
//   - All channel-CRUD client fns removed (D-10) — channels are no longer a
//     paint-managed concept; segments are mirrored from the WLED device's own
//     /json/state seg[] array.
//   - New: refreshSegments(device_id) → POST /devices/{id}/segments/refresh
//     (D-17). Returns the post-refresh seg cache + the count of assignments
//     dropped by the reconcile cascade.
//   - New: listSegments(device_id) → GET /devices/{id}/segments (D-18). Pure
//     cache read, never contacts the device.
//   - upsertWledAssignment / deleteWledAssignment now take the D-13 composite
//     shape (region_id, wled_device_id, seg_index, entertainment_config_id).
//   - patchRegionOrientation keeps the Phase 19 query-param contract verbatim.

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
// Phase 19.1 — Segment refresh / list + D-13 assignments
// ---------------------------------------------------------------------------

/** Per-region orientation enum for the sub-sample axis (preserved from Phase 19 D-16/D-22). */
export type WledOrientation =
  | 'auto'
  | 'horizontal-LTR'
  | 'horizontal-RTL'
  | 'vertical-TTB'
  | 'vertical-BTT'

/** Cached WLED segment row mirrored from the device's /json/state seg[] (D-12). */
export interface WledSegment {
  seg_index: number
  start_led: number
  stop_led: number
  name: string | null
  refreshed_at?: string | null
}

export interface WledSegmentsResponse {
  segments: WledSegment[]
}

export interface WledRefreshResponse {
  segments: WledSegment[]
  dropped_assignments: number
}

/**
 * Trigger a /json/state fetch on the device, write the result into
 * wled_seg_cache, and cascade-delete any wled_light_assignments rows whose
 * seg_index disappeared (D-14, D-15). Returns the freshly-written seg list
 * plus the count of assignments dropped by the cascade (D-17).
 */
export async function refreshSegments(deviceId: string): Promise<WledRefreshResponse> {
  const res = await fetch(
    `/api/wled/devices/${encodeURIComponent(deviceId)}/segments/refresh`,
    { method: 'POST' },
  )
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

/**
 * Read the cached seg[] for a device from wled_seg_cache. NEVER contacts the
 * device — used to render the strip after a page reload without forcing a
 * refresh (D-18, D-04 offline-tolerant rendering).
 */
export async function listSegments(deviceId: string): Promise<WledSegmentsResponse> {
  const res = await fetch(
    `/api/wled/devices/${encodeURIComponent(deviceId)}/segments`,
  )
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

/** Region → segment assignment (D-13 composite key). */
export interface WledAssignment {
  region_id: string
  wled_device_id: string
  seg_index: number
  entertainment_config_id: string
  orientation: WledOrientation
}

export interface WledAssignmentsResponse {
  assignments: WledAssignment[]
}

/**
 * Upsert a region→segment assignment for a specific config (D-13, D-21).
 * New assignments inherit the region's current orientation; existing rows
 * keep their orientation unchanged unless `orientation` is in the body.
 */
export async function upsertWledAssignment(body: {
  region_id: string
  wled_device_id: string
  seg_index: number
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

/** Remove a region→segment assignment for a specific config (D-13, D-21). */
export async function deleteWledAssignment(body: {
  region_id: string
  wled_device_id: string
  seg_index: number
  entertainment_config_id: string
}): Promise<void> {
  const res = await fetch('/api/wled/assignments', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new WledApiError(res.status)
}

/** List WLED assignments. With no arg returns all; with a config id, filters server-side. */
export async function listWledAssignments(
  entertainment_config_id?: string,
): Promise<WledAssignmentsResponse> {
  const url = entertainment_config_id
    ? `/api/wled/assignments?config=${encodeURIComponent(entertainment_config_id)}`
    : '/api/wled/assignments'
  const res = await fetch(url)
  if (!res.ok) throw new WledApiError(res.status)
  return res.json()
}

/**
 * Region-scoped orientation update (CONTEXT.md per-region narrowing 2026-05-14).
 *
 * Writes the same orientation value to EVERY wled_light_assignments row that
 * matches (region_id, entertainment_config_id) — one statement on the
 * backend. Returns the number of rows updated for optimistic-UI verification.
 *
 * Phase 19.1 D-22 preserves the Phase 19 query-param contract:
 *   PATCH /api/wled/regions/{region_id}/orientation?config={cfg}
 *   body: {orientation: WledOrientation}
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
