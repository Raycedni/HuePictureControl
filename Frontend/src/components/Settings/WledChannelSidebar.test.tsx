import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

// Phase 19.1 Plan 07: WledChannelSidebar is now a READ-ONLY metadata panel.
// Per D-07: no <input>s, no Delete button — just name / seg_index / range /
// length read off the selected seg via listSegments(deviceId).

import { WledChannelSidebar } from './WledChannelSidebar'
import * as wledApi from '@/api/wled'

beforeEach(() => {
  // Each test wires its own listSegments mock.
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('WledChannelSidebar (read-only metadata panel)', () => {
  it('renders the empty-state panel when no segment is selected', () => {
    render(<WledChannelSidebar selectedSeg={null} />)
    expect(screen.getByTestId('wled-channel-sidebar-empty')).toBeTruthy()
    expect(screen.getByText(/select a zone on the strip/i)).toBeTruthy()
  })

  it('renders read-only metadata for the selected segment', async () => {
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({
      segments: [
        { seg_index: 1, start_led: 50, stop_led: 119, name: 'Sofa' },
      ],
    })

    render(
      <WledChannelSidebar selectedSeg={{ device_id: 'dev-1', seg_index: 1 }} />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('wled-channel-sidebar')).toBeTruthy()
    })
    expect(screen.getByTestId('sidebar-seg-name').textContent).toBe('Sofa')
    expect(screen.getByTestId('sidebar-seg-index').textContent).toBe('1')
    expect(screen.getByTestId('sidebar-seg-range').textContent).toBe('50–119')
    expect(screen.getByTestId('sidebar-seg-length').textContent).toBe('70 LEDs')
  })

  it('falls back to "Segment N" when seg.name is null (D-08 fallback)', async () => {
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({
      segments: [
        { seg_index: 3, start_led: 0, stop_led: 29, name: null },
      ],
    })

    render(
      <WledChannelSidebar selectedSeg={{ device_id: 'dev-1', seg_index: 3 }} />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('sidebar-seg-name').textContent).toBe('Segment 3')
    })
  })

  it('renders an error panel when listSegments rejects', async () => {
    vi.spyOn(wledApi, 'listSegments').mockRejectedValue(
      new wledApi.WledApiError(502, 'unreachable'),
    )

    render(
      <WledChannelSidebar selectedSeg={{ device_id: 'dev-1', seg_index: 0 }} />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('wled-channel-sidebar-error')).toBeTruthy()
    })
  })

  it('renders a not-found panel when the selected seg_index is missing from the cache', async () => {
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({
      segments: [
        { seg_index: 0, start_led: 0, stop_led: 99, name: 'A' },
      ],
    })

    render(
      <WledChannelSidebar selectedSeg={{ device_id: 'dev-1', seg_index: 7 }} />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('wled-channel-sidebar-error')).toBeTruthy()
    })
  })

  it('has no <input> elements (read-only per D-07)', async () => {
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({
      segments: [{ seg_index: 0, start_led: 0, stop_led: 9, name: 'X' }],
    })

    const { container } = render(
      <WledChannelSidebar selectedSeg={{ device_id: 'dev-1', seg_index: 0 }} />,
    )

    await waitFor(() => {
      expect(screen.getByTestId('wled-channel-sidebar')).toBeTruthy()
    })

    expect(container.querySelectorAll('input').length).toBe(0)
  })

  it('Clear-selection button fires onClear when present', async () => {
    vi.spyOn(wledApi, 'listSegments').mockResolvedValue({
      segments: [{ seg_index: 0, start_led: 0, stop_led: 9, name: 'X' }],
    })

    const onClear = vi.fn()
    render(
      <WledChannelSidebar
        selectedSeg={{ device_id: 'dev-1', seg_index: 0 }}
        onClear={onClear}
      />,
    )

    const btn = await screen.findByTestId('wled-channel-sidebar-clear')
    fireEvent.click(btn)
    expect(onClear).toHaveBeenCalledTimes(1)
  })
})
