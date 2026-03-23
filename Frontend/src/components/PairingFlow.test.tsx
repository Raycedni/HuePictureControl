import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import PairingFlow from './PairingFlow'

// Mock global fetch
const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => {
  mockFetch.mockReset()
})

describe('PairingFlow', () => {
  it('test_renders_pairing_instructions: shows link button instructions when unpaired', async () => {
    // Mock status as unpaired
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ paired: false, bridge_ip: '', bridge_name: '' }),
    })

    render(<PairingFlow />)

    await waitFor(() => {
      expect(screen.getByText(/link button/i)).toBeInTheDocument()
    })
  })

  it('test_shows_bridge_ip_input: shows an input field for bridge IP', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ paired: false, bridge_ip: '', bridge_name: '' }),
    })

    render(<PairingFlow />)

    await waitFor(() => {
      const input = screen.getByRole('textbox')
      expect(input).toBeInTheDocument()
    })
  })

  it('test_shows_paired_status: shows Paired and bridge name when status is paired', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        paired: true,
        bridge_ip: '192.168.1.100',
        bridge_name: 'Philips hue',
      }),
    })
    // Mock entertainment configs call
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        { id: 'cfg1', name: 'Living Room', status: 'active', channel_count: 3 },
      ],
    })

    render(<PairingFlow />)

    await waitFor(() => {
      expect(screen.getByText(/Paired/i)).toBeInTheDocument()
      expect(screen.getByText(/Philips hue/i)).toBeInTheDocument()
    })
  })

  it('test_shows_error_on_403: shows link button error when pair returns 403', async () => {
    // Status call: unpaired
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ paired: false, bridge_ip: '', bridge_name: '' }),
    })
    // Pair call: 403 error
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ detail: 'Link button not pressed' }),
    })

    render(<PairingFlow />)

    // Wait for unpaired step to appear
    await waitFor(() => {
      expect(screen.getByRole('textbox')).toBeInTheDocument()
    })

    // Fill in IP and click Pair
    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: '192.168.1.100' } })

    const pairButton = screen.getByRole('button', { name: /pair/i })
    fireEvent.click(pairButton)

    // Error message should mention link button
    await waitFor(() => {
      expect(screen.getByText(/link button/i)).toBeInTheDocument()
    })
  })
})
