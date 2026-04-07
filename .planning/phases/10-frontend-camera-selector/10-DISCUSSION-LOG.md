# Phase 10: Frontend Camera Selector - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-07
**Phase:** 10-frontend-camera-selector
**Areas discussed:** Dropdown placement, Preview switching, Zone-camera UX, Empty/error states

---

## Dropdown Placement

| Option | Description | Selected |
|--------|-------------|----------|
| Above canvas | Compact bar above EditorCanvas, between toolbar and canvas | |
| Inside toolbar row | Camera dropdown inline with drawing tools | |
| Sidebar panel | Camera selector in the right-side LightPanel alongside light assignment | ✓ |

**User's choice:** Sidebar panel
**Notes:** Groups all configuration controls together in the right panel.

### Follow-up: PreviewPage inclusion

| Option | Description | Selected |
|--------|-------------|----------|
| Editor only | Camera selector only in EditorPage sidebar | ✓ |
| Both pages | Camera dropdown in both EditorPage and PreviewPage | |
| You decide | Claude picks | |

**User's choice:** Editor only
**Notes:** PreviewPage continues using zone's assigned camera automatically.

### Follow-up: Panel position

| Option | Description | Selected |
|--------|-------------|----------|
| Top of panel | Camera selector at top, above lights list | ✓ |
| Bottom of panel | Camera selector below lights list | |
| You decide | Claude picks | |

**User's choice:** Top of panel
**Notes:** Natural top-down configuration flow.

### Follow-up: Entertainment config selector

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, add config selector | Config dropdown above camera dropdown in sidebar | ✓ |
| No, camera only | Only camera dropdown, config stays on PreviewPage | |
| You decide | Claude picks | |

**User's choice:** Yes, add config selector
**Notes:** Users can switch zones, see assigned camera, and edit regions all from editor page.

---

## Preview Switching

| Option | Description | Selected |
|--------|-------------|----------|
| Instant swap | Close old WS, open new. Double-buffer prevents flash. | ✓ |
| Loading placeholder | Show spinner over canvas while waiting for first frame | |
| You decide | Claude picks | |

**User's choice:** Instant swap
**Notes:** Existing double-buffer pattern in EditorCanvas prevents blank flash.

### Follow-up: Persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-save | Immediately persist via PUT /api/cameras/assignments/{config_id} | ✓ |
| Explicit save button | Local-only until user clicks Save | |
| You decide | Claude picks | |

**User's choice:** Auto-save
**Notes:** Consistent with existing region auto-save pattern.

---

## Zone-Camera UX

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, auto-update | Switching zone loads that zone's camera assignment | ✓ |
| Independent selection | Camera dropdown stays on last selected, independent of zone | |
| You decide | Claude picks | |

**User's choice:** Yes, auto-update
**Notes:** Everything stays in sync — zone, camera, and preview.

### Follow-up: No camera assigned

| Option | Description | Selected |
|--------|-------------|----------|
| Placeholder prompt | Show "Select camera..." as default | ✓ |
| Auto-select first camera | Pre-select first available camera | |
| You decide | Claude picks | |

**User's choice:** Placeholder prompt
**Notes:** Clear signal that assignment is needed.

---

## Empty/Error States

| Option | Description | Selected |
|--------|-------------|----------|
| Inline banner | Warning banner above canvas, dropdown disabled | ✓ |
| Full-page block | Block editor entirely | |
| You decide | Claude picks | |

**User's choice:** Inline banner
**Notes:** Editor remains usable for reviewing existing regions.

### Follow-up: Camera disconnect

| Option | Description | Selected |
|--------|-------------|----------|
| Badge + stale frame | Disconnected badge, canvas keeps last frame | ✓ |
| Auto-fallback | Auto-switch to first available camera | |
| You decide | Claude picks | |

**User's choice:** Badge + stale frame
**Notes:** User can pick different camera or use existing reconnect mechanism.

### Follow-up: Camera refresh

**User's choice:** Both — manual refresh button AND automatic refresh on dropdown open
**Notes:** User explicitly requested implementing both mechanisms. Refresh button next to dropdown + auto re-scan on dropdown open.

---

## Claude's Discretion

- Native `<select>` vs custom dropdown component for camera/zone selectors
- Camera list caching strategy (new hook, inline fetch, or extend existing)
- Exact styling of disconnected badge and no-cameras banner
- Whether zone selector filters lights list to that zone's channels only

## Deferred Ideas

None — discussion stayed within phase scope
