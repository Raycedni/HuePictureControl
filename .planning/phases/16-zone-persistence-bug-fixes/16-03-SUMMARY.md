---
phase: 16-zone-persistence-bug-fixes
plan: 03
subsystem: frontend
tags: [frontend, react, zustand, websocket, bug-fix, BFIX-01, BFIX-02]
requires:
  - 16-01 (backend `last_entertainment_config_id` on GET /api/cameras + PUT /api/cameras/last-zone/{stable_id})
  - 16-02 (/ws/status `active_config_id` / `active_device_path` fields)
provides:
  - CameraDevice.last_entertainment_config_id typed field
  - putLastZone(stableId, configId) fire-and-forget API client
  - useStatusStore.activeConfigId / activeDevicePath (camelCase Zustand fields)
  - useStatusWS parses active_config_id / active_device_path with tri-state semantics
  - LightPanel 3-tier initial zone resolution (streaming > camera last-zone > first config)
  - LightPanel auto-save on zone-dropdown change
  - LightPanel camera-change auto-switches zone (D-08)
  - data-testid="zone-select" on the zone `<select>` (W3)
affects:
  - Frontend/src/api/cameras.ts
  - Frontend/src/api/cameras.test.ts
  - Frontend/src/store/useStatusStore.ts
  - Frontend/src/hooks/useStatusWS.ts
  - Frontend/src/components/LightPanel.tsx
  - Frontend/src/components/LightPanel.test.tsx
tech-stack:
  added: []
  patterns:
    - Tri-state WS field parse (string | null | undefined) preserves Partial<setMetrics> semantics
    - findByTestId for async component regions that only render after promise resolution
    - Guard-clause-based priority cascade inside a single useEffect for multi-tier selection
key-files:
  created: []
  modified:
    - Frontend/src/api/cameras.ts
    - Frontend/src/api/cameras.test.ts
    - Frontend/src/store/useStatusStore.ts
    - Frontend/src/hooks/useStatusWS.ts
    - Frontend/src/components/LightPanel.tsx
    - Frontend/src/components/LightPanel.test.tsx
decisions:
  - D-03 honored — auto-save on every zone dropdown change via PUT /api/cameras/last-zone
  - D-04 honored — CameraDevice.last_entertainment_config_id exposes the read-side; putLastZone wraps the write side
  - D-07/D-11 honored — activeConfigId overrides persisted value; zone select remains disabled while streaming
  - D-08 honored — camera dropdown change auto-switches zone when the target camera has a non-null last_entertainment_config_id that still exists in configs
  - D-09 honored — 3-tier fallback (streaming > camera persisted > configs[0])
  - Claude's Discretion (stale-clear) — when persisted config no longer exists, UI falls back silently AND calls putLastZone to overwrite the dangling row
  - W2 closure — read-only happy-path pre-selection verified by explicit `not.toHaveBeenCalled()` negative assertion
  - W3 closure — stable data-testid="zone-select" handle replaces all index-based DOM queries
metrics:
  completed: 2026-04-20
  duration: ~25 minutes
  tasks: 2
  commits: 2
  files_changed: 6
  tests_added: 12 (5 API + 7 LightPanel)
  tests_total_frontend: 52 (baseline 40 + 12 new)
---

# Phase 16 Plan 03: Frontend 3-tier Zone Selection + Auto-save Summary

**One-liner:** Wire the frontend to consume the 16-01 `last_entertainment_config_id` field + `putLastZone` endpoint and the 16-02 `active_config_id` WS payload, replacing the single-branch "pick configs[0]" init with a streaming > camera > first-config cascade and auto-saving on every zone dropdown change.

## What Was Built

### `Frontend/src/api/cameras.ts`
- `CameraDevice` interface extended with `last_entertainment_config_id: string | null` — the read-side of the persistence loop (populated by 16-01's `LEFT JOIN camera_last_zone`).
- New `putLastZone(stableId, entertainmentConfigId)` wrapping `PUT /api/cameras/last-zone/{stable_id}`. `encodeURIComponent(stableId)` hardens the path segment (T-16-09); 4xx/5xx throws `HTTP {status}` matching the existing `putCameraAssignment` pattern.

### `Frontend/src/store/useStatusStore.ts`
- Two new camelCase fields — `activeConfigId: string | null` + `activeDevicePath: string | null` — with `null` initial state. The existing `setMetrics(m: Partial<...>)` shape is preserved, so the fields stay `undefined`-skippable.

### `Frontend/src/hooks/useStatusWS.ts`
- The `onmessage` parser now extracts `active_config_id` / `active_device_path` with **tri-state semantics**:
  - `string` → pass through.
  - explicit `null` → set to `null` (the idle/error transition path from 16-02).
  - missing/undefined → leave `undefined` so `setMetrics` skips the field entirely (backwards compatibility with pre-16-02 payloads).

### `Frontend/src/components/LightPanel.tsx`
- Imports: `putLastZone` alongside `putCameraAssignment`; `activeConfigId` Zustand selector added beside `isStreaming`.
- **Initial selection effect replaced** (was `[]` dep, 3-branch inline inside the config-load `.then`). The new effect runs on `[configs, activeConfigId, selectedConfigId, selectedDevice, camerasData, onConfigChange]` and implements a three-tier cascade with explicit early returns:
  1. `activeConfigId` non-null → pre-select it (D-07/D-11).
  2. `selectedConfigId` already set → leave it alone.
  3. Selected camera has a persisted `last_entertainment_config_id` that exists in `configs` → pre-select that (D-09 Tier 2).
  4. Otherwise fall back to `configs[0].id` (D-09 Tier 3); if a persisted-but-stale value was the reason, also fire `putLastZone(stable_id, configs[0].id)` to clear the dangling row (Claude's Discretion per 16-CONTEXT.md).
- `handleZoneChange` (new handler): propagates via `onConfigChange` AND calls `putLastZone(cam.stable_id, newConfigId)` when not streaming. Early-returns when streaming (documents the D-07 invariant, even though the `<select>` is disabled in that state).
- `handleCameraChange` extended with a D-08 tail:
  - After the existing `putCameraAssignment` call,
  - if `!isStreaming` AND the target camera's `last_entertainment_config_id` is non-null AND that config still exists in the current `configs` list → call `onConfigChange(persisted)`.
  - Null or stale persisted values leave the current zone untouched ("last touched wins").
- Zone `<select>` gains `data-testid="zone-select"` (W3 stable test handle) and `onChange={handleZoneChange}`. The existing `disabled={isStreaming}` attribute is preserved unchanged.

### `Frontend/src/components/LightPanel.test.tsx`
- `vi.mock('@/api/cameras', ...)` extended with `putLastZone: vi.fn().mockResolvedValue(undefined)`.
- Imports: `putLastZone`, `useStatusStore`, `fireEvent`, `waitFor`.
- Mock devices at lines 30–45 gain `last_entertainment_config_id: null` (kept the baseline suite green after the CameraDevice interface extension).
- New `describe('BFIX-01/BFIX-02: zone persistence', ...)` block with a `beforeEach` that resets `useStatusStore` state + clears mocks, and 7 test cases:
  1. **"reload with persisted zone pre-selects saved config (BFIX-01) and does NOT write back (W2)"** — includes the W2 negative assertion `expect(vi.mocked(putLastZone)).not.toHaveBeenCalled()`.
  2. **"streaming active_config_id overrides persisted (BFIX-02, D-11)"** — sets the store to streaming + active_config_id='config-1' before mount, verifies the zone select is disabled via `getByTestId('zone-select')` (W3).
  3. **"camera switch auto-switches zone when new camera has last_entertainment_config_id (D-08)"** — selects a new camera whose persisted config exists, asserts `onConfigChange` fires.
  4. **"camera switch does NOT auto-switch zone when new camera has null last_entertainment_config_id (D-08)"** — the null-persisted branch; asserts `onConfigChange` never fires.
  5. **"missing stored config falls back to first and PUTs to clear stale row"** — exercises Claude's Discretion; asserts both the `onConfigChange('config-1')` fallback and the stale-clear `putLastZone(stableId, 'config-1')` PUT.
  6. **"zone change while not streaming PUTs last-zone (D-03)"** — `fireEvent.change` on the testid-selected `<select>`, asserts PUT call.
  7. **"zone select disabled while streaming (D-07 invariant)"** — DOM disabled-attribute assertion via `findByTestId`.

All queries in the new block use `screen.getByTestId('zone-select')` or `screen.findByTestId('zone-select')` — no `querySelectorAll('select')[0]` index access anywhere in BFIX tests (W3 closure).

Notable implementation notes:
- Tests 6 and 7 needed `findByTestId` rather than `getByTestId` because the zone `<select>` only renders once the `configs.length > 0` ternary resolves, which happens after `getEntertainmentConfigs` settles.

## Decisions Honored

| ID  | Decision                                                                         | Delivered By                                                        |
| --- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| D-03 | Auto-save on every zone-dropdown change                                          | `handleZoneChange` → `putLastZone`                                  |
| D-04 | Field on CameraDevice + PUT endpoint path                                        | `CameraDevice.last_entertainment_config_id`; `putLastZone` wrapper  |
| D-07 | Streaming overrides; zone select disabled while streaming                        | `disabled={isStreaming}` preserved; Tier 1 in init effect           |
| D-08 | Camera change auto-switches zone ("last touched wins")                           | `handleCameraChange` tail after `putCameraAssignment`               |
| D-09 | 3-tier load-time priority                                                        | Cascade inside init effect with explicit early returns              |
| D-11 | Active streaming overrides persisted defaults                                    | Tier 1 always wins; subsequent tiers return early when it fires     |

## Threat Model Honored

| ID      | Threat                                                             | Mitigation                                                                                                 |
| ------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| T-16-09 | Path traversal via untrusted stable_id in putLastZone URL          | `encodeURIComponent(stableId)` — verified by dedicated "url-encodes the stable_id" test in cameras.test.ts |
| T-16-12 | Stale persisted config left in DB after bridge-side config deletion | `persistedExists` guard + stale-clear `putLastZone` fallback branch                                        |

## The Exact putLastZone Decision Points (per Output spec)

`putLastZone` fires in **exactly two** code paths in `LightPanel.tsx`:

1. **handleZoneChange** — user-initiated dropdown change while not streaming (the D-03 happy path).
2. **Init-effect stale-clear branch** — when a persisted value exists but is no longer in the configs list. This overwrites the dangling row with the first-config fallback.

`putLastZone` is **never** called on the happy-path pre-selection (persisted value matches an existing config). This is the W2 invariant and is protected by an explicit `not.toHaveBeenCalled()` negative assertion in Test 1.

## Verification

- `cd Frontend && npx vitest run` → **52 passed / 0 failed** (7 test files). Baseline was 40 passed.
- `grep -c "activeConfigId" Frontend/src/components/LightPanel.tsx Frontend/src/store/useStatusStore.ts Frontend/src/hooks/useStatusWS.ts` — ≥ 5 ✓ (5 / 2 / 3 respectively).
- `grep -c "putLastZone" Frontend/src/components/LightPanel.tsx Frontend/src/api/cameras.ts` — ≥ 3 ✓ (4 / 2).
- `grep -c 'data-testid="zone-select"' Frontend/src/components/LightPanel.tsx` — 1 ✓ (W3).
- `grep -c "not.toHaveBeenCalled" Frontend/src/components/LightPanel.test.tsx` — 2 ✓ (W2 negative assertion + D-08 null-branch assertion).

## Windows Tooling Note

The Frontend `node_modules` checkout committed to this tree bundled the Linux rolldown binding (`@rolldown/binding-linux-x64-gnu` + `-musl`) but not the Windows native binding, causing a `MODULE_NOT_FOUND: @rolldown/binding-win32-x64-msvc` at vitest startup. Installed `@rolldown/binding-win32-x64-msvc` locally with `--no-save` to run the suite; this is a dev-env quirk, not a plan-scope change, and wasn't committed to the repo.

## Deviations from Plan

- **None in scope.** All deviations were test-shape clarifications discovered while making Tests 6 + 7 pass: the zone `<select>` is gated by `configs.length > 0`, so the test needed `findByTestId` (awaits render) instead of `getByTestId` (synchronous). Plan spec used `getByTestId` — no functional contract changed, just the matching test helper.
- **Docs-only diff from plan Task 1:** Added a third `putLastZone` test ("url-encodes the stable_id") beyond the two called out in the `<behavior>` block. This exercises T-16-09 (path traversal) directly and is the only test that verifies `encodeURIComponent` actually applied — cheap coverage for a security mitigation.

## Downstream Contract

This is the user-visible completion of Phase 16. No downstream plan in this phase consumes this plan's output. Phase 18 (HA control endpoints, v1.3) may extend the same `/ws/status` surface with additional fields, but `activeConfigId`/`activeDevicePath` are now load-bearing for LightPanel initial render and should be treated as stable.

## Self-Check: PASSED

**Files verified present and containing required symbols:**
- `Frontend/src/api/cameras.ts` — contains `last_entertainment_config_id` (line 7) + `putLastZone` export (line 46) ✓
- `Frontend/src/store/useStatusStore.ts` — contains `activeConfigId` (lines 9, 20) ✓
- `Frontend/src/hooks/useStatusWS.ts` — contains `active_config_id` parse (lines 29–31) ✓
- `Frontend/src/components/LightPanel.tsx` — contains `activeConfigId` (5×), `putLastZone` (4×), `handleZoneChange` (2×), `data-testid="zone-select"` (line 237) ✓
- `Frontend/src/components/LightPanel.test.tsx` — contains `getByTestId('zone-select')` (3×), `not.toHaveBeenCalled` (2× including W2 putLastZone negative) ✓

**Commits present in git log:**
- `4511a08` — feat(16-03): add putLastZone API + activeConfigId store/WS plumbing ✓
- `94e3549` — feat(16-03): 3-tier zone init + auto-save + camera-zone auto-switch ✓

**Full frontend test suite:** 52/52 passed ✓
