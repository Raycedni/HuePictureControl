import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

// Phase 19.1 Plan 07: WledStripPainter is now a READ-ONLY segment visualizer.
// All paint/boundary gestures are gone; the Konva strip just renders one zone
// per segment from `listSegments(deviceId)` + offers a per-device Refresh button
// that calls `refreshSegments(deviceId)`. A stale-badge appears when the cached
// segments' `refreshed_at` is older than 60 s.
//
// This Vitest file covers:
//   - ResizeObserver-driven width sync (kept from Phase 19)
//   - Empty-state rendering (kept from Phase 19)
//   - One zone per segment rendered from listSegments
//   - Refresh button POSTs refreshSegments and re-renders
//   - Pointer events on the Stage do NOT call any API (D-06)

// Stub react-konva so JSDOM does not attempt to create a canvas element.
// Note: react-konva tree returns React elements; Stage/Layer must pass children
// through so the inner Rect/Group children get rendered as no-op nulls but the
// device header (the `<div data-testid="wled-strip-{id}">` wrapper) still mounts.
vi.mock('react-konva', () => ({
  Stage: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  Layer: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  Group: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  Rect: () => null,
  Line: () => null,
  Text: () => null,
}))

import { WledStripPainter } from './WledStripPainter'
import * as wledApi from '@/api/wled'

// JSDOM does not implement ResizeObserver — install a no-op stub globally.
let observeSpy: ReturnType<typeof vi.fn>
let disconnectSpy: ReturnType<typeof vi.fn>

beforeEach(() => {
  observeSpy = vi.fn()
  disconnectSpy = vi.fn()
  // Must be a real class (new-able) because the component uses `new ResizeObserver(...)`.
  class MockResizeObserver {
    observe = observeSpy
    disconnect = disconnectSpy
    unobserve = vi.fn()
  }
  vi.stubGlobal('ResizeObserver', MockResizeObserver)
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const NOOP = () => {}

const DEV_1 = {
  id: 'dev-1',
  ip: '10.0.0.1',
  name: 'Strip A',
  led_count: 100,
  enabled: true,
  created_at: '',
  connected: true,
  last_error: null,
  last_success_at: null,
}

const DEV_2 = {
  id: 'dev-2',
  ip: '10.0.0.2',
  name: 'Strip B',
  led_count: 200,
  enabled: true,
  created_at: '',
  connected: true,
  last_error: null,
  last_success_at: null,
}

describe('WledStripPainter (read-only segment visualizer)', () => {
  it('renders one Stage per registered WLED device', async () => {
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [DEV_1, DEV_2] })
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({ segments: [] })

    render(<WledStripPainter selectedSeg={null} onSelectSegment={NOOP} />)
    await waitFor(() => {
      expect(screen.getByTestId('wled-strip-dev-1')).toBeTruthy()
      expect(screen.getByTestId('wled-strip-dev-2')).toBeTruthy()
    })
  })

  it('renders one zone per segment from listSegments response', async () => {
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [DEV_1] })
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({
      segments: [
        { seg_index: 0, start_led: 0, stop_led: 49, name: 'Sofa' },
        { seg_index: 1, start_led: 50, stop_led: 99, name: null },
      ],
    })

    render(<WledStripPainter selectedSeg={null} onSelectSegment={NOOP} />)

    await waitFor(() => {
      expect(screen.getByTestId('wled-seg-dev-1-0')).toBeTruthy()
      expect(screen.getByTestId('wled-seg-dev-1-1')).toBeTruthy()
    })
  })

  it('clicking Refresh button calls refreshSegments and updates zones', async () => {
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [DEV_1] })
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({ segments: [] })
    const refreshSpy = vi.spyOn(wledApi, 'refreshSegments').mockResolvedValue({
      segments: [{ seg_index: 0, start_led: 0, stop_led: 49, name: 'New' }],
      dropped_assignments: 0,
    })

    render(<WledStripPainter selectedSeg={null} onSelectSegment={NOOP} />)

    const btn = await screen.findByTestId('wled-refresh-button-dev-1')
    fireEvent.click(btn)

    await waitFor(() => {
      expect(refreshSpy).toHaveBeenCalledWith('dev-1')
    })
    await waitFor(() => {
      expect(screen.getByTestId('wled-seg-dev-1-0')).toBeTruthy()
    })
  })

  it('Refresh failure surfaces an inline error message + preserves cached zones', async () => {
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [DEV_1] })
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({
      segments: [{ seg_index: 0, start_led: 0, stop_led: 99, name: 'Cached' }],
    })
    vi.spyOn(wledApi, 'refreshSegments').mockRejectedValue(
      new wledApi.WledApiError(502, 'unreachable'),
    )

    render(<WledStripPainter selectedSeg={null} onSelectSegment={NOOP} />)

    const btn = await screen.findByTestId('wled-refresh-button-dev-1')
    fireEvent.click(btn)

    await waitFor(() => {
      expect(screen.getByTestId('wled-refresh-error-dev-1')).toBeTruthy()
    })
    // Cached zone still rendered.
    expect(screen.getByTestId('wled-seg-dev-1-0')).toBeTruthy()
  })

  it('stale-badge appears when refreshed_at is older than 60 s', async () => {
    const oldStamp = new Date(Date.now() - 5 * 60_000).toISOString()
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [DEV_1] })
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({
      segments: [
        { seg_index: 0, start_led: 0, stop_led: 99, name: 'Sofa', refreshed_at: oldStamp },
      ],
    })

    render(<WledStripPainter selectedSeg={null} onSelectSegment={NOOP} />)

    await waitFor(() => {
      const badge = screen.getByTestId('wled-stale-badge-dev-1')
      expect(badge.textContent ?? '').toMatch(/stale/i)
    })
  })

  it('pointer events on the Stage do not call refreshSegments or any mutation', async () => {
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [DEV_1] })
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({
      segments: [{ seg_index: 0, start_led: 0, stop_led: 99, name: 'Sofa' }],
    })
    const refreshSpy = vi.spyOn(wledApi, 'refreshSegments').mockResolvedValue({
      segments: [],
      dropped_assignments: 0,
    })

    render(<WledStripPainter selectedSeg={null} onSelectSegment={NOOP} />)
    const stripWrapper = await screen.findByTestId('wled-strip-dev-1')
    fireEvent.mouseDown(stripWrapper, { clientX: 100, clientY: 50 })
    fireEvent.mouseMove(stripWrapper, { clientX: 200, clientY: 50 })
    fireEvent.mouseUp(stripWrapper, { clientX: 200, clientY: 50 })

    expect(refreshSpy).not.toHaveBeenCalled()
  })

  it('resize observer: registers + disconnects when paint slot container mounts/unmounts', async () => {
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [] })

    const { unmount } = render(
      <WledStripPainter selectedSeg={null} onSelectSegment={NOOP} />,
    )
    await waitFor(() => {
      expect(observeSpy).toHaveBeenCalledTimes(1)
    })
    unmount()
    expect(disconnectSpy).toHaveBeenCalledTimes(1)
  })

  it('empty state: zero devices renders "No WLED devices." + body copy', async () => {
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [] })

    render(<WledStripPainter selectedSeg={null} onSelectSegment={NOOP} />)
    await waitFor(() => {
      expect(screen.getByTestId('wled-strip-painter-empty')).toBeTruthy()
      expect(screen.getByText('No WLED devices.')).toBeTruthy()
    })
  })
})
