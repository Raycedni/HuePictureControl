import { describe, it } from 'vitest'

// RegionOrientationPopover ships in Plan 19-08. Vitest stubs for the
// per-region behavior locked in CONTEXT.md D-19 + UI-SPEC.

describe('RegionOrientationPopover', () => {
  it.todo('renders only when selectedId is non-null AND region has >=1 WLED assignment')

  it.todo('per-region single control: renders ONE OrientationSegmentedControl regardless of assignment count')

  it.todo('renders read-only assignment list below the segmented control')

  it.todo('close trigger: × button calls setSelectedId(null)')

  it.todo('close trigger: outside-click closes via Base UI Popover.onOpenChange')

  it.todo('close trigger: region deselect (selectedId → null) hides popover')

  it.todo('auto-flip: popover positioned bottom-left by default')

  it.todo('empty state copy: "Drag a channel from the LightPanel to add an assignment." when no WLED assignments')
})
