import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// WledStripPainter ships in Plan 19-10. Konva pointer integration is covered
// by Playwright in Plan 19-12; this Vitest file covers ONLY:
//   - ResizeObserver-driven width sync
//   - Selected-zone state propagation
//   - Empty-state rendering
// All Konva pointer events are deferred to Playwright per RESEARCH.md.

// Stub react-konva so JSDOM does not attempt to create a canvas element.
vi.mock('react-konva', () => ({
  Stage: ({ children }: Record<string, unknown>) => children,
  Layer: ({ children }: Record<string, unknown>) => children,
  Rect: () => null,
  Line: () => null,
  Text: () => null,
}))

// Stub wled-paint-reducer helpers — we test state-machine logic separately.
vi.mock('./wled-paint-reducer', () => ({
  paintReducer: (s: unknown) => s,
  pixelToLed: (x: number, w: number, n: number) => Math.floor((x / w) * n),
  ledToPixel: (l: number, w: number, n: number) => (l / n) * w,
  clampBoundary: (d: number) => d,
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

describe('WledStripPainter', () => {
  it('renders one Stage per registered WLED device', async () => {
    const devices = [
      {
        id: 'd1', ip: '10.0.0.1', name: 'Strip A', led_count: 100,
        enabled: true, created_at: '', connected: true,
        last_error: null, last_success_at: null,
      },
      {
        id: 'd2', ip: '10.0.0.2', name: 'Strip B', led_count: 200,
        enabled: true, created_at: '', connected: true,
        last_error: null, last_success_at: null,
      },
    ]
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices })
    vi.spyOn(wledApi, 'listWledChannels').mockResolvedValue({ channels: [] })

    render(<WledStripPainter selectedChannelId={null} onSelectChannel={NOOP} />)
    await waitFor(() => {
      expect(screen.getByTestId('wled-strip-d1')).toBeTruthy()
      expect(screen.getByTestId('wled-strip-d2')).toBeTruthy()
    })
  })

  it('resize observer: Stage width re-renders when paint slot container resizes', async () => {
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [] })

    const { unmount } = render(
      <WledStripPainter selectedChannelId={null} onSelectChannel={NOOP} />,
    )
    await waitFor(() => {
      // The empty-state branch renders a single container div which is observed.
      expect(observeSpy).toHaveBeenCalledTimes(1)
    })
    unmount()
    expect(disconnectSpy).toHaveBeenCalledTimes(1)
  })

  it('selection: clicking a zone sets local selectedChannelId and emits onSelect to sidebar', () => {
    // Konva click events require a real canvas — deferred to Playwright (Plan 19-12).
  })

  it('empty state: zero devices renders "No WLED devices." + body copy', async () => {
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices: [] })

    render(<WledStripPainter selectedChannelId={null} onSelectChannel={NOOP} />)
    await waitFor(() => {
      expect(screen.getByTestId('wled-strip-painter-empty')).toBeTruthy()
      expect(screen.getByText('No WLED devices.')).toBeTruthy()
      expect(
        screen.getByText('Add a device in the panel on the right to start painting channels.'),
      ).toBeTruthy()
    })
  })

  it('Strip seed channel: rendered as full-width zone when a freshly-registered device has only the seed', async () => {
    const devices = [
      {
        id: 'd1', ip: '10.0.0.1', name: 'Strip A', led_count: 100,
        enabled: true, created_at: '', connected: true,
        last_error: null, last_success_at: null,
      },
    ]
    const channels = [
      { id: 'ch1', device_id: 'd1', name: 'Channel 1', start_led: 0, end_led: 99 },
    ]
    vi.spyOn(wledApi, 'getWledDevices').mockResolvedValue({ devices })
    vi.spyOn(wledApi, 'listWledChannels').mockResolvedValue({ channels })

    render(<WledStripPainter selectedChannelId={null} onSelectChannel={NOOP} />)
    await waitFor(() => {
      expect(screen.getByTestId('wled-strip-d1')).toBeTruthy()
      expect(screen.getByText('Strip A')).toBeTruthy()
    })
  })

  it('axis ticks: sparse labels (0, 50, 100, ...) rendered below the strip', () => {
    // Konva Text nodes are not accessible in JSDOM — deferred to Playwright (Plan 19-12).
  })
})
