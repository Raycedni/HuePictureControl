import { describe, it } from 'vitest'

// WledStripPainter ships in Plan 19-07. Konva pointer integration is covered
// by Playwright in Plan 19-12; this Vitest file covers ONLY:
//   - ResizeObserver-driven width sync
//   - Selected-zone state propagation
//   - Empty-state rendering
// All Konva pointer events are deferred to Playwright per RESEARCH.md.

describe('WledStripPainter', () => {
  it.todo('renders one Stage per registered WLED device')

  it.todo('resize observer: Stage width re-renders when paint slot container resizes')

  it.todo('selection: clicking a zone sets local selectedChannelId and emits onSelect to sidebar')

  it.todo('empty state: zero devices renders "No WLED devices." + body copy')

  it.todo('Strip seed channel: rendered as full-width zone when a freshly-registered device has only the seed')

  it.todo('axis ticks: sparse labels (0, 50, 100, ...) rendered below the strip')
})
