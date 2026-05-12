# Stack Research — v1.3 Home Assistant Integration Polish

**Domain:** Home Assistant integration for an existing FastAPI service
**Researched:** 2026-05-12
**Confidence:** HIGH
**Scope:** ONLY new capabilities for v1.3 (MQTT discovery, YAML docs, HA-status WebSocket push, per-device WLED health). v1.0–v1.2 stack is fixed — see "Already Have" below.

## TL;DR

| New capability | Recommended addition | Verdict |
|----------------|----------------------|---------|
| MQTT auto-discovery publisher | **`aiomqtt>=2.5,<3`** (BSD 3-clause; wraps `paho-mqtt`) | Add |
| HA discovery topic/payload formatting | **stdlib `json` + Pydantic models** (already present) | No new dep |
| WebSocket push for HA status | **FastAPI WebSocket + existing `StatusBroadcaster`** | No new dep |
| Per-device WLED health in `/api/ha/status` | **Existing `httpx` + WLED `/json/info`** | No new dep |
| YAML snippet docs | **Plain `.md` files in `docs/home-assistant/`** | No new dep |

**One library added.** Everything else is recomposition of code already in the tree.

---

## Recommended Stack Additions

### Core Technology (Backend — New)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `aiomqtt` | `>=2.5,<3` | Publish HA MQTT discovery configs + state/availability updates from inside the FastAPI event loop | (1) **Idiomatic asyncio** — `async with aiomqtt.Client(...) as client:` plus `await client.publish(...)` slots directly into the existing `lifespan` context manager pattern used in `Backend/main.py` for `db`, `registry`, `broadcaster`, `coordinator`. (2) **Thin wrapper, not a fork** — internally uses Eclipse Paho's `paho-mqtt 2.1.0` (EPL-2.0/BSD-3-Clause) as the protocol engine, so we inherit Mosquitto/EMQX/HiveMQ compatibility for free. (3) **No callback hell** — pure async iterators for incoming messages, exceptions for errors. Aligns with how `services/status_broadcaster.py` already uses asyncio queues. (4) **MQTT 5 + 3.1.1** support — needed because some HA Mosquitto deployments still run 3.1.1 defaults. (5) **License-compatible** — BSD-3-Clause stacks cleanly with HuePictureControl's existing deps (FastAPI/MIT, paho/EPL-2.0 or BSD-3, OpenCV/Apache-2.0). |

### Supporting Libraries (Backend — All Already Present)

| Library | Already at version | Purpose for v1.3 |
|---------|--------------------|------------------|
| `httpx` | `>=0.27,<1` | Per-device WLED health probe — `GET http://<wled-ip>/json/info` returns `live`, `leds.count`, `ver`, `name`, `fxname`. Same pattern as Phase 17's WLED registration code. Refreshed lazily inside `/api/ha/status` with a short `httpx.Timeout(connect=0.5, read=0.5)` so a down WLED never blocks the status endpoint (Pitfall 4 in `routers/ha.py` already established this convention). |
| `fastapi` WebSocket | `>=0.115,<1` (via Starlette) | New `WS /ws/ha-status` route. Use the existing `StatusBroadcaster` pattern from `routers/streaming_ws.py` verbatim — register a second connection set, push the same payload `_build_status_response()` returns today, debounce to ~5 Hz (matches `StreamingCoordinator` metric cadence). Zero new libs. |
| `pydantic` | `>=2.10,<3` | New `HaDiscoveryPayload`, `WledHealthEntry` models. Validation + JSON serialization for both MQTT payloads and `/api/ha/status` extensions. |
| `aiosqlite` | `>=0.20,<1` | Persist MQTT broker config in a new `mqtt_config` table (host, port, username, password_ref, base_topic, discovery_prefix, last_published_at). Single-row table consistent with `bridge_config` and `ha_state`. |
| `python-multipart`, `uvicorn[standard]`, `pytest`, `pytest-asyncio`, `opencv-python-headless`, `zeroconf`, `hue-entertainment-pykit` | as pinned in `requirements.txt` | Untouched. No interaction with v1.3 surface. |

### Frontend Additions

**None.** v1.3 surfaces are HA-facing (MQTT topics + new WS endpoint) plus markdown docs. No new UI is in scope — only a thin settings card to enter MQTT broker host/port/credentials, which renders with existing `shadcn/ui` `Input` + `Button` + the existing Zustand store pattern.

### Documentation Tooling

| Tool | Purpose | Notes |
|------|---------|-------|
| Plain Markdown in `docs/home-assistant/` | Ship `rest_command.yaml`, `sensors.yaml`, `input_select.yaml`, `automations.yaml` examples + a top-level `README.md` | No static-site generator, no Sphinx, no MkDocs. The project doesn't publish docs anywhere; it's a local LAN tool. Markdown next to the code is the lowest-friction format and renders correctly on GitHub if the repo ever gets pushed there. |

---

## Already Have (Do Not Re-Research)

The v1.0–v1.2 stack is the foundation v1.3 sits on. None of these are revisited.

| Layer | Technology | Version | Used For (in v1.3) |
|-------|-----------|---------|---------------------|
| Web framework | `fastapi` | `>=0.115,<1` | Existing routers + new `/ws/ha-status` |
| ASGI server | `uvicorn[standard]` | `>=0.32,<1` | Hosts the new WS endpoint; existing `--reload` dev workflow unchanged |
| Async DB | `aiosqlite` | `>=0.20,<1` | New `mqtt_config` table |
| HTTP client | `httpx` | `>=0.27,<1` | WLED `/json/info` health probes for `/api/ha/status` |
| HDMI capture (Linux V4L2) | custom ctypes/ioctl + mmap in `services/capture_v4l2.py` | n/a | Untouched |
| Frame decode | `opencv-python-headless` | `>=4.10,<5` | Untouched |
| Hue streaming | `hue-entertainment-pykit` | `==0.9.4` | Untouched |
| Python runtime | `3.12` (pinned — `hue-entertainment-pykit` incompatible with 3.13+) | 3.12 | Untouched |
| Frontend | React 19 + TypeScript + Konva.js + Zustand + shadcn/ui | — | New settings card only |
| Device enumeration | `linuxpy` | `>=0.24` | Untouched |
| Pydantic | `pydantic` | `>=2.10,<3` | New discovery/health models |
| WS infra | `StatusBroadcaster` in `services/status_broadcaster.py` | n/a | Pattern copied for HA status fan-out |
| mDNS | `zeroconf` | `>=0.148,<2` | Untouched; v1.3 does not auto-discover Mosquitto |

---

## Integration Points with Existing Code

### `Backend/main.py` — `lifespan` extension

The aiomqtt client lives in `app.state` exactly like `db`, `coordinator`, and `broadcaster` do today:

```python
# Startup (after broadcaster/coordinator init)
mqtt_cfg = await load_mqtt_config(db)  # may return None — feature off
if mqtt_cfg and mqtt_cfg.enabled:
    publisher = HaDiscoveryPublisher(mqtt_cfg, broadcaster=broadcaster)
    await publisher.start()  # connects, publishes discovery, subscribes to homeassistant/status
    app.state.ha_mqtt = publisher
else:
    app.state.ha_mqtt = None

yield

# Shutdown — BEFORE coordinator.stop() so LWT/availability "offline" lands first
if app.state.ha_mqtt is not None:
    await app.state.ha_mqtt.stop()
```

The publisher owns one persistent `aiomqtt.Client` for the app lifetime. It subscribes to `homeassistant/status` to re-publish discovery on HA reboot (HA birth message convention), and subscribes to `<base>/cmd/start`, `<base>/cmd/stop`, etc. as the MQTT analogues of the existing `/api/ha/start`, `/api/ha/stop` REST endpoints.

### `Backend/routers/ha.py` — additions, no rewrites

- Extend `HaStatusResponse` with `wled_devices: list[WledHealthEntry] | None = None`. `response_model_exclude_none=True` is already set on the route, so existing HA installations without WLED don't see the field.
- `_build_status_response()` gains a parallel `asyncio.gather()` of WLED `/json/info` probes (one `httpx.AsyncClient` reused, timeout 500ms each). Failures degrade to `online=False` per the existing Pitfall 4 convention — never raises.

### New router: `Backend/routers/ha_ws.py`

Mirrors `routers/streaming_ws.py` line-for-line. The `StatusBroadcaster` already supports multiple connection groups; add a `connect_ha()` / `disconnect_ha()` pair that fans out the curated `HaStatusResponse` shape (not the raw metrics dict). Push trigger: any time `_build_status_response()` would change — bridge-pair events, coordinator state transitions, WLED health changes.

### New service: `Backend/services/ha_mqtt.py`

~250 LOC class `HaDiscoveryPublisher`:
- `start()` — connect, publish device-bundle discovery topic (`homeassistant/device/huepicturecontrol_<host>/config`) with `switch.streaming`, `sensor.state`, `sensor.fps`, `sensor.latency_ms`, `select.zone`, `select.camera` components in a single payload, then publish initial state + `availability: online`.
- `_state_loop()` — async task: `async for change in broadcaster.subscribe_ha_changes(): await client.publish(...)`.
- `_command_loop()` — async task: `async for msg in client.messages: await dispatch(msg.topic, msg.payload)`. Topic-to-handler map calls the same internal logic as the REST handlers in `routers/ha.py` (refactor those handlers to call shared helpers — already partially done; `_build_status_response` is the precedent).
- `_on_birth()` — when `homeassistant/status == "online"` arrives, re-publish discovery + state.
- `stop()` — publish `availability: offline` (one shot, retain=true is fine here), then exit the `async with` block.

LWT (Last Will and Testament) is set in the `aiomqtt.Client(...)` constructor with `will=aiomqtt.Will(topic=f"{base}/availability", payload="offline", qos=1, retain=True)` — handled entirely by `paho-mqtt`'s wire-level setup; no extra library.

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| `aiomqtt>=2.5,<3` | **`paho-mqtt` raw** | `paho-mqtt 2.1.0` runs its own thread by default (`loop_start()` spawns a daemon thread) or requires manual `loop()` ticks from an asyncio task — neither matches the rest of HPC's pure-asyncio pattern. The `paho.mqtt.python/examples/loop_asyncio.py` example exists but is rough: bare `add_reader`/`add_writer` integration with no built-in reconnect-with-backoff, no async iteration over messages, manual queue plumbing. `aiomqtt` is ~1.5k LOC wrapping paho and is the path Home Assistant Core itself takes for its MQTT integration. Choosing `aiomqtt` over raw paho saves ~200 LOC of glue code we'd otherwise rewrite. |
| `aiomqtt>=2.5,<3` | **`gmqtt 0.7.0`** | Pure-Python MQTT 5 client with native asyncio API. Verdict: **inactive** per Snyk's package-health analysis (no PR activity in the last month, low repo cadence, only released versions occasionally in the past year). Wialon maintains it for their internal product. For a feature that touches the LWT/birth/discovery flow that HA users will exercise hard, betting on an inactive client is a risk. `aiomqtt` ships releases monthly (2.5.0 Jan 2026, 2.5.1 Mar 2026, 3.0.0a1 Apr 2026) and is the de-facto Python asyncio MQTT client today. |
| `aiomqtt>=2.5,<3` | **`fastapi-mqtt`** | Wraps `gmqtt`. Inherits gmqtt's maintenance risk. Adds a FastAPI-specific API surface (decorators, dependency providers) that's nice but ties HA discovery code to FastAPI lifecycle assumptions. We already manage lifecycle explicitly in `main.py:lifespan`; no extra abstraction needed. |
| `aiomqtt>=2.5,<3` | **`asyncio-mqtt`** (PyPI predecessor) | Same code base — `asyncio-mqtt` was renamed to `aiomqtt` in 2023 when the project moved namespaces. PyPI `asyncio-mqtt` now redirects/deprecates. Use the new name. |
| `aiomqtt>=2.5,<3` | **`asyncio-paho`** | Thin asyncio shim over paho. Less idiomatic than aiomqtt (still callback-flavored API surface) and less popular (~150 stars vs aiomqtt ~1.1k). No advantage. |
| **Markdown in `docs/home-assistant/`** | **MkDocs / Sphinx site** | The user explicitly scopes this as a local LAN tool with no public website. A static-site generator would add CI complexity for zero benefit — the YAML snippets ship as text users copy/paste into their own `configuration.yaml`. |
| **`StatusBroadcaster` second channel** | **`websockets` library directly** | FastAPI's WebSocket support is Starlette-based; we'd be reinventing what already works in `routers/streaming_ws.py`. Plus `websockets` would mean a separate event-loop client list to track. |
| **Extend `HaStatusResponse`** | **Separate `/api/ha/wled` endpoint** | Each HA REST poll cost is one HTTP round-trip. Adding a second endpoint forces HA users to make two `rest_command:` definitions or two `sensor:` polls instead of one. Field-additive on the existing payload is strictly better. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `homeassistant-api` (PyPI, GrandMoff100) | Wraps **HA's outbound REST/WebSocket API** — i.e., HPC would call HA to read entity states and call services. That's the inverse of v1.3's design (HA calls HPC; HPC publishes MQTT discovery so HA pulls it). Would also force storing an HA long-lived access token in HPC, violating the no-auth-no-secrets boundary already documented in v1.2's STACK.md "What NOT to Use" line. | (a) HA's MQTT integration consumes our retained discovery messages; (b) HA's `rest_command:` calls our existing `/api/ha/*` endpoints. Both are pull-from-HA, not push-from-HPC. |
| `hass-client` / `hassapi` / `HomeAssistant API` | Same reason as above — all are HA outbound API wrappers, not "be a Home Assistant integration" libraries. None of them help us publish HA-conformant MQTT topics. | Direct `aiomqtt.Client.publish(topic, payload)` of HA discovery JSON. |
| `python-homeassistant` | Does not exist as a publicly maintained package on PyPI. The name occasionally appears in search results for `homeassistant` (the Home Assistant Core distribution itself, which would pull in 100+ MB of irrelevant Core dependencies). | Not applicable — there is nothing here to install. |
| `homeassistant` (HA Core itself, PyPI) | This is the entire HA Core supervisor/runtime as a PyPI package. Pulls hundreds of dependencies. Designed to be a HA install, not a library. | Direct MQTT discovery message publishing with `aiomqtt`. |
| `paho-mqtt` raw threading mode (`loop_start()`) | Spawns a non-daemon background thread that runs paho's own select() loop. Cleanup ordering against asyncio shutdown is fragile (LWT may or may not flush). | `aiomqtt` async context manager — clean `async with` shutdown publishes the offline availability message reliably. |
| Retained discovery messages without LWT planning | HA docs explicitly warn: "retained messages can create ghost entities that keep coming back" if HPC ever changes its discovery prefix or device id. | Pair `retain=True` discovery with a documented `unique_id` per entity that **never changes** for the install (suggest `huepicturecontrol_<sha256-of-hostname-or-machine-id>[:12]`). Re-publish on `homeassistant/status == "online"` birth message. |
| `mqtt://broker:1883` insecure auth over WAN | Out of scope; HPC is LAN-only by design. | Document MQTT username/password in plain HPC config; explicitly note in the YAML doc that this is for trusted LAN brokers only — same trust boundary as the rest of HPC. |
| Static-site doc generator (Sphinx, MkDocs, Docusaurus) | No public docs site exists for this project. Adds CI/build complexity. | Plain `.md` files alongside the YAML snippets. GitHub renders them natively if/when the repo is published. |
| Background reconnect loop hand-rolled in HPC | `aiomqtt 2.x` does NOT auto-reconnect — the `async with Client(...)` block exits on disconnect by design. Hand-rolling a `while True: try: async with Client(...): ... except MqttError: await asyncio.sleep(backoff)` is the documented pattern in `aiomqtt`'s "Alongside FastAPI" guide. | Use the documented `aiomqtt` reconnect loop pattern verbatim — ~10 lines, well-trodden. Don't import a "reconnect helper" library. |

---

## MQTT 5.0 vs 3.1.1 Decision

**Recommendation:** **Connect with MQTT 5.0 (`aiomqtt.Client(..., protocol=aiomqtt.ProtocolVersion.V5)`), fall back to 3.1.1 only on connect failure.**

Rationale:
- Mosquitto 2.x defaults to MQTT 5 since 2020; almost all HA deployments use Mosquitto 2.x or EMQX (5.0-native).
- HA's MQTT integration handles both transparently. HA discovery payloads are identical on the wire.
- MQTT 5 gives us reason codes (better error reporting) and richer LWT properties (will-delay-interval — useful so a quick HPC restart doesn't flap entities to offline-then-online).
- The fallback is one extra try block; `aiomqtt` doesn't make this fall through automatically because the protocol-version mismatch is detected at TCP connect time, not later.

---

## License Compatibility

| Package | License | Compatible With HPC? |
|---------|---------|----------------------|
| `aiomqtt` | BSD 3-clause | Yes. Pure permissive. |
| `paho-mqtt` (transitive via aiomqtt) | Dual: EPL-2.0 OR BSD-3-Clause | Yes. Either branch is permissive; choose BSD-3 to match the rest. |
| `fastapi` (existing) | MIT | Compatible with everything above. |
| `pydantic` (existing) | MIT | Compatible. |
| `aiosqlite` (existing) | MIT | Compatible. |
| Eclipse Mosquitto (broker, user-supplied) | EPL-2.0 / EDL-1.0 | n/a — we don't link Mosquitto. We just talk MQTT to it over TCP. |

**Net:** No new license obligations. The project remains permissively licensed.

---

## Mosquitto / Broker Compatibility

`aiomqtt` is a pure-protocol MQTT client — it talks to any MQTT 3.1.1 / 5.0 conformant broker. Verified compatibility (per `aiomqtt` README + HA docs):

- Eclipse Mosquitto 2.x — primary HA OS add-on broker, verified by HA's own docs.
- EMQX 5.x — verified by EMQX's 2025 Python MQTT comparison article.
- HiveMQ CE / Cloud — same protocol surface.
- AWS IoT Core — same (with TLS + client cert; out of scope for v1.3).

For the recommended deployment (HA Mosquitto add-on on the same LAN), zero configuration is required beyond pointing HPC at `<ha-host>:1883` with the broker credentials.

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `aiomqtt>=2.5,<3` | Python 3.8–3.13 (HPC pins 3.12) | Pure async/await, no threading shim required. Uses `paho-mqtt` internally for wire-protocol parsing. |
| `aiomqtt>=2.5,<3` | `fastapi>=0.115`, `uvicorn[standard]>=0.32` | No interaction. Lives in `app.state.ha_mqtt` and is driven from `lifespan` — exactly like `coordinator`. |
| `aiomqtt>=2.5,<3` | `pytest-asyncio>=0.24` | Tests can spin up a Mosquitto container fixture or use `aiomqtt` against an in-process mock. The codebase already uses pytest-asyncio; no change. |
| `aiomqtt>=2.5,<3` | `hue-entertainment-pykit==0.9.4` | No interaction whatsoever — separate sockets, separate event-loop tasks. The DTLS streaming path (Hue) and the MQTT publisher coexist as peers of `coordinator`. |
| `paho-mqtt 2.1.0` (transitive) | Python 3.7+ | Pulled in automatically; do NOT list separately in `requirements.txt` — version-pinning the transitive directly causes upgrade lock-step issues. |
| **Avoid pinning** `paho-mqtt` in `requirements.txt` | — | Let `aiomqtt` resolve it. Pinning both creates a dependency-resolver footgun when `aiomqtt 2.6` or 3.0 changes its paho requirement range. |

---

## Installation

Add to `Backend/requirements.txt` (one line):

```
aiomqtt>=2.5,<3
```

Install:

```bash
source /tmp/hpc-venv/bin/activate && pip install -r Backend/requirements.txt
```

No system packages required (`paho-mqtt` is pure Python). No Docker rebuild beyond the standard `pip install` step.

---

## Sources

- [aiomqtt on PyPI](https://pypi.org/project/aiomqtt/) — v2.5.1 (Mar 2026), v3.0.0a1 (Apr 2026); BSD-3-Clause; Python 3.8–3.13; depends on `paho-mqtt`; supports MQTT 5.0/3.1.1/3.1. **HIGH confidence.**
- [empicano/aiomqtt GitHub README](https://github.com/empicano/aiomqtt) — idiomatic asyncio MQTT, no callbacks, `async with` lifecycle. **HIGH confidence.**
- [aiomqtt Alongside FastAPI guide](https://aiomqtt.bo3hm.com/alongside-fastapi-and-co.html) — canonical FastAPI lifespan integration pattern, reconnect-loop recipe. **HIGH confidence.**
- [paho-mqtt on PyPI](https://pypi.org/project/paho-mqtt/) — v2.1.0 (Apr 2024); EPL-2.0 OR BSD-3-Clause; threaded + asyncio-glue examples but no native async API. **HIGH confidence.**
- [Home Assistant MQTT integration docs](https://www.home-assistant.io/integrations/mqtt/) — discovery topic format `<discovery_prefix>/<component>/[<node_id>/]<object_id>/config`; retain-flag tradeoffs; `homeassistant/status` birth message; LWT/availability; device-bundle discovery (`homeassistant/device/<object_id>/config`); `unique_id` requirement. **HIGH confidence.**
- [HA MQTT publish API changes blog (developers.home-assistant.io, 2026-05-11)](https://developers.home-assistant.io/blog/2026/05/11/mqtt-publish-api-changes/) — recent API tweaks; confirms discovery topic format unchanged. **HIGH confidence.**
- [HA MQTT Switch component](https://www.home-assistant.io/integrations/switch.mqtt/), [MQTT Sensor](https://www.home-assistant.io/integrations/sensor.mqtt/), [MQTT Select](https://www.home-assistant.io/integrations/select.mqtt/) — component-specific discovery payload schemas (state_topic, command_topic, options, etc.). **HIGH confidence.**
- [gmqtt PyPI / Snyk health](https://snyk.io/advisor/python/gmqtt) — v0.7.0; classified **inactive** by maintenance cadence. Disqualifies it for HA-critical surface. **MEDIUM confidence** (signal-based judgment, not failure data).
- [Eclipse Mosquitto](https://mosquitto.org/) — broker license EPL/EDL; MQTT 5.0/3.1.1/3.1 conformant. **HIGH confidence.**
- [Comparison of Python MQTT Clients, EMQ 2025](https://www.emqx.com/en/blog/comparision-of-python-mqtt-client) — Independent comparison ranking aiomqtt as the leading asyncio choice over gmqtt and fastapi-mqtt for production. **MEDIUM confidence** (vendor blog but cites concrete benchmarks).
- [GrandMoff100/HomeAssistantAPI](https://homeassistantapi.readthedocs.io/) — confirms it's an outbound REST/WS wrapper for talking TO HA, not for being a HA integration. **HIGH confidence.**

---
*Stack research for: v1.3 Home Assistant Integration Polish (MQTT discovery + WS push + WLED health + YAML docs)*
*Researched: 2026-05-12*
*Net dependency cost: +1 PyPI package (`aiomqtt`), +1 transitive (`paho-mqtt`)*
