export interface CameraDevice {
  device_path: string
  stable_id: string
  display_name: string
  connected: boolean
  last_seen_at: string | null
}

export interface ZoneHealth {
  entertainment_config_id: string
  camera_name: string
  camera_stable_id: string
  connected: boolean
  device_path: string | null
}

export interface CamerasResponse {
  devices: CameraDevice[]
  identity_mode: string
  cameras_available: boolean
  zone_health: ZoneHealth[]
}

export async function getCameras(): Promise<CamerasResponse> {
  const res = await fetch('/api/cameras')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function putCameraAssignment(
  configId: string,
  cameraStableId: string,
  cameraName: string,
): Promise<void> {
  const res = await fetch(`/api/cameras/assignments/${configId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ camera_stable_id: cameraStableId, camera_name: cameraName }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}
