# Phase 19: HA YAML Documentation - Context

**Gathered:** 2026-05-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship a single `docs/HOME_ASSISTANT.md` so users without an MQTT broker (or who want to verify the integration before enabling Phase 21 discovery) can wire HuePictureControl into Home Assistant entirely from paste-able YAML.

In scope:
1. **rest_command:** snippets for the seven `/api/ha/*` endpoints already shipped by Phase 18.
2. **REST `sensor:`** snippets that read `/api/ha/status` and surface the Phase 18 `HaStatusResponse` shape as HA entities.
3. **`input_select:`** snippets + companion automations so HA users can pick the active entertainment zone and camera from the HA UI.
4. **Doc-test** under `Backend/tests/` that parses fenced ```yaml blocks and asserts every `rest_command:` URL+method maps to an existing route on `routers.ha.router`.
5. **MQTT coexistence warning** so users don't mix this YAML doc with Phase 21 MQTT auto-discovery (would create duplicate entities — HA-DOCS-02).

Explicitly out of scope:
- MQTT auto-discovery itself (Phase 21).
- Per-WLED YAML entities — `wled_devices` array is not yet on `/api/ha/status` (Phase 20). YAML doc references "see Phase 21 MQTT for automatic per-WLED entities" and moves on.
- HPC web-UI changes — Phase 19 is documentation-only; no backend code changes beyond adding the doc-test.
- Authentication / per-caller authorization on HA endpoints (LAN trust boundary per CLAUDE.md and PROJECT.md).
- Outbound HPC → HA calls (HA → HPC direction only; no HA token storage).
- New HPC config plumbing for "recommended polling interval" — the doc just prescribes 10 s as the recommendation; users edit their own `scan_interval:` if they want different cadence.

</domain>

<decisions>
## Implementation Decisions

### Doc structure & entity coverage

- **D-01:** Two-tier doc structure. The file `docs/HOME_ASSISTANT.md` opens with a **Quick start** section (5 entities: `switch.huepicturecontrol_streaming`, `sensor.huepicturecontrol_state`, `sensor.huepicturecontrol_active_zone`, `select`-like `input_select.huepicturecontrol_zone`, and the `start`/`stop` rest_commands) and follows with an **Advanced — full parity with MQTT** section that adds the remaining 6 entities from the Phase 21 manifest (`binary_sensor.huepicturecontrol_bridge_paired`, `sensor.huepicturecontrol_fps`, `sensor.huepicturecontrol_latency`, `sensor.huepicturecontrol_active_camera`, `input_select.huepicturecontrol_camera`, `sensor.huepicturecontrol_last_error`). Beginners are productive in 5 minutes; power users get parity with what Phase 21 will emit, so switching paths is a clean rename-free swap.

- **D-02:** Per-WLED device entities (connected / last_error / cooldown) are **out of scope** for the YAML doc. Reasons: (a) Phase 20 hasn't added `wled_devices[]` to `/api/ha/status` yet, (b) even after Phase 20, manual N-instance YAML duplication per device is brittle, (c) auto-loop Jinja over arrays in HA template sensors is fragile. The doc includes one sentence: "Per-device WLED health entities are auto-generated when you enable Phase 21 MQTT auto-discovery — see *Migrating to MQTT* below."

- **D-03:** Entity naming convention: every entity in the YAML uses the `huepicturecontrol_` prefix on its `object_id` / friendly name → produces entity IDs like `switch.huepicturecontrol_streaming`, `sensor.huepicturecontrol_fps`, `input_select.huepicturecontrol_zone`. Rationale: matches the Phase 21 MQTT manifest's `object_id` prefix exactly (`huepicturecontrol_*` per `.planning/research/FEATURES.md` §1 discovery payload examples), so user automations referencing `switch.huepicturecontrol_streaming` keep working byte-for-byte when the user later migrates from YAML to MQTT.

### REST sensor pattern

- **D-04:** One parent REST sensor + N template sensors. The doc shows a single `sensor.huepicturecontrol_status` configured under `rest:` (modern HA REST integration, not legacy `sensor:` platform) that polls `GET /api/ha/status` and stores the full JSON in `json_attributes:`. Each per-field entity (FPS, latency, state, active zone, etc.) is a cheap `template:` sensor reading from `state_attr('sensor.huepicturecontrol_status', '<field>')`. One HTTP poll per cycle = minimal HPC backend load, atomic snapshot (all fields from same instant), no rate-limit risk on `/api/ha/status`.

- **D-05:** Recommended `scan_interval: 10` seconds in the doc YAML. Users may edit their own copy. No HPC-side config for this — the value lives entirely in the user's `configuration.yaml`. Doc calls out that users can drop to `scan_interval: 5` while debugging and bump to `scan_interval: 30` if they prefer minimal HA polling.

- **D-06:** Every template using a `HaStatusResponse` field MUST use defensive Jinja: `value_json.<field> | default('unknown')` for string fields, `value_json.<field> | default(0)` for numeric fields, `value_json.<field> | default(false)` for booleans. Required by success criterion #3 (HA-DOCS-01). Applies uniformly across the Quick start, Advanced, and Lovelace sections.

### Zone/camera selection UX

- **D-07:** `input_select.huepicturecontrol_zone` and `input_select.huepicturecontrol_camera` ship with **hardcoded** option lists that the user manually edits to match their setup. Example options use realistic placeholders (`TV-Bereich`, `Sofa`, `Küche` from the user's actual hardware) and the doc calls out: "Replace these names with the values from `GET /api/ha/zones` and `GET /api/ha/cameras`."

- **D-08:** Doc ships a companion **"refresh" `rest_command`** (`rest_command.hpc_zones_refresh` / `rest_command.hpc_cameras_refresh`) using `response_variable` to call `/api/ha/zones` / `/api/ha/cameras` and dump the current options to HA logs. Users run this manually whenever they add/remove zones or cameras to discover what to paste into their `input_select` options list. No auto-rebuild of the `input_select` itself — HA does not formally support dynamic option lists from YAML.

- **D-09:** Doc ships **one automation per selector** in the trigger-only direction (HA → HPC):
  - Trigger: `state_changed` on `input_select.huepicturecontrol_zone` (or `_camera`).
  - Condition: none.
  - Action: `service: rest_command.hpc_select_zone` (or `_camera`) with `data:` that maps the selected option name (friendly) to the corresponding ID. The mapping table lives inline in the automation's `data:` block as a Jinja `{% set zones = {'TV-Bereich': 'abc-uuid', ...} %}` — user edits this when their zones change. Same pattern as the option list maintenance in D-07.
  - **No reverse sync** (HA reflecting HPC-side ha_selected_config_id changes). Out of scope for v1.3 polish — would require a debounced state automation and a circular-update guard; Phase 21 MQTT solves this natively for users who care.

### Doc-test

- **D-10:** Test file location: `Backend/tests/test_ha_docs.py`. Runs under the existing `python -m pytest` command (CLAUDE.md autonomous testing checklist) — same pytest invocation as the existing 23 HA unit tests + e2e test from Phase 18. No new test infrastructure, no second CI invocation.

- **D-11:** Test strictness: **URL + HTTP method match only.** The test:
  1. Reads `docs/HOME_ASSISTANT.md`.
  2. Extracts every fenced ```yaml block and parses it (`yaml.safe_load`).
  3. For each `rest_command:` entry in the parsed YAML, pulls `url:` + `method:`.
  4. Strips the `http://{host}:{port}` prefix (doc uses a placeholder like `http://hpc.local:8000`); the test only inspects the path component.
  5. Asserts the `(method, path)` pair appears in `routers.ha.router.routes` (introspected via `route.path` and `route.methods`).
  6. Body schema, value_template field names, and `json_attributes:` paths are **NOT** verified — keeps the test focused on the brittle drift (renamed endpoints, removed routes) and lets example payloads evolve freely.

- **D-12:** Failure mode: fail loudly with a diff-style message. On mismatch:
  ```
  docs/HOME_ASSISTANT.md (yaml block starting line {N}):
    rest_command '{rest_command_name}' references {METHOD} {path}
    No matching route in routers.ha.router.
    Closest match: {METHOD'} {path'} (delta: {short diff})
  Either update the doc to reference the new route, or restore the missing route in routers/ha.py.
  ```
  Closest-match uses simple Levenshtein or set-of-segments comparison — implementation detail left to the planner.

### Extras & MQTT coexistence

- **D-13:** Include **one curated Lovelace `entities` card** YAML example (~15 lines) near the end of the doc. Card surfaces: `switch.huepicturecontrol_streaming`, `sensor.huepicturecontrol_state`, `input_select.huepicturecontrol_zone`, `sensor.huepicturecontrol_fps`. Gives users a "this works!" visual moment after pasting the integration; doc-test ignores it (no `rest_command:` inside). No additional Lovelace variants (glance, button, automation panel) — diminishing returns.

- **D-14:** **Skip automation examples** (sunset trigger, error notifications, etc.). Doc stays pure-plumbing reference + minimum-viable Lovelace card. Rationale: every automation example expands the surface the doc-test must reason about and locks in taste decisions; users who want automation patterns can search the wider HA community. The selector-sync automations from D-09 are the only automations that ship (they're load-bearing for the input_select UX, not illustrative).

- **D-15:** MQTT/YAML coexistence warning is **layered, three locations**:
  1. **Top-of-page admonition** (first content block under the title, before Table of Contents): a blockquote `> ⚠️ **Pick one path: YAML *or* MQTT, never both.** If you enable Phase 21 MQTT auto-discovery (`MQTT_BROKER_HOST` set) while these YAML snippets are also installed, every HuePictureControl entity will appear twice in Home Assistant. See *Migrating to MQTT* below if you want to switch.`
  2. **One-line reminder** at the top of each major YAML-emitting section (`## rest_command`, `## REST sensors`, `## input_select`): `> Reminder: do not combine these YAML blocks with MQTT auto-discovery — see warning at top.`
  3. **"Migrating to MQTT" appendix** at the bottom: numbered steps — (a) remove the `rest_command:`, `rest:`, `template:`, `input_select:` blocks added from this doc, (b) restart Home Assistant, (c) set `MQTT_BROKER_HOST` in HuePictureControl, (d) restart HuePictureControl. Notes that entity IDs are preserved (D-03) so existing automations keep working.

### Claude's Discretion

- **Doc layout / table of contents:** Writer's call (anchor link conventions, section ordering after Quick start vs. Advanced, sub-heading depth). Constraint: the three warning locations from D-15 must be findable by a reader who jumps in mid-page.
- **Example zone/camera names:** Use `TV-Bereich` (the actual zone name from the project) plus 1–2 plausible secondaries like `Sofa`, `Küche` for realism. Call out clearly that users must replace these.
- **Lovelace card type:** D-13 says "entities card" — writer may pick the exact `type:` (`entities`, `glance`, or `tile`) based on which renders best for the four entities listed. Document only one type; do not show variants.
- **Doc-test parser:** Library choice (`PyYAML` already in Backend/requirements.txt via FastAPI's transitive deps, or `ruamel.yaml` for comment-preservation). Use whatever is already imported in Backend/. No new requirement entries.
- **Closest-match algorithm in D-12:** Implementation detail. SequenceMatcher from stdlib `difflib` is sufficient — don't pull in Levenshtein-c or rapidfuzz.
- **HTTP host placeholder in YAML examples:** Use `http://hpc.local:8000` consistently (matches the Phase 18 18-CONTEXT.md §Specifics example). Call out once in a "Before you start" section: "Replace `hpc.local:8000` with your HuePictureControl host:port if different."
- **Doc-test failure on unparseable YAML:** Surface as a pytest assertion error pointing to the line of the offending block, with the raw `yaml.YAMLError` message included.
- **Per-section `> Reminder:` line wording (D-15.2):** Writer's call — keep it under one line each, link back to the top admonition.

### Folded Todos

None — `.planning/todos/` is empty.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roadmap & Project
- `.planning/ROADMAP.md` §Phase 19 — four success criteria for HA YAML Documentation (HA-DOCS-01, HA-DOCS-02), including the doc-test requirement on success criterion #4
- `.planning/PROJECT.md` §"Current Milestone: v1.3 Home Assistant Integration Polish" — confirms YAML doc is part of the polish goal
- `.planning/PROJECT.md` §Active (v1.3) — "HA YAML snippet documentation — rest_command:, sensor:, input_select: examples for the non-MQTT path"
- `.planning/PROJECT.md` §Constraints — "No auth: Web UI is unauthenticated — local network tool only" (applies to HA endpoints documented in this phase)
- `.planning/STATE.md` §"Current Position" — confirms Phase 19 is the next planned phase

### Prior Phase Contexts (must-read)
- `.planning/phases/18-home-assistant-control-endpoints/18-CONTEXT.md` — defines the seven `/api/ha/*` endpoints the doc must reference (D-01), the `HaStatusResponse` shape (D-09) that template sensors read fields from, the PUT-with-JSON-body selection convention (D-02), and the rejected "inline body on /start" pattern (D-03). The doc's `rest_command:` snippets MUST conform to this contract; the doc-test MUST verify against the route shapes locked here.

### Research artifacts (must-read for the manifest)
- `.planning/research/SUMMARY.md` §"Stack Additions" and §"Feature Scope (from FEATURES.md)" — confirms zero new backend deps for Phase 19; entity manifest table lists the 11 base entities the Advanced section mirrors
- `.planning/research/FEATURES.md` §"1. MQTT Auto-Discovery" — discovery payload examples define the `unique_id` / `object_id` patterns (`huepicturecontrol_*`) that D-03 keeps in sync between YAML and MQTT paths; entity manifest table is the source of D-01's 5+6 split
- `.planning/research/PITFALLS.md` — defensive Jinja patterns and HA template-sensor pitfalls that D-06 codifies

### Project conventions
- `CLAUDE.md` §"Home Assistant REST API (Inbound)" — HA → HPC direction only; user configures `rest_command:` in their `configuration.yaml`; this phase ships the canonical version of those snippets
- `CLAUDE.md` §"Alternatives Considered" — confirms `rest_command:` is the supported HA-side integration; doc reinforces this choice
- `CLAUDE.md` §"Autonomous Testing Checklist" — `python -m pytest` runs all backend tests including the new `test_ha_docs.py` (D-10)

### Backend Files (read-only reference — source of truth for doc-test)
- `Backend/routers/ha.py` — the seven routes (`POST /start`, `POST /stop`, `GET /status`, `PUT /zone`, `PUT /camera`, `GET /zones`, `GET /cameras`) the doc-test introspects. `HaStatusResponse` Pydantic model (lines 66–80) defines the field set every YAML template sensor reads. Do NOT modify in this phase — Phase 19 is doc + test only.
- `Backend/main.py` — confirms `app.include_router(ha.router)` wiring; no changes needed.
- `Backend/tests/test_ha_router.py` and `Backend/tests/test_ha_e2e.py` — existing 23+ HA tests; `test_ha_docs.py` (D-10) follows the same import + fixture style.

### Backend Files (new)
- `Backend/tests/test_ha_docs.py` — new doc-test per D-10/D-11/D-12.

### Documentation Files (new)
- `docs/HOME_ASSISTANT.md` — the deliverable. New `docs/` folder at repo root (does not exist yet — create as part of this phase).

### External Docs
- [Home Assistant REST integration docs](https://www.home-assistant.io/integrations/rest/) — `sensor:` with `json_attributes:` pattern referenced in D-04
- [Home Assistant `rest_command:` integration docs](https://www.home-assistant.io/integrations/rest_command/) — payload + method + response_variable conventions used in D-08
- [Home Assistant `input_select:` docs](https://www.home-assistant.io/integrations/input_select/) — confirms options must be static at config-load time; informs D-07 / D-08 manual-edit choice
- [Home Assistant `template:` sensor docs](https://www.home-assistant.io/integrations/template/) — `state_attr(...)` pattern used in D-04 per-field sensors

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Backend/routers/ha.py::router.routes` — FastAPI route objects with `.path` and `.methods` attributes. The doc-test (D-10/D-11) introspects this directly — no test fixtures, no new abstractions. Same pattern any FastAPI router exposes.
- `Backend/routers/ha.py::HaStatusResponse` — the locked Pydantic model whose field names every YAML template sensor (D-04, D-06) must reference. Reading the model definition is faster than reading the doc.
- `Backend/tests/test_ha_router.py` — existing pytest style for HA tests (fixtures, app construction with mocked coordinator). `test_ha_docs.py` follows the same import + fixture conventions.
- The 18-CONTEXT.md §Specifics block already contains a draft `rest_command:` snippet (illustrative, not shipped) — the doc-writer can lift its structure as the starting template.

### Established Patterns
- `python -m pytest` runs everything under `Backend/tests/` (CLAUDE.md). New tests slot in automatically — no `conftest.py` changes.
- Markdown documents live at repo root or under feature-specific subdirectories. There is no existing `docs/` folder — Phase 19 creates `docs/HOME_ASSISTANT.md` and establishes this convention.
- Pydantic models live in their owning router file (`routers/ha.py`) — no separate `models/ha.py`. Doc-test inspects models directly via import.

### Integration Points
- `docs/HOME_ASSISTANT.md` is read by humans, not the backend at runtime. Backend code change in this phase = zero (only the new test file).
- `Backend/tests/test_ha_docs.py` is read by pytest only — no `main.py` wiring.
- No frontend changes. No database changes.

</code_context>

<specifics>
## Specific Ideas

- **Realistic example values:** Use `TV-Bereich` as the primary example zone name (matches the user's actual hardware per `CLAUDE.md` §"Hardware" — "Entertainment config 'TV-Bereich' (6 channels)"). Secondaries: `Sofa`, `Küche`. Camera example uses `usb-046d:0825-front` or similar — a realistic stable-id shape.

- **Top-of-page warning wording (D-15.1):** First-person voice, blockquote with the ⚠️ emoji explicitly because HA's docs render emoji admonitions. Example exact phrasing: `> ⚠️ **Pick one path: YAML *or* MQTT, never both.** If you enable Phase 21 MQTT auto-discovery (\`MQTT_BROKER_HOST\` set on HuePictureControl) while these YAML snippets are also in your \`configuration.yaml\`, every HuePictureControl entity will appear twice in Home Assistant. See *Migrating to MQTT* at the bottom of this page if you want to switch.`

- **Doc-test "closest match" UX:** The diff string in D-12 should be readable on a terminal — keep it to one line per delta. Example: `docs/HOME_ASSISTANT.md (yaml block at line 142): rest_command 'hpc_zone' references PUT /api/ha/zones — closest match: PUT /api/ha/zone (extra trailing 's' in path).`

- **Selector-sync automation friendly-name → id mapping (D-09):** The inline Jinja `{% set zones = {...} %}` map is the user's manual edit. The doc must demonstrate this in a way that's obviously editable (use bold comments above the block: `# EDIT ME: map your zone display names to the zone_id values from /api/ha/zones`). Same for cameras.

- **D-13 Lovelace card type:** Pick `entities` (vertical list) over `glance` (horizontal tile row) — the four entities mix scalar sensors with controls (switch + input_select), which `entities` handles cleaner than `glance`.

- **Migration appendix tone (D-15.3):** Matter-of-fact numbered steps, no marketing language. Explicitly mentions: "Entity IDs are unchanged when you migrate — your existing automations keep working as long as you used the `huepicturecontrol_` prefix (which this doc does by default)."

</specifics>

<deferred>
## Deferred Ideas

- **Per-WLED YAML entities** — Surface via Phase 21 MQTT instead (per D-02). If/when Phase 20 lands `wled_devices[]` on `/api/ha/status`, a follow-up doc edit could add an appendix showing the manual N-instance template pattern, but it's not load-bearing for v1.3.
- **Reverse sync (HA input_select reflecting server-side `ha_selected_config_id` changes)** — Out of scope per D-09. Phase 21 MQTT solves this natively via the `state_topic` on the `select` entity.
- **Multiple Lovelace card variants** — Skipped per D-13. The single curated `entities` card is the one example that ships.
- **Sample automations (sunset trigger, motion-based start, error notifications)** — Skipped per D-14. Users can build these from the documented entity surface.
- **HPC-side "recommended polling interval" config plumbing** — User raised this mid-discussion; resolved by simply prescribing `scan_interval: 10` in the doc YAML (D-05). No backend setting added.
- **Auto-rebuild of `input_select` options via automation** — Considered and rejected (D-07/D-08): HA does not formally support dynamic option lists from YAML, and the `input_select.set_options` service call from automation is fragile in practice. Phase 21 MQTT `select` entity replaces this entirely.
- **OpenAPI export → YAML generator** — Considered as a "single source of truth" alternative to maintaining the YAML by hand + doc-test. Rejected because the YAML's value is partly in the *commentary* (warnings, example values, defensive Jinja patterns) which an autogen can't carry. Doc-test guarantees the URL+method invariant; that's the right bar.

### Reviewed Todos (not folded)

None — `.planning/todos/` was empty at the time of this discussion.

</deferred>

---

*Phase: 19-ha-yaml-documentation*
*Context gathered: 2026-05-12*
