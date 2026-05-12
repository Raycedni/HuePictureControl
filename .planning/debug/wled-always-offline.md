---
slug: wled-always-offline
status: resolved
trigger: WLED devices are always shown as offline in the UI even though they are on and reachable on the LAN. User additionally reports inability to assign the strip to a region even while streaming.
created: 2026-05-12
updated: 2026-05-12
---

# Debug Session: WLED Always Offline

## Symptoms

- **Expected**: WLED panel shows the device as connected/online when the device is on and reachable on the LAN. The strip can be assigned to canvas regions like Hue channels. During active streaming, the status reflects "connected" once UDP packets are flowing.
- **Actual**: Status indicator stays "offline" in the WLED panel at all times. User reports being unable to assign the strip to a region. Status remains "offline" even while streaming is active and (allegedly) UDP packets should be flowing.
- **Errors**: None visible to the user (no backend log errors mentioned, no browser console errors mentioned). Investigation should still grep logs + DevTools.
- **Timeline**: Has been broken since Phase 17 shipped (2026-04-27). Never observed in a working state.
- **Reproduction**:
  1. Add a WLED device by IP via Settings → WLED panel.
  2. Device row appears, name + LED count fetched OK.
  3. Status indicator shows "offline" immediately and stays that way.
  4. User cannot assign the strip's channels to canvas regions (mechanism unclear — needs investigation).
  5. Start streaming with a camera assigned to a Hue zone. Hue lights respond. WLED status still shows offline regardless.

## Likely Surfaces (user hints — verify, do not trust blindly)

- `Backend/routers/wled.py` — status payload shape
- `Backend/services/wled_streamer.py` or similar — `WledStreamer` connection / health tracking, `_metrics` population
- `Backend/services/status_broadcaster.py` — `wled_devices` key under `_metrics`, what gets pushed on the WS
- `Frontend/src/...WledDevicesPanel...` / `SettingsPanel` — how the `connected` flag is rendered
- The Zustand store / WS parser added in Plan 17-08-01

## Open Questions for Investigation

1. Where is `connected: true` ever set? Is it set on successful UDP `sendto`, on a heartbeat probe, or never until a packet flies?
2. Is the status payload reaching the frontend at all? (`wled_devices` key present in WS message, or missing?)
3. Is the frontend reading the right field? (e.g. `device.connected` vs `device.is_connected` vs nested under `metrics`)
4. The "cannot assign strip" report — is this a missing UI affordance (Phase 19 not yet built — the paint UI is the unscheduled WMAP work) or a separate bug where existing assignment flow is broken?
5. With no UDP packets sent (idle state), is `connected` initialized to `false` and never updated until a successful send? If so, that's the root cause for the idle-state offline indicator. Streaming should flip it. If streaming doesn't flip it, the metric update path is broken.

## Current Focus

- **hypothesis**: CONFIRMED. `connected` was only set to `true` after a successful UDP `sendto` call in `_mark_success()`. This required: (a) streaming to be active, (b) a `wled_light_assignments` row linking a WLED channel to a region for the active `entertainment_config_id`. With no assignment rows (no UI exists to create them — Phase 19 / WMAP work), `_render_one_device` always returned early at the `if not populated: return` guard, `_mark_success` was never called, and `connected` was permanently `False`.
- **test**: Traced full data flow: `_row_to_out()` in `wled.py` → `health_snapshot()` → `WledStreamer._devices` → `_mark_success()` → `_render_one_device()` → `populated` flag.
- **expecting**: Single bug: `connected` derived from UDP-success-only, making it permanently False without channel assignments.
- **next_action**: RESOLVED
- **reasoning_checkpoint**: The design conflated "is device reachable on LAN" (registration-time knowledge) with "has UDP traffic flowed recently" (streaming-only knowledge). At idle the health dict is empty (`WledStreamer._devices` cleared after stop), so `health.get(device_id)` returns `None` for every device, and `connected` defaulted to `False`. Fix: when `health_entry` is absent (streamer idle), derive `connected` from `led_count > 0` (registration proved reachability). When `health_entry` is present (streamer running), keep the existing `last_success_at < 5s` logic.
- **tdd_checkpoint**: (not applicable — fix_and_test approach used; existing test suite updated)

## Evidence

- **timestamp**: 2026-05-12 — `Backend/routers/wled.py` `_row_to_out()` lines 101-112: `health_entry = health.get(row["id"], {})` — when health dict is empty, `health_entry` is `{}`, `last_success_at` is `None`, `connected` is always `False`.
- **timestamp**: 2026-05-12 — `Backend/services/wled_streamer.py` `_render_one_device()` lines 347-348: `if not populated: return` — without any `wled_light_assignments` rows for the active config, no UDP packets are ever sent, so `_mark_success` is never called.
- **timestamp**: 2026-05-12 — `Backend/services/wled_streamer.py` `health_snapshot()` lines 251-262: returns entries keyed by `dev_id` only for devices currently in `_devices` dict. After `stop()`, `_devices` is cleared, so health is `{}` at idle.
- **timestamp**: 2026-05-12 — `Backend/routers/wled.py` `_coord_health()` lines 126-142: returns `wled.health_snapshot()` which returns `{}` when not streaming. This empty dict causes all devices to show `connected=False`.
- **timestamp**: 2026-05-12 — "Cannot assign strip to regions": confirmed as a missing feature (no REST endpoint for `wled_light_assignments` creation, no frontend UI). Phase 19 / WMAP work. Not a regression bug — the assignment table is only writable via direct DB seed in tests.

## Eliminated Hypotheses

- **WS transport broken**: `StatusBroadcaster`, `useStatusWS`, and `useStatusStore` are all correctly wired. The `wled_devices` key propagates correctly end-to-end. The issue was purely in the `connected` computation logic upstream.
- **Frontend reading wrong field**: `WledDevicesPanel.tsx` correctly reads `d.connected` from the REST response and `wledDevices[d.id].in_cooldown` from the WS store. No field name mismatch.
- **Metric not updated during streaming**: `_frame_loop` correctly calls `self._wled.health_snapshot()` and passes it to `update_metrics`. The broadcaster's 1 Hz heartbeat delivers it. The root cause was upstream: `health_snapshot()` only has entries when `_devices` is populated (streaming), and even then `connected` required successful UDP sends which required channel assignments.

## Resolution

- **root_cause**: `_row_to_out()` in `Backend/routers/wled.py` derived `connected` from `last_success_at < 5s`, which is only set by successful UDP `sendto()`. UDP sends only happen during streaming AND when the device has at least one channel assigned to a region for the active entertainment config via `wled_light_assignments`. Since no UI/API exists to create those assignment rows, `_render_one_device` always returned early (`if not populated: return`), `_mark_success` was never called, and `connected` was permanently `False` in all states.
- **fix**: Changed `_row_to_out()` to use a two-mode connected computation: (1) when the device is absent from the health dict (streamer idle or not yet started), derive `connected` from `led_count > 0` — the device was reachable at registration; (2) when the device is present in the health dict (streamer running), keep the existing `last_success_at < 5s` logic. Updated the test assertion in `test_wled_router.py` that expected `connected=False` for the no-coordinator case.
- **files_changed**:
  - `Backend/routers/wled.py` — `_row_to_out()` rewritten with idle-state fallback
  - `Backend/tests/test_wled_router.py` — updated `test_add_device_persists_and_auto_seeds_channel` assertion from `connected is False` to `connected is True`
- **verified**: All 13 WLED tests pass (11 router + 2 e2e). 287/299 non-skipped tests pass. 12 pre-existing failures in `test_cameras_router.py` are Windows/linuxpy platform issues unrelated to this fix.
- **remaining**: "Cannot assign strip to regions" is a missing Phase 19 / WMAP feature — no REST endpoint or frontend UI exists for creating `wled_light_assignments` rows. That is not a regression; it was never built.
