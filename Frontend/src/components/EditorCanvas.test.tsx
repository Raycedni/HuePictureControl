import { describe, it } from 'vitest'

// EditorCanvas tests target the drop-handler branch added in Plan 19-09.
// Wave 0 only seeds the structure; the assertions flip green once the WLED
// branch is wired.

describe('EditorCanvas.handleDrop — WLED branch', () => {
  it.todo('WLED drop: when wledChannelId is present, calls upsertWledAssignment and returns')

  it.todo('WLED drop: refreshes regions via setRegions after successful upsert')

  it.todo('WLED drop: sets selectedId to the hit region after upsert')

  it.todo('Hue drop preserved: payload without wledChannelId still calls updateRegionAPI')

  it.todo('WLED branch returns: payload with BOTH wledChannelId and lightId only calls WLED handler')

  it.todo('No payload: handler exits without API calls when neither key is present')
})

describe('EditorCanvas — popover mount', () => {
  it.todo('renders RegionOrientationPopover as a sibling of Konva Stage')
})
