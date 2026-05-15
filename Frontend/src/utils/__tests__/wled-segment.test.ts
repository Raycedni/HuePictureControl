import { describe, it, expect } from 'vitest'
import { segmentName } from '../wled-segment'

describe('segmentName (D-08)', () => {
  it('returns seg.n when name is a non-empty string', () => {
    expect(segmentName({ seg_index: 2, start_led: 0, stop_led: 9, name: 'Sofa' })).toBe('Sofa')
  })

  it('returns "Segment {seg_index}" when name is null', () => {
    expect(segmentName({ seg_index: 0, start_led: 0, stop_led: 9, name: null })).toBe('Segment 0')
  })

  it('returns "Segment {seg_index}" when name is an empty string', () => {
    expect(segmentName({ seg_index: 3, start_led: 0, stop_led: 9, name: '' })).toBe('Segment 3')
  })

  it('returns "Segment {seg_index}" when name is whitespace-only', () => {
    expect(segmentName({ seg_index: 5, start_led: 0, stop_led: 9, name: '   ' })).toBe('Segment 5')
  })
})
