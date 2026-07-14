---
phase: quick-260714-pzk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - Backend/services/wled_streamer.py
  - Backend/tests/test_wled_streamer.py
  - Frontend/src/components/Settings/BrightnessCutoffControl.tsx
  - Frontend/src/components/Settings/BrightnessCutoffControl.test.tsx
autonomous: true
requirements: [QUICK-260714-pzk]

must_haves:
  truths:
    - "Setting brightness_cutoff_threshold to any value has NO effect on WledStreamer output — WLED always renders its actual computed gradient color"
    - "Hue streaming keeps applying the brightness cutoff unchanged (streaming_service.py untouched)"
    - "The Settings UI copy makes clear the cutoff is Hue-only and does not affect WLED"
  artifacts:
    - path: "Backend/services/wled_streamer.py"
      provides: "WLED render path with no brightness-cutoff gating"
    - path: "Backend/tests/test_wled_streamer.py"
      provides: "Tests proving cutoff never affects WLED output"
    - path: "Frontend/src/components/Settings/BrightnessCutoffControl.tsx"
      provides: "Hue-only clarification in the description copy"
  key_links:
    - from: "Backend/services/wled_streamer.py::_render_one_device"
      to: "colors[clip_lo:clip_hi] assignment"
      via: "slice_arr flows through unmodified (no luma gating)"
      pattern: "colors\\[clip_lo:clip_hi\\]"
---

<objective>
Scope the global `brightness_cutoff_threshold` setting to Hue devices only. Today both the Hue sink (`streaming_service.py`) and the WLED sink (`wled_streamer.py`) independently read and apply the cutoff. The user wants only Hue to gate on it; WLED must always render its actual computed color.

Purpose: WLED devices should not go dark for low-luma regions — the cutoff is a Hue-specific behavior.
Output: WLED render path with the cutoff removed, tests proving the new invariant, and clarified UI copy.
</objective>

<execution_context>
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/workflows/execute-plan.md
@C:/Users/Lukas/IdeaProjects/HuePictureControl/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@CLAUDE.md

Bug is fully diagnosed. Exact locations in `Backend/services/wled_streamer.py::_render_one_device`:
- Lines ~351-363: "quick-task 260516-kra: per-frame read of the global brightness cutoff" block that reads `self._app_state.brightness_cutoff_threshold` into `threshold`.
- Lines ~394-411: "quick-task 260516-kra: per-channel brightness gating" block — `if threshold > 0.0:` computes mean Rec.709 luma of the source gradient and, when below threshold, replaces `slice_arr` with `np.zeros((range_len, 3), dtype=np.uint8)`.

Both blocks must be deleted so `slice_arr` (from the resample/broadcast logic above) flows straight into `colors[clip_lo:clip_hi] = ...` unchanged.

DO NOT touch: `streaming_service.py` (Hue cutoff is correct and stays), `streaming_coordinator.py` sink wiring (Hue still needs `_app_state`), `routers/settings.py`, or any `saturation_boost`/`color_vibrancy` code.

Note on `_app_state`: after removal, `_app_state` may become unused in `wled_streamer.py`. It is still set by the coordinator as harmless dead plumbing — leaving it is fine. Do not remove the coordinator wiring. Optionally remove only the now-dead local reference inside this file if trivial; do not over-scope.

The three tests to rewrite live at the bottom of `Backend/tests/test_wled_streamer.py` (lines ~399-499), under the "quick-task 260516-kra: WLED brightness-cutoff gating" section. Existing gradient fixtures: dark `[25,25,25]` (luma ≈ 0.098) and bright `[204,204,204]` (luma ≈ 0.8). Loopback listener uses `udp_listener(port=LOOPBACK_PORT)` with `WledStreamer(udp_port=LOOPBACK_PORT)`. Packet body starts at byte offset 2 (DRGB: `0x02`, timeout `0x02`).
</context>

<tasks>

<task type="auto">
  <name>Task 1: Remove brightness-cutoff gating from WledStreamer and rewrite its cutoff tests</name>
  <files>Backend/services/wled_streamer.py, Backend/tests/test_wled_streamer.py</files>
  <action>
In `Backend/services/wled_streamer.py`, inside `_render_one_device`:
1. Delete the threshold-read block (~lines 351-363): the comment "quick-task 260516-kra: per-frame read of the global brightness cutoff" through the `threshold = 0.0` except fallback, including the `app_state = getattr(...)` read.
2. Delete the gating block (~lines 394-411): the comment "quick-task 260516-kra: per-channel brightness gating" through the `slice_arr = np.zeros((range_len, 3), dtype=np.uint8)` line and its `if threshold > 0.0:` / `if luma < threshold:` wrappers.
3. Leave `slice_arr` (from the `if src_n == range_len / elif src_n == 1 / else resample` block) flowing directly into the `clip_lo`/`clip_hi` intersect logic and `colors[clip_lo:clip_hi] = ...` assignment — unchanged.
Do NOT touch the coordinator's `_app_state` wiring. If `_app_state` is now referenced nowhere else in this file, leaving the coordinator's assignment as harmless dead plumbing is acceptable — do not refactor further.

In `Backend/tests/test_wled_streamer.py`, rewrite the three cutoff tests (the "quick-task 260516-kra: WLED brightness-cutoff gating" section, lines ~399-499) to prove the NEW invariant: `brightness_cutoff_threshold` set to any value has NO effect on WLED output.
- `test_render_zero_threshold_no_change`: keep or repurpose — assert a low-luma `[25,25,25]` gradient renders its real triplets with threshold=0.0.
- `test_render_above_threshold_zeros_led_slice`: rewrite to assert that with `brightness_cutoff_threshold=0.5` (or 1.0) set on `_app_state`, a below-threshold `[76,76,76]` (or `[25,25,25]`) gradient still renders its real (NON-zeroed) triplets in the packet body.
- `test_render_above_threshold_only_zeros_below_threshold_channels`: rewrite the mixed dark/bright device to assert NEITHER channel is zeroed — dark LEDs `[0..4]` carry `[25,25,25]` and bright LEDs `[5..9]` carry `[204,204,204]`, regardless of a high threshold.
Update the section header comment to describe the new "cutoff never affects WLED" contract. Consolidating into fewer tests is acceptable as long as the invariant is proven across threshold values 0.0 / 0.5 / 1.0.
  </action>
  <verify>
    <automated>source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_streamer.py -q</automated>
  </verify>
  <done>WledStreamer has no threshold read or luma-gating code; all tests in test_wled_streamer.py pass, and the rewritten tests prove a high threshold does not zero any WLED LEDs.</done>
</task>

<task type="auto">
  <name>Task 2: Clarify Hue-only scope in the brightness cutoff UI copy</name>
  <files>Frontend/src/components/Settings/BrightnessCutoffControl.tsx, Frontend/src/components/Settings/BrightnessCutoffControl.test.tsx</files>
  <action>
In `BrightnessCutoffControl.tsx`, update the description paragraph (line ~113, currently "Lights below this brightness will turn off.") to clarify Hue-only scope, e.g. "Lights below this brightness will turn off. Hue only — does not affect WLED." Also update the leading file comment block (lines 1-9) which currently says "WLED writes (0,0,0) to those LEDs" — correct it to state the cutoff applies to Hue only and no longer affects WLED.
In `BrightnessCutoffControl.test.tsx`, check for any assertion matching the description copy. The current tests (mount GET, loaded value, slider PUT, error caption) do NOT assert on the description text, so no test change is likely needed — but verify and update any text-matching assertion if present so the suite stays green.
  </action>
  <verify>
    <automated>cd Frontend && npx vitest run src/components/Settings/BrightnessCutoffControl.test.tsx</automated>
  </verify>
  <done>UI description states the cutoff is Hue-only and does not affect WLED; BrightnessCutoffControl tests pass.</done>
</task>

</tasks>

<verification>
- `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` — all backend tests pass (167+)
- `cd Frontend && npx vitest run` — all frontend tests pass (30+)
- Grep confirms no remaining `brightness_cutoff_threshold` or `threshold`-based luma gating in `wled_streamer.py`
- `streaming_service.py` diff is empty (Hue behavior untouched)
</verification>

<success_criteria>
- WledStreamer never applies the brightness cutoff — colors always render as computed regardless of `brightness_cutoff_threshold`
- Hue sink (`streaming_service.py`) is byte-for-byte unchanged
- Rewritten WLED tests assert the no-effect invariant across threshold 0.0 / 0.5 / 1.0
- UI copy communicates the Hue-only scope
- Full backend and frontend test suites pass
</success_criteria>

<output>
After completion, create `.planning/quick/260714-pzk-scope-brightness-cutoff-threshold-to-hue/260714-pzk-SUMMARY.md`
</output>
