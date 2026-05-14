/**
 * Derived per-channel render-fill palette (Phase 19 D-09, D-11).
 *
 * Golden-angle HSL: hue = (index × 137.508°) mod 360, sat 60%, light 60%.
 * The 137.508° constant maximises hue separation between adjacent indices,
 * so a freshly painted Channel N is always visually distinct from its
 * neighbour N-1. Saturation/lightness are picked so the dark text colour
 * `rgba(0,0,0,0.78)` (UI-SPEC §Typography) stays AA-readable across all
 * indices.
 *
 * Pure function — call at render time. Never persist the result. The input
 * is the per-device channel index (D-10), not a database column.
 *
 * @param index Zero-based per-device channel index.
 * @returns CSS HSL string usable as a `background` or `color` value.
 *
 * @example
 *   channelColor(0)  // 'hsl(0, 60%, 60%)'
 *   channelColor(1)  // 'hsl(137.508, 60%, 60%)'
 *   channelColor(3)  // 'hsl(52.524, 60%, 60%)'
 */
export function channelColor(index: number): string {
  const hue = (index * 137.508) % 360
  return `hsl(${hue}, 60%, 60%)`
}
