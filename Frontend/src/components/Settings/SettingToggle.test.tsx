// quick-task 260704-w88: vitest specs for the generic SettingToggle.
//
// Idiom mirrors SettingSlider.test.tsx: `vi.stubGlobal('fetch', ...)` per
// test, the component fires a mount-time GET so every test sees an initial
// GET request, and `vi.unstubAllGlobals()` in afterEach keeps tests
// hermetic. settingKey="hdr_input" is the representative instance.

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import '@testing-library/jest-dom'
import { SettingToggle } from './SettingToggle'

const KEY = 'hdr_input'

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

describe('SettingToggle', () => {
  it('renders unchecked (off) from GET value 0.0 on mount', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResp({ value: 0 })))
    render(
      <SettingToggle
        settingKey={KEY}
        label="HDR input (HDR10 -> sRGB)"
        description="Convert HDR10 source colors to sRGB."
      />,
    )
    await waitFor(() => {
      const toggle = screen.getByTestId(`setting-toggle-${KEY}`)
      expect(toggle).not.toBeDisabled()
    })
    const toggle = screen.getByTestId(
      `setting-toggle-${KEY}`,
    ) as HTMLInputElement
    expect(toggle.checked).toBe(false)
  })

  it('renders checked (on) when the loaded value is >= 0.5', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResp({ value: 1.0 })))
    render(
      <SettingToggle settingKey={KEY} label="HDR input" description="" />,
    )
    await waitFor(() => {
      const toggle = screen.getByTestId(
        `setting-toggle-${KEY}`,
      ) as HTMLInputElement
      expect(toggle.checked).toBe(true)
    })
  })

  it('toggling on calls PUT with value 1.0', async () => {
    let putBody: unknown = null
    let putUrl: string | null = null
    const fetchMock = mockFetch((url, init) => {
      if (!init || init.method === undefined) {
        return jsonResp({ value: 0 })
      }
      if (init.method === 'PUT') {
        putUrl = url
        putBody = JSON.parse(init.body as string)
        return jsonResp({ value: 1.0 })
      }
      return jsonResp({ value: 0 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <SettingToggle settingKey={KEY} label="HDR input" description="" />,
    )
    await waitFor(() => {
      expect(screen.getByTestId(`setting-toggle-${KEY}`)).not.toBeDisabled()
    })

    const toggle = screen.getByTestId(`setting-toggle-${KEY}`)
    fireEvent.click(toggle)

    await waitFor(() => {
      expect(putBody).toEqual({ value: 1.0 })
    })
    expect(putUrl).toBe(`/api/settings/${KEY}`)

    await waitFor(() => {
      expect((toggle as HTMLInputElement).checked).toBe(true)
    })
  })

  it('toggling off calls PUT with value 0.0', async () => {
    let putBody: unknown = null
    const fetchMock = mockFetch((_url, init) => {
      if (!init || init.method === undefined) {
        return jsonResp({ value: 1.0 })
      }
      if (init.method === 'PUT') {
        putBody = JSON.parse(init.body as string)
        return jsonResp({ value: 0.0 })
      }
      return jsonResp({ value: 1.0 })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <SettingToggle settingKey={KEY} label="HDR input" description="" />,
    )
    await waitFor(() => {
      const toggle = screen.getByTestId(
        `setting-toggle-${KEY}`,
      ) as HTMLInputElement
      expect(toggle.checked).toBe(true)
    })

    const toggle = screen.getByTestId(`setting-toggle-${KEY}`)
    fireEvent.click(toggle)

    await waitFor(() => {
      expect(putBody).toEqual({ value: 0.0 })
    })
    await waitFor(() => {
      expect((toggle as HTMLInputElement).checked).toBe(false)
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
      <SettingToggle settingKey={KEY} label="HDR input" description="" />,
    )
    await waitFor(() => {
      expect(screen.getByTestId(`setting-toggle-${KEY}`)).not.toBeDisabled()
    })

    fireEvent.click(screen.getByTestId(`setting-toggle-${KEY}`))

    const err = await screen.findByTestId(`setting-toggle-error-${KEY}`)
    expect(err.textContent).toMatch(/500/)
  })

  it('shows error caption when initial GET fails', async () => {
    vi.stubGlobal(
      'fetch',
      mockFetch(() => jsonResp({ detail: 'nope' }, 404)),
    )
    render(
      <SettingToggle settingKey={KEY} label="HDR input" description="" />,
    )
    const err = await screen.findByTestId(`setting-toggle-error-${KEY}`)
    expect(err.textContent).toMatch(/404/)
  })
})
