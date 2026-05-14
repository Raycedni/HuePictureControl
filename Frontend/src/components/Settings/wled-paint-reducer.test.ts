import { describe, it, expect } from 'vitest'
import { paintReducer, pixelToLed, clampBoundary } from './wled-paint-reducer'

describe('paintReducer (paint state machine)', () => {
  it('mousedown transitions idle → painting with startLed = led', () => {
    const next = paintReducer({ phase: 'idle' }, { type: 'mousedown', led: 50 })
    expect(next).toEqual({ phase: 'painting', startLed: 50, currentLed: 50 })
  })

  it('mousemove updates currentLed while in painting', () => {
    const next = paintReducer(
      { phase: 'painting', startLed: 50, currentLed: 50 },
      { type: 'mousemove', led: 80 },
    )
    expect(next).toMatchObject({ phase: 'painting', currentLed: 80 })
  })

  it('mouseup commits with min/max(start, current) and returns to idle', () => {
    let committed: [number, number] | null = null
    const commit = (s: number, e: number) => {
      committed = [s, e]
    }
    const next = paintReducer(
      { phase: 'painting', startLed: 80, currentLed: 50 },
      { type: 'mouseup', led: 50, commit },
    )
    expect(committed).toEqual([50, 80])
    expect(next).toEqual({ phase: 'idle' })
  })

  it('cancel returns to idle without committing', () => {
    const next = paintReducer(
      { phase: 'painting', startLed: 50, currentLed: 70 },
      { type: 'cancel' },
    )
    expect(next).toEqual({ phase: 'idle' })
  })
})

describe('pixelToLed', () => {
  it('maps x=0 to led=0', () => {
    expect(pixelToLed(0, 1000, 300)).toBe(0)
  })

  it('maps x=stripWidth to led=count-1', () => {
    expect(pixelToLed(1000, 1000, 300)).toBe(299)
  })

  it('clamps negative x to 0', () => {
    expect(pixelToLed(-50, 1000, 300)).toBe(0)
  })

  it('clamps x > stripWidth to count-1', () => {
    expect(pixelToLed(2000, 1000, 300)).toBe(299)
  })
})

describe('boundary clamp', () => {
  it('clamps boundary to leftMin + 1', () => {
    // left zone is [0, 49], right zone is [50, 99]. boundary = 50.
    // dragging to 0 should clamp at 1 (left keeps at least 1 LED).
    expect(clampBoundary(0, 0, 99)).toBe(1)
  })

  it('clamps boundary to rightMax', () => {
    // dragging to 200 (past right end 99) clamps to 99 (right keeps 1 LED).
    expect(clampBoundary(200, 0, 99)).toBe(99)
  })

  it('passes through in-range boundary unchanged', () => {
    expect(clampBoundary(40, 0, 99)).toBe(40)
  })
})
