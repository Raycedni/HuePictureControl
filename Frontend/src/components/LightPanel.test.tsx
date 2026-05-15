import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import { LightPanel } from './LightPanel'
import { putLastZone } from '@/api/cameras'
import { useStatusStore } from '@/store/useStatusStore'

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
  putLastZone: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/api/regions', () => ({
  getRegions: vi.fn().mockResolvedValue([]),
  fetchRegions: vi.fn().mockResolvedValue([]),
  startStreaming: vi.fn().mockResolvedValue(undefined),
  stopStreaming: vi.fn().mockResolvedValue(undefined),
  clearAllAssignments: vi.fn().mockResolvedValue(undefined),
}))

// Phase 19.1: mock the WLED API so LightPanel can be tested without a backend.
// Default: no devices registered (WLED section hidden).
vi.mock('@/api/wled', () => ({
  getWledDevices: vi.fn().mockResolvedValue({ devices: [] }),
  listSegments: vi.fn().mockResolvedValue({ segments: [] }),
  listWledAssignments: vi.fn().mockResolvedValue({ assignments: [] }),
}))

const mockCamerasData = {
  devices: [
    {
      device_path: '/dev/video0',
      stable_id: 'usb-0403:6010-00000000',
      display_name: 'USB Capture Card',
      connected: true,
      last_seen_at: '2026-04-07T12:00:00',
      last_entertainment_config_id: null,
    },
    {
      device_path: '/dev/video2',
      stable_id: 'usb-1234:5678-00000001',
      display_name: 'Elgato HD60',
      connected: true,
      last_seen_at: null,
      last_entertainment_config_id: null,
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

  describe('BFIX-01/BFIX-02: zone persistence', () => {
    beforeEach(() => {
      useStatusStore.setState({
        activeConfigId: null,
        activeDevicePath: null,
        isStreaming: false,
      })
      vi.clearAllMocks()
    })

    it('reload with persisted zone pre-selects saved config (BFIX-01) and does NOT write back (W2)', async () => {
      const onConfigChange = vi.fn()
      const camerasWithPersisted = {
        ...mockCamerasData,
        devices: [
          { ...mockCamerasData.devices[0], last_entertainment_config_id: 'config-2' },
          ...mockCamerasData.devices.slice(1),
        ],
      }
      render(
        <LightPanel
          {...defaultProps}
          selectedConfigId=""
          onConfigChange={onConfigChange}
          camerasData={camerasWithPersisted}
        />,
      )
      await waitFor(() => expect(onConfigChange).toHaveBeenCalledWith('config-2'))
      // W2 — pre-selection is read-only; no PUT on the happy path.
      // Guards against a future regression that writes on every render.
      expect(vi.mocked(putLastZone)).not.toHaveBeenCalled()
    })

    it('streaming active_config_id overrides persisted (BFIX-02, D-11)', async () => {
      useStatusStore.setState({ activeConfigId: 'config-1', isStreaming: true })
      const onConfigChange = vi.fn()
      const camerasWithPersisted = {
        ...mockCamerasData,
        devices: [
          { ...mockCamerasData.devices[0], last_entertainment_config_id: 'config-2' },
          ...mockCamerasData.devices.slice(1),
        ],
      }
      render(
        <LightPanel
          {...defaultProps}
          selectedConfigId=""
          onConfigChange={onConfigChange}
          camerasData={camerasWithPersisted}
        />,
      )
      await waitFor(() => expect(onConfigChange).toHaveBeenCalledWith('config-1'))
      // W3 — query by stable testid, not DOM index.
      const zoneSelect = screen.getByTestId('zone-select')
      expect(zoneSelect).toHaveAttribute('disabled')
    })

    it('camera switch auto-switches zone when new camera has last_entertainment_config_id (D-08)', async () => {
      const onConfigChange = vi.fn()
      const onDeviceChange = vi.fn()
      const camerasWithTargetPersisted = {
        ...mockCamerasData,
        devices: [
          mockCamerasData.devices[0],
          { ...mockCamerasData.devices[1], last_entertainment_config_id: 'config-2' },
        ],
      }
      render(
        <LightPanel
          {...defaultProps}
          selectedConfigId="config-1"
          onConfigChange={onConfigChange}
          selectedDevice="/dev/video0"
          onDeviceChange={onDeviceChange}
          camerasData={camerasWithTargetPersisted}
        />,
      )
      // Wait for configs to load so the handler's `configs.some(...)` check succeeds.
      await waitFor(() =>
        expect(screen.getByTestId('zone-select')).toHaveValue('config-1'),
      )
      const cameraSelects = screen.getAllByRole('combobox')
      // Camera select is the second <select> in the panel (zone is first).
      const cameraSelect = cameraSelects[1]
      fireEvent.change(cameraSelect, { target: { value: '/dev/video2' } })
      await waitFor(() => expect(onConfigChange).toHaveBeenCalledWith('config-2'))
    })

    it('camera switch does NOT auto-switch zone when new camera has null last_entertainment_config_id (D-08)', async () => {
      const onConfigChange = vi.fn()
      const onDeviceChange = vi.fn()
      render(
        <LightPanel
          {...defaultProps}
          selectedConfigId="config-1"
          onConfigChange={onConfigChange}
          selectedDevice="/dev/video0"
          onDeviceChange={onDeviceChange}
          camerasData={mockCamerasData}
        />,
      )
      await waitFor(() =>
        expect(screen.getByTestId('zone-select')).toHaveValue('config-1'),
      )
      onConfigChange.mockClear()
      const cameraSelects = screen.getAllByRole('combobox')
      const cameraSelect = cameraSelects[1]
      fireEvent.change(cameraSelect, { target: { value: '/dev/video2' } })
      // Allow any pending promises from handleCameraChange to resolve.
      await waitFor(() => expect(onDeviceChange).toHaveBeenCalledWith('/dev/video2'))
      expect(onConfigChange).not.toHaveBeenCalled()
    })

    it('missing stored config falls back to first and PUTs to clear stale row', async () => {
      const onConfigChange = vi.fn()
      const camerasWithStale = {
        ...mockCamerasData,
        devices: [
          { ...mockCamerasData.devices[0], last_entertainment_config_id: 'deleted-config-xyz' },
          ...mockCamerasData.devices.slice(1),
        ],
      }
      render(
        <LightPanel
          {...defaultProps}
          selectedConfigId=""
          onConfigChange={onConfigChange}
          camerasData={camerasWithStale}
        />,
      )
      await waitFor(() => expect(onConfigChange).toHaveBeenCalledWith('config-1'))
      // Stale-clear PUT overwrites the dangling row with the first-config fallback.
      await waitFor(() =>
        expect(vi.mocked(putLastZone)).toHaveBeenCalledWith(
          'usb-0403:6010-00000000',
          'config-1',
        ),
      )
    })

    it('zone change while not streaming PUTs last-zone (D-03)', async () => {
      useStatusStore.setState({ isStreaming: false })
      const onConfigChange = vi.fn()
      render(
        <LightPanel
          {...defaultProps}
          selectedConfigId="config-1"
          onConfigChange={onConfigChange}
          camerasData={mockCamerasData}
        />,
      )
      // W3 — stable testid query, not querySelectorAll('select')[0].
      // Use findBy to wait for the zone <select> to appear after configs load.
      const zoneSelect = await screen.findByTestId('zone-select')
      expect(zoneSelect).not.toHaveAttribute('disabled')
      fireEvent.change(zoneSelect, { target: { value: 'config-2' } })
      await waitFor(() =>
        expect(vi.mocked(putLastZone)).toHaveBeenCalledWith(
          mockCamerasData.devices[0].stable_id,
          'config-2',
        ),
      )
    })

    it('zone select disabled while streaming (D-07 invariant)', async () => {
      useStatusStore.setState({ isStreaming: true, activeConfigId: 'config-1' })
      render(
        <LightPanel
          {...defaultProps}
          selectedConfigId="config-1"
          onConfigChange={vi.fn()}
          camerasData={mockCamerasData}
        />,
      )
      // findByTestId waits for configs to load (the <select> renders only
      // inside configs.length > 0). W3 — stable testid query.
      const zoneSelect = await screen.findByTestId('zone-select')
      expect(zoneSelect).toHaveAttribute('disabled')
    })
  })
})

// Phase 19.1 Plan 08 — WLED section tests rewritten for composite-key drag payload.

import { getWledDevices, listSegments, listWledAssignments } from '@/api/wled'

const mockDevice1 = {
  id: 'dev-1',
  ip: '192.168.1.50',
  name: 'Living Room Strip',
  led_count: 120,
  enabled: true,
  created_at: '2026-01-01T00:00:00',
  connected: true,
  last_error: null,
  last_success_at: null,
}

const mockSeg1 = {
  seg_index: 0,
  start_led: 0,
  stop_led: 59,
  name: 'Sofa',
  refreshed_at: '2026-05-15T19:00:00',
}

const mockSeg2 = {
  seg_index: 1,
  start_led: 60,
  stop_led: 119,
  name: 'TV',
  refreshed_at: '2026-05-15T19:00:00',
}

const wledDefaultProps = {
  selectedConfigId: 'config-1',
  onConfigChange: vi.fn(),
  selectedDevice: '/dev/video0',
  onDeviceChange: vi.fn(),
  camerasData: mockCamerasData,
  onCamerasRefresh: vi.fn().mockResolvedValue(undefined),
}

describe('LightPanel WLED section', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset WLED mocks to defaults (no devices) before each test
    vi.mocked(getWledDevices).mockResolvedValue({ devices: [] })
    vi.mocked(listSegments).mockResolvedValue({ segments: [] })
    vi.mocked(listWledAssignments).mockResolvedValue({ assignments: [] })
  })

  it('renders WLED section header below Lights section', async () => {
    vi.mocked(getWledDevices).mockResolvedValue({ devices: [mockDevice1] })
    vi.mocked(listSegments).mockResolvedValue({ segments: [mockSeg1] })

    render(<LightPanel {...wledDefaultProps} />)

    const section = await screen.findByTestId('lightpanel-wled-section')
    expect(section).toBeInTheDocument()
    // "WLED" heading is inside the section
    expect(section).toHaveTextContent('WLED')
  })

  it('counter chip: "M" mono text with text-muted-foreground (no threshold colors per D-14)', async () => {
    const dev2 = { ...mockDevice1, id: 'dev-2', name: 'Bedroom Strip', ip: '192.168.1.51' }
    vi.mocked(getWledDevices).mockResolvedValue({ devices: [mockDevice1, dev2] })
    // Each device has 3 segments — total = 6
    const makeSegs = () => [
      { seg_index: 0, start_led: 0, stop_led: 29, name: 'A', refreshed_at: null },
      { seg_index: 1, start_led: 30, stop_led: 59, name: 'B', refreshed_at: null },
      { seg_index: 2, start_led: 60, stop_led: 89, name: 'C', refreshed_at: null },
    ]
    vi.mocked(listSegments).mockImplementation(() =>
      Promise.resolve({ segments: makeSegs() }),
    )

    render(<LightPanel {...wledDefaultProps} />)

    const counter = await screen.findByTestId('lightpanel-wled-counter')
    expect(counter).toHaveTextContent('6')
    expect(counter).toHaveClass('font-mono')
    expect(counter).toHaveClass('text-muted-foreground')
    // Must NOT have threshold-color classes (D-14)
    expect(counter).not.toHaveClass('text-red-400')
    expect(counter).not.toHaveClass('text-hue-amber')
  })

  it('WLED section is hidden entirely when no WLED devices are registered', async () => {
    // getWledDevices already mocked to return [] in beforeEach
    render(<LightPanel {...wledDefaultProps} />)

    // Allow effects to settle
    await waitFor(() => expect(vi.mocked(getWledDevices)).toHaveBeenCalled())
    expect(screen.queryByTestId('lightpanel-wled-section')).toBeNull()
  })

  it.todo('groups segments per device with sub-header showing {ip} · {led_count} LEDs · {seg_count} segments')

  it.todo('WLED chip matches palette: each segment row chip background equals channelColor(seg.seg_index)')

  it('WLED drag payload uses wledDeviceId + seg_index per D-13', async () => {
    vi.mocked(getWledDevices).mockResolvedValue({ devices: [mockDevice1] })
    vi.mocked(listSegments).mockResolvedValue({ segments: [mockSeg1, mockSeg2] })

    render(<LightPanel {...wledDefaultProps} />)

    const row = await screen.findByTestId(
      `lightpanel-wled-seg-${mockDevice1.id}-${mockSeg1.seg_index}`,
    )

    const setData = vi.fn()
    fireEvent.dragStart(row, {
      dataTransfer: { setData, effectAllowed: '' },
    })

    expect(setData).toHaveBeenCalledWith('wledDeviceId', mockDevice1.id)
    expect(setData).toHaveBeenCalledWith('seg_index', String(mockSeg1.seg_index))
    expect(setData).toHaveBeenCalledWith('wledSegName', mockSeg1.name)
    expect(setData).toHaveBeenCalledWith(
      'entertainment_config_id',
      wledDefaultProps.selectedConfigId,
    )
  })

  it('WLED drag payload: legacy Phase-19 keys (wledChannelId/wledChannelName) and Hue keys are NOT set on WLED rows', async () => {
    vi.mocked(getWledDevices).mockResolvedValue({ devices: [mockDevice1] })
    vi.mocked(listSegments).mockResolvedValue({ segments: [mockSeg1] })

    render(<LightPanel {...wledDefaultProps} />)

    const row = await screen.findByTestId(
      `lightpanel-wled-seg-${mockDevice1.id}-${mockSeg1.seg_index}`,
    )

    const setData = vi.fn()
    fireEvent.dragStart(row, {
      dataTransfer: { setData, effectAllowed: '' },
    })

    const calledKeys = setData.mock.calls.map((call) => call[0])
    expect(calledKeys).not.toContain('wledChannelId')
    expect(calledKeys).not.toContain('wledChannelName')
    expect(calledKeys).not.toContain('channelId')
    expect(calledKeys).not.toContain('channelName')
    expect(calledKeys).not.toContain('lightId')
    expect(calledKeys).not.toContain('configId')
  })

  it('chip color uses channelColor(seg_index) per D-09 parity', async () => {
    vi.mocked(getWledDevices).mockResolvedValue({ devices: [mockDevice1] })
    const segA = { seg_index: 2, start_led: 0, stop_led: 9, name: null, refreshed_at: null }
    const segB = { seg_index: 5, start_led: 10, stop_led: 19, name: null, refreshed_at: null }
    vi.mocked(listSegments).mockResolvedValue({ segments: [segA, segB] })

    render(<LightPanel {...wledDefaultProps} />)

    const chipA = await screen.findByTestId(
      `lightpanel-wled-chip-${mockDevice1.id}-${segA.seg_index}`,
    )
    const chipB = await screen.findByTestId(
      `lightpanel-wled-chip-${mockDevice1.id}-${segB.seg_index}`,
    )
    // JSDOM normalizes hsl(...) to rgb(...) in style.background; assert the
    // two chips differ (proving seg_index drives the palette, per D-09).
    expect(chipA.style.background).not.toBe('')
    expect(chipB.style.background).not.toBe('')
    expect(chipA.style.background).not.toBe(chipB.style.background)
  })

  it('segment display uses segmentName() — falls back to "Segment N" when name is null', async () => {
    vi.mocked(getWledDevices).mockResolvedValue({ devices: [mockDevice1] })
    const unnamed = { seg_index: 3, start_led: 0, stop_led: 9, name: null, refreshed_at: null }
    vi.mocked(listSegments).mockResolvedValue({ segments: [unnamed] })

    render(<LightPanel {...wledDefaultProps} />)

    const row = await screen.findByTestId(
      `lightpanel-wled-seg-${mockDevice1.id}-${unnamed.seg_index}`,
    )
    expect(row).toHaveTextContent('Segment 3')
  })

  it.todo('Assigned-to line: when seg has an assignment, "Assigned: {region.name}" renders in text-hue-amber/60')
})
