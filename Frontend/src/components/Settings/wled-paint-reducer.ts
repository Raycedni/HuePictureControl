/**
 * Pure paint state machine + pixel/LED conversion + boundary clamp for the
 * WledStripPainter. Extracted out of the Konva component so the geometry can
 * be exhaustively unit-tested without JSDOM, react-konva, or the canvas
 * element. The Konva component imports these helpers and supplies the side
 * effects (POST on commit, dragBoundFunc on handles).
 *
 * RESEARCH.md §Testing Strategy notes that Konva pointer events are hard to
 * unit-test in Vitest. Splitting the state machine into a reducer plus
 * helpers is the canonical workaround.
 */

export type PaintState =
  | { phase: 'idle' }
  | { phase: 'painting'; startLed: number; currentLed: number }

export type PaintAction =
  | { type: 'mousedown'; led: number }
  | { type: 'mousemove'; led: number }
  | { type: 'mouseup'; led: number; commit: (start: number, end: number) => void }
  | { type: 'cancel' }

/**
 * Deterministic reducer for the paint gesture state machine.
 *
 * No side effects except invoking `commit(min, max)` exactly once during
 * 'mouseup' from a 'painting' state. Mouseup from 'idle' (i.e. mouseup with
 * no prior mousedown) is a no-op so a stray click on the strip doesn't
 * accidentally POST.
 */
export function paintReducer(state: PaintState, action: PaintAction): PaintState {
  switch (action.type) {
    case 'mousedown':
      return { phase: 'painting', startLed: action.led, currentLed: action.led }

    case 'mousemove':
      if (state.phase !== 'painting') return state
      return { ...state, currentLed: action.led }

    case 'mouseup': {
      if (state.phase !== 'painting') return state
      const start = Math.min(state.startLed, action.led)
      const end = Math.max(state.startLed, action.led)
      action.commit(start, end)
      return { phase: 'idle' }
    }

    case 'cancel':
      return { phase: 'idle' }

    default: {
      // Exhaustiveness guard (TS will flag unknown action types at compile time).
      const _exhaustive: never = action
      return state
    }
  }
}

/**
 * Map a strip-canvas pixel x-coordinate to a discrete LED index in
 * [0, ledCount-1]. Clamps negative and over-strip values so a paint gesture
 * that drifts off-canvas still commits to a valid range.
 *
 * @param x Pixel x in the strip Konva Stage's local coordinate space.
 * @param stripWidth Total stage width in pixels.
 * @param ledCount Total LEDs in the strip (`wled_devices.led_count`).
 */
export function pixelToLed(x: number, stripWidth: number, ledCount: number): number {
  if (stripWidth <= 0 || ledCount <= 0) return 0
  const t = x / stripWidth
  const ledFloat = t * ledCount
  const ledIdx = Math.floor(ledFloat)
  if (ledIdx < 0) return 0
  if (ledIdx >= ledCount) return ledCount - 1
  return ledIdx
}

/**
 * Inverse of pixelToLed — map a LED index back to its pixel center on the
 * canvas. Used to position boundary handles and zone rectangles.
 */
export function ledToPixel(led: number, stripWidth: number, ledCount: number): number {
  if (stripWidth <= 0 || ledCount <= 0) return 0
  return (led / ledCount) * stripWidth
}

/**
 * Boundary drag clamp: the boundary between two adjacent zones cannot pass
 * through either neighbour. Both zones must keep at least 1 LED.
 *
 * For adjacent zones A=[leftMin..boundary-1] and B=[boundary..rightMax],
 * the constraint is `leftMin + 1 <= boundary <= rightMax`. Returns the
 * clamped value.
 *
 * Per RESEARCH.md Risk R4 / Boundary Drag-Handle Resize: refuse-to-collapse
 * is preferred over auto-delete during drag (delete only happens via the
 * sidebar Delete button).
 *
 * @param desired The boundary LED index the user is dragging towards.
 * @param leftMin Start LED of the LEFT zone.
 * @param rightMax End LED of the RIGHT zone.
 */
export function clampBoundary(
  desired: number,
  leftMin: number,
  rightMax: number,
): number {
  const min = leftMin + 1
  const max = rightMax
  if (desired < min) return min
  if (desired > max) return max
  return desired
}
