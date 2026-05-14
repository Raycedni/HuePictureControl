import { describe, it, expect } from 'vitest'

// Paint reducer ships in Plan 19-05. Vitest collection guard:
type PaintState = unknown
type PaintAction = unknown
let paintReducer:
  | ((state: PaintState, action: PaintAction) => PaintState)
  | null = null
let pixelToLed: ((x: number, w: number, count: number) => number) | null = null
let clampBoundary:
  | ((boundary: number, leftMin: number, rightMax: number) => number)
  | null = null
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const mod = require('./wled-paint-reducer')
  paintReducer = mod.paintReducer
  pixelToLed = mod.pixelToLed
  clampBoundary = mod.clampBoundary
} catch {
  paintReducer = null
  pixelToLed = null
  clampBoundary = null
}

describe('paintReducer (paint state machine)', () => {
  it.skipIf(paintReducer === null)(
    'mousedown transitions idle → painting with startLed = led',
    () => {
      const next = paintReducer!({ phase: 'idle' }, { type: 'mousedown', led: 50 })
      expect(next).toEqual({ phase: 'painting', startLed: 50, currentLed: 50 })
    },
  )

  it.skipIf(paintReducer === null)(
    'mousemove updates currentLed while in painting',
    () => {
      const next = paintReducer!(
        { phase: 'painting', startLed: 50, currentLed: 50 },
        { type: 'mousemove', led: 80 },
      )
      expect(next).toMatchObject({ phase: 'painting', currentLed: 80 })
    },
  )

  it.skipIf(paintReducer === null)(
    'mouseup commits with min/max(start, current) and returns to idle',
    () => {
      let committed: [number, number] | null = null
      const commit = (s: number, e: number) => {
        committed = [s, e]
      }
      const next = paintReducer!(
        { phase: 'painting', startLed: 80, currentLed: 50 },
        { type: 'mouseup', led: 50, commit },
      )
      expect(committed).toEqual([50, 80])
      expect(next).toEqual({ phase: 'idle' })
    },
  )

  it.skipIf(paintReducer === null)(
    'cancel returns to idle without committing',
    () => {
      const next = paintReducer!(
        { phase: 'painting', startLed: 50, currentLed: 70 },
        { type: 'cancel' },
      )
      expect(next).toEqual({ phase: 'idle' })
    },
  )
})

describe('pixelToLed', () => {
  it.skipIf(pixelToLed === null)('maps x=0 to led=0', () => {
    expect(pixelToLed!(0, 1000, 300)).toBe(0)
  })

  it.skipIf(pixelToLed === null)('maps x=stripWidth to led=count-1', () => {
    expect(pixelToLed!(1000, 1000, 300)).toBe(299)
  })

  it.skipIf(pixelToLed === null)('clamps negative x to 0', () => {
    expect(pixelToLed!(-50, 1000, 300)).toBe(0)
  })

  it.skipIf(pixelToLed === null)('clamps x > stripWidth to count-1', () => {
    expect(pixelToLed!(2000, 1000, 300)).toBe(299)
  })
})

describe('boundary clamp', () => {
  it.skipIf(clampBoundary === null)(
    'clamps boundary to leftMin + 1',
    () => {
      // left zone is [0, 49], right zone is [50, 99]. boundary = 50.
      // dragging to 0 should clamp at 1 (left keeps at least 1 LED).
      expect(clampBoundary!(0, 0, 99)).toBe(1)
    },
  )

  it.skipIf(clampBoundary === null)(
    'clamps boundary to rightMax',
    () => {
      // dragging to 200 (past right end 99) clamps to 99 (right keeps 1 LED).
      expect(clampBoundary!(200, 0, 99)).toBe(99)
    },
  )

  it.skipIf(clampBoundary === null)(
    'passes through in-range boundary unchanged',
    () => {
      expect(clampBoundary!(40, 0, 99)).toBe(40)
    },
  )
})
