export interface PairResponse {
  status: string
  bridge_ip: string
  bridge_name: string
}

export interface BridgeStatus {
  paired: boolean
  bridge_ip: string
  bridge_name: string
}

export interface EntertainmentConfig {
  id: string
  name: string
  status: string
  channel_count: number
}

export interface Light {
  id: string
  name: string
  type: string
}

export async function pairBridge(bridgeIp: string): Promise<PairResponse> {
  const response = await fetch('/api/hue/pair', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bridge_ip: bridgeIp }),
  })
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
  return response.json()
}

export async function getBridgeStatus(): Promise<BridgeStatus> {
  const response = await fetch('/api/hue/status')
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
  return response.json()
}

export async function getEntertainmentConfigs(): Promise<EntertainmentConfig[]> {
  const response = await fetch('/api/hue/configs')
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
  return response.json()
}

export async function getLights(): Promise<Light[]> {
  const response = await fetch('/api/hue/lights')
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
  return response.json()
}
