# Architecture: v1.3 Home Assistant Integration Polish

**Domain:** FastAPI service integration — MQTT auto-discovery, WS push, expanded HA status, YAML docs
**Researched:** 2026-05-12
**Overall confidence:** HIGH (existing code patterns verified; aiomqtt API verified via Context7)

---

## Executive Summary

v1.3 layers four loosely-coupled capabilities on top of the existing FastAPI lifespan + broadcaster + coordinator stack. The biggest architectural surface is **MQTT** — it owns a long-lived client, two background tasks (publisher loop + command consumer loop), and a state-change subscription on `StatusBroadcaster`. The other three features are small:

- **YAML docs** — a single new file under `docs/`. Zero code changes.
- **WS push for HA** — a new router file consuming the existing `StatusBroadcaster.connect()` pattern. Optionally a dedicated subscriber loop if HA needs a tailored payload shape.
- **Per-device WLED health** — a flatten-step inside `_build_status_response()` in `routers/ha.py`. No new components.

The hardest design decision is **how the MQTT client observes state changes**. The existing `StatusBroadcaster` was built for WebSocket fan-out only — it has no subscriber registry. Three options exist (full pub/sub callback, polling `_metrics`, hybrid). Recommendation below: lightweight **callback list on `StatusBroadcaster`** (add `subscribers: list[Callable]` invoked from `push_state` and `update_metrics`). This avoids polling overhead, keeps the change surgical (4-line addition to `status_broadcaster.py`), and matches how the existing WS connection pool already iterates.

The hardest **lifecycle** decision is **MQTT optionality**. Pattern: read `MQTT_BROKER_HOST` env var in lifespan; if unset, skip MQTT entirely (no task started, no `app.state.mqtt` set). All MQTT consumer code uses `getattr(app.state, "mqtt", None)` — identical to the existing `getattr(request.app.state, "coordinator", None)` pattern in `routers/ha.py:236`.

---

## Recommended Architecture

```
                          FastAPI lifespan (main.py:27-68)
                          ┌──────────────────────────────────────────────┐
                          │ init_db ─► broadcaster ─► coordinator        │
                          │                              │               │
                          │                              ├─► HueStreamer │
                          │                              └─► WledStreamer│
                          │                                              │
                          │ + NEW: HaMqttPublisher (optional, env-gated) │
                          └──────────────┬───────────────────────────────┘
                                         │
                                         │ subscribes to broadcaster
                                         ▼
                          ┌──────────────────────────────────────────────┐
                          │ StatusBroadcaster._metrics                   │
                          │  ─► on update_metrics()/push_state(): fan    │
                          │     out to WS pool AND subscriber callbacks  │
                          └──────────────┬───────────────────────────────┘
                                         │
              ┌──────────────────────────┼─────────────────────────┐
              ▼                          ▼                         ▼
   /ws/status (existing)       /ws/ha (NEW, optional)     HaMqttPublisher.on_state(...)
   broad WS clients            HA-shaped payload only     publishes state to MQTT
                                                                  │
                                                                  ▼
                                                          MQTT broker (mosquitto)
                                                                  │
                                                                  ▼
                                                          Home Assistant
                                                                  │
                                                                  │ commands flow back
                                                                  ▼
                                                          HaMqttPublisher.on_command(...)
                                                                  │
                                                                  ▼
                                                          Reuse routers/ha.py helpers
                                                          (coordinator.start/stop,
                                                          ha_state upserts)
```

### Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `HaMqttPublisher` (NEW service) | MQTT client lifecycle, discovery publish on connect, state→MQTT bridge, command topic consumer | `StatusBroadcaster` (subscribe), `StreamingCoordinator` (start/stop), `app.state.db` (ha_state upserts), `routers/ha.py` business-logic helpers (extracted) |
| `StatusBroadcaster` (MODIFIED) | Existing WS fan-out + NEW lightweight subscriber callbacks | `StreamingCoordinator` writes; WS clients + MQTT publisher subscribe |
| `routers/ha_ws.py` (NEW, optional) | WS endpoint shaped for HA's WS template integration | `StatusBroadcaster` (re-uses existing connect pattern) |
| `routers/ha.py` (MODIFIED) | Flatten `wled_devices` into `/api/ha/status`; extract reusable helpers for MQTT commands to call | Adds new fields to `HaStatusResponse`; refactors `ha_start`/`ha_stop`/`ha_put_zone`/`ha_put_camera` bodies into helper functions |
| `routers/health.py` (MODIFIED) | Surface MQTT broker connection status in health payload (so users debug "discovery isn't appearing") | Reads `app.state.mqtt.connected` |
| `docs/home-assistant-yaml.md` (NEW) | Copy-paste YAML for `rest_command:`, `sensor:`, `input_select:` | Documentation only |

### Data Flow

#### State outbound (HuePictureControl → HA)
```
Coordinator state change
  → broadcaster.push_state(...)  [status_broadcaster.py:65]
    → for each ws in self._connections:  send_text(payload)     [existing]
    → for each cb in self._subscribers:  cb(self._metrics)      [NEW]
        → HaMqttPublisher.on_state(metrics)
          → builds entity-specific MQTT payloads
          → publishes to homeassistant/<comp>/<id>/state via aiomqtt
```

#### Command inbound (HA → HuePictureControl)
```
HA service call (homeassistant/switch/.../set, .../select, etc.)
  → MQTT broker
    → HaMqttPublisher._command_consumer_loop()  [background task]
      → routes by topic suffix:
         set_streaming(True/False)  → coordinator.start/stop  (reuse routers/ha.py logic)
         select_zone(zone_id)       → reuse _put_zone_logic(db, zone_id)   [extracted helper]
         select_camera(stable_id)   → reuse _put_camera_logic(db, stable_id) [extracted helper]
      → broadcaster.push_state(...) is triggered indirectly by coordinator,
        which re-publishes outbound state via the subscriber callback chain
```

---

## Answers to the Specific Questions

### Q1. Where does the MQTT client live?

**Decision:** New service class `HaMqttPublisher` in `Backend/services/ha_mqtt_publisher.py`. Exposed as `app.state.mqtt`. Optional — set to `None` (or attribute absent) when no broker configured.

**Why this shape:**
- **Mirrors existing service pattern** — `StreamingCoordinator`, `StatusBroadcaster`, `CaptureRegistry`, `WledStreamer`, `HueStreamer` all live in `Backend/services/`. Routers stay thin. Lifespan wires them.
- **Mirrors existing optional-app-state pattern** — `routers/ha.py:236-238` already does `getattr(request.app.state, "coordinator", None)` with a 503 if missing. This is the canonical "service unavailable" idiom in the codebase.
- **One class, not multiple modules.** The publisher loop, command consumer, discovery publisher, and reconnect logic all share the same `aiomqtt.Client` instance. Splitting across modules forces passing the client around or stashing it in a global — both are worse than a single class with methods.

**Class signature:**

```python
# Backend/services/ha_mqtt_publisher.py
import asyncio
import json
import logging
from typing import Any

import aiomqtt  # NEW dependency

from services.status_broadcaster import StatusBroadcaster
from services.streaming_coordinator import StreamingCoordinator

logger = logging.getLogger(__name__)


class HaMqttPublisher:
    """MQTT bridge between HuePictureControl and Home Assistant.

    Owns:
      * One aiomqtt.Client with reconnect=True (built-in exponential backoff)
      * Background task: command_consumer_loop()
      * Subscriber callback registered on StatusBroadcaster

    Lifecycle (called from main.py lifespan):
        mqtt = HaMqttPublisher(db, coordinator, broadcaster, config)
        await mqtt.start()       # connects, publishes discovery, subscribes to commands
        ...
        await mqtt.stop()        # cancels task, publishes offline state, closes client

    Optional:
        Construct only when MQTT_BROKER_HOST env var is set; otherwise
        leave app.state.mqtt unset and all consumers use getattr() fallback.
    """

    DISCOVERY_PREFIX = "homeassistant"
    DEVICE_ID = "huepicturecontrol"

    def __init__(
        self,
        db,
        coordinator: StreamingCoordinator,
        broadcaster: StatusBroadcaster,
        config: dict[str, Any],
    ) -> None:
        self._db = db
        self._coordinator = coordinator
        self._broadcaster = broadcaster
        self._config = config  # {host, port, username, password, base_topic}
        self._client: aiomqtt.Client | None = None
        self._client_cm = None  # async context manager handle for clean shutdown
        self._consumer_task: asyncio.Task | None = None
        self._connected: bool = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        """Open MQTT connection, publish discovery, subscribe to commands."""
        self._client_cm = aiomqtt.Client(
            hostname=self._config["host"],
            port=self._config["port"],
            username=self._config.get("username"),
            password=self._config.get("password"),
            identifier=f"hpc-{self.DEVICE_ID}",
            reconnect=True,
            keep_alive=30,
            will=aiomqtt.Will(
                topic=f"{self._config['base_topic']}/availability",
                payload=b"offline",
                retain=True,
            ),
        )
        self._client = await self._client_cm.__aenter__()
        self._connected = True
        await self._publish_availability("online")
        await self._publish_discovery()                  # retained config messages
        await self._client.subscribe(f"{self._config['base_topic']}/cmd/#")
        self._broadcaster.subscribe(self.on_state)       # callback registration (Q2)
        self._consumer_task = asyncio.create_task(self._command_consumer_loop())

    async def stop(self) -> None:
        """Graceful shutdown: cancel consumer, publish offline, exit context."""
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        self._broadcaster.unsubscribe(self.on_state)
        if self._client and self._connected:
            try:
                await self._publish_availability("offline")
            except Exception:
                pass
        if self._client_cm:
            await self._client_cm.__aexit__(None, None, None)
        self._connected = False

    # ---- State outbound (Q2) ----
    async def on_state(self, metrics: dict) -> None:
        """Subscriber callback invoked by StatusBroadcaster on state changes."""
        ...   # publishes to homeassistant/switch/.../state, .../sensor/.../state, etc.

    # ---- Commands inbound (Q3) ----
    async def _command_consumer_loop(self) -> None:
        """Background task: route inbound MQTT commands to coordinator + DB."""
        ...

    # ---- Helpers ----
    async def _publish_discovery(self) -> None:
        """Publish retained HA discovery configs for switch/sensor/select entities."""
        ...

    async def _publish_availability(self, status: str) -> None:
        ...
```

**Library choice:** `aiomqtt` (v3+, asyncio-native, built-in reconnect with exponential backoff, MQTTv5 support, Mosquitto-compatible). Verified via Context7 — automatic reconnection via `reconnect=True` and `keep_alive=30` is now first-class in v3.

---

### Q2. How does it observe StreamingCoordinator state changes?

**Decision:** Add a lightweight subscriber callback list to `StatusBroadcaster`. The MQTT publisher registers `self.on_state` as a subscriber during `start()`. `StatusBroadcaster._send_to_all()` and `update_metrics()` invoke every subscriber after writing `_metrics`.

**Why callback (not polling, not pub/sub library):**

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Callback list on broadcaster (chosen)** | 4-line change to existing file. Single observation point — `push_state` and `update_metrics` already centralize state writes. Async-safe (callbacks await inline). | Adds one new public method (`subscribe`/`unsubscribe`). Couples MQTT publisher to broadcaster instance (already needed). | Recommended — minimal change, follows existing fan-out shape. |
| Polling `_metrics` from MQTT loop | Zero changes to broadcaster | Wastes CPU at 1+Hz; misses transient state. Worse latency than callbacks. | Rejected. |
| Full pub/sub library (e.g. blinker, asyncio.Queue) | Decouples publisher↔subscriber | Adds a dependency for one publisher consumer. Overkill. | Rejected. |
| WS client (MQTT publisher dials its own /ws/status) | Zero changes to broadcaster | Forces JSON round-trip in-process; needs lifecycle ordering vs. WS router. | Rejected. |

**Modification to `Backend/services/status_broadcaster.py`:**

```python
# Add to __init__:
self._subscribers: list[Callable[[dict], Awaitable[None]]] = []

# Add public methods:
def subscribe(self, cb: Callable[[dict], Awaitable[None]]) -> None:
    """Register an async callback invoked on every state change.

    Callbacks receive a snapshot of the current _metrics dict.
    Errors raised by callbacks are logged but never propagate to other
    subscribers or the WS pool.
    """
    self._subscribers.append(cb)

def unsubscribe(self, cb: Callable) -> None:
    try:
        self._subscribers.remove(cb)
    except ValueError:
        pass

async def _notify_subscribers(self) -> None:
    """Fire all subscribers concurrently; isolate per-callback errors."""
    if not self._subscribers:
        return
    snap = dict(self._metrics)
    await asyncio.gather(
        *(self._safe_invoke(cb, snap) for cb in list(self._subscribers)),
        return_exceptions=False,
    )

async def _safe_invoke(self, cb, snap) -> None:
    try:
        await cb(snap)
    except Exception:
        logger.warning("Subscriber callback %r failed", cb, exc_info=True)
```

**Call sites in `status_broadcaster.py`:**
- `push_state()` (line 99, after `_send_to_all`): also call `await self._notify_subscribers()`.
- `update_metrics()` (line 57): does NOT notify (called at 50 Hz inside the frame loop — would spam MQTT). Subscribers see metric updates via the 1 Hz `_heartbeat_loop` only.

**Critical design point — heartbeat rate vs MQTT publish rate:**
- `StatusBroadcaster._heartbeat_loop` runs at 1 Hz (line 116). That's the MQTT outbound rate ceiling for sensors (fps, latency).
- State transitions (`push_state`) are immediate — switch entity flips within ~1 frame of coordinator state change.
- This is desirable. HA does not need 50 Hz telemetry; 1 Hz is plenty for HA dashboard refresh.
- Add a guard inside `on_state` to dedupe rapid state changes (publish only if state, fps bucket, or wled health hash changed) — prevents broker spam during reconnect storms.

---

### Q3. How does it handle bidirectional flow (commands inbound)?

**Decision:** Single `_command_consumer_loop` background task; routes inbound MQTT messages by topic suffix; **reuses business-logic helpers extracted from `routers/ha.py`**.

**Topic shape (HA-discovery aligned):**
```
huepicturecontrol/cmd/streaming/set      -> "ON" / "OFF"
huepicturecontrol/cmd/zone/select        -> "<entertainment_config_id>"
huepicturecontrol/cmd/camera/select      -> "<known_cameras.stable_id>"
```

State topics (mirror, for HA's state subscription):
```
huepicturecontrol/state/streaming        -> "ON" / "OFF" / "STARTING" / "ERROR"
huepicturecontrol/state/zone             -> "<config_id>"
huepicturecontrol/state/camera           -> "<stable_id>"
huepicturecontrol/state/fps              -> "60.0"
huepicturecontrol/state/latency_ms       -> "16.7"
huepicturecontrol/state/wled/<dev>/online -> "ON" / "OFF"
huepicturecontrol/availability           -> "online" / "offline" (LWT)
```

**Required refactor — extract helpers from `routers/ha.py`:**

Currently `ha_put_zone`, `ha_put_camera`, `ha_start`, `ha_stop` carry all their business logic inline in route handler functions. MQTT commands cannot call them directly because:
1. They take a FastAPI `Request` object
2. They return a Pydantic response model (MQTT doesn't care)
3. They use `HTTPException` to signal errors (wrong for MQTT)

Refactor each route into a **pure helper** + **thin route wrapper**:

```python
# Backend/routers/ha.py — refactored shape (Phase 18 logic preserved exactly)

async def select_zone(db, zone_id: str) -> dict:
    """Pure helper — used by HTTP route AND MQTT consumer.

    Raises ValueError on validation errors (HTTP wrapper converts to HTTPException;
    MQTT consumer logs and republishes prior state).
    """
    async with db.execute("SELECT id FROM entertainment_configs WHERE id = ?", (zone_id,)) as cur:
        if (await cur.fetchone()) is None:
            raise ValueError(f"zone_id '{zone_id}' not found")
    # ... existing D-06 upsert + camera_last_zone dual-write logic ...

async def select_camera(db, stable_id: str) -> dict:
    """Pure helper — D-07 logic."""
    ...

async def start_streaming(db, coordinator) -> dict:
    """Pure helper — D-08 preconditions + coordinator.start()."""
    ...

async def stop_streaming(coordinator) -> None:
    """Pure helper — idempotent stop."""
    if coordinator is not None:
        await coordinator.stop()


# Thin route wrappers:
@router.put("/zone", response_model=HaStatusResponse, response_model_exclude_none=True)
async def ha_put_zone(body: HaZoneRequest, request: Request) -> HaStatusResponse:
    try:
        await select_zone(request.app.state.db, body.zone_id)
    except ValueError as exc:
        raise HTTPException(404, detail=str(exc))
    return await _build_status_response(request)
```

The MQTT consumer then calls `select_zone(self._db, payload)` directly. No HTTP round-trip.

**Consumer loop shape (per aiomqtt v3 idiom):**

```python
async def _command_consumer_loop(self) -> None:
    base = self._config["base_topic"]
    cmd_handlers = {
        f"{base}/cmd/streaming/set":  self._handle_streaming_set,
        f"{base}/cmd/zone/select":    self._handle_zone_select,
        f"{base}/cmd/camera/select":  self._handle_camera_select,
    }
    async for message in self._client.messages():
        handler = cmd_handlers.get(str(message.topic))
        if handler is None:
            continue
        try:
            await handler(message.payload.decode("utf-8").strip())
        except Exception:
            logger.warning("MQTT command handler failed: %s", message.topic, exc_info=True)

async def _handle_streaming_set(self, payload: str) -> None:
    from routers import ha as ha_helpers   # avoid import cycle at module load
    if payload.upper() in ("ON", "1", "TRUE", "START"):
        await ha_helpers.start_streaming(self._db, self._coordinator)
    else:
        await ha_helpers.stop_streaming(self._coordinator)
    # coordinator emits push_state → on_state callback → re-publishes /state/streaming
```

**Why one consumer task (not one per topic):** aiomqtt's `client.messages()` is a single async iterator. Multiple iterators don't multiplex on the same connection. One loop, dispatch by topic.

---

### Q4. Where does MQTT configuration live?

**Decision: environment variables + new `mqtt_config` SQLite row (single-row, like `bridge_config`).**

Hybrid because the two have different lifecycles:
- **Broker host/port/auth** — set once by the operator, infrequent changes, fits env vars (matches existing `DATABASE_PATH`, `CAPTURE_DEVICE`, `MIN_REGION_AREA` pattern in this codebase).
- **MQTT-specific tunables that need to survive container restart without redeployment** (e.g. base_topic override, enable/disable toggle from UI) — fit a DB row.

**Recommended split:**

| Setting | Source | Default | Rationale |
|---------|--------|---------|-----------|
| `MQTT_BROKER_HOST` | env var | unset → MQTT disabled | Connection critical, infrequent change |
| `MQTT_BROKER_PORT` | env var | `1883` | Same |
| `MQTT_USERNAME` | env var | unset | Secret-ish; do not store in DB |
| `MQTT_PASSWORD` | env var | unset | Secret; do not store in DB |
| `MQTT_BASE_TOPIC` | env var | `huepicturecontrol` | Allows multi-instance on shared broker |
| `MQTT_DISCOVERY_PREFIX` | env var | `homeassistant` | HA-side override |
| (optional) `mqtt_state.enabled` | new DB row | `1` | Future UI toggle without container restart |

**Why not all in DB:**
- Existing codebase puts infrastructure config in env (`DATABASE_PATH`, `CAPTURE_DEVICE`). Adding a `mqtt_config` table for the broker URL would diverge from this convention.
- Docker Compose `.env` is the existing operator interface. Adding YAML/UI config for the broker means building a Settings UI tab for one feature — not justified.

**Why not all in env:**
- A future v1.4 user-facing "Enable MQTT" toggle in the web UI cannot live in env vars (read-only inside container).
- Defer the DB row until needed. v1.3 ships env-only.

**Reading the config in `main.py` lifespan:**

```python
# After broadcaster + coordinator creation:
mqtt_host = os.getenv("MQTT_BROKER_HOST")
if mqtt_host:
    from services.ha_mqtt_publisher import HaMqttPublisher
    mqtt_cfg = {
        "host": mqtt_host,
        "port": int(os.getenv("MQTT_BROKER_PORT", "1883")),
        "username": os.getenv("MQTT_USERNAME"),
        "password": os.getenv("MQTT_PASSWORD"),
        "base_topic": os.getenv("MQTT_BASE_TOPIC", "huepicturecontrol"),
        "discovery_prefix": os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant"),
    }
    mqtt = HaMqttPublisher(db, coordinator, broadcaster, mqtt_cfg)
    try:
        await mqtt.start()
        app.state.mqtt = mqtt
    except Exception as exc:
        logger.warning("MQTT broker unreachable (%s); HA MQTT integration disabled.", exc)
        app.state.mqtt = None
else:
    logger.info("MQTT_BROKER_HOST unset; HA MQTT integration disabled.")
    # Do not set app.state.mqtt — getattr fallback handles it.
```

**Graceful degrade behavior:**
- No `MQTT_BROKER_HOST` → no MQTT task started, no `app.state.mqtt`. App boots normally. All existing features work.
- `MQTT_BROKER_HOST` set but broker unreachable at boot → `aiomqtt.Client.__aenter__` raises `MqttError` → caught in lifespan → `app.state.mqtt = None` set explicitly so `/api/health` can report "MQTT disabled".
- Broker reachable at boot but disconnects later → `aiomqtt` reconnects with built-in exponential backoff (verified via Context7). State publishes during disconnect raise `ConnectError` and are swallowed inside `on_state`. HA's HPC entities go `unavailable` via LWT.

---

### Q5. Build order

**Recommended order (4 plans, ascending risk):**

| # | Feature | Risk | Why this order |
|---|---------|------|----------------|
| 1 | **YAML docs** (`docs/home-assistant-yaml.md`) | Trivial — pure docs | Lowest risk. Closes the deferred Phase 18 item. Validates the REST surface is HA-templatable without writing any code. Users can ship a working HA integration with v1.2 + these docs alone. |
| 2 | **WLED health flattening in `/api/ha/status`** | Low — adds fields to existing Pydantic model + helper | Small, contained edit to `routers/ha.py:_build_status_response()`. Makes the HA template surface complete before MQTT joins. Allows YAML-path users (Plan 1) to access WLED telemetry. |
| 3 | **MQTT auto-discovery (read-only)** | Medium — new dep, new lifespan branch, subscriber callback infra | Discovery + state-publish only. **No command consumer yet**. Validates the broker connection, discovery payload shape, and StatusBroadcaster.subscribe() mechanism in isolation. HA entities appear and update; commands still go through `rest_command:` from Plan 1's YAML docs. |
| 4 | **MQTT command consumer (bidirectional)** | Higher — couples MQTT to coordinator/DB; refactors `routers/ha.py` to extract helpers | Last because it needs Plan 3's MQTT client + needs the helper-extraction refactor in `routers/ha.py`. Refactor is mechanical but touches all four HA routes and their tests. Save for when discovery is proven stable. |

**Why YAML first (and not "MQTT first because it's the headline feature"):**
- **Falsifies "do users actually want MQTT"** before any backend work. If `rest_command:` docs solve 90% of HA users' needs, MQTT can stay deferred.
- **Decouples MVP value from infrastructure work.** A user with no MQTT broker is unblocked by Plan 1 alone.
- **Zero rollback cost.** If we cut v1.3 short for any reason, Plan 1 + Plan 2 still ship demonstrable value.

**WS push for HA — NOT in v1.3 unless asked.** PROJECT.md lists it in Active. Re-read of Phase 18 design (HA polls `/api/ha/status` at 1–5 Hz over REST) shows REST polling is fine for the actual HA UI refresh rate. MQTT (Plan 3) gives push for free via state topics. Drop dedicated `/ws/ha` from v1.3 scope — recommend deferring to v1.4 with the bug-fix bundle. If kept, it's a 30-line addition consuming the same `broadcaster.connect()` API as `/ws/status` with an HA-tailored initial-snapshot shape (no new architecture).

**Optional final plan (Plan 5):** `/api/health` MQTT status surface — one-line addition reading `app.state.mqtt.connected`. Trivial, ship anytime after Plan 3.

---

### Q6. Integration points: which files get modified, which are new

#### New files

| File | Purpose | LOC est. |
|------|---------|----------|
| `Backend/services/ha_mqtt_publisher.py` | `HaMqttPublisher` class — MQTT lifecycle, discovery, state→MQTT, command consumer | ~350 |
| `Backend/tests/test_ha_mqtt_publisher.py` | Unit tests with `aiomqtt` mock + integration test against ephemeral Mosquitto | ~200 |
| `docs/home-assistant-yaml.md` | Copy-paste YAML for `rest_command:`, `sensor:`, `input_select:`, `input_boolean:`, automation triggers | ~150 (markdown) |
| (optional Plan WS) `Backend/routers/ha_ws.py` | `/ws/ha` endpoint shaped for HA WS template integration | ~40 |

#### Modified files (with file:line precision)

| File | What changes | Where |
|------|-------------|-------|
| `Backend/main.py` | Add MQTT init block (env-gated) after coordinator creation; add MQTT teardown before registry shutdown | After line 56 (post-`app.state.coordinator = coordinator`); after line 62 (in shutdown, before `registry.shutdown()`) |
| `Backend/main.py` | Optional Plan WS: `app.include_router(ha_ws_router)` | After line 85 (after existing `ha_router` include) |
| `Backend/services/status_broadcaster.py` | Add `_subscribers: list`; add `subscribe()`/`unsubscribe()` methods; add `_notify_subscribers()`; call it from `push_state` only (NOT `update_metrics` — 50 Hz storm) | __init__ ~line 27; new methods after line 56; call site at end of `push_state` line 99 |
| `Backend/routers/ha.py` | (Plan 2) Add `wled_devices: dict = {}` field to `HaStatusResponse`; flatten `broadcaster._metrics["wled_devices"]` in `_build_status_response`; add deprecation/clarity comment | `HaStatusResponse` model line 66–80; helper line 88–177; line 100 `metrics =` block needs wled_devices key |
| `Backend/routers/ha.py` | (Plan 4) Extract business logic from `ha_start`/`ha_stop`/`ha_put_zone`/`ha_put_camera` into module-level pure async helpers; routes become thin wrappers | Lines 185–363 — full refactor of all four route bodies |
| `Backend/routers/health.py` | Surface MQTT connection status: `{"mqtt": {"enabled": bool, "connected": bool}}` | New field in health response |
| `Backend/requirements.txt` | Add `aiomqtt>=3.0,<4` (v3 has built-in reconnect) | Append |
| `docker-compose.yml` (if used) | Document `MQTT_BROKER_HOST` etc. env vars (commented out by default so MQTT stays opt-in) | environment section |

#### NOT modified (deliberate)

| File | Why preserved |
|------|--------------|
| `Backend/services/streaming_coordinator.py` | All MQTT-side observation happens via `StatusBroadcaster` callback. Coordinator stays sink-agnostic per its existing design contract. |
| `Backend/services/wled_streamer.py`, `Backend/services/streaming_service.py` | Sink classes already expose `health_snapshot()`. Plan 2 reads through existing `broadcaster._metrics["wled_devices"]`. |
| `Backend/database.py` | No new tables for v1.3. (Future `mqtt_config` row deferred to v1.4 settings-UI work.) |
| `Backend/routers/capture.py`, `Backend/routers/wled.py`, `Backend/routers/hue.py`, `Backend/routers/regions.py`, `Backend/routers/cameras.py` | No changes. MQTT is observation + control, not feature-area code. |
| `Backend/routers/streaming_ws.py`, `Backend/routers/preview_ws.py` | Existing WS endpoints unchanged. New `/ws/ha` (if built) lives in its own router. |
| Frontend/* | Zero frontend changes. MQTT is HA-only. (A future "MQTT connected" badge in the web UI is v1.4+.) |

---

## Patterns to Follow

### Pattern 1: Optional service via `app.state` + `getattr` fallback
**What:** Construct optional services only when their config is present. Use `getattr(app.state, "name", None)` to read.
**When:** Any feature that may be disabled at deploy time (MQTT, future cloud sync, future telemetry).
**Example:** Existing `routers/ha.py:236` does `getattr(request.app.state, "coordinator", None)` with 503 on missing. MQTT follows the identical pattern.

### Pattern 2: Pure helper + thin route wrapper
**What:** Route bodies become 3-line wrappers that call a pure async helper. Helpers take `db`/`coordinator` directly (no `Request` object), raise `ValueError` instead of `HTTPException`.
**When:** When the same business logic must be invoked from a non-HTTP path (MQTT consumer, scheduled task, WebSocket message).
**Example:** Plan 4 refactor of `routers/ha.py`. Same pattern Phase 18 partially established but didn't extract.

### Pattern 3: Subscriber callback on broadcaster
**What:** Long-lived background consumers register an async callback on `StatusBroadcaster` and react inline on state changes.
**When:** Any in-process observer of streaming state that's not a WebSocket client.
**Example:** `HaMqttPublisher.on_state`. Future: a Prometheus exporter could register the same way.

### Pattern 4: Env-var config with DB-row escape hatch
**What:** Operator-set infrastructure config goes in env vars (matches existing `DATABASE_PATH`, `CAPTURE_DEVICE`). User-set per-install config goes in single-row SQLite tables (matches `bridge_config`, `ha_state`).
**When:** New config for v1.3+. MQTT is env-only initially; reserve `mqtt_state` table for future UI toggle.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Polling `broadcaster._metrics` from MQTT loop
**Why bad:** Wastes CPU; introduces latency; misses transient states (e.g. `starting`→`error` within 1s).
**Instead:** Subscribe to broadcaster callbacks (Pattern 3).

### Anti-Pattern 2: MQTT publisher dialing its own `/ws/status` over WebSocket
**Why bad:** Forces in-process WebSocket protocol overhead; tangles lifecycle ordering (publisher must wait for WS router to be ready); creates an extra failure mode if WS port changes.
**Instead:** Direct subscriber callback on the in-process broadcaster instance.

### Anti-Pattern 3: Storing MQTT credentials in SQLite
**Why bad:** No-auth design + plain-text SQLite + LAN trust boundary already documented. Adding a credential to the DB violates the no-secrets-in-HPC posture established for the HA token decision (see CLAUDE.md "Alternatives Considered").
**Instead:** Env vars only. Operator manages secrets at the Docker / systemd level.

### Anti-Pattern 4: MQTT publish at frame rate (50–60 Hz)
**Why bad:** Broker spam; no HA dashboard refreshes that fast; will trigger Mosquitto rate-limit warnings.
**Instead:** Publish only on `push_state` (state transitions, immediate) and on `_heartbeat_loop` (1 Hz aggregated metrics).

### Anti-Pattern 5: Coupling `HaMqttPublisher` directly to `WledStreamer` / `HueStreamer`
**Why bad:** Breaks the "coordinator is sink-agnostic" invariant. Every sink would need to know about MQTT.
**Instead:** Read sink health via `broadcaster._metrics["wled_devices"]` (already populated by coordinator `_frame_loop` line 549). Single observation point.

### Anti-Pattern 6: Synchronous `paho-mqtt` blocking calls inside async handlers
**Why bad:** `paho-mqtt`'s loop is thread-based; mixing with asyncio requires `loop.run_in_executor` wrappers or paho's `loop_forever` in a thread. Same library footgun the WledStreamer notes about blocking ioctls inside async (CLAUDE.md "Python `socket` stdlib").
**Instead:** Use `aiomqtt` (asyncio-native). Verified API via Context7.

---

## Scalability Considerations

| Concern | At 1 HA user | At 5 HA users | At 100+ HA users |
|---------|--------------|---------------|------------------|
| MQTT broker | Single Mosquitto on HA host | Same | Same — MQTT is one→many naturally |
| Discovery messages | ~5 retained configs | Same | Same — retained, one-time per topic |
| State publish rate | 1 Hz heartbeat | Same | Same — broker fans out, HPC publishes once |
| Command consumer | 1 task | Same | Same — commands are user-initiated, low rate |
| Memory | +~5 MB (aiomqtt client + buffers) | Same | Same |

MQTT is the natural scaling pattern here. HPC publishes once; the broker fans out. No HPC-side concern even with many HA instances on the LAN.

The actual scaling limit is **streaming light count**, not HA integration. v1.3 features do not affect the streaming hot path (frame loop unchanged).

---

## Open Architectural Questions

These are surfaced as research flags for the Roadmap phase, not blockers:

1. **MQTT discovery for WLED per-device sensors:** publish one set of WLED `online`/`last_error` sensors per `wled_devices` row? This requires discovery messages to update when devices are added/removed via `/api/wled/...`. Either (a) re-publish full discovery on every WLED CRUD, or (b) accept that newly-added WLED devices need a discovery refresh action. Lean toward (a) — re-emit retained discovery from `routers/wled.py` CRUD endpoints via a new `HaMqttPublisher.refresh_wled_discovery()` method. This decision belongs in the Plan 3 design doc, not v1.3 entry.

2. **Discovery payload schema versioning:** HA's discovery format evolves. Pin a schema version in our payload (`sw_version: "1.3.0"`, `device: {via_device: ...}` for sub-entities). Existing `bridge_config` and `wled_devices` tables give us stable identifiers — use them.

3. **WS push (`/ws/ha`) vs MQTT redundancy:** Once MQTT (Plan 3) ships, the WS push feature in PROJECT.md becomes redundant for users with a broker. Recommend explicitly deferring `/ws/ha` to v1.4 and re-evaluating once MQTT is in real use. Flag this in v1.3 milestone retrospective.

4. **Friendly-name resolution latency:** `_build_status_response` already calls `list_entertainment_configs` against the Hue Bridge on every `/api/ha/status` GET — cached only by Bridge HTTP. If MQTT publishes state at 1 Hz with bridge name resolution, that's 1 Hue Bridge call per second. Either (a) cache `config_name_by_id` in `HaMqttPublisher` (invalidate on `/api/hue/configs` change), or (b) publish only IDs to MQTT and let HA's template sensors resolve names. Lean toward (a) — names rarely change. Belongs in Plan 3 design.

---

## Sources

- **aiomqtt official docs** via Context7 (`/empicano/aiomqtt`): built-in reconnect with exponential backoff via `reconnect=True`, `keep_alive`, `connected()`/`disconnected()`, MQTTv5 LWT support — HIGH confidence
- **CLAUDE.md "Integration Points with Existing Code"**: confirms sibling-service pattern (`WledStreamingService` analog), no Hue token stored in HPC posture — HIGH confidence
- **`Backend/main.py:27-68`** (read 2026-05-12): existing lifespan with `app.state.{db, broadcaster, coordinator, capture_registry}` — HIGH confidence
- **`Backend/services/streaming_coordinator.py:65-100, 481-553`** (read 2026-05-12): broadcaster wiring + `update_metrics`/`push_state` call sites — HIGH confidence
- **`Backend/services/status_broadcaster.py:25-132`** (read 2026-05-12): `_metrics` dict shape, `_heartbeat_loop` 1 Hz rate, WS fan-out pattern → callback subscribers fit naturally — HIGH confidence
- **`Backend/routers/ha.py:236-241, 88-177`** (read 2026-05-12): existing `getattr(app.state, "coordinator", None)` pattern + Phase 18 status payload assembly that needs flattening — HIGH confidence
- **`Backend/services/wled_streamer.py:251-262`** (read 2026-05-12): `health_snapshot()` already exists and is already aggregated into `broadcaster._metrics["wled_devices"]` by coordinator line 549 — HIGH confidence
- **`Backend/database.py:5, Backend/services/capture_service.py:29`** (read 2026-05-12): existing env-var-with-default config pattern → MQTT env vars consistent — HIGH confidence
- **Home Assistant MQTT Discovery docs**: discovery topic structure `homeassistant/<component>/<id>/config`, switch/sensor/select entity schemas — MEDIUM confidence (training data; verify exact JSON shapes during Plan 3 design)
