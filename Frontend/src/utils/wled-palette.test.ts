import { describe, it, expect } from 'vitest'

// WLED palette helper does not exist yet — it ships in Plan 19-05.
// Import is wrapped in try/catch so vitest collection passes; tests fail
// loudly once the helper lands and the expected behavior is shippable.
let channelColor: ((idx: number) => string) | null = null
try {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  channelColor = require('./wled-palette').channelColor
} catch {
  channelColor = null
}

describe('channelColor (golden-angle HSL)', () => {
  it.skipIf(channelColor === null)('returns hsl(0, 60%, 60%) for index 0', () => {
    expect(channelColor!(0)).toBe('hsl(0, 60%, 60%)')
  })

  it.skipIf(channelColor === null)('returns hsl(137.508, 60%, 60%) for index 1', () => {
    expect(channelColor!(1)).toBe('hsl(137.508, 60%, 60%)')
  })

  it.skipIf(channelColor === null)('adjacent indices differ', () => {
    expect(channelColor!(2)).not.toBe(channelColor!(3))
  })

  it.skipIf(channelColor === null)('wraps modulo 360', () => {
    // (3 * 137.508) % 360 = 52.524
    expect(channelColor!(3)).toBe('hsl(52.524, 60%, 60%)')
  })

  it.todo('AA-readable: dark text rgba(0,0,0,0.78) over the first 12 indices')
})
