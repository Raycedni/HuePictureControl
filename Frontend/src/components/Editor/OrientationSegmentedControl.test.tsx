import { describe, it } from 'vitest'

// OrientationSegmentedControl ships in Plan 19-08.

describe('OrientationSegmentedControl', () => {
  it.todo('renders 5 buttons with labels: auto, →, ←, ↓, ↑')

  it.todo('default selected button is "auto" when value="auto"')

  it.todo('click on a non-auto button fires onChange(<new orientation>) once')

  it.todo('patches region endpoint: parent component wires onChange to patchRegionOrientation(regionId, configId, value)')

  it.todo('active button styling: applies var(--accent-bg) background and var(--accent) color')

  it.todo('optimistic update: button reflects new value before await resolves')

  it.todo('error revert: when PATCH rejects, button reverts to previous value and inline error renders')
})
