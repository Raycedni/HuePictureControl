# Domain Pitfalls — v1.3 Home Assistant Integration Polish

**Domain:** Adding HA MQTT auto-discovery, MQTT availability/state push, WS-push for `/api/ha/status`, and per-device WLED health to an existing FastAPI + aiosqlite + HA-REST app
**Researched:** 2026-05-12
**Confidence:** HIGH (all critical pitfalls verified against official HA docs, paho/aiomqtt source, real GitHub issues, and existing project code)
**Build-on:** `.planning/phases/18-home-assistant-control-endpoints/18-RESEARCH.md` §Common Pitfalls (Pitfalls 1–6 there are still authoritative for REST-only path; this file extends to MQTT + WS push)

---

## How to read this file

Every pitfall in this file is specific to **adding the four v1.3 features to THIS codebase**, not generic MQTT advice:

- The codebase already has `StatusBroadcaster._metrics["wled_devices"]` populated (Phase 17 D-16) — pitfalls focus on consumption-side problems, not the source.
- `StreamingCoordinator.start / stop / state` is locked (Phase 17/18 contract) — no pitfall here proposes touching it.
- HA→HPC direction is locked (no outbound HA tokens) — every pitfall preserves that.
- The MQTT broker is the only **new** outbound destination — pitfalls explicitly call out new firewall/connection failure modes.

Each pitfall lists:
1. **What goes wrong** (concrete symptom)
2. **Why it happens** (root cause anchored in code or HA spec)
3. **Warning signs** (what the developer sees in logs / HA UI / tests)
4. **Prevention** (specific code pattern, config flag, or test)
5. **Phase target** (which v1.3 phase owns the fix)

---

## Critical Pitfalls

Mistakes that cause user-visible entity loss, broken HA dashboards, or wedged streaming. Address before merging the relevant phase.

### Pitfall MQTT-1: Discovery messages not retained — HA loses every HPC entity on restart

**What goes wrong:** HPC publishes `homeassistant/sensor/hpc_state/config` without `retain=True`. User restarts Home Assistant Core. After HA reboots, the HPC switch / sensors / select entities are gone (or shown as "unavailable") until HPC happens to republish.

**Why it happens:** HA's MQTT integration only knows about an entity if it received the discovery payload after MQTT subscribed. Without the broker holding a retained copy, a restarted HA sees zero discovery messages for HPC. Official HA docs ([MQTT integration](https://www.home-assistant.io/integrations/mqtt/)) explicitly state: *"A discovery payload can be sent with a retain flag set. In that case, the discovery message will be stored at the MQTT broker and processed automatically when the MQTT integrations start."* Without retention, *"all existing MQTT devices, entities, tags, and device triggers, will be unavailable until a discovery message is received and processed."*

**Warning signs:**
- HA → Settings → Devices & Services → MQTT shows "0 devices" after HA restart
- User reports "my HPC entities disappeared from my dashboard"
- HA log `Discovery for entity ... unavailable` after a HA Core upgrade
- `mosquitto_sub -t 'homeassistant/#'` shows no retained config messages on a fresh subscriber

**Prevention:**

1. **Always publish discovery config with `retain=True`** AND **subscribe to `homeassistant/status` to republish on HA reboot.** Belt-and-suspenders. Retention covers MQTT broker survival; birth-message rediscovery covers users who manually clear retained topics or run brokers without persistence.

```python
# Backend/services/ha_mqtt_publisher.py — recommended pattern
DISCOVERY_PREFIX = "homeassistant"

async def publish_discovery(client, payload: dict, component: str, object_id: str) -> None:
    topic = f"{DISCOVERY_PREFIX}/{component}/hpc/{object_id}/config"
    await client.publish(topic, json.dumps(payload), qos=1, retain=True)  # MUST be retain=True

async def on_ha_birth(client, message) -> None:
    """Subscribe to homeassistant/status; on 'online' payload, republish all discovery messages."""
    if message.topic == "homeassistant/status" and message.payload.decode() == "online":
        logger.info("HA birth detected — republishing discovery")
        await republish_all_discovery(client)
```

2. **Cleanup on un-register:** publishing an empty retained payload to the same config topic removes the entity from HA. Reference: [HA MQTT docs](https://www.home-assistant.io/integrations/mqtt/) — *"To remove a previously discovered device, send a message with an empty payload to the discovery topic."*

```python
await client.publish(topic, payload=b"", qos=1, retain=True)  # tombstone
```

3. **Test:** integration test that publishes discovery → disconnects publisher → starts a fresh subscriber → asserts the retained config arrives. Pseudocode:

```python
async def test_discovery_survives_publisher_disconnect(broker_url):
    async with Client(broker_url) as pub:
        await pub.publish("homeassistant/sensor/hpc/state/config", payload=b'{"unique_id":"hpc_state"}', retain=True)
    # publisher gone
    async with Client(broker_url) as sub:
        await sub.subscribe("homeassistant/sensor/hpc/state/config")
        async with sub.messages() as messages:
            msg = await asyncio.wait_for(anext(messages), timeout=2)
            assert json.loads(msg.payload)["unique_id"] == "hpc_state"
```

**Anti-pattern:**

```python
# BAD — entities vanish on HA restart
await client.publish(topic, json.dumps(payload))  # default retain=False, no birth listener
```

**Phase target:** MQTT publisher phase (the phase that introduces `ha_mqtt_publisher.py`).

**Sources:**
- [HA MQTT integration docs](https://www.home-assistant.io/integrations/mqtt/) — retain-or-birth requirement, HIGH confidence
- [Community: MQTT Discovery: to retain or not?](https://community.home-assistant.io/t/mqtt-discovery-to-retain-or-not/310734) — real users describing the bug, MEDIUM confidence
- [Issue #920 docker-wyze-bridge — MQTT discovery should be re-sent on HA birth](https://github.com/mrlt8/docker-wyze-bridge/issues/920) — concrete bug from a peer project, HIGH confidence

---

### Pitfall MQTT-2: Unstable `unique_id` produces orphan entities, broken automations

**What goes wrong:** HPC restarts → generates a new `unique_id` per sensor (e.g., `uuid4()` regenerated at startup). HA sees two entities for the same sensor: the old one (now "unavailable" since the old discovery topic is no longer retained or republished) and the new one. User's automations referencing `sensor.hpc_state` break because the new entity gets ID `sensor.hpc_state_2`.

**Why it happens:** HA uses `unique_id` (from the discovery payload) as the **permanent** registry key for the entity. The entity_id (`sensor.hpc_state`) is a presentation layer derived once on first discovery. If `unique_id` changes, HA treats it as a brand-new entity. Per [HA MQTT Sensor docs](https://www.home-assistant.io/integrations/sensor.mqtt/): *"To prevent multiple identical entries if a device reconnects, a unique identifier is necessary. If two sensors have the same unique ID, Home Assistant will raise an exception."*

**Warning signs:**
- After backend restart, HA shows `sensor.hpc_state_2` alongside the original `sensor.hpc_state` (now unavailable)
- User reports "my dashboard tile shows 'unavailable' but I see a duplicate sensor"
- HA log `Platform mqtt does not generate unique IDs. ID ... already exists` (when ID accidentally **doesn't** change)
- `homeassistant/sensor/<old_id>/config` is still retained but `/<new_id>/config` was just published

**Prevention:**

Build `unique_id` from **persistent, deterministic** inputs. For HPC there are good seeds:

1. **HPC instance ID** — generate **once**, persist in a new single-row table (or reuse a hash of the SQLite DB file path). Never regenerate.

   ```python
   # database.py — append to existing CREATE TABLE blocks
   await db.execute("""
       CREATE TABLE IF NOT EXISTS hpc_identity (
           id INTEGER PRIMARY KEY CHECK (id = 1),
           instance_uuid TEXT NOT NULL,
           created_at TEXT NOT NULL
       )
   """)
   # On first lifespan startup only, insert uuid4() if row is missing.
   ```

2. **Object-level unique_id = `f"{instance_uuid}_{object}"`**

   ```python
   # GOOD — stable across restarts
   payload = {
       "unique_id": f"{instance_uuid}_state",        # e.g. "hpc-7f3e_state"
       "object_id": "hpc_state",                     # display-side hint (see Pitfall MQTT-9 — moves to default_entity_id)
       "name": "Streaming State",
       ...
   }
   ```

3. **For per-WLED-device sensors, derive from the WLED device's persisted UUID** (Phase 17 D-07 — `wled_devices.id TEXT PRIMARY KEY`). That ID is already stable across HPC restarts.

   ```python
   unique_id = f"{instance_uuid}_wled_{wled_device.id}_health"
   ```

4. **Test:** restart the app inside a test, capture the second `unique_id` for every sensor, assert equality with the first.

```python
async def test_unique_id_stable_across_restart(tmp_path):
    db_path = tmp_path / "hpc.sqlite"
    async with lifespan_app(db_path) as app1:
        ids_1 = collect_published_unique_ids(app1)
    async with lifespan_app(db_path) as app2:  # same DB → same instance UUID
        ids_2 = collect_published_unique_ids(app2)
    assert ids_1 == ids_2
```

**Anti-pattern:**

```python
# BAD — new UUID every startup
payload = {"unique_id": str(uuid.uuid4()), ...}

# ALSO BAD — hostname can change (DHCP, mDNS rename, Docker rename)
payload = {"unique_id": f"{socket.gethostname()}_state", ...}

# ALSO BAD — IP address as ID
payload = {"unique_id": f"hpc_{get_local_ip()}_state", ...}
```

**Phase target:** MQTT publisher phase (same phase as MQTT-1; the `hpc_identity` table is a new piece of DB schema).

**Sources:**
- [HA MQTT Sensor docs — unique_id semantics](https://www.home-assistant.io/integrations/sensor.mqtt/) — HIGH confidence
- [Issue #97450 home-assistant/core — duplicate entity IDs from MQTT discovery](https://github.com/home-assistant/core/issues/97450) — real bug confirming the symptom, HIGH confidence
- [Community: How to clear duplicate MQTT entities](https://homeassistant.jongriffith.com/Tutorials/Trouble-Shooting/How-To-Clear-Duplicate-MQTT-Entities-In-Home-Assistant/) — recovery procedure, MEDIUM confidence

---

### Pitfall MQTT-3: No availability topic with LWT — HA shows stale data when HPC crashes

**What goes wrong:** HPC backend crashes or its native systemd unit stops. HA dashboard continues to show the last `state_topic` value (e.g., "streaming" with last fps=60) **forever** because nothing told HA the source is dead. User assumes streaming is active when it's actually offline. Worse: HA automations triggered by `state == 'streaming'` keep firing.

**Why it happens:** MQTT is a retained-message protocol. The last published state stays on the broker. HA needs an explicit availability signal — either:
- **Last Will and Testament (LWT)** set at MQTT `CONNECT` time, published by the broker when the publisher disconnects ungracefully, OR
- **Birth message** (`online`) on connect, paired with a matching **LWT** (`offline`)

Per [Zigbee2MQTT availability docs](https://www.zigbee2mqtt.io/guide/configuration/device-availability.html) and [HA MQTT docs](https://www.home-assistant.io/integrations/mqtt/): HA supports an `availability` list per entity with `availability_mode: all|any|latest`.

**Warning signs:**
- User reports "my HA card says HPC is streaming but the backend has been off for 3 hours"
- HA card never shows the "unavailable" pill even when `curl http://hpc-host:8000/api/health` fails
- LWT message never appears at `mosquitto_sub -t 'hpc/availability'` because the publisher never registered one
- After HPC `kill -9`, HA entity stays `state: streaming` indefinitely

**Prevention:**

1. **Set LWT at connect time** using paho's `will_set` / aiomqtt's `will=` parameter. The LWT publishes to a HPC-specific availability topic with `offline` payload, **retained**.

```python
# Backend/services/ha_mqtt_publisher.py — aiomqtt example
import aiomqtt

AVAILABILITY_TOPIC = "hpc/availability"  # NOT under homeassistant/ — separate namespace

async def run_publisher():
    will = aiomqtt.Will(
        topic=AVAILABILITY_TOPIC,
        payload=b"offline",
        qos=1,
        retain=True,
    )
    async with aiomqtt.Client("mqtt.local", will=will) as client:
        # Birth message — publish online IMMEDIATELY after connect
        await client.publish(AVAILABILITY_TOPIC, b"online", qos=1, retain=True)
        # ... rest of publisher
```

2. **Every discovery payload includes `availability`**:

```python
discovery_payload = {
    "unique_id": f"{instance_uuid}_state",
    "name": "Streaming State",
    "state_topic": "hpc/state",
    "availability": [
        {"topic": "hpc/availability", "payload_available": "online", "payload_not_available": "offline"}
    ],
    "device": {...},
}
```

3. **Graceful shutdown publishes `offline` explicitly** before disconnecting (so HA gets the update without waiting for broker LWT timeout, which is typically `keepalive * 1.5`).

```python
# In FastAPI lifespan shutdown:
await client.publish(AVAILABILITY_TOPIC, b"offline", qos=1, retain=True)
await client.disconnect()  # only AFTER the offline publish has flushed
```

4. **Multi-source availability:** if HPC is online but its capture loop is degraded, expose a second availability source. Match the Zigbee2MQTT pattern with `availability_mode: all`:

```python
"availability": [
    {"topic": "hpc/availability", "payload_available": "online", "payload_not_available": "offline"},
    {"topic": "hpc/streaming/health", "payload_available": "ok", "payload_not_available": "degraded"},
],
"availability_mode": "all",  # both must be "online" for entity to be available
```

**Anti-pattern:**

```python
# BAD — no LWT, no availability_topic, no birth message
async with aiomqtt.Client("mqtt.local") as client:
    await client.publish("hpc/state", "streaming", retain=True)  # set and forget — HA never knows when HPC dies
```

**Phase target:** MQTT publisher phase. LWT must be in the **same** phase that introduces the MQTT publisher class — it cannot be added later without re-publishing all retained configs.

**Sources:**
- [HA MQTT docs — availability](https://www.home-assistant.io/integrations/mqtt/) — HIGH confidence
- [Zigbee2MQTT availability docs](https://www.zigbee2mqtt.io/guide/configuration/device-availability.html) — proven LWT pattern, HIGH confidence
- [paho-mqtt client docs — will_set](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) — API reference, HIGH confidence

---

### Pitfall MQTT-4: MQTT broker disconnect wedges the FastAPI lifespan / blocks `/api/ha/start`

**What goes wrong:** The MQTT broker is on a separate host. Network blip → broker becomes unreachable. The MQTT publisher's `publish()` call blocks (paho-mqtt 1.x default) or queues unbounded (paho-mqtt 2.x), and the next `POST /api/ha/start` hangs because the HA endpoint awaits the publisher's state update. Worse: if MQTT loop is integrated naively into the FastAPI event loop, the entire app stops processing requests.

**Why it happens:** paho-mqtt's synchronous `loop_*` calls block. The community [aiomqtt v3](https://pypi.org/project/aiomqtt/) is pure asyncio (no threads, uses `mqtt5` sans-io under the hood) and is the recommended choice for new asyncio code. Even with aiomqtt, `client.publish()` returns immediately but the underlying network write may stall; reconnects must be explicit. Per paho [issue #331](https://github.com/eclipse-paho/paho.mqtt.python/issues/331), reconnect can take >40 seconds with default settings.

This codebase already uses `asyncio.to_thread` for blocking syscalls (capture ioctls per `capture_v4l2.py`). The same isolation discipline is mandatory for MQTT.

**Warning signs:**
- `POST /api/ha/start` hangs >5 seconds when MQTT broker is unreachable
- `curl http://localhost:8000/api/health` times out during broker outage
- Backend log shows MQTT reconnect attempts piling up (`Connection refused: 111`) but no other endpoints respond
- Test `test_ha_start_works_when_mqtt_broker_down` fails

**Prevention:**

1. **MQTT publisher MUST be a sibling background task, never inline in request handlers.** No `await client.publish(...)` inside `routers/ha.py` — those handlers must remain MQTT-agnostic. Mirror the `StatusBroadcaster` pattern:

```python
# Backend/services/ha_mqtt_publisher.py
class HaMqttPublisher:
    """Background MQTT publisher. Resilient to broker disconnect.

    NEVER blocks request handlers. State and discovery publishes are
    fire-and-forget into an asyncio.Queue; a single background task drains
    the queue and survives broker reconnects with exponential backoff.
    """
    def __init__(self, broker_url: str, broadcaster: StatusBroadcaster):
        self._queue: asyncio.Queue[tuple[str, bytes, bool]] = asyncio.Queue(maxsize=1024)
        self._task: asyncio.Task | None = None
        self._broker_url = broker_url
        self._broadcaster = broadcaster

    def publish_nowait(self, topic: str, payload: bytes, retain: bool = False) -> None:
        """Called from anywhere — including request handlers. Non-blocking."""
        try:
            self._queue.put_nowait((topic, payload, retain))
        except asyncio.QueueFull:
            logger.warning("MQTT queue full — dropping publish to %s", topic)

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with aiomqtt.Client(self._broker_url, will=LWT) as client:
                    await client.publish(AVAILABILITY_TOPIC, b"online", retain=True)
                    await self._publish_all_discovery(client)
                    await client.subscribe("homeassistant/status")
                    backoff = 1.0  # reset on successful connect
                    await self._drain_loop(client)
            except aiomqtt.MqttError as exc:
                logger.warning("MQTT disconnect: %s — reconnecting in %.1fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)  # exponential, capped at 60s
```

2. **Bounded queue** (e.g., 1024 entries). Per [paho-mqtt docs](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html), *"A client will never discard its own outgoing messages on disconnect"* — unbounded growth during a multi-hour broker outage can OOM the backend. Drop oldest / log on full queue.

3. **Exponential backoff with cap.** 1s → 2s → 4s → 8s → … → 60s. Reset on successful reconnect. Anchored to the same pattern the Hue bridge reconnect uses today.

4. **Health-check exposure:** `GET /api/health` should include `mqtt_connected: bool` if MQTT is configured. Failures must NOT 500 the endpoint — same graceful-degradation pattern as Phase 18 Pitfall 4 (bridge errors).

5. **Lifespan teardown:**

```python
# main.py lifespan — startup
publisher = HaMqttPublisher(broker_url, broadcaster)
publisher._task = asyncio.create_task(publisher._run())
app.state.mqtt_publisher = publisher

yield

# shutdown — explicit offline + cancel
publisher.publish_nowait(AVAILABILITY_TOPIC, b"offline", retain=True)
await asyncio.sleep(0.1)  # give the drain loop one tick
publisher._task.cancel()
with suppress(asyncio.CancelledError):
    await publisher._task
```

**Anti-pattern:**

```python
# BAD — request handler awaits MQTT directly
@router.post("/start")
async def ha_start(request: Request):
    await coordinator.start(...)
    await request.app.state.mqtt.publish("hpc/state", "streaming")  # blocks if broker down
    return ...

# ALSO BAD — paho's blocking loop_forever() inside asyncio
import paho.mqtt.client as mqtt
client = mqtt.Client()
client.loop_forever()  # blocks the entire event loop
```

**Phase target:** MQTT publisher phase.

**Sources:**
- [aiomqtt PyPI / GitHub](https://pypi.org/project/aiomqtt/) — recommended asyncio-first client, HIGH confidence
- [paho-mqtt Issue #331 — reconnect takes >40s](https://github.com/eclipse-paho/paho.mqtt.python/issues/331) — verifies the symptom, HIGH confidence
- [paho-mqtt Issue #276 — fails to reconnect when heavily publishing QoS 2](https://github.com/eclipse-paho/paho.mqtt.python/issues/276) — known wedge mode, HIGH confidence
- [EMQX 2025 Python MQTT client comparison](https://www.emqx.com/en/blog/comparision-of-python-mqtt-client) — aiomqtt as the 2025 production choice, MEDIUM confidence

---

### Pitfall MQTT-5: Topic-namespace collisions when user runs two HPC instances on one broker

**What goes wrong:** User has two HPC instances (e.g., living room + bedroom). Both publish `homeassistant/sensor/hpc_state/config` to the same broker. The second one overwrites the first's retained config. HA shows only one entity that flip-flops between the two backends. Confusion ensues.

**Why it happens:** MQTT topics are flat strings; the broker doesn't know which client published what. If two HPC instances share an `object_id` slot (`hpc`), the last writer wins. The Phase 18 endpoints use `/api/ha/` for the HTTP namespace, but MQTT topics are a different namespace that needs equal care.

**Warning signs:**
- User reports "I added a second HPC and now my dashboard alternates between them"
- `mosquitto_sub -t 'homeassistant/sensor/+/config'` shows the same `unique_id` published from two distinct `device.identifiers`
- HA → MQTT integration → "Devices" tab shows only one device when there should be two

**Prevention:**

1. **Always include the persistent `instance_uuid` in the MQTT object_id segment** (the `<object_id>` in `<discovery_prefix>/<component>/[<node_id>/]<object_id>/config`):

```python
# GOOD — instance-scoped
def discovery_topic(component: str, object_id: str) -> str:
    return f"homeassistant/{component}/hpc-{INSTANCE_UUID_SHORT}/{object_id}/config"

# Result: homeassistant/sensor/hpc-7f3e/state/config
```

2. **`device.identifiers` must include the same instance UUID** so HA's device registry treats them as separate devices:

```python
"device": {
    "identifiers": [f"hpc-{INSTANCE_UUID}"],  # unique per HPC instance
    "name": INSTANCE_DISPLAY_NAME,            # user-editable, e.g. "HPC Living Room"
    "manufacturer": "HuePictureControl",
    "model": "v1.3",
    "sw_version": APP_VERSION,
},
```

3. **`device.name` should be user-configurable** via a new env var or settings field (e.g., `HPC_INSTANCE_NAME=Living Room`). Without this, two instances show as "HuePictureControl" / "HuePictureControl" — visually identical.

4. **Test:** spin up two `HaMqttPublisher` instances with different `INSTANCE_UUID` against an embedded broker; assert four retained configs, two distinct `device.identifiers`.

**Anti-pattern:**

```python
# BAD — hard-coded object_id collides between instances
topic = "homeassistant/sensor/hpc/state/config"

# ALSO BAD — IP-based device.identifier (changes with DHCP)
"device": {"identifiers": [f"hpc-{local_ip}"]}
```

**Phase target:** MQTT publisher phase. The `INSTANCE_UUID` is the same persistent value introduced for Pitfall MQTT-2.

**Sources:**
- [HA MQTT discovery topic format docs](https://www.home-assistant.io/integrations/mqtt/) — `<discovery_prefix>/<component>/[<node_id>/]<object_id>/config`, HIGH confidence
- [HA MQTT Sensor — device registry block](https://www.home-assistant.io/integrations/sensor.mqtt/) — HIGH confidence

---

### Pitfall MQTT-6: Using deprecated `object_id` field (will break in HA Core 2026.4)

**What goes wrong:** HPC publishes discovery payloads using `"object_id"` to set the default entity ID. HA 2025.10+ logs deprecation warnings. HA 2026.4 (April 2026 — **within this milestone's likely production lifespan**) removes the field entirely. After a HA upgrade, all HPC entities lose their custom entity IDs and revert to auto-generated names.

**Why it happens:** HA introduced `default_entity_id` to replace `object_id` (which had overloaded semantics — sometimes a topic component, sometimes an entity-ID default). The deprecation warning appears in HA Core 2025.10.0b0; complete removal targets 2026.4. Zigbee2MQTT, EMS-ESP, and other major MQTT projects have migrated.

**Warning signs:**
- HA log shows `The configuration for entity hpc_state uses the deprecated option 'object_id' to set the default entity id`
- After upgrading HA to 2026.4+, entity IDs change from `sensor.hpc_state` to `sensor.<unique_id>` (typically a UUID-looking blob)
- User automations referencing the old entity ID break

**Prevention:**

Use `default_entity_id` with the **fully qualified** entity ID (including the entity type prefix):

```python
# GOOD — works in 2025.10+ and 2026.4+
discovery_payload = {
    "unique_id": f"{INSTANCE_UUID}_state",
    "default_entity_id": "sensor.hpc_state",  # full prefix required
    "name": "Streaming State",
    "state_topic": "hpc/state",
    ...
}
```

**Anti-pattern:**

```python
# BAD — will be removed in HA 2026.4
discovery_payload = {
    "unique_id": f"{INSTANCE_UUID}_state",
    "object_id": "hpc_state",  # deprecated; warning since 2025.10
    ...
}
```

**Important nuance:** the `object_id` *URL segment* in the **discovery topic** (`homeassistant/sensor/<node>/<object_id>/config`) is NOT deprecated — only the `object_id` *field* inside the discovery payload. Pitfall MQTT-5's topic-namespacing recommendation still uses the URL segment correctly.

**Phase target:** MQTT publisher phase. Catch this before merge — easy to miss because HA pre-2025.10 silently accepted it.

**Sources:**
- [Issue #157763 home-assistant/core — `object_id` deprecation](https://github.com/home-assistant/core/issues/157763) — HIGH confidence
- [Issue #28728 zigbee2mqtt — 2025.10.0b0 deprecation warnings](https://github.com/Koenkk/zigbee2mqtt/issues/28728) — HIGH confidence
- [Community: MQTT object_id vs default_entity_id warning](https://community.home-assistant.io/t/mqtt-object-id-vs-default-entity-id-warning/937665) — migration guide, HIGH confidence

---

### Pitfall WS-1: WS subscriber leaks / race when multiple HA clients connect to one broadcaster

**What goes wrong:** Multiple HA dashboards (or a HA Core + a NodeRED instance) open WS connections to `/ws/ha-status`. One client's network drops silently (mobile dashboard backgrounded). The broadcaster's `_send_to_all` loop hits a slow/dead socket and either (a) blocks all other subscribers behind the dead one, or (b) raises an exception that takes down the heartbeat task, freezing every dashboard.

**Why it happens:** Per the existing `StatusBroadcaster._send_to_all` ([Backend/services/status_broadcaster.py:101](Backend/services/status_broadcaster.py)), the loop iterates connections **sequentially**:

```python
for ws in list(self._connections):
    try:
        await ws.send_text(payload)
    except Exception:
        dead.append(ws)
```

This is safe for the current usage (web UI clients on LAN, low count), but the **new HA WS push** endpoint may receive subscribers from HA's REST→WS adapter or NodeRED's MQTT-via-WS proxies that hold sockets open without sending pings. Per [2025 FastAPI WS patterns](https://websocket.org/guides/frameworks/fastapi/), *"the broadcast method should catch send failures and clean up dead connections, otherwise a single disconnected client that hasn't triggered WebSocketDisconnect yet blocks the entire broadcast loop."*

**Warning signs:**
- HA dashboard A updates in real-time, dashboard B never updates (stuck on old payload)
- Backend log shows `WebSocket send failed, marking for removal` only after a minute-long delay
- Backend RAM grows steadily because dead WS connection objects accumulate
- `len(broadcaster._connections)` reported via diagnostic endpoint grows beyond expected count

**Prevention:**

1. **Add a per-client `asyncio.Queue` and per-client sender task.** Fan-out via queue rather than direct iteration. Each slow client blocks only itself.

```python
# Backend/services/ha_ws_pusher.py — sibling to StatusBroadcaster, dedicated to HA WS clients
class HaWsPusher:
    def __init__(self) -> None:
        self._clients: dict[WebSocket, asyncio.Queue[str]] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=16)  # bounded — drop on slow client
        self._clients[ws] = q
        asyncio.create_task(self._sender(ws, q))

    async def _sender(self, ws: WebSocket, q: asyncio.Queue) -> None:
        try:
            while True:
                payload = await q.get()
                await ws.send_text(payload)
        except (WebSocketDisconnect, RuntimeError, ConnectionClosed):
            pass
        finally:
            self._clients.pop(ws, None)

    async def broadcast(self, payload: dict) -> None:
        text = json.dumps(payload)
        for ws, q in list(self._clients.items()):
            try:
                q.put_nowait(text)
            except asyncio.QueueFull:
                # drop frame for this slow client; do not block others
                logger.debug("WS queue full for HA client; dropping frame")
```

2. **Add a `WebSocketDisconnect` handler explicitly** in the route handler. Don't rely on `Exception` catches alone — uvicorn raises `WebSocketDisconnect`, which is a `Starlette` exception not a `ConnectionError`.

3. **Bounded queue per client** (16 frames is plenty for status; the broadcaster only emits state transitions + 1 Hz heartbeats). On full queue, drop the new frame — the client will catch up on next heartbeat.

4. **Same `_metrics` source as existing `/ws/status`.** Do not duplicate metric collection. Hook `HaWsPusher.broadcast` into `StatusBroadcaster.push_state` and the existing 1 Hz heartbeat so both channels stay consistent.

5. **Test:** open three WS clients, kill one with `socket.shutdown()` mid-stream, assert the other two still receive the next push within 1s.

**Anti-pattern:**

```python
# BAD — single dead client blocks everyone
async def broadcast(self, payload):
    for ws in self._clients:
        await ws.send_text(payload)  # blocks here if one client is slow

# ALSO BAD — exception in one client kills the task
async def heartbeat_loop(self):
    while True:
        await asyncio.sleep(1)
        for ws in self._clients:
            await ws.send_text(payload)  # uncaught exception terminates the loop
```

**Phase target:** WS push phase. Note: this is **not** a refactor of the existing `StatusBroadcaster` — that one stays for the web UI. The HA WS push is a new sibling endpoint. (See PITFALL-INTEGRATION-2 below for why.)

**Sources:**
- [FastAPI WebSocket patterns 2025](https://websocket.org/guides/frameworks/fastapi/) — fan-out and dead-client cleanup, HIGH confidence
- [Existing `StatusBroadcaster._send_to_all`](Backend/services/status_broadcaster.py) — current sequential loop, code review, HIGH confidence
- [2025 FastAPI WS scaling article](https://hexshift.medium.com/how-to-incorporate-advanced-websocket-architectures-in-fastapi-for-high-performance-real-time-b48ac992f401) — per-client queue pattern, MEDIUM confidence

---

## Moderate Pitfalls

Mistakes that confuse users or produce edge-case bugs but don't break the system.

### Pitfall MQTT-7: Mixing MQTT discovery with HA REST `rest_command:` doubles every entity

**What goes wrong:** A power user followed the Phase 18 docs to set up HA YAML `rest_command:` and template sensors **and** turned on MQTT auto-discovery. Now their HA UI has two of everything: `sensor.hpc_state` (from YAML template) and `sensor.hpc_streaming_state` (from MQTT discovery). Automations trigger twice.

**Why it happens:** The two integration paths are independent — HPC doesn't know HA has YAML configured, and HA doesn't dedupe across config sources. The Phase 18 design intentionally left both paths open ("MQTT for zero-YAML users, REST+YAML for power users") — but didn't define behavior when both are configured.

**Warning signs:**
- User reports duplicate entities (mirror image of MQTT-2 but from different cause — distinguishable because both entities are *available*, not one orphaned)
- Two switch entities both toggle the same backend state
- HA log shows two state updates per change (one from MQTT push, one from REST polling result)

**Prevention:**

1. **Explicit opt-in for MQTT.** MQTT publishing is OFF by default and requires `HPC_MQTT_BROKER` env var (or settings UI toggle) to enable. Without the env var, HPC never connects.

2. **Document the choice clearly** in the HA YAML snippet docs:

> Use **either** the MQTT integration **or** the REST/YAML approach. Do not configure both. If you want the zero-YAML experience and have an MQTT broker available, set `HPC_MQTT_BROKER=mqtt://...`. If you want full control over entity IDs, areas, and templates, use the YAML approach and leave the MQTT env var unset.

3. **Add a startup log line:** `MQTT publisher enabled — HA YAML rest_command/sensor entries are redundant and should be removed`. Visible in the systemd journal so users notice.

4. **Don't try to detect the YAML configuration server-side.** HPC has no way to read HA's YAML files. Documentation + opt-in is the right design.

**Phase target:** YAML documentation phase (where the YAML snippet docs are written) — the warning text and opt-in env var ship there.

**Sources:**
- Phase 18 RESEARCH.md — both paths designed independently, HIGH confidence (verified in `.planning/phases/18-home-assistant-control-endpoints/18-RESEARCH.md`)

---

### Pitfall MQTT-8: WLED-device sensor explosion overwhelms HA UI with 50+ entities

**What goes wrong:** User has 8 WLED devices. The MQTT publisher creates one sensor per `wled_devices[device_id]` × per field (`last_error`, `last_success_at`, `in_cooldown`). That's 24 sensors just for WLED, plus the core HPC sensors, totaling 30+. HA dashboard becomes cluttered; user can't find the entities they care about.

**Why it happens:** A naive 1:1 mapping of `broadcaster._metrics["wled_devices"]` to individual sensors produces explosion. Each WLED device has 3 fields tracked (`last_error`, `last_success_at`, `in_cooldown` per Phase 17 D-16) which would naively become 3 entities each.

Worse: each new WLED device add triggers a new round of `/config` publishes. The user might not even realize they're adding 3 entities every time they register a strip.

**Warning signs:**
- User reports "my MQTT integration has 47 HPC entities, what do I do?"
- HA → MQTT → Devices → "HuePictureControl" shows dozens of entities marked `diagnostic`

**Prevention:**

1. **Group per-WLED fields under ONE entity using JSON attributes.** HA's `json_attributes_topic` makes this trivial: one sensor per WLED device, attributes for the fields:

```python
# GOOD — one sensor per WLED device with all fields as attributes
discovery_payload = {
    "unique_id": f"{INSTANCE_UUID}_wled_{wled_id}",
    "default_entity_id": f"sensor.hpc_wled_{slugify(wled_name)}",
    "name": f"WLED {wled_name}",
    "state_topic": f"hpc/wled/{wled_id}/state",        # "ok" | "error" | "cooldown"
    "json_attributes_topic": f"hpc/wled/{wled_id}/attrs",  # {last_error, last_success_at, in_cooldown}
    "entity_category": "diagnostic",                   # collapses into device's "diagnostic" section
    "availability": [...],
    "device": {"identifiers": [f"hpc-{INSTANCE_UUID}"], ...},
}
```

This collapses 3N → N entities. User sees one sensor per WLED device; attributes are inspectable via the entity dialog.

2. **`entity_category: diagnostic`** on per-device sensors. HA renders diagnostic entities in a collapsed section by default, reducing dashboard clutter. Reference: [HA MQTT Sensor docs](https://www.home-assistant.io/integrations/sensor.mqtt/) — `entity_category` is supported and used by mature integrations.

3. **Aggregate sensor: `sensor.hpc_wled_devices_healthy`** — a single counter showing `N healthy / M total` for users who don't want device-level detail.

4. **Discovery throttling:** when the user adds N WLED devices in rapid succession (zeroconf scan returns 12 devices, user clicks "Add all"), batch the discovery publishes with `asyncio.gather` rather than per-add. Spread by ~50ms to avoid broker QoS-1 backlog spikes.

5. **Test:** registering a WLED device produces exactly 1 sensor in HA, with the per-field state as attributes:

```python
async def test_wled_sensor_groups_fields_as_attributes(mqtt_broker, hpc_app):
    await register_wled(hpc_app, ip="192.168.1.50")
    configs = await collect_published_configs(mqtt_broker, prefix="homeassistant/sensor/hpc-")
    wled_configs = [c for c in configs if "wled" in c["unique_id"]]
    assert len(wled_configs) == 1, f"Expected 1 WLED sensor, got {len(wled_configs)}: {[c['unique_id'] for c in wled_configs]}"
    assert "json_attributes_topic" in wled_configs[0]
```

**Anti-pattern:**

```python
# BAD — 3 entities per WLED device
for device_id, health in wled_devices.items():
    for field in ("last_error", "last_success_at", "in_cooldown"):
        publish_discovery(f"sensor/{device_id}_{field}", ...)
```

**Phase target:** WLED-per-device phase (the one extending `/api/ha/status` and MQTT to cover the existing `broadcaster._metrics["wled_devices"]` dict).

**Sources:**
- [HA MQTT Sensor — json_attributes_topic, entity_category](https://www.home-assistant.io/integrations/sensor.mqtt/) — HIGH confidence
- Phase 17 `StatusBroadcaster._metrics["wled_devices"]` shape — verified in `Backend/services/status_broadcaster.py:36`

---

### Pitfall HA-1: Template sensors break dashboards on missing keys / null values

**What goes wrong:** HA YAML snippet docs ship a template sensor referencing `{{ value_json.fps }}`. After v1.4 adds a new top-level field, the JSON shape changes. Or — in v1.3 — HPC returns `fps: null` when idle. The template sensor evaluates to `unknown`, dashboard tile turns gray, conditional cards disappear.

**Why it happens:** Jinja2 templates fail loudly on missing keys (`UndefinedError`) and silently on null arithmetic (`null + 1 → null → 'unknown'`). HA template sensors render `unknown` for both — but the cascade effect on dashboards is the same regardless of cause.

This isn't theoretical — Phase 18 [Pitfall 4](.planning/phases/18-home-assistant-control-endpoints/18-RESEARCH.md) already addresses one variant (bridge timeout → null `active_config_name`). v1.3's per-WLED additions to `/api/ha/status` and the WS push are new vectors.

**Warning signs:**
- HA log: `Template sensor sensor.hpc_fps_avg encountered TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'`
- Dashboard card "HPC Status" shows `unknown` instead of `Idle`
- Conditional card `state == 'streaming'` disappears entirely (because state is `unknown`, not `streaming` or anything else)

**Prevention:**

1. **YAML snippets MUST use defensive Jinja:**

```yaml
# GOOD — defensive
sensor:
  - platform: rest
    resource: http://hpc.local:8000/api/ha/status
    name: hpc_state
    value_template: "{{ value_json.state | default('unknown') }}"
    json_attributes_path: "$"
    json_attributes:
      - state
      - active_config_name
      - active_camera_name
      - fps
      - latency_ms

# BAD — breaks the moment a field is missing
value_template: "{{ value_json.state }}"

# BAD — null arithmetic
value_template: "{{ (value_json.fps + value_json.latency_ms) | round(0) }}"
```

2. **Stable JSON contract.** The Phase 18 D-09 status payload is **locked**. v1.3 additions (`wled_devices`) MUST be **additive only**:

   - Add new top-level keys; never rename or remove existing ones.
   - New keys default to safe values: `wled_devices: {}` (empty dict, not null), `wled_devices_healthy: 0`, etc.
   - Document the contract version in the response (`schema_version: 1`).

3. **`/api/ha/status` response schema:**

```python
class HaStatusResponse(BaseModel):
    # Phase 18 locked fields — DO NOT change
    state: str
    active_config_id: str | None = None
    # ... (rest as in Backend/routers/ha.py:66-80)

    # v1.3 ADDITIVE fields — safe defaults, not None
    wled_devices: dict[str, dict] = Field(default_factory=dict)  # NOT None, ALWAYS a dict
    wled_devices_healthy: int = 0
    wled_devices_total: int = 0
```

4. **`response_model_exclude_none=True`** is already used (line 185 of `routers/ha.py`) — keep using it for **optional** fields, but **NOT** for the new WLED additions. Those should always be present (defaulting to `{}` / `0`), so HA templates can rely on them.

5. **Test the YAML snippets in CI.** Ship a `tests/ha_yaml/` directory with sample YAML; lint/validate via `python -c "import yaml; yaml.safe_load(open('rest_command.yaml'))"` and a Jinja test that runs each value_template against a sample payload.

**Phase target:** YAML documentation phase (defensive Jinja) + WLED per-device phase (additive JSON contract).

**Sources:**
- [Community: How to prevent NULL values in template sensor](https://community.home-assistant.io/t/how-to-prevent-null-values-in-template-sensor/98207) — HIGH confidence
- Phase 18 Pitfall 4 — bridge timeout → null name (already documented), HIGH confidence
- [Backend/routers/ha.py:80](Backend/routers/ha.py) — current `response_model_exclude_none=True` usage, HIGH confidence

---

### Pitfall INTEGRATION-1: MQTT broker as new outbound destination violates the "no outbound" constraint expectation

**What goes wrong:** Project constraint per `CLAUDE.md` and PROJECT.md says "no outbound network connections except to user-configured Hue Bridge / WLED devices." Adding MQTT introduces a third outbound destination. A user with a strict firewall rule (Hue Bridge IP + WLED subnet) finds HPC trying to connect to a different IP and either (a) reports it as a bug or (b) silently fails because the firewall blocks it.

**Why it happens:** Project documentation hasn't been updated for the new design. A user reading PROJECT.md / CLAUDE.md sees an obsolete constraint.

**Warning signs:**
- User issue: "Why is HPC trying to connect to 192.168.1.100:1883? That's not in my allowed list."
- Mosquitto broker silently rejects HPC connections due to ACL not yet updated for new client
- HPC logs show MQTT reconnect failures with `[Errno 113] No route to host` because firewall drops outbound to broker IP

**Prevention:**

1. **Update `CLAUDE.md` "What Already Exists" → Constraints** explicitly:

   > **Network (v1.3+):** Hue Bridge must be reachable. WLED devices must be reachable. **If MQTT discovery is enabled** via `HPC_MQTT_BROKER`, the configured broker IP must also be reachable (default port 1883, or 8883 for TLS).

2. **MQTT broker config is opt-in** (already covered in MQTT-7 prevention) — no broker env var = no outbound MQTT connection attempts. Default behavior is unchanged from v1.2.

3. **Log the broker URL at startup** so users can verify what HPC is trying to connect to:

```python
logger.info("MQTT publisher enabled, target broker=%s", broker_url_redacted)  # mask username:password
```

4. **Surface broker status in `/api/health`:**

```json
{
  "status": "ok",
  "mqtt": {
    "enabled": true,
    "connected": true,
    "broker_host": "192.168.1.10",
    "last_error": null
  }
}
```

**Phase target:** MQTT publisher phase. Update CLAUDE.md and PROJECT.md in the same PR.

---

### Pitfall INTEGRATION-2: Repurposing `/ws/status` for HA push leaks internal metric churn into the HA contract

**What goes wrong:** Tempting shortcut: "HA WS push is just another subscriber to `StatusBroadcaster`; let's reuse `/ws/status`." Six months later, a frontend refactor adds `packets_sent_by_lane` to `_metrics`. HA template sensors that were keyed off the raw `_metrics` shape break — exactly the surface Phase 18 D-09 went out of its way to insulate via the curated `/api/ha/status` response.

**Why it happens:** The Phase 18 design (D-09) deliberately separates the **internal `_metrics`** shape from the **external HA contract**. Reusing the raw `/ws/status` endpoint for HA undoes that separation. Per Phase 18 RESEARCH.md State-of-the-Art table: *"_metrics exposed raw via /ws/status to existing consumers; /api/ha/status projects a curated subset — HA dashboards insulated from internal metric churn."*

**Warning signs:**
- After a frontend feature merges, HA template sensors start showing `unknown` for fields the user wasn't aware existed
- Frontend developer adds a new metric and breaks HA without realizing it
- Phase 18 D-09 lock is silently violated

**Prevention:**

1. **Add a NEW WS endpoint** `/ws/ha-status` — sibling to `/ws/status`, not a refactor of it.

2. **The HA WS pusher consumes `StatusBroadcaster`** but emits the **curated HaStatusResponse JSON shape**, the same one `GET /api/ha/status` returns:

```python
# Backend/routers/ws_ha.py
@router.websocket("/ws/ha-status")
async def ws_ha_status(websocket: WebSocket):
    pusher = websocket.app.state.ha_ws_pusher
    await pusher.connect(websocket)
    # send initial snapshot (curated, NOT raw _metrics)
    initial = await _build_status_response(websocket)  # reuse ha.py helper
    await websocket.send_text(initial.model_dump_json(exclude_none=True))
    try:
        while True:
            await asyncio.sleep(60)  # keepalive
            await websocket.send_text(b"")  # ping
    except WebSocketDisconnect:
        pusher.disconnect(websocket)
```

3. **`StatusBroadcaster.push_state` hook:** when the broadcaster pushes (state transition or 1 Hz heartbeat), the new `HaWsPusher` builds a curated payload and broadcasts to HA subscribers. This means the broadcaster needs to know about the pusher (via constructor injection) OR the pusher subscribes to broadcaster events via a callback hook.

4. **Same Pydantic model as REST.** The WS push payload **MUST** be `HaStatusResponse.model_dump_json(exclude_none=True)` — identical to the REST shape. Then YAML / template sensors work identically whether the user is on REST polling or WS push.

**Anti-pattern:**

```python
# BAD — HA receives raw _metrics
@router.websocket("/ws/status")  # existing endpoint
async def ws_status(websocket: WebSocket):
    broadcaster = websocket.app.state.broadcaster
    await broadcaster.connect(websocket)  # raw _metrics flows through — HA breaks on internal changes
```

**Phase target:** WS push phase.

**Sources:**
- Phase 18 RESEARCH.md State-of-the-Art table — HIGH confidence
- Phase 18 D-09 contract lock — HIGH confidence

---

## Minor Pitfalls

Small mistakes worth catching in code review.

### Pitfall MINOR-1: MQTT username/password leaked into logs / health endpoint

**What goes wrong:** Startup log: `MQTT publisher enabled, broker=mqtt://admin:hunter2@192.168.1.10:1883`. The broker password ends up in journalctl, GitHub bug reports, screenshots.

**Prevention:** Strip credentials from the URL before logging. Use `urllib.parse.urlparse` and reassemble without password:

```python
def redact_url(url: str) -> str:
    u = urlparse(url)
    netloc = f"{u.hostname}:{u.port}" if u.port else u.hostname
    if u.username:
        netloc = f"{u.username}:***@{netloc}"
    return f"{u.scheme}://{netloc}{u.path}"
```

Apply the same redaction to `/api/health` MQTT block.

**Phase target:** MQTT publisher phase.

---

### Pitfall MINOR-2: Discovery payload sent before broker subscription confirmed

**What goes wrong:** Publisher connects, immediately publishes 20 discovery messages, then subscribes to `homeassistant/status` — but the broker processes the subscribe-AFTER scenario such that the next HA birth message during reconnect is missed because the `_run` loop hasn't reached `subscribe` yet.

**Prevention:** Subscribe **before** publishing the first config:

```python
async with aiomqtt.Client(...) as client:
    await client.subscribe("homeassistant/status")  # FIRST
    await client.publish(AVAILABILITY_TOPIC, b"online", retain=True)
    await self._publish_all_discovery(client)  # THEN
```

**Phase target:** MQTT publisher phase.

---

### Pitfall MINOR-3: Discovery payload exceeds MQTT broker max-packet-size when bundling many WLED devices

**What goes wrong:** With 16 WLED devices and full `device` blocks per discovery message, the cumulative retained config size on the broker exceeds Mosquitto's default `message_size_limit` (varies by broker config). Some configs get rejected silently.

**Prevention:** Each config is its own retained message — they don't bundle. But individual payloads can grow. Keep `device.identifiers` to a single string, avoid embedding long `sw_version` strings, and use short topic names. Test against Mosquitto's default 268435456-byte limit but be aware some embedded brokers (HiveMQ Lite) limit to 4 KB.

**Phase target:** MQTT publisher phase.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| MQTT publisher introduction | MQTT-1 (retention), MQTT-2 (unique_id), MQTT-3 (LWT), MQTT-4 (reconnect), MQTT-5 (topic namespace), MQTT-6 (object_id deprecation), MINOR-1, MINOR-2 | Implement birth-LWT + retained discovery + persistent `INSTANCE_UUID` + bounded queue all in the FIRST cut. Adding any of these later means re-publishing all retained configs. |
| WS push for HA status | WS-1 (per-client queue), INTEGRATION-2 (don't reuse `/ws/status`) | New endpoint `/ws/ha-status` with `HaWsPusher` sibling class. Same Pydantic `HaStatusResponse` shape as REST. |
| Per-device WLED health in `/api/ha/status` | HA-1 (additive JSON contract), MQTT-8 (sensor explosion) | New fields default to `{}` / `0`, never `None`. MQTT side groups per-device fields under `json_attributes_topic` + `entity_category: diagnostic`. |
| HA YAML docs | MQTT-7 (avoid mixing paths), HA-1 (defensive Jinja in snippets) | Document "either MQTT or YAML, not both"; ship `default()` filters in every value_template. |

---

## Quick Checklist for MQTT Implementation Review

Before merging the MQTT publisher PR:

- [ ] Every `client.publish(...)` for a `homeassistant/+/+/config` topic has `retain=True`
- [ ] Subscribed to `homeassistant/status` and republishes discovery on `online` payload
- [ ] `Will` set at `aiomqtt.Client` construction time with `retain=True`, payload `offline`
- [ ] `INSTANCE_UUID` persisted to `hpc_identity` table; never regenerated
- [ ] `unique_id` for every entity derives from `INSTANCE_UUID`
- [ ] `default_entity_id` used (NOT `object_id`) for entity-ID defaults
- [ ] `device.identifiers` includes `INSTANCE_UUID`; same value across all entities for one HPC instance
- [ ] Every entity has `availability` block pointing at the HPC availability topic
- [ ] Publisher runs in a background `asyncio.Task` with reconnect + exponential backoff
- [ ] Publisher queue is bounded (e.g., 1024) with drop-on-full
- [ ] Lifespan shutdown publishes `offline` to availability topic BEFORE disconnect
- [ ] Request handlers never `await` MQTT operations directly
- [ ] `/api/health` exposes `mqtt.connected` and `mqtt.broker_host` (redacted)
- [ ] Broker URL is opt-in via `HPC_MQTT_BROKER` env var; absent = no MQTT
- [ ] `CLAUDE.md` and `PROJECT.md` updated to mention MQTT broker as new outbound destination
- [ ] Per-WLED-device fields collapsed into one entity per device via `json_attributes_topic`
- [ ] `entity_category: diagnostic` set on per-WLED-device sensors
- [ ] At least one integration test verifies discovery messages survive publisher disconnect (retention)
- [ ] At least one integration test verifies `unique_id` stable across two app starts on the same DB

---

## Sources

### Authoritative
- [Home Assistant MQTT integration docs](https://www.home-assistant.io/integrations/mqtt/) — discovery topic format, retention, birth message, availability_mode (HIGH)
- [Home Assistant MQTT Sensor docs](https://www.home-assistant.io/integrations/sensor.mqtt/) — required fields, unique_id, json_attributes_topic, entity_category (HIGH)
- [Zigbee2MQTT availability docs](https://www.zigbee2mqtt.io/guide/configuration/device-availability.html) — proven LWT + birth pattern (HIGH)
- [aiomqtt PyPI](https://pypi.org/project/aiomqtt/) — recommended asyncio client, v2.4.0 (May 2025) (HIGH)
- [paho-mqtt docs](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html) — outgoing message retention semantics (HIGH)

### Real-world bug reports
- [home-assistant/core #157763 — object_id deprecation in 2026.4](https://github.com/home-assistant/core/issues/157763) (HIGH)
- [home-assistant/core #97450 — duplicate entity IDs from MQTT](https://github.com/home-assistant/core/issues/97450) (HIGH)
- [Koenkk/zigbee2mqtt #28728 — 2025.10 deprecation warnings](https://github.com/Koenkk/zigbee2mqtt/issues/28728) (HIGH)
- [Koenkk/zigbee2mqtt #27458 — birth message rediscovery missing](https://github.com/Koenkk/zigbee2mqtt/issues/27458) (HIGH)
- [mrlt8/docker-wyze-bridge #920 — MQTT discovery should be re-sent on HA birth](https://github.com/mrlt8/docker-wyze-bridge/issues/920) (HIGH)
- [eclipse-paho/paho.mqtt.python #331 — reconnect takes >40s](https://github.com/eclipse-paho/paho.mqtt.python/issues/331) (HIGH)
- [eclipse-paho/paho.mqtt.python #276 — reconnect fails under heavy QoS 2](https://github.com/eclipse-paho/paho.mqtt.python/issues/276) (HIGH)

### Community guidance
- [Community: MQTT Discovery: to retain or not?](https://community.home-assistant.io/t/mqtt-discovery-to-retain-or-not/310734) (MEDIUM)
- [Community: MQTT object_id vs default_entity_id warning](https://community.home-assistant.io/t/mqtt-object-id-vs-default-entity-id-warning/937665) (MEDIUM)
- [Community: How to prevent NULL values in template sensor](https://community.home-assistant.io/t/how-to-prevent-null-values-in-template-sensor/98207) (MEDIUM)
- [Community: Duplicate entities for MQTT and other integrations](https://community.home-assistant.io/t/duplicate-entities-for-mqtt-and-other-integrations/747021) (MEDIUM)

### Internal references
- `.planning/phases/18-home-assistant-control-endpoints/18-RESEARCH.md` §Common Pitfalls (Pitfalls 1–6) — REST endpoint pitfalls, build on these (HIGH)
- `.planning/phases/17-wled-backend-and-streaming/17-CONTEXT.md` D-16 — `_metrics["wled_devices"]` shape (HIGH)
- `Backend/services/status_broadcaster.py:101` — current `_send_to_all` sequential loop (HIGH)
- `Backend/routers/ha.py:185-263` — current curated status assembly (HIGH)
- `CLAUDE.md` "What NOT to Use" section — pre-existing build-not-buy stance applies to MQTT layer (HIGH)
