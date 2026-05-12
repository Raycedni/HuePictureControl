# Feature Landscape — v1.3 Home Assistant Integration Polish

**Domain:** Inbound Home Assistant integration surface for an on-LAN FastAPI service (HuePictureControl) that already exposes seven HA REST endpoints under `/api/ha/*` and a `/ws/status` WebSocket for its web UI.
**Researched:** 2026-05-12
**Confidence:** HIGH (all entity shapes verified against current `home-assistant.io` integration pages; existing code paths verified by direct read of `Backend/routers/ha.py` and `Backend/services/status_broadcaster.py`).

---

## Executive Recommendation

| Feature | Verdict | Why |
|---|---|---|
| MQTT auto-discovery | **TABLE STAKES** — build | Removes all YAML for the typical HA user. Standard pattern (WLED, Zigbee2MQTT, ESPHome, Tasmota all use it). |
| HA YAML snippet docs | **TABLE STAKES** — build | Cheap (one Markdown file). Required fallback when no MQTT broker is available; also the canonical reference for what MQTT discovery emits. |
| WebSocket push for HA status | **ANTI-FEATURE** — drop | HA cannot consume external WebSocket feeds from YAML. The only consumer for `/ws/status` is our own web UI, which already has it. No latency win on the HA side. |
| Per-device WLED health in `/api/ha/status` | **DIFFERENTIATOR** — build (lightly) | Already in `broadcaster._metrics["wled_devices"]`. Surface a curated subset as an additive D-09 field plus one MQTT sensor entity per WLED device. Don't model it as a separate HA device — keep all entities under one HuePictureControl device. |

**Phase rationale for the roadmap:** MQTT auto-discovery is the centerpiece; YAML docs trail it (and are partly auto-generatable from the same entity manifest); WLED health is a small additive surface that piggybacks on the MQTT discovery work. WebSocket push is a clean cut — call it Out of Scope in `PROJECT.md` and reclaim the budget.

---

## 1. MQTT Auto-Discovery

### Classification: TABLE STAKES (build)

Users running Home Assistant with the official Mosquitto broker add-on expect new local-LAN services to surface as entities **without editing `configuration.yaml`**. Every comparable project ships this: WLED's HA integration uses local-push, but third-party MQTT-first projects (Zigbee2MQTT, Tasmota, ESPHome MQTT mode, Theengs OpenMQTTGateway) all rely on `homeassistant/<component>/<id>/config` retained discovery messages. ([Home Assistant - MQTT integration](https://www.home-assistant.io/integrations/mqtt/))

### Recommended entity manifest

One HuePictureControl instance → **one HA device** with all entities grouped under a shared `device.identifiers`. This is the [device-based discovery pattern documented as the recommended approach for multi-entity products](https://www.home-assistant.io/integrations/mqtt/).

| Entity | Type | Maps to | Notes |
|---|---|---|---|
| `Streaming` | **switch** | `POST /api/ha/start` / `POST /api/ha/stop` | The primary on/off control. State reflects `_metrics["state"] in ("streaming", "starting", "reconnecting")`. |
| `State` | **sensor** | `_metrics["state"]` raw string | Diagnostic enum: `idle/starting/streaming/stopping/error/reconnecting`. Lets users build automations on `error` transition. |
| `Bridge paired` | **binary_sensor** | `bridge_paired` from D-09 | `device_class: connectivity`. Trivial — already in payload. |
| `FPS` | **sensor** | `_metrics["fps"]` | `state_class: measurement`, `unit_of_measurement: fps`, `entity_category: diagnostic`. |
| `Latency` | **sensor** | `_metrics["latency_ms"]` | `state_class: measurement`, `unit_of_measurement: ms`, `entity_category: diagnostic`. |
| `Active zone` | **sensor** | `active_config_name` (friendly) | Plain text. Shows what is streaming right now, NULL when idle. |
| `Active camera` | **sensor** | `active_camera_name` | Plain text. Same. |
| `Selected zone` | **select** | `GET/PUT /api/ha/zone` over MQTT command_topic | Options list = `/api/ha/zones` snapshot. Republished whenever zone discovery changes. Stays editable while streaming (matches D-06 semantics). |
| `Selected camera` | **select** | `GET/PUT /api/ha/camera` over MQTT command_topic | Options list = `/api/ha/cameras` snapshot. |
| `Last error` | **sensor** | `_metrics.get("error")` | `entity_category: diagnostic`. Empty string when no error. |
| `WLED <device-name>` | **binary_sensor** | per-device entry of `_metrics["wled_devices"]` | `device_class: connectivity`. One entity per registered WLED device. See §4. |

11 entities + N WLED binary sensors. Comparable to WLED's own HA integration (≈23 entities for a typical strip — [WLED HA docs](https://www.home-assistant.io/integrations/wled/)) so the surface is in the same league as the ecosystem norm.

### Discovery topic structure

Per the current [MQTT integration spec](https://www.home-assistant.io/integrations/mqtt/) the topic format is:

```
<discovery_prefix>/<component>/<node_id>/<object_id>/config
```

- `<discovery_prefix>` — defaults to `homeassistant`, configurable in HA's MQTT integration. **Read this from a config field in HPC**, don't hardcode.
- `<component>` — `switch`, `sensor`, `binary_sensor`, `select`.
- `<node_id>` — `hpc_<instance_id>` where `instance_id` is a stable per-install UUID stored in HPC's SQLite. **Critical for name-collision avoidance** (see Pitfalls).
- `<object_id>` — short hyphenated entity slug (`streaming`, `fps`, `selected-zone`).
- Both `<node_id>` and `<object_id>` must match `[a-zA-Z0-9_-]`.

### Example discovery payload (switch)

```json
{
  "name": "Streaming",
  "unique_id": "hpc_7f9a3b2c_streaming",
  "object_id": "huepicturecontrol_streaming",
  "state_topic":   "hpc/7f9a3b2c/status",
  "value_template": "{{ 'ON' if value_json.state in ['streaming','starting','reconnecting'] else 'OFF' }}",
  "command_topic": "hpc/7f9a3b2c/command/streaming",
  "payload_on":  "ON",
  "payload_off": "OFF",
  "availability": [
    { "topic": "hpc/7f9a3b2c/availability" }
  ],
  "device": {
    "identifiers": ["hpc_7f9a3b2c"],
    "name":         "HuePictureControl",
    "manufacturer": "HuePictureControl",
    "model":        "HPC v1.3",
    "sw_version":   "1.3.0",
    "configuration_url": "http://hpc.local:8000/"
  }
}
```

### Example discovery payload (select — Selected zone)

```json
{
  "name": "Selected zone",
  "unique_id": "hpc_7f9a3b2c_selected_zone",
  "state_topic":   "hpc/7f9a3b2c/status",
  "value_template": "{{ value_json.ha_selected_config_name or 'none' }}",
  "command_topic": "hpc/7f9a3b2c/command/zone",
  "options": ["TV-Bereich", "Sofa", "Küche"],
  "availability": [{ "topic": "hpc/7f9a3b2c/availability" }],
  "device": { "identifiers": ["hpc_7f9a3b2c"] }
}
```

The `options` list is the **set of `name` fields** from `GET /api/ha/zones`. The backend MQTT subscriber translates the inbound friendly name → `zone_id` server-side before calling the existing `PUT /api/ha/zone` handler. (Alternative: emit `command_template` that picks up an internal id; friendly-name routing is simpler for the user-facing select but requires the backend to maintain a name→id map. **Recommend friendly name** — matches how HA users think.)

### Example discovery payload (sensor — FPS, JSON-attribute style)

```json
{
  "name": "FPS",
  "unique_id": "hpc_7f9a3b2c_fps",
  "state_topic":   "hpc/7f9a3b2c/status",
  "value_template": "{{ value_json.fps }}",
  "unit_of_measurement": "fps",
  "state_class": "measurement",
  "entity_category": "diagnostic",
  "availability": [{ "topic": "hpc/7f9a3b2c/availability" }],
  "device": { "identifiers": ["hpc_7f9a3b2c"] }
}
```

**Key trick:** every entity subscribes to the **same** `hpc/<id>/status` JSON state topic and extracts its own field via `value_template`. One publish, eleven entity updates. The payload IS the existing `HaStatusResponse` JSON — zero new schema work for the per-entity stream.

### Retained messages, availability, LWT

| Aspect | Recommendation | Source |
|---|---|---|
| Discovery messages | **retained** (`retain=true`, QoS 1) | HA replays them when MQTT integration restarts; entities don't vanish until HPC explicitly clears them. ([HA MQTT docs - retained discovery messages](https://www.home-assistant.io/integrations/mqtt/)) |
| Status topic publishes | **retained** (`retain=true`, QoS 0) | HA gets the last known state immediately on reconnect; otherwise entities show `unknown` until the next state push. |
| Availability topic | **retained** (`retain=true`, QoS 1) with LWT | Single `hpc/<id>/availability` topic, payload `online`/`offline`. Configure paho-mqtt `will_set("hpc/<id>/availability", "offline", retain=True)` so an HPC crash flips entities to `unavailable`. ([HA MQTT availability docs](https://www.home-assistant.io/integrations/mqtt/)) |
| `availability_mode` | omit (default `latest` is fine) | Single availability topic doesn't need aggregation. |
| Birth handling | Subscribe to `homeassistant/status`. On `online` payload, **re-publish the full discovery manifest** | Required so entities reappear when HA restarts. Standard pattern documented at [HA MQTT birth/will](https://www.home-assistant.io/integrations/mqtt/). |

### `unique_id` stability

Generate a per-install UUID at first boot, store in a new `instance_config` row in SQLite (same pattern as `bridge_config`), reuse forever. The `unique_id` for each entity = `hpc_<install_uuid>_<entity_slug>`. **This solves both problems**: stability across restarts (UUID never changes) AND collision avoidance when two HPC instances share a broker (different UUIDs).

The `device.identifiers` field also uses `hpc_<install_uuid>`. HA groups all entities under one device card.

### Name collisions across multiple HPC instances

| Risk | Mitigation |
|---|---|
| Two HPC installs publishing `homeassistant/switch/hpc/streaming/config` | Use `<node_id>` = `hpc_<install_uuid>` so topics never collide. |
| Both HPC instances appear as "HuePictureControl" in HA UI | `device.name` = `"HuePictureControl ({{ host }})"` where `{{ host }}` is the hostname. Optional config knob for users to override. |
| User intentionally points two HPC instances at one HA → wants distinguishable names | Config field `ha_display_name` in `instance_config` table; defaults to hostname; rendered into `device.name` and entity prefixes. |

### Inbound command routing

The MQTT subscriber background task handles four command topics:

| Command topic | Action |
|---|---|
| `hpc/<id>/command/streaming` payload `ON`/`OFF` | Internally calls the existing `ha_start()` / `ha_stop()` handler functions. |
| `hpc/<id>/command/zone` payload `<zone friendly name>` | Look up zone_id by name from cached `/api/ha/zones`, call `ha_put_zone()`. |
| `hpc/<id>/command/camera` payload `<camera friendly name>` | Same pattern: name → stable_id → `ha_put_camera()`. |
| `homeassistant/status` payload `online` | Re-publish discovery manifest. |

**Critical:** the MQTT command handlers reuse the existing Pydantic request handlers from `routers/ha.py` — same validation, same DB writes, same HTTP-error-equivalent logging. The MQTT layer is a thin codec, not a parallel control plane.

### Where the publishes happen

| Trigger | What is published |
|---|---|
| HPC startup | Full discovery manifest (11+ retained config messages), then `availability=online`, then initial status. |
| Every `broadcaster.push_state()` | One status publish (the existing `HaStatusResponse` JSON to `hpc/<id>/status`, retained). |
| 1 Hz heartbeat (piggyback on existing `StatusBroadcaster._heartbeat_loop`) | One status publish. |
| `/api/ha/zones` or `/api/ha/cameras` list changes | Re-publish only the affected `select` entity's config message (new `options` list). |
| HPC shutdown (graceful) | Publish `availability=offline`, then disconnect cleanly. Crash path is covered by LWT. |
| `homeassistant/status` → `online` | Full discovery + status re-publish. |

The publish rate is comfortable: roughly one ~400-byte JSON message per second. Mosquitto handles this without measurable load.

### Library choice

| Option | Verdict | Why |
|---|---|---|
| `paho-mqtt` (stdlib-style sync) | Acceptable but awkward | Sync API; requires `asyncio.to_thread` wrapping. Workable but ugly in a fully-async codebase. |
| **`aiomqtt`** (≥2.x, MIT, by empicano) | **Recommended** | Native asyncio context-manager API. Maps cleanly onto FastAPI lifespan. Active maintenance (verified at [aiomqtt on PyPI](https://pypi.org/project/aiomqtt/)). |
| `gmqtt` via `fastapi-mqtt` | Acceptable alternative | FastAPI-specific wrapper. Adds an opinionated dependency layer for a single connection — overkill for one publisher. |
| `ha-mqtt-discoverable` | **Reject** | Adds an opinionated framework on top of paho. Not needed when the discovery payloads are <50 lines of JSON per entity type. Consistent with this codebase's "no third-party Hue wrapper" stance. |

**Recommend `aiomqtt>=2.0`** wired as a singleton in `app.state.mqtt_client`, managed in the FastAPI lifespan. One reconnecting context manager, one background task that subscribes to inbound topics. Optional dependency: feature is disabled if `MQTT_BROKER_HOST` env var is unset.

### MQTT broker discovery

| Approach | Recommendation |
|---|---|
| Manual config (env vars: `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`) | **Primary**. Matches existing config conventions for `CAPTURE_DEVICE`. |
| mDNS `_mqtt._tcp.` discovery | **Defer to v1.4**. Useful for true zero-config but adds `zeroconf` dependency just for this. Manual env vars cover the actual use case. |

---

## 2. HA YAML Snippet Documentation

### Classification: TABLE STAKES (build)

Even with MQTT discovery in place, two user populations need YAML:
1. Users without an MQTT broker (don't want to set up Mosquitto for one integration).
2. Users who want to verify what the integration does before enabling discovery.

The docs are also a forcing function: writing the YAML snippets surfaces any awkward endpoint shape in `routers/ha.py` before users hit it.

### Surface area

Ship a single `docs/HOME_ASSISTANT.md` (markdown, in the repo) with these sections:

| Section | Contents | Tested? |
|---|---|---|
| **Quick start (MQTT)** | One paragraph: install Mosquitto add-on, set HPC env vars, restart HPC. Entities appear. | Manual smoke test in the GSD verification phase. |
| **REST-only setup** | The full YAML below. | Round-trip tested in `Backend/tests/test_ha_yaml_docs.py` — see "doc-test" pattern. |
| **Entity reference** | Table mapping each MQTT-discovered entity to its REST equivalent. | Auto-checkable. |
| **Example automations** | "Turn on when TV powers on", "Switch zone with media_player.source". | Reference quality. |
| **Troubleshooting** | "Why doesn't my switch appear?" (MQTT discovery not enabled, broker unreachable). | Manual. |

### REST-only YAML — concrete shape

This is what `docs/HOME_ASSISTANT.md` ships verbatim. Drop into `configuration.yaml` (`!include` style works too):

```yaml
# ===== rest_command: =====
rest_command:
  hpc_start:
    url: "http://hpc.local:8000/api/ha/start"
    method: POST
  hpc_stop:
    url: "http://hpc.local:8000/api/ha/stop"
    method: POST
  hpc_select_zone:
    url: "http://hpc.local:8000/api/ha/zone"
    method: PUT
    content_type: "application/json"
    payload: '{"zone_id": "{{ zone_id }}"}'
  hpc_select_camera:
    url: "http://hpc.local:8000/api/ha/camera"
    method: PUT
    content_type: "application/json"
    payload: '{"stable_id": "{{ stable_id }}"}'

# ===== Status sensor (polled) =====
rest:
  - resource: "http://hpc.local:8000/api/ha/status"
    scan_interval: 10           # seconds; HA default is 30, 10 is fine for ambient lighting
    sensor:
      - name: "HPC State"
        unique_id: hpc_state
        value_template: "{{ value_json.state }}"
        json_attributes:
          - active_config_name
          - active_camera_name
          - fps
          - latency_ms
          - bridge_paired
      - name: "HPC FPS"
        unique_id: hpc_fps
        value_template: "{{ value_json.fps }}"
        unit_of_measurement: "fps"
        state_class: measurement
      - name: "HPC Latency"
        unique_id: hpc_latency
        value_template: "{{ value_json.latency_ms }}"
        unit_of_measurement: "ms"
        state_class: measurement

# ===== Available zones / cameras as input_select options =====
# (Helpers must be created in UI; this is a script that REFRESHES the options
#  from /api/ha/zones once a day or on HA startup.)
script:
  hpc_refresh_zones:
    sequence:
      - service: rest_command.hpc_get_zones  # GET wrapped as rest_command
        response_variable: zones
      - service: input_select.set_options
        target:
          entity_id: input_select.hpc_zone
        data:
          options: "{{ zones['content'] | map(attribute='name') | list }}"
```

The `scan_interval: 10` here is HA-side polling. Verified at [HA RESTful Sensor docs](https://www.home-assistant.io/integrations/sensor.rest/): default 30s, no enforced minimum. 10s is comfortable for HPC's ~2 RPS upper bound. This is the **real source of "WS push for HA"** — it's the polling cadence — and 10s latency is fine for ambient-lighting dashboards (see §3).

### Reference projects

| Project | Doc style | Lesson |
|---|---|---|
| [Theengs OpenMQTTGateway HA docs](https://docs.openmqttgateway.com/integrate/home_assistant.html) | Long markdown, MQTT-first with REST fallback. | Ship the MQTT path first; YAML is the "I don't want a broker" lane. |
| [Tasmota HA integration](https://tasmota.github.io/docs/Home-Assistant/) | Heavy emphasis on discovery topic structure + example payloads. | Document the topic structure so power users can debug with `mosquitto_sub`. |
| [WLED HA integration](https://www.home-assistant.io/integrations/wled/) | First-party integration docs are short — entity list + capability matrix. | The "Entity reference" table is the most-used section. Prioritize it. |
| [Frenck/python-wled](https://github.com/frenck/python-wled) | Has no HA-specific YAML; HA's WLED integration is native (config-flow based). | Native HA integration is an option (custom_component) but doesn't fit our v1.3 budget. **Defer to v1.5+** as a "v2 integration" path if MQTT adoption is poor. |

### Doc-test pattern

Add `Backend/tests/test_ha_yaml_docs.py` that:
1. Reads `docs/HOME_ASSISTANT.md`.
2. Extracts every fenced ` ```yaml ` block.
3. Parses with `yaml.safe_load` to catch syntax drift.
4. For each `rest_command` URL/method pair, asserts a corresponding FastAPI route exists on the `ha` router.

This is ~40 lines; prevents the doc rotting when endpoint shapes evolve.

---

## 3. WebSocket Push for HA Status Changes

### Classification: ANTI-FEATURE — DROP

### Why

**HA cannot consume an external WebSocket from YAML.** Verified at [HA WebSocket API developer docs](https://developers.home-assistant.io/docs/api/websocket/): HA's `websocket_api` integration is a server endpoint that *clients* connect to. There is no `websocket_sensor` or `websocket_subscription` YAML platform that points HA at an outside `ws://` URL.

The three paths that would actually deliver "push" to HA are:

| Path | Verdict | Why not |
|---|---|---|
| **MQTT** | This is the answer | Already being built in §1. Sub-second latency, retained state. Strictly better than any custom WS in every dimension. |
| **HA webhooks** (HA exposes a webhook URL HPC can POST to) | Workable but inferior to MQTT | Adds outbound HA secret (the webhook URL) to HPC config — violates CLAUDE.md "no HA token / no outbound secrets" stance. Also each fired webhook only triggers an automation, not an entity state update. |
| **Custom HA integration** (`custom_component`) | Out of scope this milestone | Would let HA open a WS to HPC. ~600 LOC of Python integration code, manifest, config_flow. Sized as its own v1.5 milestone if MQTT proves insufficient. |

### What about the existing `/ws/status`?

`/ws/status` is consumed by the web UI (`Frontend/`) for the streaming-metrics overlay. That's load-bearing and stays. The only thing being dropped is the **"v1.3 adds WS push for HA"** roadmap line — HA was never a real consumer of it.

### Recommendation for PROJECT.md

Move the bullet to Out of Scope with this reason: *"HA cannot consume external WebSocket feeds from YAML. MQTT discovery (built in v1.3) delivers sub-second push with retained state, which is strictly better. Revisit only if MQTT adoption is poor and a custom_component path becomes viable."*

This is a **research win** — surfacing the un-feasibility frees up a phase of execution time for higher-leverage work (broader entity coverage, automation cookbook, mDNS broker discovery).

---

## 4. Per-Device WLED Health in Status

### Classification: DIFFERENTIATOR — build (lightly)

### What "health" actually means here

`broadcaster._metrics["wled_devices"]` is already populated by Phase 17. The expected shape per device (verify in Phase 17 code if there's any doubt, but the Phase 18 deferred list specifically named this metric as ready-to-surface):

```python
{
  "<wled_device_id>": {
    "name": "Living-room strip",
    "ip": "192.168.178.42",
    "connected": True,             # last UDP send succeeded
    "packets_sent": 12345,
    "packets_dropped": 0,
    "last_error": None,            # last UDP/connect error string, or None
    "last_success_at": "2026-05-12T19:40:12Z"
  },
  ...
}
```

UDP is fire-and-forget — `connected` here means "last sendto() did not raise", not "the device ACKed", because WLED doesn't ACK. That's a known limitation, document it.

### Two delivery surfaces

**(a) Additive D-09 field in `/api/ha/status`:**

```jsonc
{
  // ... existing D-09 fields ...
  "wled_devices": [
    {
      "id": "wled_living_room",
      "name": "Living-room strip",
      "connected": true,
      "last_error": null
    }
  ]
}
```

**Only four fields per device.** `packets_sent`/`packets_dropped`/`last_success_at` stay internal — HA dashboards don't need raw counters. This keeps the D-09 contract additive (existing template sensors break only if they explicitly forbid extra keys, which HA's JSON parsing doesn't).

The D-09 §"Stable contract" comment in `CONTEXT.md` is now slightly out of date — the new field needs a doc update naming `wled_devices` as the one explicit exception to "no `_metrics` leakage." That's a conscious trade: WLED users absolutely need this surfaced for HA alerting.

**(b) Per-device MQTT binary_sensor (one entity per WLED device, under the HPC device):**

```json
{
  "name": "WLED: Living-room strip",
  "unique_id": "hpc_7f9a3b2c_wled_living_room",
  "state_topic": "hpc/7f9a3b2c/status",
  "value_template": "{{ 'ON' if (value_json.wled_devices | selectattr('id', 'equalto', 'wled_living_room') | map(attribute='connected') | first) else 'OFF' }}",
  "device_class": "connectivity",
  "json_attributes_topic": "hpc/7f9a3b2c/status",
  "json_attributes_template": "{{ value_json.wled_devices | selectattr('id', 'equalto', 'wled_living_room') | first | tojson }}",
  "availability": [{ "topic": "hpc/7f9a3b2c/availability" }],
  "device": { "identifiers": ["hpc_7f9a3b2c"] }
}
```

The value_template uses Jinja `selectattr` filtering on the shared `wled_devices` array — same status payload, different filter per WLED device. **One state publish updates all WLED binary_sensors simultaneously.**

### Should each WLED device be its own HA device?

**No — keep them as entities under the HPC device.** Reasons:

1. **Single source of truth:** HPC drives the WLED via UDP; it knows what's actually happening (packet errors, connection drops). The native WLED HA integration polls the WLED's own JSON API, which doesn't know whether HPC is streaming to it. Having two HA "devices" representing the same physical strip is confusing.
2. **Lifecycle simplicity:** When a user deletes a WLED from HPC's UI, the matching binary_sensor goes away (publish empty discovery payload on the entity's topic to clear it). If WLEDs were separate devices, we'd need to manage HA device lifecycle too.
3. **Already an established pattern in HA:** Tasmota groups all entities for a single physical device under one HA device. Zigbee2MQTT groups multiple Zigbee endpoints (one physical bulb might be multiple HA entities) under one device. The "physical box → HA device, signals → HA entities" mapping is the convention.

If users also run the native WLED HA integration on the same strip, they get **complementary** entities: the native integration covers WLED-side health (uptime, free memory, Wi-Fi RSSI per [WLED HA docs](https://www.home-assistant.io/integrations/wled/)), HPC's entity covers the *HPC-to-WLED streaming session* health. Different layers, both useful.

### When does WLED-device-as-HA-device make sense?

If v1.5+ adds non-streaming WLED control surface (preset selection, segment toggles directly from HPC's UI) AND a user might not run the native WLED HA integration, then it's worth giving each WLED its own HA device. Until then: entities under HPC.

---

## Anti-Features (explicitly NOT building)

| Anti-feature | Why avoid | What to do instead |
|---|---|---|
| **HA Cloud integration / Nabu Casa hooks** | LAN-only design (PROJECT.md Constraints). Cloud relay would require an HA bearer token in HPC — violates the no-secrets stance. ([HA Cloud overview](https://www.home-assistant.io/integrations/cloud/)) | LAN is the trust boundary. Users who need remote access use HA's remote-access layer to reach HA, which reaches HPC. |
| **HA long-lived access token storage in HPC** | Reiterating CLAUDE.md §"What NOT to Use". Storing HA tokens means HPC becomes a secret-managing service. | HA → HPC direction only. MQTT is brokered (broker holds nothing sensitive about HA), REST is unauthenticated on LAN. |
| **WebSocket push to HA** | §3 — HA can't consume. | MQTT discovery covers the use case. |
| **Custom HA integration (`custom_component`)** | High maintenance burden; HACS publish cycle; duplicates work MQTT already does. | Defer to a hypothetical v1.5+. MQTT discovery is the path of least surprise. |
| **Authentication on `/api/ha/*` endpoints** | Out of scope per PROJECT.md. LAN trust boundary. | Network-level access control is the operator's responsibility. |
| **`/api/ha/restart` combined verb** | Already deferred in Phase 18 CONTEXT. HA can chain `hpc_stop` then `hpc_start`. | Two-call pattern in YAML. |
| **`PUT /api/ha/target_hz` runtime tuning** | Already deferred. No user demand. | Coordinator default (60 Hz) remains hardcoded. Revisit on demand. |
| **`zeroconf` for MQTT broker discovery** | Adds a dependency for a one-time setup convenience. | Manual env vars (`MQTT_BROKER_HOST=...`). Most users already know their Mosquitto IP. |
| **A second status payload schema for HA** | Two payloads diverge over time. | Reuse `HaStatusResponse` for both `/api/ha/status` REST and `hpc/<id>/status` MQTT. |
| **MQTT publish per-frame (50 Hz)** | Floods broker. HA doesn't care about per-frame state. | Publish on `push_state` (state transitions, ~rare) + 1 Hz heartbeat (piggyback on `StatusBroadcaster._heartbeat_loop`). |

---

## Feature Dependencies

```
                       MQTT auto-discovery (§1)
                                  |
            +---------------------+---------------------+
            |                                           |
   Per-device WLED                          HA YAML snippet docs (§2)
   health entities (§4)                     (entity reference table
            |                                shares manifest with §1)
            |
   Additive `wled_devices` field
   in /api/ha/status (§4)
   (also surfaces in MQTT status topic,
    no extra publish needed)


   WS push to HA (§3) ── DROPPED ── no dependency edges
```

- §1 is the keystone — §2 derives its entity table from it, §4 piggybacks on the status topic it establishes.
- §4 splits cleanly into two PRs: (a) the additive REST field (no MQTT dependency, can ship first), (b) the per-WLED MQTT binary_sensor (depends on §1).
- §2 can ship in parallel with §1; the entity-reference section blocks on §1 finalization.

---

## MVP Recommendation (for the v1.3 roadmap)

Prioritize:

1. **Phase 19 — MQTT discovery foundation** (§1): aiomqtt singleton, lifespan wiring, instance UUID storage, 11 base entity discoveries (no WLED entities yet), inbound command routing, LWT + birth handling, status republish on `homeassistant/status=online`.
2. **Phase 20 — WLED health surfacing** (§4): additive `wled_devices` field in `HaStatusResponse`, per-WLED binary_sensor discovery, dynamic publish/clear on WLED device add/remove.
3. **Phase 21 — HA documentation** (§2): `docs/HOME_ASSISTANT.md`, the doc-test, automation cookbook.

Defer:
- **WS push for HA** → Out of Scope (§3 reasoning in PROJECT.md update).
- **mDNS broker discovery** → v1.4 polish.
- **`custom_component`** → v1.5+, only if MQTT adoption is poor.

Phase ordering is dependency-driven (§1 → §4 → §2). §4's REST half could optionally ship before §1 if there's any reason to land it first — it's a 1-day additive field — but bundling with the MQTT side keeps the milestone story tight.

---

## Sources

- [Home Assistant - MQTT Integration](https://www.home-assistant.io/integrations/mqtt/) — discovery topic format, device-based discovery, availability, birth/will, retained discovery, `device` object fields including `identifiers`/`manufacturer`/`model`/`configuration_url`/`via_device`. HIGH confidence (official docs, current).
- [Home Assistant - MQTT Sensor](https://www.home-assistant.io/integrations/sensor.mqtt/) — `state_topic`, `value_template`, `unit_of_measurement`, `state_class`, `entity_category`, `json_attributes_topic`/`json_attributes_template`. HIGH confidence.
- [Home Assistant - MQTT Switch](https://www.home-assistant.io/integrations/switch.mqtt/) — `state_topic`, `command_topic`, `payload_on/off`, `state_on/off`, `optimistic` mode. HIGH confidence.
- [Home Assistant - MQTT Select](https://www.home-assistant.io/integrations/select.mqtt/) — `command_topic`, `state_topic`, `options` list, `value_template`/`command_template`. HIGH confidence.
- [Home Assistant - RESTful Sensor](https://www.home-assistant.io/integrations/sensor.rest/) — `scan_interval` default 30s with no enforced minimum, `json_attributes`/`json_attributes_path`, `value_template`. HIGH confidence.
- [Home Assistant - RESTful Command](https://www.home-assistant.io/integrations/rest_command/) — `url`, `method`, `payload`, template support for the body. HIGH confidence.
- [Home Assistant - Input Select](https://www.home-assistant.io/integrations/input_select/) — frontend helper for user-driven selection; combine with REST script to refresh options from `/api/ha/zones`. HIGH confidence.
- [Home Assistant - WLED Integration](https://www.home-assistant.io/integrations/wled/) — entity inventory: per-segment lights, per-device sensors (current mA, free memory, Wi-Fi RSSI), update entity, presets/palettes/playlists as select. No per-device "connected" binary_sensor in the native integration — confirms HPC's binary_sensor adds non-overlapping value. HIGH confidence.
- [HA Developer Docs - WebSocket API](https://developers.home-assistant.io/docs/api/websocket/) — confirms HA's `websocket_api` is a server endpoint for client consumption, NOT a YAML-configurable consumer of external feeds. Settles §3 as anti-feature. HIGH confidence.
- [HA Developer Docs - REST API](https://developers.home-assistant.io/docs/api/rest/) — confirms bearer-token format applies HA-as-server side, not consumed by HPC. HIGH confidence.
- [Zigbee2MQTT HA integration docs](https://www.zigbee2mqtt.io/guide/usage/integrations/home_assistant.html) — reference for device-based discovery with multiple entities per physical device, MQTT topic conventions, retained discovery messages. HIGH confidence (production-grade ecosystem example).
- [Tasmota HA Integration docs](https://tasmota.github.io/docs/Home-Assistant/) — reference for "physical box → HA device, signals → HA entities" mapping. HIGH confidence.
- [Theengs OpenMQTTGateway HA docs](https://docs.openmqttgateway.com/integrate/home_assistant.html) — reference for MQTT-first integration docs structure. MEDIUM confidence (style reference, not normative).
- [aiomqtt on PyPI](https://pypi.org/project/aiomqtt/) — current asyncio MQTT client, active maintenance, used in `lifespan` patterns. HIGH confidence.
- [ha-mqtt-discoverable on PyPI](https://pypi.org/project/ha-mqtt-discoverable/) — surveyed and rejected as adding an opinionated framework for what is <50 lines of JSON per entity type. Listed for completeness. MEDIUM confidence.
- [Home Assistant Cloud](https://www.home-assistant.io/integrations/cloud/) — confirms Cloud is not relevant for LAN-only inbound integrations. HIGH confidence.
- Internal: `Backend/services/status_broadcaster.py` (verified `_metrics` shape, including `wled_devices` key), `Backend/routers/ha.py` (verified D-09 status payload structure ships today), `.planning/phases/18-home-assistant-control-endpoints/18-CONTEXT.md` (D-09/D-10 status schema, D-07 decoupling, deferred ideas). HIGH confidence (direct file reads).
