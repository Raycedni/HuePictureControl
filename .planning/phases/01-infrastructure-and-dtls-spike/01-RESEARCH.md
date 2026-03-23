# Phase 1: Infrastructure and DTLS Spike - Research

**Researched:** 2026-03-23
**Domain:** Docker Compose setup, FastAPI bootstrapping, hue-entertainment-pykit DTLS transport, aiosqlite schema initialization, Hue Bridge pairing via CLIP v2 REST
**Confidence:** MEDIUM-HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BRDG-01 | User can pair with Hue Bridge via link button press from the web UI | CLIP v2 pairing POST /api with generateclientkey=true; zeroconf mDNS discovery |
| BRDG-02 | Bridge credentials (application key + client key) are persisted and survive restarts | aiosqlite bridge_config table; SQLite volume mount in Docker Compose |
| BRDG-03 | Application discovers all lights, rooms, and entertainment configurations from the bridge | GET /clip/v2/resource/entertainment_configuration with hue-application-key header |
| BRDG-05 | Entertainment configuration can be selected from the UI (lists available configs) | Entertainment service discovery via hue-entertainment-pykit or direct CLIP v2 |
| UI-02 | Bridge pairing flow is guided in the UI (instructions + status feedback) | React frontend skeleton; FastAPI POST /api/hue/pair endpoint; status polling |
| INFR-01 | Backend and frontend run as separate Docker Compose services | Two-service docker-compose.yaml; backend + frontend directories |
| INFR-02 | USB capture card is passed through to the backend container | Docker Compose `devices` directive + `group_add: [video]` |
| INFR-03 | Backend uses host networking for DTLS/UDP and mDNS access to Hue Bridge | `network_mode: host` on backend service |
| INFR-05 | Configuration persists in SQLite database with volume mount | aiosqlite + named volume; schema created in lifespan startup |
</phase_requirements>

---

## Summary

Phase 1 proves the hardest technical unknown — the DTLS transport layer to the Hue Bridge — and builds the Docker environment everything else depends on. The DTLS problem is fully solved by `hue-entertainment-pykit`, which wraps mbedTLS and handles PSK key exchange internally. Python has no stdlib DTLS solution; this library is the only viable Python path.

The backend is FastAPI on Python 3.12 (hard pin — mbedTLS wheels break on 3.13+). Bridge pairing uses the legacy `POST /api` endpoint (not CLIP v2) with `generateclientkey: true` to get both the application key and the DTLS PSK (clientkey). The clientkey cannot be retrieved again; it must be stored immediately to SQLite via aiosqlite. The `hue-entertainment-pykit` library takes all bridge credentials at construction time, so it needs the `identification`, `rid`, `ip_address`, `swversion`, `username`, `hue_app_id`, and `clientkey` fields — most of which come from querying `GET /clip/v2/resource/bridge` after pairing.

Docker networking: backend uses `network_mode: host` (required for DTLS/UDP on port 2100 and mDNS). The frontend nginx container is on bridge networking. The nginx `proxy_pass` to the backend CANNOT use a Docker service name — it must use `host.docker.internal` with `extra_hosts: ["host.docker.internal:host-gateway"]` in the frontend service, or use `127.0.0.1:8000` if both containers share the host network. The recommended approach for this Linux deployment is `extra_hosts: host-gateway` so nginx uses `host.docker.internal` as the upstream.

**Primary recommendation:** Start with the DTLS spike as a standalone CLI script (`spike/dtls_test.py`) before wiring into FastAPI. Once a real light changes color, integrate into the API layer.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12 (pinned) | Runtime | `hue-entertainment-pykit` mbedTLS wheels break on 3.13+ — hard constraint |
| FastAPI | 0.115.x | Backend framework | Native asyncio; built-in WebSocket; Pydantic validation |
| Uvicorn | 0.32.x | ASGI server | Standard FastAPI companion; asyncio event loop |
| hue-entertainment-pykit | 0.9.3 | DTLS transport to Hue Bridge | Only viable Python DTLS PSK solution; wraps python-mbedtls |
| aiosqlite | 0.20.x | Async SQLite access | Async-compatible; no separate DB service; atomic writes |
| zeroconf | 0.131.x | mDNS bridge discovery | Used by hue-entertainment-pykit Discovery class; standard Hue discovery |
| httpx | 0.27.x | Async HTTPS client for CLIP v2 | Async-native; better than requests for asyncio context |
| requests | 2.32.x | Sync HTTPS for pairing endpoint | Pairing is a one-shot sync call; acceptable here |
| python-multipart | 0.0.x | FastAPI form body parsing | Required when using Form() in FastAPI endpoints |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | 2.x | Request/response validation | Built into FastAPI; models for BridgeConfig, EntertainmentConfig |
| python-dotenv | 1.x | Environment variable loading | Dev convenience; not used in production Docker (env: in compose) |
| urllib3 | 2.x | HTTP transport (requests dep) | SSL warning suppression for self-signed bridge cert |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| hue-entertainment-pykit | Raw dtls package + manual DTLS | `dtls` package PSK cipher support is unreliable; hue-entertainment-pykit is tested against real bridges |
| hue-entertainment-pykit | python-mbedtls directly | More control; significantly more boilerplate; same underlying library |
| aiosqlite (raw) | SQLAlchemy async + aiosqlite | SQLAlchemy adds ORM complexity for a simple config store; raw aiosqlite is simpler |
| httpx | aiohttp | httpx has better ergonomics and first-class async support |

**Installation:**
```bash
pip install fastapi uvicorn[standard] hue-entertainment-pykit aiosqlite zeroconf httpx requests python-multipart
```

---

## Architecture Patterns

### Recommended Project Structure

```
Backend/
├── Dockerfile
├── requirements.txt
├── main.py                 # FastAPI app + lifespan; mounts routers
├── database.py             # aiosqlite init, get_db dependency, schema
├── routers/
│   ├── hue.py              # /api/hue/pair, /api/hue/configs, /api/hue/lights
│   └── health.py           # /api/health
├── models/
│   └── hue.py              # Pydantic models: BridgeCredentials, EntertainmentConfig
├── services/
│   └── hue_client.py       # CLIP v2 REST calls (discover, pair, list configs)
└── spike/
    └── dtls_test.py        # Standalone CLI spike: open DTLS, send one packet, see light change

Frontend/
├── Dockerfile
├── nginx.conf
├── package.json
├── vite.config.ts
└── src/
    ├── main.tsx
    ├── App.tsx
    └── components/
        └── PairingFlow.tsx  # Step-by-step instructions + status + bridge dropdown

docker-compose.yaml
data/                        # SQLite volume mount target (created by Docker)
```

### Pattern 1: FastAPI Lifespan with aiosqlite Schema Initialization

**What:** Use `@asynccontextmanager` lifespan to open the database, run `CREATE TABLE IF NOT EXISTS`, and store the connection in `app.state`. Endpoints access it via `request.app.state.db`.

**When to use:** Always — the database must exist before any endpoint runs.

```python
# Source: FastAPI official lifespan docs + aiosqlite pattern
from contextlib import asynccontextmanager
import aiosqlite
from fastapi import FastAPI

DATABASE_PATH = "/app/data/config.db"

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open DB and create schema
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("""
        CREATE TABLE IF NOT EXISTS bridge_config (
            id INTEGER PRIMARY KEY,
            bridge_id TEXT NOT NULL,
            rid TEXT NOT NULL,
            ip_address TEXT NOT NULL,
            username TEXT NOT NULL,
            hue_app_id TEXT NOT NULL,
            client_key TEXT NOT NULL,
            swversion INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL DEFAULT ''
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS entertainment_configs (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'inactive',
            channel_count INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            id TEXT PRIMARY KEY,
            name TEXT,
            polygon TEXT NOT NULL,   -- JSON array of [x, y] normalized coords
            order_index INTEGER DEFAULT 0
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS light_assignments (
            region_id TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            entertainment_config_id TEXT NOT NULL,
            PRIMARY KEY (region_id, channel_id, entertainment_config_id)
        )
    """)
    await db.commit()
    app.state.db = db
    yield
    # Shutdown: close DB
    await db.close()

app = FastAPI(lifespan=lifespan)
```

### Pattern 2: Hue Bridge Pairing Flow

**What:** Two-step process — mDNS discovery (or manual IP), then POST to the v1 `/api` endpoint with `generateclientkey: true` to obtain application key + clientkey.

**When to use:** First-time setup; when user presses "Pair" in UI after pressing bridge link button.

```python
# Source: Hue developer docs (hue-api.md Section 2) + hue-entertainment-pykit README
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def pair_with_bridge(bridge_ip: str, app_name: str = "HuePictureControl#backend") -> dict:
    """
    Must be called within 30 seconds of pressing the physical link button.
    Returns: {"username": "...", "clientkey": "..."}
    clientkey is the DTLS PSK — store immediately, cannot be retrieved again.
    """
    payload = {
        "devicetype": app_name,
        "generateclientkey": True   # CRITICAL: required for Entertainment API
    }
    response = requests.post(
        f"https://{bridge_ip}/api",
        json=payload,
        verify=False,
        timeout=5
    )
    data = response.json()[0]
    if "error" in data:
        raise ValueError(f"Pairing failed: {data['error']['description']}")
    return data["success"]   # {"username": "...", "clientkey": "..."}
```

### Pattern 3: Fetching Bridge Metadata for hue-entertainment-pykit

**What:** After pairing, fetch bridge resource to get `identification`, `rid`, `hue_app_id`, and `swversion` — all required by `create_bridge()`.

**When to use:** Immediately after successful pairing, before storing credentials.

```python
# Source: Hue CLIP v2 docs + hue-api.md Section 2
def fetch_bridge_metadata(bridge_ip: str, username: str) -> dict:
    """
    Fetches bridge identification, rid, hue_app_id, swversion from CLIP v2.
    Returns dict with all fields needed for create_bridge().
    """
    headers = {"hue-application-key": username}
    response = requests.get(
        f"https://{bridge_ip}/clip/v2/resource/bridge",
        headers=headers,
        verify=False,
        timeout=5
    )
    data = response.json()["data"][0]
    # bridge_id maps to identification
    # id maps to rid
    # owner.rid maps to hue_app_id
    return {
        "identification": data["bridge_id"],   # e.g. "4abb74df-..."
        "rid": data["id"],                     # UUID of bridge resource
        "hue_app_id": data.get("owner", {}).get("rid", ""),
        "swversion": data.get("swversion", 0),
        "name": data.get("metadata", {}).get("name", "Hue Bridge")
    }
```

### Pattern 4: hue-entertainment-pykit DTLS Streaming

**What:** Create `Bridge`, initialize `Entertainment` and `Streaming`, call `start_stream()`, send `set_input()` tuples, call `stop_stream()`.

**When to use:** DTLS spike and all streaming operations.

```python
# Source: hue-entertainment-pykit README + example.py
from hue_entertainment_pykit import create_bridge, Entertainment, Streaming

def run_dtls_spike(credentials: dict, config_name: str | None = None):
    """
    CLI spike: open DTLS session, send one color to first entertainment config channel.
    credentials: dict with identification, rid, ip_address, swversion,
                 username, hue_app_id, clientkey, name
    """
    bridge = create_bridge(
        identification=credentials["identification"],
        rid=credentials["rid"],
        ip_address=credentials["ip_address"],
        swversion=credentials["swversion"],
        username=credentials["username"],
        hue_app_id=credentials["hue_app_id"],
        clientkey=credentials["clientkey"],
        name=credentials["name"]
    )

    entertainment_service = Entertainment(bridge)
    configs = entertainment_service.get_entertainment_configs()

    if not configs:
        raise RuntimeError("No entertainment configurations found. Create one in the Hue app first.")

    config = list(configs.values())[0]

    streaming = Streaming(bridge, config, entertainment_service.get_ent_conf_repo())
    streaming.start_stream()
    streaming.set_color_space("xyb")

    # Send red to channel 0: (x, y, brightness, channel_id)
    streaming.set_input((0.675, 0.322, 0.8, 0))

    import time
    time.sleep(2)  # Hold the color for 2 seconds
    streaming.stop_stream()
    print("DTLS spike complete — check your light!")
```

### Pattern 5: Docker Compose with Host-Network Backend + nginx Frontend

**What:** Backend on `network_mode: host`; frontend nginx on bridge network using `extra_hosts: host-gateway` to reach backend.

**When to use:** All deployments — this is the required configuration for DTLS/UDP.

```yaml
# Source: architecture.md + verified nginx/Docker research
services:
  backend:
    build:
      context: ./Backend
      dockerfile: Dockerfile
    network_mode: host
    devices:
      - "/dev/video0:/dev/video0"
    group_add:
      - video
    volumes:
      - hue_data:/app/data
    environment:
      - LOG_LEVEL=INFO
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

  frontend:
    build:
      context: ./Frontend
      dockerfile: Dockerfile
    ports:
      - "80:80"
    extra_hosts:
      - "host.docker.internal:host-gateway"   # Makes host.docker.internal work on Linux
    depends_on:
      backend:
        condition: service_healthy
    restart: unless-stopped

volumes:
  hue_data:
```

```nginx
# Frontend nginx.conf — proxy to host-network backend via host.docker.internal
server {
    listen 80;

    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://host.docker.internal:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /ws {
        proxy_pass http://host.docker.internal:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400s;
    }
}
```

### Anti-Patterns to Avoid

- **Using `backend:8000` in nginx proxy_pass:** The backend is on host network, not Docker internal DNS. This will fail with "Connection refused" in nginx.
- **Using `127.0.0.1:8000` in bridge-network nginx:** `127.0.0.1` inside the nginx container is the nginx container's loopback, not the host. Use `host.docker.internal:8000`.
- **Calling `FastAPI BackgroundTasks` for the capture loop:** `BackgroundTasks` cannot be cancelled; use `asyncio.create_task()` with an `asyncio.Event` stop signal instead.
- **Omitting `generateclientkey: True` in pairing request:** Without it, the bridge returns only `username` and omits `clientkey`. The Entertainment API is unusable without the PSK.
- **Opening DTLS before calling `PUT /entertainment_configuration/{id}` with `{"action": "start"}`:** The bridge silently rejects the DTLS handshake if entertainment mode is not active. `hue-entertainment-pykit`'s `start_stream()` handles this internally.
- **Storing only the clientkey:** You also need `identification`, `rid`, `hue_app_id`, and `swversion` for `create_bridge()`. Fetch and store all of them at pairing time.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DTLS 1.2 PSK handshake | Custom Python DTLS | `hue-entertainment-pykit` | PSK cipher suite (`TLS_PSK_WITH_AES_128_GCM_SHA256`) is not in Python stdlib; raw implementation requires native extension and bridge-specific quirks |
| mDNS bridge discovery | Custom UDP multicast scanner | `hue-entertainment-pykit`'s `Discovery` class (uses `zeroconf`) | mDNS over Bonjour/Zeroconf has edge cases; `zeroconf` library is battle-tested |
| Async SQLite access | Sync sqlite3 calls from async context | `aiosqlite` | Sync sqlite3 blocks the event loop; aiosqlite wraps it in a thread executor |
| HueStream v2 packet building | Custom binary struct packer | Use pattern from hue-api.md Section 7.4 (not a library, but copy the known-correct format) | The binary format has specific offset requirements; getting byte order wrong causes silent rejection |

**Key insight:** The DTLS handshake is the single most complex problem. Years of community effort produced `hue-entertainment-pykit` to solve exactly this; replicating it provides zero value.

---

## Common Pitfalls

### Pitfall 1: clientkey Lost Forever
**What goes wrong:** Pairing succeeds, `clientkey` is returned, but not stored immediately — it is never returned again by any API endpoint.
**Why it happens:** `clientkey` is a one-time credential. The bridge can confirm the `username` exists but will not re-expose the PSK.
**How to avoid:** Store both `username` and `clientkey` to SQLite atomically as the very first action after a successful pairing response. Use a transaction.
**Warning signs:** DTLS handshake fails with PSK mismatch; bridge returns 200 on CLIP v2 calls but DTLS refuses connection.

### Pitfall 2: hue-entertainment-pykit Requires All Bridge Fields
**What goes wrong:** `create_bridge()` called with only `ip_address`, `username`, and `clientkey` — missing `identification`, `rid`, `hue_app_id`, `swversion`.
**Why it happens:** The README example shows all fields but doesn't explain where they come from; the pairing endpoint doesn't return them.
**How to avoid:** After pairing, call `GET /clip/v2/resource/bridge` with the application key to retrieve `bridge_id` (→ `identification`), `id` (→ `rid`), and other metadata. Store everything together.
**Warning signs:** `create_bridge()` instantiates but `start_stream()` raises authentication/configuration errors.

### Pitfall 3: nginx proxy_pass Uses Wrong Target Address
**What goes wrong:** nginx config uses `proxy_pass http://backend:8000` — Docker resolves `backend` to an IP on the internal bridge network, not the host. Connection refused.
**Why it happens:** `network_mode: host` removes the backend from Docker's internal DNS.
**How to avoid:** Use `host.docker.internal:8000` in nginx config AND add `extra_hosts: ["host.docker.internal:host-gateway"]` to the frontend service in docker-compose.yaml.
**Warning signs:** `/api/` requests return 502 Bad Gateway from nginx; `docker logs frontend` shows "Connection refused" upstream errors.

### Pitfall 4: Entertainment Mode Not Activated Before DTLS
**What goes wrong:** DTLS connection attempt silently fails or times out.
**Why it happens:** The bridge only accepts DTLS connections when an entertainment configuration is in "active" status.
**How to avoid:** `hue-entertainment-pykit`'s `start_stream()` calls the CLIP v2 activation endpoint automatically before opening the DTLS socket. Do not bypass this by calling the DTLS layer directly.
**Warning signs:** DTLS handshake timeout; no error from the bridge, just silence.

### Pitfall 5: Python 3.13+ Breaks mbedTLS
**What goes wrong:** Docker image built with `python:3.13-slim`; `pip install hue-entertainment-pykit` fails because `python-mbedtls` has no 3.13 wheel.
**Why it happens:** `python-mbedtls` uses C extension wheels pinned to specific Python ABI versions.
**How to avoid:** Pin `FROM python:3.12-slim` in the backend Dockerfile. Add a comment explaining why.
**Warning signs:** `pip install` completes but `import hue_entertainment_pykit` raises `ImportError` for `_mbedtls`.

### Pitfall 6: USB Device Passthrough Fails Without video Group
**What goes wrong:** `cv2.VideoCapture(0)` returns a capture object but `cap.isOpened()` is False, or all frames are black.
**Why it happens:** `/dev/video0` on the host is owned by group `video` (GID 44). The container process runs as root but still needs the supplementary group for device access.
**How to avoid:** Add `group_add: [video]` to the backend service in docker-compose.yaml.
**Warning signs:** OpenCV `VideoCapture` silently fails; no error logged.

### Pitfall 7: hue-entertainment-pykit Streaming Is Synchronous (Blocking)
**What goes wrong:** `streaming.start_stream()` and `streaming.set_input()` are synchronous calls. Calling them directly in an `async def` endpoint blocks the asyncio event loop.
**Why it happens:** The library uses a background thread internally but its public API is sync.
**How to avoid:** In Phase 1 (DTLS spike), run the streaming test as a standalone CLI script or use `asyncio.get_event_loop().run_in_executor(None, streaming_call)` when integrating into the FastAPI endpoint. The long-running stream loop in Phase 3 will need this pattern.
**Warning signs:** FastAPI REST endpoints become unresponsive while streaming is active.

---

## Code Examples

Verified patterns from official sources:

### Bridge Discovery via mDNS (zeroconf)
```python
# Source: hue-api.md Section 2 + hue-entertainment-pykit Discovery usage
from hue_entertainment_pykit import Discovery, Bridge

def discover_bridges() -> dict[str, Bridge]:
    """Discovers Hue bridges on the local network via mDNS/SSDP."""
    discovery = Discovery()
    bridges = discovery.discover_bridges()  # Returns {name: Bridge}
    return bridges
```

### Pairing Endpoint (FastAPI)
```python
# Source: hue-api.md Section 2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import requests, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

router = APIRouter(prefix="/api/hue")

class PairRequest(BaseModel):
    bridge_ip: str

class PairResponse(BaseModel):
    status: str
    bridge_ip: str

@router.post("/pair", response_model=PairResponse)
async def pair_bridge(req: PairRequest, request: Request):
    """
    Must be called within 30s of user pressing the physical link button.
    Stores username + clientkey to SQLite on success.
    """
    try:
        response = requests.post(
            f"https://{req.bridge_ip}/api",
            json={"devicetype": "HuePictureControl#backend", "generateclientkey": True},
            verify=False, timeout=5
        )
        data = response.json()[0]
    except Exception as e:
        raise HTTPException(502, f"Bridge unreachable: {e}")

    if "error" in data:
        desc = data["error"]["description"]
        if "link button" in desc:
            raise HTTPException(403, "Link button not pressed — press it and retry within 30s")
        raise HTTPException(400, desc)

    creds = data["success"]   # username + clientkey
    # TODO: fetch bridge metadata and store to SQLite (see Pattern 3)
    return PairResponse(status="paired", bridge_ip=req.bridge_ip)
```

### Entertainment Config List
```python
# Source: hue-api.md Section 7.1
import httpx

async def list_entertainment_configs(bridge_ip: str, username: str) -> list[dict]:
    async with httpx.AsyncClient(verify=False) as client:
        response = await client.get(
            f"https://{bridge_ip}/clip/v2/resource/entertainment_configuration",
            headers={"hue-application-key": username},
            timeout=10
        )
    return response.json()["data"]
```

### Health Endpoint
```python
# Source: architecture.md Section 7
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/health")
async def health():
    return {"status": "ok", "service": "HuePictureControl Backend"}
```

### Frontend Pairing Flow Skeleton (React)
```typescript
// Source: architecture.md Section 4 + Phase 1 delivers
// src/components/PairingFlow.tsx — guided step-by-step pairing
interface PairingStatus {
  step: "idle" | "discovering" | "awaiting_button" | "pairing" | "paired" | "error";
  message: string;
  bridgeIp?: string;
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hue v1 API (numbered light IDs, `/api/<username>/lights/1`) | CLIP v2 (UUID-based, `/clip/v2/resource/`) | 2021 (v2 released) | v2 exposes gradient segments; required for per-segment control |
| v1 Entertainment API (single channel per gradient strip) | v2 Entertainment API (per-segment channels) | 2021 | Enables 7-segment independent control |
| SSDP/UPnP bridge discovery | mDNS (`_hue._tcp.local.`) via zeroconf | 2022 (SSDP deprecated) | No internet required for discovery |
| `python:3.12-slim` as latest recommended | Still `python:3.12-slim` | Present | 3.13 broke mbedTLS wheels; 3.12 remains the correct pin |
| docker-compose v2 file format (`version: '3'`) | docker-compose v3 without `version:` key | 2024 | `version:` key deprecated in Compose spec; omit it |

**Deprecated/outdated:**
- `version: '3.8'` at top of docker-compose.yaml: deprecated, omit entirely in current Docker Compose
- SSDP discovery for Hue bridges: use mDNS (`_hue._tcp.local.`) via zeroconf instead
- `hue-application-id` header: replaced by `hue-application-key` in CLIP v2

---

## Open Questions

1. **hue-entertainment-pykit `hue_app_id` field source**
   - What we know: `create_bridge()` requires it; example shows a UUID like `"94530efc-933a-4f7c-97e5-ccf1a9fc79af"`
   - What's unclear: Exactly which CLIP v2 field maps to it. Likely `owner.rid` on the bridge resource, but this needs verification during the spike.
   - Recommendation: During the DTLS spike, inspect `GET /clip/v2/resource/bridge` response and log all fields. Try instantiating with an empty string first — the library may not validate it for authentication.

2. **hue-entertainment-pykit `swversion` field requirement**
   - What we know: It's listed as a `Bridge` model field with default 0
   - What's unclear: Whether `swversion=0` causes issues, or if the library uses it for anything critical vs. just storing it
   - Recommendation: During spike, try `swversion=0` as fallback; if streaming fails, fetch it from `GET /clip/v2/resource/bridge`.

3. **hue-entertainment-pykit thread safety when integrated with asyncio**
   - What we know: The library's README says "thread-safe service"; `set_input()` is a blocking sync call
   - What's unclear: Whether the background thread it uses internally causes issues when called from within a FastAPI lifespan
   - Recommendation: In Phase 1, run the spike as a standalone script only. In Phase 3, use `run_in_executor` for `set_input()` calls.

4. **nginx `host.docker.internal` reliability on all Linux Docker versions**
   - What we know: `extra_hosts: host-gateway` syntax works in Docker Compose v2+
   - What's unclear: Whether older Docker Engine versions (pre-20.10) support `host-gateway` as a special value
   - Recommendation: Test during Phase 1 Docker setup. If it fails, fallback is to also put frontend on `network_mode: host` — simpler but less isolated.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (none detected yet — Wave 0 creates it) |
| Config file | `Backend/pytest.ini` — Wave 0 |
| Quick run command | `cd Backend && python -m pytest tests/ -x -q` |
| Full suite command | `cd Backend && python -m pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BRDG-01 | POST /api/hue/pair returns 403 when link button not pressed | unit (mock requests) | `pytest tests/test_hue_router.py::test_pair_link_button_not_pressed -x` | Wave 0 |
| BRDG-01 | POST /api/hue/pair returns 200 with valid mock bridge response | unit (mock requests) | `pytest tests/test_hue_router.py::test_pair_success -x` | Wave 0 |
| BRDG-02 | Bridge credentials written to SQLite and retrievable after restart | integration | `pytest tests/test_database.py::test_credentials_persist -x` | Wave 0 |
| BRDG-03 | GET /api/hue/configs returns list from mock CLIP v2 response | unit (mock httpx) | `pytest tests/test_hue_router.py::test_list_configs -x` | Wave 0 |
| BRDG-05 | Entertainment config list is non-empty when bridge is paired | integration (real bridge) | manual — requires physical bridge | manual-only |
| UI-02 | Pairing flow component renders step instructions | unit (Vitest + React Testing Library) | `cd Frontend && npm run test -- PairingFlow` | Wave 0 |
| INFR-01 | `docker compose up` starts both services without error | smoke | `docker compose up --wait && curl http://localhost/api/health` | manual |
| INFR-02 | /dev/video0 accessible inside backend container | smoke | manual — requires capture card hardware | manual-only |
| INFR-03 | Backend can reach bridge IP via host network | smoke | manual — verify `curl https://<bridge-ip>/api` from container | manual-only |
| INFR-05 | SQLite file exists at /app/data/config.db after first start | integration | `pytest tests/test_database.py::test_db_file_created -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd Backend && python -m pytest tests/ -x -q`
- **Per wave merge:** `cd Backend && python -m pytest tests/ -v`
- **Phase gate:** All automated tests green + manual DTLS spike confirms real light changes color

### Wave 0 Gaps
- [ ] `Backend/tests/__init__.py` — package marker
- [ ] `Backend/tests/conftest.py` — shared fixtures (in-memory aiosqlite, mock requests)
- [ ] `Backend/tests/test_hue_router.py` — covers BRDG-01, BRDG-03
- [ ] `Backend/tests/test_database.py` — covers BRDG-02, INFR-05
- [ ] `Backend/pytest.ini` — pytest-asyncio mode = auto
- [ ] `Frontend/src/components/PairingFlow.test.tsx` — covers UI-02
- [ ] Framework install: `pip install pytest pytest-asyncio httpx` (backend) + `npm install -D vitest @testing-library/react` (frontend)

---

## Sources

### Primary (HIGH confidence)
- hue-api.md (project research) — CLIP v2 authentication flow, pairing endpoint, entertainment config structure, binary packet format
- architecture.md (project research) — FastAPI patterns, Docker Compose setup, asyncio task pattern, nginx configuration
- [hue-entertainment-pykit README + example.py](https://github.com/hrdasdominik/hue-entertainment-pykit) — complete usage pattern verified against repository source
- [FastAPI lifespan docs](https://fastapi.tiangolo.com/advanced/events/) — lifespan context manager pattern
- [FastAPI WebSocket docs](https://fastapi.tiangolo.com/advanced/websockets/) — WebSocket pattern
- [aiosqlite gist example](https://gist.github.com/petrilli/81511edd88db935d17af0ec271ed950b) — dependency injection pattern

### Secondary (MEDIUM confidence)
- [IoTech Blog — Entertainment API](https://iotech.blog/posts/philips-hue-entertainment-api/) — DTLS flow and packet format (verified against project research)
- [oneuptime — nginx docker localhost](https://oneuptime.com/blog/post/2025-12-16-nginx-docker-localhost-host/view) — `host.docker.internal` on Linux via `extra_hosts: host-gateway`
- [Docker Community Forums — reverse proxy nginx](https://forums.docker.com/t/reverse-proxy-from-nginx-container-to-url-on-host/26473) — Linux proxy_pass patterns
- [openHAB v2 binding docs](https://www.openhab.org/addons/bindings/hue/doc/readme_v2.html) — CLIP v2 rate limits and authentication

### Tertiary (LOW confidence)
- `hue_app_id` field mapping: inferred from Bridge model source; exact CLIP v2 response field needs empirical verification during spike
- `swversion` default=0 acceptability: untested; needs spike verification

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified against official sources and project research
- Architecture: HIGH — patterns derived from FastAPI official docs and architecture.md
- hue-entertainment-pykit API: MEDIUM — library source inspected; a few fields (hue_app_id, swversion) need spike verification
- Docker networking: MEDIUM — host-gateway extra_hosts pattern verified for Linux; needs integration test
- Pitfalls: HIGH — derived from project research (architecture.md, hue-api.md) and verified community sources

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable stack; hue-entertainment-pykit unlikely to change API in 30 days)
