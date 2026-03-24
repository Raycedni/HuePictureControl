import { describe, it, expect } from 'vitest'
import { normalize, denormalize, pointInPolygon } from './geometry'

describe('normalize', () => {
  it('converts pixel coordinates to normalized [0..1] range', () => {
    const result = normalize([[100, 200]], 1000, 1000)
    expect(result).toEqual([[0.1, 0.2]])
  })

  it('normalizes multiple points', () => {
    const result = normalize([[0, 0], [500, 500], [1000, 1000]], 1000, 1000)
    expect(result).toEqual([[0, 0], [0.5, 0.5], [1, 1]])
  })

  it('handles different width and height', () => {
    const result = normalize([[400, 300]], 800, 600)
    expect(result[0][0]).toBeCloseTo(0.5)
    expect(result[0][1]).toBeCloseTo(0.5)
  })
})

describe('denormalize', () => {
  it('converts normalized [0..1] coords to pixel coordinates', () => {
    const result = denormalize([[0.5, 0.5]], 800, 600)
    expect(result).toEqual([[400, 300]])
  })

  it('denormalizes multiple points', () => {
    const result = denormalize([[0, 0], [1, 1]], 100, 200)
    expect(result).toEqual([[0, 0], [100, 200]])
  })
})

describe('normalize/denormalize roundtrip', () => {
  it('recovers original pixel coordinates after roundtrip', () => {
    const original: [number, number][] = [[123, 456], [789, 321]]
    const width = 1920
    const height = 1080
    const roundtripped = denormalize(normalize(original, width, height), width, height)
    for (let i = 0; i < original.length; i++) {
      expect(roundtripped[i][0]).toBeCloseTo(original[i][0], 5)
      expect(roundtripped[i][1]).toBeCloseTo(original[i][1], 5)
    }
  })
})

describe('pointInPolygon', () => {
  const square: [number, number][] = [[0, 0], [10, 0], [10, 10], [0, 10]]

  it('returns true for a point inside a square', () => {
    expect(pointInPolygon([5, 5], square)).toBe(true)
  })

  it('returns false for a point outside a square', () => {
    expect(pointInPolygon([15, 15], square)).toBe(false)
  })

  it('returns false for a point clearly outside', () => {
    expect(pointInPolygon([-1, 5], square)).toBe(false)
  })

  it('handles a triangle', () => {
    const triangle: [number, number][] = [[0, 0], [10, 0], [5, 10]]
    expect(pointInPolygon([5, 4], triangle)).toBe(true)
    expect(pointInPolygon([9, 9], triangle)).toBe(false)
  })
})
