import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, cleanup } from '@testing-library/react'
import { usePreviewWS } from './usePreviewWS'

class MockWebSocket {
  static instances: MockWebSocket[] = []
  url: string
  binaryType: string = 'blob'
  onmessage: ((ev: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  readyState: number = WebSocket.OPEN
  closed = false

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  close() {
    this.closed = true
  }
}

describe('usePreviewWS', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:mock-url'),
      revokeObjectURL: vi.fn(),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    cleanup()
  })

  it('opens a WebSocket when enabled=true', () => {
    renderHook(() => usePreviewWS(true))
    expect(MockWebSocket.instances).toHaveLength(1)
    expect(MockWebSocket.instances[0].url).toContain('/ws/preview')
  })

  it('does not open a WebSocket when enabled=false', () => {
    renderHook(() => usePreviewWS(false))
    expect(MockWebSocket.instances).toHaveLength(0)
  })

  it('closes WebSocket on unmount', () => {
    const { unmount } = renderHook(() => usePreviewWS(true))
    const ws = MockWebSocket.instances[0]
    unmount()
    expect(ws.closed).toBe(true)
  })

  it('returns null imgSrc initially', () => {
    const { result } = renderHook(() => usePreviewWS(true))
    expect(result.current).toBeNull()
  })
})
