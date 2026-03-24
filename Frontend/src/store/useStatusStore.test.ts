import { describe, it, expect, beforeEach } from 'vitest'
import { useStatusStore } from './useStatusStore'

describe('useStatusStore', () => {
  beforeEach(() => {
    useStatusStore.setState({
      fps: 0,
      latency: 0,
      bridgeState: 'unknown',
      error: null,
      isStreaming: false,
    })
  })

  it('has correct initial state defaults', () => {
    const state = useStatusStore.getState()
    expect(state.fps).toBe(0)
    expect(state.latency).toBe(0)
    expect(state.bridgeState).toBe('unknown')
    expect(state.error).toBeNull()
    expect(state.isStreaming).toBe(false)
  })

  it('setMetrics with partial update leaves other fields unchanged', () => {
    useStatusStore.getState().setMetrics({ fps: 30 })
    const state = useStatusStore.getState()
    expect(state.fps).toBe(30)
    expect(state.latency).toBe(0)
    expect(state.bridgeState).toBe('unknown')
    expect(state.error).toBeNull()
    expect(state.isStreaming).toBe(false)
  })

  it('setMetrics with full update replaces all fields', () => {
    useStatusStore.getState().setMetrics({
      fps: 60,
      latency: 25,
      bridgeState: 'connected',
      error: 'test error',
      isStreaming: true,
    })
    const state = useStatusStore.getState()
    expect(state.fps).toBe(60)
    expect(state.latency).toBe(25)
    expect(state.bridgeState).toBe('connected')
    expect(state.error).toBe('test error')
    expect(state.isStreaming).toBe(true)
  })

  it('setMetrics can clear error by setting it to null', () => {
    useStatusStore.getState().setMetrics({ error: 'some error' })
    expect(useStatusStore.getState().error).toBe('some error')
    useStatusStore.getState().setMetrics({ error: null })
    expect(useStatusStore.getState().error).toBeNull()
  })
})
