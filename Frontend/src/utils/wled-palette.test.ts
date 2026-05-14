import { describe, it, expect } from 'vitest'
import { channelColor } from './wled-palette'

describe('channelColor (golden-angle HSL)', () => {
  it('returns hsl(0, 60%, 60%) for index 0', () => {
    expect(channelColor(0)).toBe('hsl(0, 60%, 60%)')
  })

  it('returns hsl(137.508, 60%, 60%) for index 1', () => {
    expect(channelColor(1)).toBe('hsl(137.508, 60%, 60%)')
  })

  it('adjacent indices differ', () => {
    expect(channelColor(2)).not.toBe(channelColor(3))
  })

  it('wraps modulo 360', () => {
    // (3 * 137.508) % 360 = 52.524
    expect(channelColor(3)).toBe('hsl(52.524, 60%, 60%)')
  })

  it.todo('AA-readable: dark text rgba(0,0,0,0.78) over the first 12 indices')
})
