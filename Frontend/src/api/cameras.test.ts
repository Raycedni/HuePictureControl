import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { getCameras, putCameraAssignment, putLastZone } from './cameras'
import type { CamerasResponse } from './cameras'

const mockResponse: CamerasResponse = {
  devices: [
    {
      device_path: '/dev/video0',
      stable_id: 'usb-0403:6010-00000000',
      display_name: 'USB Capture Card',
      connected: true,
      last_seen_at: '2026-04-07T12:00:00',
      last_entertainment_config_id: null,
    },
  ],
  identity_mode: 'stable',
  cameras_available: true,
  zone_health: [
    {
      entertainment_config_id: 'abc-123',
      camera_name: 'USB Capture Card',
      camera_stable_id: 'usb-0403:6010-00000000',
      connected: true,
      device_path: '/dev/video0',
    },
  ],
}

describe('cameras API', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('getCameras', () => {
    it('fetches from /api/cameras and returns typed response', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response)

      const result = await getCameras()
      expect(fetch).toHaveBeenCalledWith('/api/cameras')
      expect(result.devices).toHaveLength(1)
      expect(result.devices[0].stable_id).toBe('usb-0403:6010-00000000')
      expect(result.cameras_available).toBe(true)
      expect(result.zone_health).toHaveLength(1)
    })

    it('throws on non-ok response', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: false,
        status: 503,
      } as Response)

      await expect(getCameras()).rejects.toThrow('HTTP 503')
    })
  })

  describe('putCameraAssignment', () => {
    it('sends PUT with camera_stable_id and camera_name body', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
      } as Response)

      await putCameraAssignment('config-abc', 'usb-0403:6010-00000000', 'USB Capture Card')

      expect(fetch).toHaveBeenCalledWith(
        '/api/cameras/assignments/config-abc',
        expect.objectContaining({
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            camera_stable_id: 'usb-0403:6010-00000000',
            camera_name: 'USB Capture Card',
          }),
        }),
      )
    })

    it('throws on non-ok response', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: false,
        status: 404,
      } as Response)

      await expect(
        putCameraAssignment('config-abc', 'usb-0403:6010-00000000', 'USB Capture Card'),
      ).rejects.toThrow('HTTP 404')
    })
  })

  describe('getCameras last_entertainment_config_id field', () => {
    it('exposes last_entertainment_config_id when server returns a config id', async () => {
      const responseWithPersisted: CamerasResponse = {
        ...mockResponse,
        devices: [
          {
            ...mockResponse.devices[0],
            last_entertainment_config_id: 'cfg-abc',
          },
        ],
      }
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        json: async () => responseWithPersisted,
      } as Response)

      const result = await getCameras()
      expect(result.devices[0].last_entertainment_config_id).toBe('cfg-abc')
    })

    it('exposes last_entertainment_config_id as null when never set', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: true,
        json: async () => mockResponse,
      } as Response)

      const result = await getCameras()
      expect(result.devices[0].last_entertainment_config_id).toBeNull()
    })
  })

  describe('putLastZone', () => {
    it('sends PUT with entertainment_config_id body', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({ ok: true } as Response)

      await putLastZone('usb-FOO', 'cfg-x')

      expect(fetch).toHaveBeenCalledWith(
        '/api/cameras/last-zone/usb-FOO',
        expect.objectContaining({
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entertainment_config_id: 'cfg-x' }),
        }),
      )
    })

    it('throws on non-ok response', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({
        ok: false,
        status: 404,
      } as Response)

      await expect(putLastZone('usb-FOO', 'cfg-x')).rejects.toThrow('HTTP 404')
    })

    it('url-encodes the stable_id to prevent path traversal', async () => {
      vi.mocked(fetch).mockResolvedValueOnce({ ok: true } as Response)

      await putLastZone('usb/with space', 'cfg-x')

      const callUrl = vi.mocked(fetch).mock.calls[0][0] as string
      expect(callUrl).toBe('/api/cameras/last-zone/usb%2Fwith%20space')
    })
  })
})
