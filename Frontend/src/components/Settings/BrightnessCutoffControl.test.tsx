// quick-task 260516-kra: vitest specs for the BrightnessCutoffControl.
//
// Idiom mirrors WledDevicesPanel.test.tsx: `vi.stubGlobal('fetch', ...)`
// per test, the component fires a mount-time GET so every test sees an
// initial GET request, and `vi.unstubAllGlobals()` in afterEach keeps
// tests hermetic.

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import '@testing-library/jest-dom'
import { BrightnessCutoffControl } from './BrightnessCutoffControl'

function jsonResp(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response
}

function mockFetch(
  impl: (url: string, init?: RequestInit) => Response | Promise<Response>,
) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    return Promise.resolve(impl(url, init))
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BrightnessCutoffControl', () => {
  it('renders default value 0.00 from GET on mount', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResp({ value: 0 })))
    render(<BrightnessCutoffControl />)
    await waitFor(() => {
      // The slider becomes enabled once the GET resolves.
      const slider = screen.getByTestId('brightness-cutoff-slider')
      expect(slider).not.toBeDisabled()
    })
    expect(screen.getByTestId('brightness-cutoff-value').textContent).toBe(
      '0.00',
    )
    const slider = screen.getByTestId(
      'brightness-cutoff-slider',
    ) as HTMLInputElement
    expect(slider.value).toBe('0')
  })

  it('displays loaded value from server', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResp({ value: 0.42 })))
    render(<BrightnessCutoffControl />)
    await waitFor(() => {
      expect(
        screen.getByTestId('brightness-cutoff-value').textContent,
      ).toBe('0.42')
    })
  })

  it('slider change triggers PUT with the new value', async () => {
    let putBody: unknown = null
    const fetchMock = mockFetch((url, init) => {
      if (!init || init.method === undefined) {
        // GET on mount
        return jsonResp({ value: 0 })
      }
      if (init.method === 'PUT') {
        putBody = JSON.parse(init.body as string)
        return jsonResp({ value: 0.5 })
      }
      return jsonResp({ value: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<BrightnessCutoffControl />)
    await waitFor(() => {
      expect(screen.getByTestId('brightness-cutoff-slider')).not.toBeDisabled()
    })

    const slider = screen.getByTestId('brightness-cutoff-slider')
    fireEvent.change(slider, { target: { value: '0.5' } })

    await waitFor(() => {
      expect(putBody).toEqual({ value: 0.5 })
    })

    // Verify the PUT URL too
    const putCall = fetchMock.mock.calls.find(
      (call) => (call[1] as RequestInit | undefined)?.method === 'PUT',
    )
    expect(putCall).toBeDefined()
    expect(putCall![0]).toBe('/api/settings/brightness_cutoff_threshold')

    // Display updates to the persisted value
    await waitFor(() => {
      expect(
        screen.getByTestId('brightness-cutoff-value').textContent,
      ).toBe('0.50')
    })
  })

  it('shows error caption when PUT fails', async () => {
    const fetchMock = mockFetch((_url, init) => {
      if (!init || init.method === undefined) {
        return jsonResp({ value: 0 })
      }
      if (init.method === 'PUT') {
        return jsonResp({ detail: 'broken' }, 500)
      }
      return jsonResp({ value: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<BrightnessCutoffControl />)
    await waitFor(() => {
      expect(screen.getByTestId('brightness-cutoff-slider')).not.toBeDisabled()
    })

    fireEvent.change(screen.getByTestId('brightness-cutoff-slider'), {
      target: { value: '0.7' },
    })

    const err = await screen.findByTestId('brightness-cutoff-error')
    expect(err.textContent).toMatch(/500/)
  })
})
