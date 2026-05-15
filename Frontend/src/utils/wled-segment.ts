/**
 * Phase 19.1 D-08: resolve display name for a WLED segment.
 *
 * Returns `seg.name` (the WLED-side `n` field) when it is a non-empty,
 * non-whitespace string; otherwise returns the fallback `"Segment {seg_index}"`.
 *
 * Used by every UI surface that displays segment identity: the strip's inline
 * label, the LightPanel WLED chip row, the region orientation popover's channel
 * list, and `WledChannelSidebar`. Pure function — call at render time.
 *
 * @param seg The cached or freshly-fetched WLED segment row.
 * @returns The display string for the segment.
 *
 * @example
 *   segmentName({ seg_index: 0, start_led: 0, stop_led: 29, name: 'Sofa' }) // 'Sofa'
 *   segmentName({ seg_index: 0, start_led: 0, stop_led: 29, name: null })  // 'Segment 0'
 *   segmentName({ seg_index: 3, start_led: 0, stop_led: 29, name: '' })    // 'Segment 3'
 *   segmentName({ seg_index: 5, start_led: 0, stop_led: 29, name: '   ' }) // 'Segment 5'
 */
export interface WledSegment {
  seg_index: number
  start_led: number
  stop_led: number
  name: string | null
  refreshed_at?: string | null
}

export function segmentName(seg: WledSegment): string {
  if (typeof seg.name === 'string' && seg.name.trim().length > 0) {
    return seg.name
  }
  return `Segment ${seg.seg_index}`
}
