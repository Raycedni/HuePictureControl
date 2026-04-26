import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  addWledDevice,
  deleteWledDevice,
  getWledDevices,
  scanWledDevices,
  setWledDeviceEnabled,
  WledApiError,
} from './wled'

function mockFetch(status: number, body: unknown = {}) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as Response)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('wled api', () => {
  it('getWledDevices returns devices list', async () => {
    vi.stubGlobal('fetch', mockFetch(200, { devices: [] }))
    const r = await getWledDevices()
    expect(r).toEqual({ devices: [] })
  })

  it('addWledDevice posts ip body', async () => {
    const fetchMock = mockFetch(201, {
      id: 'x',
      ip: '10.0.0.5',
      name: 'W',
      led_count: 100,
      enabled: true,
      created_at: 'now',
      connected: false,
      last_error: null,
      last_success_at: null,
    })
    vi.stubGlobal('fetch', fetchMock)
    const dev = await addWledDevice('10.0.0.5')
    expect(dev.ip).toBe('10.0.0.5')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wled/devices',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ ip: '10.0.0.5' }),
      }),
    )
  })

  it('addWledDevice throws WledApiError with status 502 on unreachable', async () => {
    vi.stubGlobal('fetch', mockFetch(502))
    try {
      await addWledDevice('10.0.0.5')
      expect.fail('should have thrown')
    } catch (e) {
      expect(e).toBeInstanceOf(WledApiError)
      expect((e as WledApiError).status).toBe(502)
    }
  })

  it('deleteWledDevice DELETE with encoded id', async () => {
    const fetchMock = mockFetch(204)
    vi.stubGlobal('fetch', fetchMock)
    await deleteWledDevice('abc/123')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wled/devices/abc%2F123',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('setWledDeviceEnabled sends enabled bool', async () => {
    const fetchMock = mockFetch(200, { id: 'x', enabled: false })
    vi.stubGlobal('fetch', fetchMock)
    await setWledDeviceEnabled('x', false)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wled/devices/x/enabled',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ enabled: false }),
      }),
    )
  })

  it('scanWledDevices returns candidates', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(200, { candidates: [{ ip: '1.2.3.4', name: 'WLED' }] }),
    )
    const r = await scanWledDevices()
    expect(r.candidates).toHaveLength(1)
  })
})
