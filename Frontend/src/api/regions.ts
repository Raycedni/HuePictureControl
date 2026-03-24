export interface Region {
  id: string
  name: string
  polygon: number[][]
  order_index: number
}

export interface Config {
  id: string
  name: string
  status: string
  channel_count: number
}

export interface AutoMapResult {
  regions_created: number
  warning?: string
}

export async function fetchRegions(): Promise<Region[]> {
  const response = await fetch('/api/regions')
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
  return response.json()
}

export async function triggerAutoMap(configId: string): Promise<AutoMapResult> {
  const response = await fetch('/api/regions/auto-map', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config_id: configId }),
  })
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
  return response.json()
}

export async function fetchConfigs(): Promise<Config[]> {
  const response = await fetch('/api/hue/configs')
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
  return response.json()
}

export async function startStreaming(configId: string): Promise<void> {
  const response = await fetch('/api/capture/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config_id: configId }),
  })
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
}

export async function stopStreaming(): Promise<void> {
  const response = await fetch('/api/capture/stop', {
    method: 'POST',
  })
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`) as Error & { status: number }
    error.status = response.status
    throw error
  }
}
