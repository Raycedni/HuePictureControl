import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  addWledDevice,
  deleteWledAssignment,
  deleteWledDevice,
  getWledDevices,
  listSegments,
  listWledAssignments,
  patchRegionOrientation,
  refreshSegments,
  scanWledDevices,
  setWledDeviceEnabled,
  upsertWledAssignment,
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

describe('wled api — device CRUD (unchanged from Phase 17)', () => {
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

describe('wled api — segment refresh / list (D-17, D-18)', () => {
  it('refreshSegments POSTs and returns segments + dropped_assignments', async () => {
    const fetchMock = mockFetch(200, {
      segments: [
        { seg_index: 0, start_led: 0, stop_led: 99, name: 'Sofa', refreshed_at: '2026-05-15T19:00:00Z' },
      ],
      dropped_assignments: 2,
    })
    vi.stubGlobal('fetch', fetchMock)
    const result = await refreshSegments('dev-1')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wled/devices/dev-1/segments/refresh',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(result.segments).toHaveLength(1)
    expect(result.segments[0].name).toBe('Sofa')
    expect(result.dropped_assignments).toBe(2)
  })

  it('refreshSegments percent-encodes device id', async () => {
    const fetchMock = mockFetch(200, { segments: [], dropped_assignments: 0 })
    vi.stubGlobal('fetch', fetchMock)
    await refreshSegments('abc/123')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wled/devices/abc%2F123/segments/refresh',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('refreshSegments throws WledApiError on 502', async () => {
    vi.stubGlobal('fetch', mockFetch(502))
    await expect(refreshSegments('dev-1')).rejects.toMatchObject({ status: 502 })
  })

  it('listSegments GETs and returns segments (no device contact)', async () => {
    const fetchMock = mockFetch(200, {
      segments: [{ seg_index: 0, start_led: 0, stop_led: 99, name: null }],
    })
    vi.stubGlobal('fetch', fetchMock)
    const result = await listSegments('dev-1')
    expect(fetchMock).toHaveBeenCalledWith('/api/wled/devices/dev-1/segments')
    expect(result.segments).toHaveLength(1)
    expect(result.segments[0].name).toBeNull()
  })

  it('listSegments throws WledApiError on 404', async () => {
    vi.stubGlobal('fetch', mockFetch(404))
    await expect(listSegments('missing')).rejects.toMatchObject({ status: 404 })
  })
})

describe('wled api — assignment CRUD (D-13 composite key)', () => {
  it('upsertWledAssignment PUTs with composite (region_id, wled_device_id, seg_index, entertainment_config_id) body', async () => {
    const fetchMock = mockFetch(200, {
      region_id: 'r1',
      wled_device_id: 'd1',
      seg_index: 0,
      entertainment_config_id: 'c1',
      orientation: 'auto',
    })
    vi.stubGlobal('fetch', fetchMock)
    const out = await upsertWledAssignment({
      region_id: 'r1',
      wled_device_id: 'd1',
      seg_index: 0,
      entertainment_config_id: 'c1',
    })
    expect(out.wled_device_id).toBe('d1')
    expect(out.seg_index).toBe(0)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wled/assignments',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({
          region_id: 'r1',
          wled_device_id: 'd1',
          seg_index: 0,
          entertainment_config_id: 'c1',
        }),
      }),
    )
  })

  it('upsertWledAssignment passes orientation when provided', async () => {
    const fetchMock = mockFetch(200, {
      region_id: 'r1',
      wled_device_id: 'd1',
      seg_index: 2,
      entertainment_config_id: 'c1',
      orientation: 'horizontal-LTR',
    })
    vi.stubGlobal('fetch', fetchMock)
    await upsertWledAssignment({
      region_id: 'r1',
      wled_device_id: 'd1',
      seg_index: 2,
      entertainment_config_id: 'c1',
      orientation: 'horizontal-LTR',
    })
    const callBody = (fetchMock.mock.calls[0][1] as RequestInit).body as string
    const parsed = JSON.parse(callBody)
    expect(parsed.orientation).toBe('horizontal-LTR')
    expect(parsed.seg_index).toBe(2)
  })

  it('deleteWledAssignment DELETEs with composite body', async () => {
    const fetchMock = mockFetch(204)
    vi.stubGlobal('fetch', fetchMock)
    await deleteWledAssignment({
      region_id: 'r1',
      wled_device_id: 'd1',
      seg_index: 0,
      entertainment_config_id: 'c1',
    })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wled/assignments',
      expect.objectContaining({
        method: 'DELETE',
        body: JSON.stringify({
          region_id: 'r1',
          wled_device_id: 'd1',
          seg_index: 0,
          entertainment_config_id: 'c1',
        }),
      }),
    )
  })

  it('deleteWledAssignment accepts 204 No-Content as success', async () => {
    const fetchMock = mockFetch(204)
    vi.stubGlobal('fetch', fetchMock)
    await expect(
      deleteWledAssignment({
        region_id: 'r1',
        wled_device_id: 'd1',
        seg_index: 0,
        entertainment_config_id: 'c1',
      }),
    ).resolves.toBeUndefined()
  })

  it('listWledAssignments GETs with config filter when provided', async () => {
    const fetchMock = mockFetch(200, { assignments: [] })
    vi.stubGlobal('fetch', fetchMock)
    await listWledAssignments('cfg-1')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wled/assignments?config=cfg-1',
    )
  })
})

describe('wled api — region orientation PATCH (D-22, query-param config)', () => {
  it('patchRegionOrientation PATCHes with ?config= query param and {orientation} body', async () => {
    const fetchMock = mockFetch(200, { updated: 3 })
    vi.stubGlobal('fetch', fetchMock)
    const out = await patchRegionOrientation('reg-1', 'cfg-1', 'vertical-TTB')
    expect(out.updated).toBe(3)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/wled/regions/reg-1/orientation?config=cfg-1',
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ orientation: 'vertical-TTB' }),
      }),
    )
  })
})
