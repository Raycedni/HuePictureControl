import { describe, it, expect, vi, beforeEach } from 'vitest'

// Tests will import from cameras.ts once it exists (Plan 01)
// For now, define the expected response shapes inline

describe('cameras API', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  describe('getCameras', () => {
    it('fetches GET /api/cameras and returns typed CamerasResponse', async () => {
      const mockResponse = {
        devices: [
          {
            device_path: '/dev/video0',
            stable_id: 'usb-0403:6010-00000000',
            display_name: 'USB Capture Card',
            connected: true,
            last_seen_at: '2026-04-07T12:00:00',
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
      ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve(mockResponse),
      })

      const { getCameras } = await import('./cameras')
      const result = await getCameras()
      expect(fetch).toHaveBeenCalledWith('/api/cameras')
      expect(result.devices).toHaveLength(1)
      expect(result.devices[0].stable_id).toBe('usb-0403:6010-00000000')
      expect(result.identity_mode).toBe('stable')
      expect(result.cameras_available).toBe(true)
      expect(result.zone_health).toHaveLength(1)
    })

    it('throws on non-ok response', async () => {
      ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: false,
        status: 500,
      })

      const { getCameras } = await import('./cameras')
      await expect(getCameras()).rejects.toThrow('HTTP 500')
    })
  })

  describe('putCameraAssignment', () => {
    it('sends PUT with camera_stable_id and camera_name body', async () => {
      ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({ ok: true })

      const { putCameraAssignment } = await import('./cameras')
      await putCameraAssignment('config-1', 'usb-0403:6010-00000000', 'USB Capture Card')

      expect(fetch).toHaveBeenCalledWith(
        '/api/cameras/assignments/config-1',
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
      ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
        ok: false,
        status: 404,
      })

      const { putCameraAssignment } = await import('./cameras')
      await expect(
        putCameraAssignment('config-1', 'usb-id', 'cam'),
      ).rejects.toThrow('HTTP 404')
    })
  })
})
