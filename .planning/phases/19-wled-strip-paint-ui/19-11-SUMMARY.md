---
phase: 19
plan: 11
subsystem: frontend
tags: [phase-19, wled, lightpanel, drag-source, wave-5]
dependency_graph:
  requires: [19-05, 19-07]
  provides: [wled-drag-source, lightpanel-wled-section]
  affects: [Frontend/src/components/LightPanel.tsx, Frontend/src/components/LightPanel.test.tsx]
tech_stack:
  added: []
  patterns:
    - WLED section mirrors Hue Lights section structure (per-device sub-header + draggable channel rows)
    - channelColor(index) palette chip computed at render time (no DB lookup)
    - D-13 drag payload extends Hue contract additively (no Hue keys on WLED rows)
    - D-14 mono counter chip: static text-muted-foreground, no threshold colors
key_files:
  modified:
    - Frontend/src/components/LightPanel.tsx
    - Frontend/src/components/LightPanel.test.tsx
decisions:
  - WledAssignment import removed from LightPanel.tsx — listWledAssignments return type inferred, avoiding unused-import TS error
  - setData('entertainment_config_id', ...) uses multi-line form to stay under line length; grep for single-line pattern fails but content is correct and verified by passing tests
metrics:
  duration: ~25 minutes
  completed: 2026-05-14
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 19 Plan 11: LightPanel WLED Section Summary

WLED section inserted into LightPanel.tsx between Lights and Assignments, with per-device sub-headers, draggable channel rows using channelColor palette chips, D-13 drag payload (wledChannelId/wledDeviceId/wledChannelName/entertainment_config_id), and D-14 mono counter chip. Five Wave 1 LightPanel test stubs flipped from `it.todo` to green.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add WLED state hooks, load effect, channel count | 8b5ffe0 | LightPanel.tsx (+59 lines) |
| 2 | Insert WLED section JSX + flip 5 test stubs to green | 00294a9 | LightPanel.tsx (+~100 lines JSX), LightPanel.test.tsx (+~130 lines) |

## What Was Built

### LightPanel.tsx Changes

**New imports (lines 5-14):**
- `getWledDevices`, `listWledChannels`, `listWledAssignments`, `WledDevice`, `WledChannel` from `@/api/wled`
- `channelColor` from `@/utils/wled-palette`

**New state (3 slots):**
- `wledDevices: WledDevice[]` — registered devices list
- `wledChannelsByDevice: Record<string, WledChannel[]>` — channels indexed by device id
- `wledAssignmentsByChannel: Record<string, string>` — channelId -> region.name for "Assigned:" display

**New load effect:** Fires on `[selectedConfigId, regions]`. Fetches all devices, then per-device channels (sequential to avoid race), then assignments scoped to the selected config. Cleans up with `alive` flag.

**New derived value:** `wledChannelCount` — sum of all channel counts across all devices, used by the D-14 mono chip.

**WLED section JSX (between Lights `</div>` and Assignments block):**
- Hidden entirely when `wledDevices.length === 0` (no placeholder per UI-SPEC empty state)
- Visual separator `<div className="h-px bg-white/[0.06]" />`
- Section header "WLED" + mono counter chip (`data-testid="lightpanel-wled-counter"`)
- Per-device sub-headers: name + `{ip} · {led_count} LEDs · {channels.length} channels`
- Per-channel rows: `draggable`, D-13 `onDragStart`, `channelColor(channelIndex)` chip, LED range with en-dash (`–`), optional "Assigned:" line

**D-13 drag payload (verbatim):**
```tsx
e.dataTransfer.setData('wledChannelId', channel.id)
e.dataTransfer.setData('wledDeviceId', device.id)
e.dataTransfer.setData('wledChannelName', channel.name)
e.dataTransfer.setData('entertainment_config_id', selectedConfigId ?? '')
e.dataTransfer.effectAllowed = 'copy'
```
No Hue keys (`channelId`/`channelName`/`lightId`/`configId`) set on WLED rows.

### LightPanel.test.tsx Changes

**Added top-level mock:** `vi.mock('@/api/wled', ...)` with default empty-devices response so existing Hue tests are unaffected.

**Test stub flip results:**

| Stub | Status | Notes |
|------|--------|-------|
| renders WLED section header below Lights section | GREEN | findByTestId('lightpanel-wled-section') |
| counter chip: "M" mono text with text-muted-foreground (no threshold colors per D-14) | GREEN | checks font-mono, text-muted-foreground, NOT text-red-400 or text-hue-amber |
| WLED section is hidden entirely when no WLED devices are registered | GREEN | queryByTestId returns null |
| groups channels per device with sub-header | TODO (kept) | Visual assertion difficult in JSDOM |
| WLED chip matches palette | TODO (kept) | inline style assertion brittle in JSDOM |
| WLED drag payload: setData called with 4 keys | GREEN | fireEvent.dragStart captures all 4 setData calls |
| WLED drag payload: Hue keys NOT set on WLED rows | GREEN | asserts channelId/channelName/lightId/configId absent |
| Assigned-to line | TODO (kept) | Requires assignment mock wiring; deferred |

**Before/after todo count:**
- Before: 8 `it.todo` in WLED section
- After: 3 `it.todo` remain (visual/complex assertions deferred per plan instructions)
- Net: 5 stubs flipped to passing tests

## Verification

```
LightPanel.test.tsx: 17 passed | 3 todo (20)
Full suite:          85 passed | 32 todo (117) — 11 passed, 4 skipped files
TypeScript: 0 errors
```

## Deviations from Plan

### Minor: WledAssignment type not imported

The plan listed `type WledAssignment` in the import block but it is not referenced in LightPanel.tsx (the assignments are mapped inline without using the type). Importing an unused type would cause a TypeScript `verbatimModuleSyntax` warning in some configs. Omitted to keep the import clean. The `listWledAssignments` return type is inferred from the API function signature.

## Known Stubs

None — the WLED section fully renders draggable channel rows with correct drag payload. The 3 remaining `it.todo` entries cover visual details (sub-header format, palette chip inline style, assigned-to line) that do not block the plan's goal.

## Threat Flags

None — drag payload keys are sandboxed to the `EditorCanvas.handleDrop` branch that explicitly reads `wledChannelId`. No new network endpoints, auth paths, or file access patterns introduced.

## Self-Check: PASSED

- `/c/Users/Lukas/IdeaProjects/HuePictureControl/.claude/worktrees/agent-a014425e24123befd/Frontend/src/components/LightPanel.tsx` — exists, modified
- `/c/Users/Lukas/IdeaProjects/HuePictureControl/.claude/worktrees/agent-a014425e24123befd/Frontend/src/components/LightPanel.test.tsx` — exists, modified
- Commit 8b5ffe0 — exists (Task 1)
- Commit 00294a9 — exists (Task 2)
- TypeScript: 0 errors
- Vitest: 85 passed, 0 failures
