# Phase 19: HA YAML Documentation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-12
**Phase:** 19-ha-yaml-documentation
**Areas discussed:** Entity coverage & scope, REST sensor strategy + selection UX, Doc-test scope & location, Extras + MQTT coexistence warning

---

## Gray Area Selection

| Area | Selected |
|------|----------|
| Entity coverage & scope | ✓ |
| REST sensor strategy + selection UX | ✓ |
| Doc-test scope & location | ✓ |
| Extras + MQTT coexistence warning | ✓ |

**User's choice:** All four areas selected for discussion.

---

## Entity coverage & scope

### Q1: What entity coverage should docs/HOME_ASSISTANT.md ship?

| Option | Description | Selected |
|--------|-------------|----------|
| Two-tier: Quick start + Advanced | 5-entity quick start + Advanced section adding the other 6 base entities. Beginners productive in 5 min; power users get parity with Phase 21. | ✓ |
| Full parity only (all 11 base entities) | One section, all 11 entities matching Phase 21 MQTT manifest. Longer but switching to MQTT is a byte-for-byte swap. | |
| Minimal kit only (5 essential entities) | Just streaming switch, state, active zone, selected zone select, start/stop. Lowest cognitive load; weak MQTT migration story. | |

**User's choice:** Two-tier: Quick start + Advanced.
**Notes:** Beginners and power users both served. Maps to D-01.

### Q2: How should per-WLED device entities appear in the YAML doc?

| Option | Description | Selected |
|--------|-------------|----------|
| Out of scope for YAML doc | Phase 20 hasn't shipped wled_devices array yet; manual N-instance YAML is brittle. Mention Phase 21 MQTT and move on. | ✓ |
| Appendix snippet only (template, user adapts) | One illustrative block at the bottom, user manually duplicates per device. | |
| First-class entities in Advanced section | Jinja for-loop over wled_devices[] — brittle, high footgun risk. | |

**User's choice:** Out of scope for YAML doc.
**Notes:** Deferred to Phase 21 MQTT path. Maps to D-02.

### Q3: What entity naming convention should the YAML snippets use?

| Option | Description | Selected |
|--------|-------------|----------|
| Prefix every entity with 'huepicturecontrol_' | switch.huepicturecontrol_streaming etc. Matches Phase 21 MQTT manifest's object_id; preserves entity_id when migrating. | ✓ |
| Short 'hpc_' prefix | switch.hpc_streaming. Less typing; collision risk; inconsistent with Phase 21 manifest. | |
| No prefix, let HA generate | switch.streaming etc. Cleanest IDs; high collision risk on busy HA instances. | |

**User's choice:** Prefix every entity with 'huepicturecontrol_'.
**Notes:** Aligns YAML path with future MQTT path for entity_id stability. Maps to D-03.

---

## REST sensor strategy + selection UX

### Q1: How should REST sensors read /api/ha/status — one poll or many?

| Option | Description | Selected |
|--------|-------------|----------|
| One REST sensor + N template sensors | Single sensor.huepicturecontrol_status polls /api/ha/status, exposes JSON via json_attributes. Per-field entities are cheap template sensors. | ✓ |
| Many small REST sensors (one per field) | 11 separate REST sensors hitting the same endpoint. Wasteful; fields can drift apart. | |
| Mixed: REST for fast-changing, command_response for slow | Use REST sensor for fps/latency/state, command_response_variable script for friendly names. Cleaner separation, doubles doc length. | |

**User's choice:** One REST sensor + N template sensors.
**Notes:** Atomic snapshot, minimal backend load. Maps to D-04.

### Q2: What polling interval should the doc recommend?

| Option | Description | Selected |
|--------|-------------|----------|
| 10 seconds | Ambient lighting telemetry cadence; negligible HPC load. Standard HA REST integration default. | ✓ (after clarification) |
| 30 seconds | More conservative; slight HA dashboard lag when toggling streaming. | |
| 5 seconds | Snappier dashboards; double HTTP load (still trivial). Useful while debugging. | |

**User's choice:** Initially "it should be configurable in the hpc settings" (free text); clarified to "set it to 10 seconds then" after the assistant explained that the REST sensor's scan_interval is a static HA-side YAML value.
**Notes:** No HPC-side polling-rate config plumbing — the doc just prescribes 10 s in the example YAML and users edit their own. Maps to D-05. The "configurable" idea is captured in §Deferred Ideas of CONTEXT.md.

### Q3: How should the zone/camera input_select options be populated?

| Option | Description | Selected |
|--------|-------------|----------|
| Hardcoded options + 'refresh' rest_command | input_select options edited by user manually; companion refresh script using command_response_variable on /api/ha/zones logs current options to HA. | ✓ |
| Fully auto-populated via automation + rest_command | Dynamically rebuild options on HA start. Fragile — HA doesn't formally support dynamic input_select options from YAML. | |
| Just show /api/ha/zones; user wires their own UX | Document the endpoint only, punt UX to the user. Weak product story. | |

**User's choice:** Hardcoded options + 'refresh' rest_command.
**Notes:** Honest about manual maintenance; no flaky auto-sync. Maps to D-07 + D-08.

### Q4: How should HA's input_select changes propagate to HPC?

| Option | Description | Selected |
|--------|-------------|----------|
| Automation in the doc with explicit trigger | State-change trigger on input_select fires rest_command.hpc_select_zone with zone_id from selected option. Standard HA pattern. | ✓ |
| Only document the rest_command, no auto-sync | User figures out triggering. Breaks 'paste and go' promise. | |
| Two-way sync: input_select reflects HPC's current ha_selected_config_id too | Plus reverse automation to update input_select when server changes. Solves edge case; circular-update risk. | |

**User's choice:** Automation in the doc with explicit trigger.
**Notes:** HA → HPC direction only. Reverse sync deferred (Phase 21 MQTT handles it natively). Maps to D-09.

---

## Doc-test scope & location

### Q1: Where should the doc-test live?

| Option | Description | Selected |
|--------|-------------|----------|
| Backend/tests/test_ha_docs.py | Alongside existing HA pytest tests; runs in standard `python -m pytest` flow. Single CI signal. | ✓ |
| Dedicated tests/docs/ folder at repo root | Cleaner mental model; adds a second pytest invocation. | |
| Standalone Python script + Makefile target | Decoupled from pytest; doesn't run in autonomous-testing checklist. Worst spot for must-verify test. | |

**User's choice:** Backend/tests/test_ha_docs.py.
**Notes:** Reuses existing pytest infrastructure. Maps to D-10.

### Q2: How strict should the doc-test be when parsing fenced ```yaml blocks?

| Option | Description | Selected |
|--------|-------------|----------|
| URL + HTTP method match | Parse rest_command url+method, strip http://{host} prefix, assert (method, path) appears in routers.ha.router.routes. Body schema NOT checked. | ✓ |
| URL + method + body schema match | Also assert payload keys match the Pydantic request model. More test code; false positives on illustrative payloads. | |
| URL + method + sensor json paths match | Also walk every value_template / json_attributes. 200-line Jinja parser; high blast radius. | |

**User's choice:** URL + HTTP method match.
**Notes:** Focuses on the brittle drift (renamed/removed routes); lets examples evolve freely. Maps to D-11.

### Q3: When the doc-test detects drift, what should the failure mode be?

| Option | Description | Selected |
|--------|-------------|----------|
| Fail loudly with diff | pytest assert with closest-match hint. Forces immediate reconciliation. | ✓ |
| Soft warning + still pass | pytest.warns(); test logs drift but CI stays green. Will be ignored. | |
| Fail loudly + suggest exact diff to fix | Plus unified diff suggesting YAML edit. Nice ergonomics; doubles test code. | |

**User's choice:** Fail loudly with diff.
**Notes:** Closest-match hint is usually enough; full diff generator is overbuild. Maps to D-12.

---

## Extras + MQTT coexistence warning

### Q1: Should the doc include a sample Lovelace dashboard card?

| Option | Description | Selected |
|--------|-------------|----------|
| One curated card example | Single entities-card YAML, ~15 lines. Doc-test ignores it. | ✓ |
| Skip Lovelace entirely | Doc is plumbing-only. Less satisfying first-run experience. | |
| Multiple cards (entities + glance + button + automation panel) | 3-4 variants. Diminishing returns; higher maintenance. | |

**User's choice:** One curated card example.
**Notes:** Visual 'this works!' moment after pasting. Maps to D-13.

### Q2: Should the doc include sample automations?

| Option | Description | Selected |
|--------|-------------|----------|
| Two practical examples | Sunset trigger + error notify. ~25 lines total. Reinforces API surface. | |
| Skip automations entirely | Pure plumbing reference. No automation taste decisions. | ✓ |
| Five+ examples covering common patterns | Comprehensive; bloats the doc. | |

**User's choice:** Skip automations entirely.
**Notes:** The selector-sync automations from D-09 ship because they're load-bearing for input_select UX, not illustrative. Maps to D-14.

### Q3: How prominent should the MQTT/YAML coexistence warning be?

| Option | Description | Selected |
|--------|-------------|----------|
| Top-of-page admonition + per-section reminder + Migration appendix | Three locations: top banner, section reminders, migration appendix. Catches skimmers and deep-linkers. | ✓ |
| Top-of-page banner only | Single admonition at the top. Users who skip the intro miss it. | |
| Per-section callouts only | Inline warnings without top banner. Loses 'this is the first thing you should know' framing. | |

**User's choice:** Top-of-page admonition + per-section reminder + Migration appendix.
**Notes:** Layered defense against HA-DOCS-02's duplicate-entity failure mode. Maps to D-15.

---

## Claude's Discretion

The following decisions were left to Claude / the doc-writer:

- Exact Markdown table of contents structure and anchor link conventions.
- Exact placeholder zone/camera names beyond "TV-Bereich" (the user's actual zone).
- Exact Lovelace card `type:` field (constrained to `entities` per D-13 / §Specifics).
- YAML parser library choice for the doc-test (use whatever's already in Backend/ deps).
- Closest-match string-similarity algorithm in the doc-test failure message (stdlib `difflib.SequenceMatcher` recommended).
- HTTP host placeholder string in YAML examples (`http://hpc.local:8000` recommended in §Specifics).

---

## Deferred Ideas

Captured in CONTEXT.md §Deferred. Highlights:

- Per-WLED YAML entities (Phase 21 MQTT handles instead).
- Reverse sync of input_select from HPC-side state (Phase 21 MQTT handles).
- Multiple Lovelace card variants (skipped per D-13).
- Sample automations beyond the load-bearing selector sync (skipped per D-14).
- HPC-side recommended-polling-interval config plumbing (raised mid-discussion; resolved by simply prescribing `scan_interval: 10` in the example YAML).
- Auto-rebuild of input_select options via automation (rejected — HA doesn't formally support dynamic options from YAML).
- OpenAPI → YAML autogen as single source of truth (rejected — doc's value is partly in the commentary, which autogen can't carry).
