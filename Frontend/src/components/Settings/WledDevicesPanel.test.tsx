import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import { WledDevicesPanel } from './WledDevicesPanel'

// Test idiom: vi.stubGlobal('fetch', ...) per test, the panel calls
// getWledDevices on mount so every test sees an initial GET first; the
// `impl` callback gets each subsequent (url, init) pair and decides what
// to return. Mirrors Frontend/src/api/cameras.test.ts mocking style.

function jsonResp(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response
}

function mockFetch(impl: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    return Promise.resolve(impl(url, init))
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('WledDevicesPanel', () => {
  it('renders empty state when no devices', async () => {
    vi.stubGlobal('fetch', mockFetch(() => jsonResp({ devices: [] })))
    render(<WledDevicesPanel />)
    await waitFor(() => screen.getByText(/no wled devices/i))
  })

  it('renders device rows with name / IP / led count', async () => {
    const devices = [
      {
        id: 'd1',
        ip: '10.0.0.5',
        name: 'Strip A',
        led_count: 100,
        enabled: true,
        created_at: '',
        connected: true,
        last_error: null,
        last_success_at: null,
      },
    ]
    vi.stubGlobal('fetch', mockFetch(() => jsonResp({ devices })))
    render(<WledDevicesPanel />)
    await waitFor(() => screen.getByText('Strip A'))
    expect(screen.getByText(/10\.0\.0\.5.*100 LEDs/i)).toBeInTheDocument()
  })

  it('Add button POSTs /api/wled/devices with entered IP and refreshes', async () => {
    let callCount = 0
    const fetchMock = mockFetch((url, init) => {
      callCount++
      // First request is the mount-time GET — return empty list so we render the input.
      if (callCount === 1) return jsonResp({ devices: [] })
      // The subsequent POST returns the freshly-created device.
      if (url === '/api/wled/devices' && init?.method === 'POST') {
        return jsonResp(
          {
            id: 'd1',
            ip: '10.0.0.5',
            name: 'X',
            led_count: 100,
            enabled: true,
            created_at: '',
            connected: false,
            last_error: null,
            last_success_at: null,
          },
          201,
        )
      }
      // Refresh GET after the POST.
      return jsonResp({
        devices: [
          {
            id: 'd1',
            ip: '10.0.0.5',
            name: 'X',
            led_count: 100,
            enabled: true,
            created_at: '',
            connected: false,
            last_error: null,
            last_success_at: null,
          },
        ],
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<WledDevicesPanel />)
    await waitFor(() => screen.getByTestId('wled-ip-input'))

    fireEvent.change(screen.getByTestId('wled-ip-input'), {
      target: { value: '10.0.0.5' },
    })
    fireEvent.click(screen.getByTestId('wled-add-button'))

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')
      expect(postCall).toBeDefined()
      expect((postCall![1] as RequestInit).body).toBe(JSON.stringify({ ip: '10.0.0.5' }))
    })
  })

  it('toggle button PUTs /enabled with new value', async () => {
    const devices = [
      {
        id: 'd1',
        ip: '10.0.0.5',
        name: 'X',
        led_count: 10,
        enabled: true,
        created_at: '',
        connected: true,
        last_error: null,
        last_success_at: null,
      },
    ]
    const fetchMock = mockFetch((url, init) => {
      if (url.endsWith('/enabled') && init?.method === 'PUT') {
        return jsonResp({ id: 'd1', enabled: false })
      }
      return jsonResp({ devices })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<WledDevicesPanel />)
    await waitFor(() => screen.getByTestId('wled-toggle-d1'))

    fireEvent.click(screen.getByTestId('wled-toggle-d1'))

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === 'PUT',
      )
      expect(putCall).toBeDefined()
      expect(JSON.parse((putCall![1] as RequestInit).body as string)).toEqual({
        enabled: false,
      })
    })
  })

  it('Remove button calls DELETE and refreshes', async () => {
    const devices = [
      {
        id: 'd1',
        ip: '10.0.0.5',
        name: 'X',
        led_count: 10,
        enabled: true,
        created_at: '',
        connected: false,
        last_error: null,
        last_success_at: null,
      },
    ]
    const fetchMock = mockFetch((_url, init) => {
      if (init?.method === 'DELETE') return jsonResp(null, 204)
      return jsonResp({ devices })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<WledDevicesPanel />)
    await waitFor(() => screen.getByTestId('wled-remove-d1'))
    fireEvent.click(screen.getByTestId('wled-remove-d1'))
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          (c) => (c[1] as RequestInit | undefined)?.method === 'DELETE',
        ),
      ).toBe(true)
    })
  })

  it('Scan button populates candidates list', async () => {
    const fetchMock = mockFetch((url, init) => {
      if (url === '/api/wled/scan' && init?.method === 'POST') {
        return jsonResp({
          candidates: [{ ip: '10.0.0.7', name: 'WLED-Kitchen' }],
        })
      }
      return jsonResp({ devices: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<WledDevicesPanel />)
    await waitFor(() => screen.getByTestId('wled-scan-button'))
    fireEvent.click(screen.getByTestId('wled-scan-button'))
    await waitFor(() => screen.getByText(/WLED-Kitchen/))
  })

  it('shows 502 error message on unreachable add', async () => {
    const fetchMock = mockFetch((_url, init) => {
      if (init?.method === 'POST') return jsonResp(null, 502)
      return jsonResp({ devices: [] })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<WledDevicesPanel />)
    await waitFor(() => screen.getByTestId('wled-ip-input'))
    fireEvent.change(screen.getByTestId('wled-ip-input'), {
      target: { value: '10.0.0.99' },
    })
    fireEvent.click(screen.getByTestId('wled-add-button'))
    await waitFor(() => screen.getByRole('alert'))
    expect(screen.getByRole('alert').textContent).toMatch(/unreachable/i)
  })
})
