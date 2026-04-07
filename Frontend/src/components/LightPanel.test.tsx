import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom'
import { LightPanel } from './LightPanel'

// Mock the API and hooks that LightPanel will import
vi.mock('@/api/hue', () => ({
  getEntertainmentConfigs: vi.fn().mockResolvedValue([
    { id: 'config-1', name: 'TV-Bereich', status: 'inactive', channel_count: 6 },
    { id: 'config-2', name: 'Wohnzimmer', status: 'inactive', channel_count: 4 },
  ]),
  getLights: vi.fn().mockResolvedValue([]),
  fetchConfigChannels: vi.fn().mockResolvedValue([]),
}))

vi.mock('@/api/cameras', () => ({
  putCameraAssignment: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/api/regions', () => ({
  getRegions: vi.fn().mockResolvedValue([]),
  fetchRegions: vi.fn().mockResolvedValue([]),
  startStreaming: vi.fn().mockResolvedValue(undefined),
  stopStreaming: vi.fn().mockResolvedValue(undefined),
  clearAllAssignments: vi.fn().mockResolvedValue(undefined),
}))

const mockCamerasData = {
  devices: [
    {
      device_path: '/dev/video0',
      stable_id: 'usb-0403:6010-00000000',
      display_name: 'USB Capture Card',
      connected: true,
      last_seen_at: '2026-04-07T12:00:00',
    },
    {
      device_path: '/dev/video2',
      stable_id: 'usb-1234:5678-00000001',
      display_name: 'Elgato HD60',
      connected: true,
      last_seen_at: null,
    },
  ],
  identity_mode: 'stable',
  cameras_available: true,
  zone_health: [
    {
      entertainment_config_id: 'config-1',
      camera_name: 'USB Capture Card',
      camera_stable_id: 'usb-0403:6010-00000000',
      connected: true,
      device_path: '/dev/video0',
    },
  ],
}

describe('LightPanel', () => {
  const defaultProps = {
    selectedConfigId: 'config-1',
    onConfigChange: vi.fn(),
    selectedDevice: '/dev/video0',
    onDeviceChange: vi.fn(),
    camerasData: mockCamerasData,
    onCamerasRefresh: vi.fn().mockResolvedValue(undefined),
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('CMUI-01: zone selector above camera dropdown', () => {
    it('renders a Zone heading', () => {
      render(<LightPanel {...defaultProps} />)
      expect(screen.getByText('Zone')).toBeInTheDocument()
    })

    it('renders a Camera heading below Zone', () => {
      render(<LightPanel {...defaultProps} />)
      const zoneHeading = screen.getByText('Zone')
      const cameraHeading = screen.getByText('Camera')
      // Zone must appear before Camera in DOM order
      expect(
        zoneHeading.compareDocumentPosition(cameraHeading) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy()
    })
  })

  describe('CMUI-02: camera option format', () => {
    it('shows camera options as "display_name (device_path)"', () => {
      render(<LightPanel {...defaultProps} />)
      expect(
        screen.getByText('USB Capture Card (/dev/video0)'),
      ).toBeInTheDocument()
      expect(
        screen.getByText('Elgato HD60 (/dev/video2)'),
      ).toBeInTheDocument()
    })
  })

  describe('empty state', () => {
    it('shows "No cameras" when cameras_available is false', () => {
      const noCamerasData = {
        ...mockCamerasData,
        cameras_available: false,
        devices: [],
      }
      render(<LightPanel {...defaultProps} camerasData={noCamerasData} />)
      expect(screen.getByText('No cameras')).toBeInTheDocument()
    })

    it('shows "Select camera..." placeholder when no device is selected', () => {
      render(<LightPanel {...defaultProps} selectedDevice={undefined} />)
      expect(screen.getByText('Select camera...')).toBeInTheDocument()
    })
  })
})
