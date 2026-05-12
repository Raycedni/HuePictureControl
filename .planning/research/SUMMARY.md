# v1.3 Home Assistant Integration Polish — Research Summary

**Project:** HuePictureControl
**Milestone:** v1.3 Home Assistant Integration Polish
**Researched:** 2026-05-12
**Sources:** [STACK.md](./STACK.md), [FEATURES.md](./FEATURES.md), [ARCHITECTURE.md](./ARCHITECTURE.md), [PITFALLS.md](./PITFALLS.md)
**Overall confidence:** HIGH

---

## TL;DR

- **One library added — `aiomqtt>=2.5,<3` (BSD-3-Clause).** Everything else is recomposition of code already in the tree. No frontend dependencies, no new system packages.
- **WebSocket push for HA is dropped as an anti-feature.** HA cannot consume external WebSockets from YAML — verified at the HA developer WS API docs. MQTT delivers sub-second push with retained state. Reclaim that phase budget.
- **Architectural insight: MQTT observes state via a 4-line subscriber-callback addition to `StatusBroadcaster`** — no polling, no second library, no in-process WS round-trip.
- **Critical pitfall: `unique_id` must derive from a persistent per-install UUID stored in a new `hpc_identity` SQLite row.** Skipping this on the first cut means every HPC restart spawns orphan entities and breaks user automations. Pair with `retain=True` + `homeassistant/status` birth re-publish + LWT-on-availability — all three must land in the same phase as the publisher.
- **Build order is risk-ascending: YAML docs → WLED health flattening → MQTT discovery (read-only) → MQTT commands (bidirectional, requires `routers/ha.py` helper extraction).**

---

## Stack Additions (from STACK.md)

### Single new dependency

| Package | Version | License | Purpose |
|---------|---------|---------|---------|
| `aiomqtt` | `>=2.5,<3` | BSD-3-Clause | Native asyncio MQTT client. Slots into the existing `lifespan` next to `db`/`registry`/`broadcaster`/`coordinator`. Internally wraps `paho-mqtt 2.1.0` (EPL-2.0 / BSD-3-Clause). Built-in MQTT 5.0 + 3.1.1, `aiomqtt.Will` for LWT. |

Transitive `paho-mqtt` pulled automatically — **do NOT pin it separately** in `requirements.txt` (resolver lock-step footgun).

### Recompositions (zero new deps)

- **Per-device WLED health in `/api/ha/status`**: existing `httpx` for `/json/info` probes. `broadcaster._metrics["wled_devices"]` already populated by `streaming_coordinator.py:549` (Phase 17 D-16).
- **Pydantic models** for `HaDiscoveryPayload` and `WledHealthEntry`: existing `pydantic>=2.10,<3`.
- **YAML snippet docs**: plain Markdown under `docs/home-assistant/`. No static-site generator.

### What NOT to add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `paho-mqtt` raw threading mode | Non-daemon thread; LWT-flush ordering vs asyncio shutdown is fragile. | `aiomqtt` async context manager. |
| `gmqtt` / `fastapi-mqtt` | `gmqtt` classified inactive (Snyk health); `fastapi-mqtt` wraps gmqtt. | `aiomqtt` — monthly releases, HA Core itself uses it. |
| `homeassistant-api` / `hass-client` / `hassapi` | All are HA **outbound** API wrappers — would store an HA long-lived token in HPC, violating no-secrets-in-HPC. | HA → HPC direction only: MQTT + unauthenticated REST. |
| `ha-mqtt-discoverable` | Opinionated framework over `paho`; not needed for <50 lines of JSON per entity. | `aiomqtt.Client.publish` of plain dicts. |
| MkDocs / Sphinx / Docusaurus | LAN tool with no public docs site. | Plain `.md` files alongside YAML snippets. |
| MQTT credentials in SQLite | Plain-text DB + LAN trust boundary. | Env vars only — `MQTT_BROKER_HOST`, `MQTT_USERNAME`, `MQTT_PASSWORD`. |

### License / maintenance notes

- `aiomqtt` BSD-3-Clause + `paho-mqtt` dual EPL-2.0/BSD-3 → permissively compatible with FastAPI/MIT, Pydantic/MIT, aiosqlite/MIT.
- `aiomqtt 2.x` ships monthly (2.5.0 Jan 2026, 2.5.1 Mar 2026, 3.0.0a1 Apr 2026). Pin `>=2.5,<3` to avoid the 3.x alpha.
- `aiomqtt 2.x` does **NOT** auto-reconnect — `async with Client(...)` exits on disconnect by design. Hand-roll the documented "Alongside FastAPI" reconnect loop (~10 lines).
- Protocol negotiation: **connect MQTT 5.0 first, fall back to 3.1.1 on connect failure.**

---

## Feature Scope (from FEATURES.md)

### Classification

| Feature | Verdict | Why |
|---------|---------|-----|
| **MQTT auto-discovery** | TABLE STAKES — build | Removes all YAML for the typical HA user. Standard pattern: Zigbee2MQTT, Tasmota, ESPHome use retained `homeassistant/<component>/<id>/config`. |
| **HA YAML snippet docs** | TABLE STAKES — build | Cheap (one Markdown file). Required fallback when no MQTT broker is available. |
| **WebSocket push for HA status** | ANTI-FEATURE — drop | HA cannot consume external WS feeds from YAML (verified at HA developer WS API docs). **Reclaim the phase budget.** |
| **Per-device WLED health in `/api/ha/status`** | DIFFERENTIATOR — build (lightly) | Already in `broadcaster._metrics["wled_devices"]`. Surface 4 curated fields as an additive D-09 field + one MQTT `binary_sensor` per WLED. |

### Entity manifest (one HA device, 11 base entities + N WLED binary_sensors)

| Entity | Type | Maps to |
|--------|------|---------|
| `Streaming` | switch | `POST /api/ha/start` / `POST /api/ha/stop` |
| `State` | sensor | `_metrics["state"]` enum |
| `Bridge paired` | binary_sensor (`device_class: connectivity`) | `bridge_paired` |
| `FPS` | sensor (`unit: fps`, diagnostic) | `_metrics["fps"]` |
| `Latency` | sensor (`unit: ms`, diagnostic) | `_metrics["latency_ms"]` |
| `Active zone` | sensor | `active_config_name` |
| `Active camera` | sensor | `active_camera_name` |
| `Selected zone` | select | `GET/PUT /api/ha/zone` over MQTT |
| `Selected camera` | select | `GET/PUT /api/ha/camera` over MQTT |
| `Last error` | sensor (diagnostic) | `_metrics.get("error")` |
| `WLED <name>` | binary_sensor (`device_class: connectivity`, diagnostic) | per-device `wled_devices` entry |

**Key trick:** every entity subscribes to the same `hpc/<id>/status` JSON state topic and extracts its own field via `value_template`. One publish, eleven entity updates.

### Anti-features (NOT building)

HA Cloud / Nabu Casa, HA token storage in HPC, WS push to HA, `custom_component`, mDNS broker discovery (defer to v1.4), second HA-specific status schema, MQTT publish per-frame (50 Hz), `/api/ha/restart`, `PUT /api/ha/target_hz` runtime tuning.

### Recommended scope changes

1. Move WS push from Active → Out of Scope in PROJECT.md.
2. Cap MQTT publish rate: state transitions immediately + 1 Hz heartbeat. No per-frame publishes.
3. MQTT enablement is **opt-in** via `MQTT_BROKER_HOST` env var. Default v1.2 behavior unchanged.

---

## Architecture Integration (from ARCHITECTURE.md)

### Component placement (file paths)

| Status | Path | Purpose |
|--------|------|---------|
| NEW | `Backend/services/ha_mqtt_publisher.py` | `HaMqttPublisher` class — owns `aiomqtt.Client`, command consumer, discovery publisher, reconnect loop. ~350 LOC. |
| NEW | `Backend/tests/test_ha_mqtt_publisher.py` | aiomqtt mock + integration test. ~200 LOC. |
| NEW | `docs/home-assistant/` | `README.md` + YAML snippets. ~150 LOC markdown. |
| MOD | `Backend/main.py` | Env-gated MQTT init after coordinator; teardown before registry shutdown. |
| MOD | `Backend/services/status_broadcaster.py` | Add `_subscribers: list`, `subscribe()`/`unsubscribe()`, `_notify_subscribers()`. Call only from `push_state` (NOT `update_metrics` — 50 Hz storm). |
| MOD | `Backend/routers/ha.py` | (a) Add `wled_devices` to `HaStatusResponse` with safe default `[]`. (b) Extract business logic from `ha_start`/`ha_stop`/`ha_put_zone`/`ha_put_camera` into pure async helpers callable from the MQTT consumer. |
| MOD | `Backend/routers/health.py` | Surface `{"mqtt": {"enabled": bool, "connected": bool, "broker_host": <redacted>}}`. |
| MOD | `Backend/database.py` | Add `hpc_identity` single-row table (`id INTEGER PRIMARY KEY CHECK (id=1), instance_uuid TEXT NOT NULL, created_at TEXT NOT NULL`). |
| MOD | `Backend/requirements.txt` | Append `aiomqtt>=2.5,<3`. |
| UNCHANGED | `streaming_coordinator.py`, `wled_streamer.py`, all `Frontend/*` | MQTT is observation + control via existing hooks. No hot-path or sink changes. |

### State observation: subscriber-callback hook

```python
# Backend/services/status_broadcaster.py — 4-line addition
self._subscribers: list[Callable[[dict], Awaitable[None]]] = []  # __init__

def subscribe(self, cb): self._subscribers.append(cb)
def unsubscribe(self, cb):
    try: self._subscribers.remove(cb)
    except ValueError: pass

async def _notify_subscribers(self):
    if not self._subscribers: return
    snap = dict(self._metrics)
    await asyncio.gather(*(self._safe_invoke(cb, snap) for cb in list(self._subscribers)))
```

Call only from `push_state` (state transitions). Subscribers see metric updates via the 1 Hz `_heartbeat_loop` only.

### Config: env vars (DB escape hatch deferred to v1.4)

| Setting | Source | Default |
|---------|--------|---------|
| `MQTT_BROKER_HOST` | env var | unset → MQTT disabled |
| `MQTT_BROKER_PORT` | env var | `1883` |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | env var | unset |
| `MQTT_BASE_TOPIC` | env var | `huepicturecontrol` |
| `MQTT_DISCOVERY_PREFIX` | env var | `homeassistant` |
| `HPC_INSTANCE_NAME` | env var | hostname |

**Graceful degrade:** broker unreachable at boot → caught in lifespan, `app.state.mqtt = None`, `/api/health` reports "MQTT disabled". Broker disconnects later → reconnect loop with exponential backoff (1s → 60s cap). HA's HPC entities go `unavailable` via LWT.

### Build order — risk ascending

| # | Plan | Risk | Why this order |
|---|------|------|----------------|
| 1 | **YAML docs** | Trivial | Lowest risk. Unblocks users with no broker IMMEDIATELY. |
| 2 | **WLED health flattening** | Low | Small additive Pydantic field. Completes the HA template surface before MQTT joins. |
| 3 | **MQTT discovery (read-only)** | Medium | New dep, new lifespan branch, subscriber callback infra. NO command consumer yet. |
| 4 | **MQTT command consumer** | Higher | Refactors `routers/ha.py` to extract pure helpers; touches all four HA routes and their tests. |
| 5 (optional) | `/api/health` MQTT surface | Trivial | One-line addition. Ship anytime after Plan 3. |

---

## Critical Pitfalls (from PITFALLS.md)

| # | Pitfall | One-line fix | Phase |
|---|---------|--------------|-------|
| **MQTT-1** | Discovery messages not retained → HA loses every HPC entity on restart. | Always `retain=True, qos=1` on `homeassistant/+/+/config` AND subscribe to `homeassistant/status` to republish on HA birth. | Plan 3 |
| **MQTT-2** | Unstable `unique_id` → orphan entities + broken automations after every HPC restart. | Persist a per-install UUID in a new `hpc_identity` SQLite row. `unique_id = f"{instance_uuid}_{slug}"`. Never derive from hostname/IP/PID. | Plan 3 |
| **MQTT-3** | No LWT → HA shows stale "streaming" state forever after HPC crash. | Set `aiomqtt.Will(topic="hpc/<id>/availability", payload=b"offline", qos=1, retain=True)` at construction. Birth-publish `online` on connect. | Plan 3 |
| **MQTT-4** | MQTT broker disconnect wedges FastAPI event loop / hangs `/api/ha/start`. | Sibling background task with bounded (1024) `asyncio.Queue` and `publish_nowait()`. Request handlers never `await client.publish(...)` directly. Exponential backoff (1s → 60s). | Plan 3 |
| **MQTT-5** | Two HPC instances on one broker → topic collisions, flip-flopping entities. | Include `instance_uuid` in `<object_id>` topic segment AND `device.identifiers`. `HPC_INSTANCE_NAME` env var sets a friendly `device.name`. | Plan 3 |
| **MQTT-6** | Deprecated `object_id` field → entity IDs revert to UUIDs after HA 2026.4 upgrade. | Use `default_entity_id: "sensor.hpc_state"` (fully qualified). NOT `object_id`. | Plan 3 |
| **MQTT-8** | Naïve per-WLED-field discovery → 24+ sensors clutter HA UI. | One `binary_sensor` per WLED device with `json_attributes_topic` for `last_error`/`last_success_at`/`in_cooldown`. `entity_category: diagnostic`. | Plan 2 |
| **HA-1** | Template sensors break on missing keys / null values. | YAML snippets use `{{ value_json.fps \| default('unknown') }}`. `/api/ha/status` additions are additive-only; new keys default to `[]` / `0`, never `None`. | Plan 1 + Plan 2 |

### Phase-mapping summary

- **Plan 1 (YAML docs):** HA-1 (defensive Jinja), MQTT-7 (document "either MQTT or YAML, not both").
- **Plan 2 (WLED health):** HA-1 (additive contract with safe defaults), MQTT-8 (json_attributes_topic grouping).
- **Plan 3 (MQTT discovery):** MQTT-1 through MQTT-6, credential redaction in logs, subscribe-before-publish ordering, INTEGRATION-1 (update CLAUDE.md/PROJECT.md to mention MQTT as new outbound destination).
- **Plan 4 (MQTT commands):** No new pitfalls beyond Plan 3 — helper extraction is mechanical.

---

## Open Decisions for Roadmap

1. **Phase count and grouping.** Architecture's 4-plan risk-ascending order is recommended over Features' 3-phase grouping.
2. **WS push fate.** Drop from v1.3 entirely; move PROJECT.md "Active" → "Out of Scope."
3. **WLED-device-as-HA-device.** Keep WLEDs as entities under HPC device. Re-publish full WLED discovery on every WLED CRUD via a new `HaMqttPublisher.refresh_wled_discovery()` method.
4. **Friendly-name resolution cache.** `_build_status_response()` calls `list_entertainment_configs` per status build — at 1 Hz MQTT publish that's 1 Hue Bridge call per second. Cache `config_name_by_id` in `HaMqttPublisher`, invalidated on `/api/hue/configs` change.
5. **Discovery payload schema versioning.** Pin `sw_version: "1.3.0"` and stable `device.identifiers`.
6. **MQTT-7 mixing prevention.** Documentation + opt-in env var (MQTT off by default).
7. **Initial protocol version negotiation.** MQTT 5.0 first, fall back to 3.1.1 on connect failure.

---

## Key Conflicts Resolved Between Sources

### Conflict #1: Build order — Features (MQTT-first) vs Architecture (YAML-first)

**Resolution: Architecture wins.** Use the 4-plan risk-ascending order (YAML → WLED → MQTT discovery → MQTT commands).

### Conflict #2: WS push — anti-feature vs optional plan

**Resolution: Features wins — drop entirely from v1.3.** Update PROJECT.md "Active" → "Out of Scope."

### Conflict #3: Library choice — Features (paho/gmqtt "acceptable") vs Stack+Architecture (aiomqtt only)

**Resolution: Stack and Architecture win.** Use `aiomqtt>=2.5,<3`. Version pin is **`>=2.5,<3`** — Architecture says "v3+" but Stack pins below 3 to avoid the 3.0.0a1 alpha.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All claims verified against PyPI / official docs / GitHub. |
| Features | HIGH | Every entity schema verified against current `home-assistant.io` integration pages. WS-can't-consume verified at HA developer WS API docs. |
| Architecture | HIGH | Existing patterns verified by direct file reads. `aiomqtt` API verified via Context7. |
| Pitfalls | HIGH | Every critical pitfall verified against official HA docs, `aiomqtt`/`paho-mqtt` source/issues, and real GitHub issues from peer projects. |

**Overall confidence: HIGH.**

---

### Roadmap Implications

Suggested phases: **4 active + 1 optional**

1. **YAML docs (`docs/home-assistant/`)** — closes deferred Phase 18 item; zero backend risk.
2. **WLED health flattening in `/api/ha/status`** — additive Pydantic field.
3. **MQTT discovery (read-only)** — `aiomqtt` + `HaMqttPublisher` + `hpc_identity` table + `StatusBroadcaster` subscriber hook + LWT/birth/retain trifecta.
4. **MQTT command consumer** — extracts pure helpers from `routers/ha.py`; bidirectional control.
5. *(optional)* `/api/health` MQTT surface — one-line addition.

---
*Research synthesized: 2026-05-12*
*Net dependency cost: +1 PyPI package (`aiomqtt`), +1 transitive (`paho-mqtt`)*
*Net scope change vs PROJECT.md: WS push moves Active → Out of Scope*
