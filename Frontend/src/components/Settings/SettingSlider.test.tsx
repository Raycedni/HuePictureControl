// quick-task 260704-iss: vitest specs for the generic SettingSlider.
//
// Idiom mirrors BrightnessCutoffControl.test.tsx: `vi.stubGlobal('fetch', ...)`
// per test, the component fires a mount-time GET so every test sees an
// initial GET request, and `vi.unstubAllGlobals()` in afterEach keeps tests
// hermetic. Parameterized with settingKey="color_vibrancy" as the
// representative instance (per plan D-4 — one instance is enough coverage
// since the component logic is settingKey-agnostic).

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import '@testing-library/jest-dom'
import { SettingSlider } from './SettingSlider'

const KEY = 'color_vibrancy'

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

describe('SettingSlider', () => {
  it('renders default value 0.00 from GET on mount', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResp({ value: 0 })))
    render(
      <SettingSlider
        settingKey={KEY}
        label="Color vibrancy (white suppression)"
        description="Suppresses bright white pixels."
      />,
    )
    await waitFor(() => {
      const slider = screen.getByTestId(`setting-slider-${KEY}`)
      expect(slider).not.toBeDisabled()
    })
    expect(screen.getByTestId(`setting-value-${KEY}`).textContent).toBe(
      '0.00',
    )
    const slider = screen.getByTestId(
      `setting-slider-${KEY}`,
    ) as HTMLInputElement
    expect(slider.value).toBe('0')
  })

  it('displays loaded value from server', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResp({ value: 0.42 })))
    render(
      <SettingSlider settingKey={KEY} label="Color vibrancy" description="" />,
    )
    await waitFor(() => {
      expect(screen.getByTestId(`setting-value-${KEY}`).textContent).toBe(
        '0.42',
      )
    })
  })

  it('slider change triggers PUT to /api/settings/{key} with the new value', async () => {
    let putBody: unknown = null
    let putUrl: string | null = null
    const fetchMock = mockFetch((url, init) => {
      if (!init || init.method === undefined) {
        return jsonResp({ value: 0 })
      }
      if (init.method === 'PUT') {
        putUrl = url
        putBody = JSON.parse(init.body as string)
        return jsonResp({ value: 0.5 })
      }
      return jsonResp({ value: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <SettingSlider settingKey={KEY} label="Color vibrancy" description="" />,
    )
    await waitFor(() => {
      expect(screen.getByTestId(`setting-slider-${KEY}`)).not.toBeDisabled()
    })

    const slider = screen.getByTestId(`setting-slider-${KEY}`)
    fireEvent.change(slider, { target: { value: '0.5' } })

    await waitFor(() => {
      expect(putBody).toEqual({ value: 0.5 })
    })
    expect(putUrl).toBe(`/api/settings/${KEY}`)

    await waitFor(() => {
      expect(screen.getByTestId(`setting-value-${KEY}`).textContent).toBe(
        '0.50',
      )
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

    render(
      <SettingSlider settingKey={KEY} label="Color vibrancy" description="" />,
    )
    await waitFor(() => {
      expect(screen.getByTestId(`setting-slider-${KEY}`)).not.toBeDisabled()
    })

    fireEvent.change(screen.getByTestId(`setting-slider-${KEY}`), {
      target: { value: '0.7' },
    })

    const err = await screen.findByTestId(`setting-error-${KEY}`)
    expect(err.textContent).toMatch(/500/)
  })
})
