// quick-task 260516-kra: typed client for /api/settings/*.
// Mirrors the shape of api/wled.ts (typed exports + a dedicated error class
// so the UI can branch on HTTP status if needed).

export class SettingsApiError extends Error {
  public status: number
  constructor(status: number, message?: string) {
    super(message ?? `HTTP ${status}`)
    this.name = 'SettingsApiError'
    this.status = status
  }
}

export interface BrightnessCutoffResponse {
  value: number
}

export async function getBrightnessCutoff(): Promise<BrightnessCutoffResponse> {
  const res = await fetch('/api/settings/brightness_cutoff_threshold')
  if (!res.ok) throw new SettingsApiError(res.status)
  return res.json()
}

export async function putBrightnessCutoff(
  value: number,
): Promise<BrightnessCutoffResponse> {
  const res = await fetch('/api/settings/brightness_cutoff_threshold', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
  if (!res.ok) throw new SettingsApiError(res.status)
  return res.json()
}

// quick-task 260704-iss: generic key-parameterized client for the new
// color_vibrancy / saturation_boost settings (and any future single-float
// settings key). getBrightnessCutoff/putBrightnessCutoff above stay
// untouched for backward-compat.

export interface SettingResponse {
  value: number
}

export async function getSetting(key: string): Promise<SettingResponse> {
  const res = await fetch(`/api/settings/${key}`)
  if (!res.ok) throw new SettingsApiError(res.status)
  return res.json()
}

export async function putSetting(
  key: string,
  value: number,
): Promise<SettingResponse> {
  const res = await fetch(`/api/settings/${key}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
  if (!res.ok) throw new SettingsApiError(res.status)
  return res.json()
}
