# Architecture Research: HuePictureControl

**Domain:** Real-time ambient lighting system (HDMI capture → color analysis → Hue Entertainment API streaming)
**Researched:** 2026-03-23
**Overall confidence:** MEDIUM-HIGH (WebSearch verified against official docs/GitHub for critical claims)

---

## 1. Python Backend Framework

### Verdict: FastAPI

**Recommendation:** Use FastAPI with Uvicorn. Do not use Flask or aiohttp for this project.

### Why FastAPI Wins

This project has three concurrent concerns that must coexist cleanly:

1. A continuously-running capture/analysis/streaming loop (asyncio background task)
2. REST endpoints for configuration CRUD
3. WebSocket connections for live preview frames and real-time status

FastAPI is built on Starlette and runs on an asyncio event loop natively. All three concerns live in the same event loop, so the capture loop can push frames directly to connected WebSocket clients without thread boundaries or queues. Flask's sync-by-default model would require either threads (adding locking complexity) or Flask-SocketIO with eventlet/gevent monkey-patching, which creates subtle compatibility issues. aiohttp is equally async-capable but has worse developer experience, weaker ecosystem, and less community documentation for the specific patterns this project needs.

FastAPI benchmarks show ~15,000-20,000 req/s vs Flask's ~2,000-3,000 req/s, but raw throughput is not the bottleneck here. What matters is that FastAPI's async model eliminates the need for thread synchronization around shared state (current config, running task handle, WebSocket client registry).

**FastAPI-specific features used:**
- Native WebSocket support (`websockets` protocol, no extensions needed)
- `lifespan` context manager for startup/shutdown lifecycle
- `asyncio.create_task()` for the capture loop
- Pydantic models for config validation on REST endpoints
- `BackgroundTasks` for one-shot async work (e.g., saving config after update)

### Why Not Flask

Flask does not have native async support or WebSocket support. Flask-SocketIO (with eventlet) works but introduces a non-standard async model that conflicts with asyncio. The capture loop would run in a thread, requiring locks around every state read/write.

### Why Not aiohttp

aiohttp is a lower-level HTTP client/server library. It lacks FastAPI's automatic validation, schema generation, and the ergonomic routing layer. It would work, but requires significantly more boilerplate for the same result. It has no advantage over FastAPI for this use case.

**Confidence:** HIGH — verified against FastAPI official docs and multiple 2025 comparison articles.

---

## 2. The Capture Loop: Background Task Pattern

The capture/analysis/Hue-streaming loop must:
- Run continuously when enabled
- Be stoppable/startable on demand via the API
- Share state with WebSocket handlers (to push preview frames)
- Not block REST request handling

### Recommended Pattern: asyncio.Task with Event Control

Do NOT use FastAPI's built-in `BackgroundTasks`. That class is designed for fire-and-forget post-response work. There is no mechanism to cancel a running `BackgroundTask` — it runs to completion and cannot be stopped. The FastAPI GitHub discussions explicitly confirm this limitation.

Use `asyncio.create_task()` directly, storing the task handle in application state:

```python
# In app state (attached to app or via dependency injection)
class AppState:
    capture_task: asyncio.Task | None = None
    stop_event: asyncio.Event = asyncio.Event()
    ws_clients: set[WebSocket] = set()
    config: Config = Config()  # current region/light config

async def capture_loop(state: AppState):
    """Runs until stop_event is set."""
    cap = cv2.VideoCapture(0)
    try:
        while not state.stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                await asyncio.sleep(0.05)
                continue
            colors = analyze_regions(frame, state.config.regions)
            await stream_to_hue(colors)  # async UDP send
            # Push preview frame to all connected WS clients
            jpeg = encode_jpeg(frame)
            dead = set()
            for ws in state.ws_clients:
                try:
                    await ws.send_bytes(jpeg)
                except Exception:
                    dead.add(ws)
            state.ws_clients -= dead
            await asyncio.sleep(0)  # yield to event loop
    finally:
        cap.release()

# REST endpoint to toggle on/off
@app.post("/api/capture/start")
async def start_capture(request: Request):
    state = request.app.state
    if state.capture_task and not state.capture_task.done():
        return {"status": "already_running"}
    state.stop_event.clear()
    state.capture_task = asyncio.create_task(capture_loop(state))
    return {"status": "started"}

@app.post("/api/capture/stop")
async def stop_capture(request: Request):
    state = request.app.state
    state.stop_event.set()
    if state.capture_task:
        await state.capture_task  # wait for clean exit
    return {"status": "stopped"}
```

**Key design points:**

- `asyncio.Event` as the stop signal is clean and avoids polling a boolean flag with race conditions.
- The task handle is stored in `app.state` so any endpoint can check or cancel it.
- `await asyncio.sleep(0)` at the bottom of each loop iteration yields control back to the event loop so WebSocket message handling and REST requests aren't starved.
- The `finally` block ensures the VideoCapture device is always released, even on exception.
- OpenCV's `VideoCapture.read()` is a blocking C extension call. For 4K capture at low FPS this may block the event loop for tens of milliseconds. Wrap it with `asyncio.get_event_loop().run_in_executor(None, cap.read)` if loop starvation becomes an issue during testing.

### Configuration Hot-Reload

When the user updates region mappings via REST while the loop is running, the loop reads `state.config.regions` on every iteration. An atomic replacement is sufficient:

```python
@app.put("/api/config/regions")
async def update_regions(regions: list[Region], request: Request):
    request.app.state.config = request.app.state.config.model_copy(update={"regions": regions})
    save_config(request.app.state.config)  # persist to disk
    return {"status": "updated"}
```

Because Python's GIL protects object reference replacement, and asyncio is single-threaded, there are no race conditions here. The loop reads the old config for one more iteration at most, then picks up the new one.

**Confidence:** HIGH — pattern based on FastAPI official docs (lifespan, WebSocket) and asyncio stdlib.

---

## 3. Docker Compose Setup

### Service Structure

Two containers: `backend` (FastAPI + OpenCV + Hue streaming) and `frontend` (nginx serving built React static files). The backend is the only container that needs device access or special network config.

```yaml
services:
  backend:
    build:
      context: ./Backend
      dockerfile: Dockerfile
    devices:
      - "/dev/video0:/dev/video0"
    group_add:
      - video              # grants video group permissions inside container
    network_mode: host     # see network section below
    restart: unless-stopped
    volumes:
      - ./data:/app/data   # persisted config (SQLite or JSON)
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  frontend:
    build:
      context: ./Frontend
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    depends_on:
      backend:
        condition: service_healthy
    restart: unless-stopped
```

### USB/Video Device Passthrough

The `devices` directive in Docker Compose maps host device nodes directly into the container. For a UVC capture card:

```yaml
devices:
  - "/dev/video0:/dev/video0"
```

The container must also have the `video` group membership via `group_add: [video]` because `/dev/video0` on the host is typically owned by the `video` group (GID 44 on most Linux distros). Without this, OpenCV's `VideoCapture` will fail silently or return an empty/black frame.

**Device node stability:** USB devices can get different `/dev/videoN` indices across reboots. For a dedicated machine this is rarely a problem. If it is, create a udev rule on the host:

```bash
# /etc/udev/rules.d/99-capture-card.rules
SUBSYSTEM=="video4linux", ATTRS{idVendor}=="XXXX", ATTRS{idProduct}=="YYYY", SYMLINK+="capture_card"
```

Then map `/dev/capture_card:/dev/video0` in Compose.

**Important caveat:** USB device passthrough only works on Linux Docker hosts. It does not work on Docker Desktop for Windows or macOS (the VM between Docker and the hardware blocks direct device access). This project must run on a native Linux host or Linux VM with USB passthrough to the VM.

**Confidence:** MEDIUM — core pattern confirmed by Docker documentation; udev unevent rules are Linux host configuration, not Docker-specific.

### Network Mode: Host vs Bridge

**Recommendation: `network_mode: host` for the backend container.**

The Hue Bridge is a physical device on the LAN. The critical constraint is that the Entertainment API requires the container to initiate a DTLS/UDP session to the Bridge, and the Bridge must be able to send responses back. With bridge networking, outbound TCP connections work fine, but DTLS over UDP is more sensitive to NAT translation edge cases.

More importantly, `network_mode: host` on Linux is zero-overhead and zero-configuration. The container uses the host's IP directly and can reach any LAN device without port mapping. This is the correct choice for a single-user local-network tool.

**Bridge network concerns:**
- Docker's default bridge NAT works for outbound TCP, but the Hue Entertainment API requires DTLS (UDP) sessions. These can work through NAT but require careful firewall/iptables rules.
- The Hue Bridge mDNS discovery (used to find the Bridge IP automatically) requires multicast packets that don't propagate through Docker bridge networks by default.

**macvlan is overkill:** Macvlan gives the container its own MAC address and LAN IP, making it appear as a physical device. This is unnecessary here — the backend only needs to reach the Bridge, not be reachable by the Bridge as a named LAN device.

**Frontend uses normal bridge networking:** The frontend container only talks to the backend (via internal Docker network) and serves HTTP to the user's browser. It does not need host networking. Use `ports: ["3000:80"]`.

If `network_mode: host` is unacceptable (e.g., running on a shared machine where host network access is a concern), the fallback is bridge mode with `extra_hosts` to ensure DNS resolution works and careful verification that DTLS sessions work through NAT.

**Confidence:** MEDIUM — host network recommendation is established practice for LAN-device-accessing containers. DTLS-through-NAT behavior verified via Hue developer documentation references.

### Multi-Stage Docker Build for Python/OpenCV

OpenCV (with contrib) is ~500MB of compiled libraries. A naive `pip install opencv-python` image will be 1.5GB+. Use a multi-stage build:

```dockerfile
# Stage 1: Build/install heavy dependencies
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime image
FROM python:3.12-slim AS runtime

# Copy only the installed packages from builder
COPY --from=builder /root/.local /root/.local

# Runtime system deps for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

ENV PATH=/root/.local/bin:$PATH
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Use `opencv-python-headless`** instead of `opencv-python` — the headless variant omits GUI/display dependencies (GTK, Qt) that are never needed in a container. This alone cuts ~100MB.

**Do not compile OpenCV from source** unless specific codec or hardware-acceleration support is required. The PyPI wheel is sufficient for UVC capture via V4L2.

**Confidence:** HIGH — multi-stage build pattern well-documented; opencv-python-headless confirmed via PyPI package description.

### Frontend: nginx + Multi-Stage React Build

Build the React app in a Node.js stage, then serve static files with nginx. Do not serve the frontend from the Python backend — nginx is faster, handles static asset caching correctly, and keeps the backend focused on API concerns.

```dockerfile
# Frontend Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

The nginx config proxies `/api` and `/ws` to the backend:

```nginx
server {
    listen 80;

    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
    }

    location /ws {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**Note:** With `network_mode: host` on the backend, the backend container is not part of the Docker internal network. The nginx `proxy_pass` must use the host's loopback or LAN IP rather than the Docker service name. Use an environment variable: `proxy_pass http://${BACKEND_HOST}:8000;` with `BACKEND_HOST=127.0.0.1` for same-machine deployments.

**Alternative:** If frontend and backend are on the same machine, the frontend can proxy to `http://localhost:8000` since both containers resolve to the host network.

**Confidence:** MEDIUM — nginx reverse proxy pattern for WebSocket upgrade is standard; host-network proxy_pass complication is a known nuance.

---

## 4. Backend Architecture: Component Boundaries

```
┌─────────────────────────────────────────────────────────┐
│  FastAPI Application (single process, asyncio event loop) │
│                                                           │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │  REST Router  │  │  WebSocket   │  │  Capture Loop  │ │
│  │  /api/...    │  │  /ws/preview │  │  (asyncio Task)│ │
│  │  /api/config │  │  /ws/status  │  │                │ │
│  └──────┬───────┘  └──────┬───────┘  └───────┬────────┘ │
│         │                 │                   │          │
│         └─────────────────┴───────────────────┘          │
│                           │                              │
│                    ┌──────▼───────┐                      │
│                    │  App State   │                      │
│                    │  - config    │                      │
│                    │  - task ref  │                      │
│                    │  - ws_clients│                      │
│                    └──────┬───────┘                      │
└───────────────────────────┼─────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
     ┌────────▼────────┐        ┌────────▼────────┐
     │  Config Storage │        │  Hue Bridge     │
     │  (SQLite file)  │        │  REST v2 CLIP   │
     │  /app/data/     │        │  + Entertainment│
     └─────────────────┘        │  API (DTLS/UDP) │
                                └─────────────────┘
```

### Capture Loop Internal Flow

```
cv2.VideoCapture.read()
        │
        ▼
  decode JPEG/raw frame
        │
        ▼
  for each region in config:
    sample pixels in polygon mask
    compute dominant color (k-means or weighted average)
        │
        ▼
  batch all light assignments
        │
        ▼
  Entertainment API DTLS stream
  (single UDP packet per frame for all lights)
        │
        ▼
  encode preview JPEG (lower resolution)
        │
        ▼
  send_bytes() to all WebSocket /ws/preview clients
        │
        ▼
  asyncio.sleep(0)  ← yield event loop
```

### WebSocket Channels

Two separate WebSocket endpoints serve different consumers:

| Endpoint | Data | Format | Rate |
|---|---|---|------|
| `/ws/preview` | JPEG frame bytes | Binary (raw bytes) | ~10-15fps |
| `/ws/status` | FPS, latency, light states, errors | JSON text | ~2-4Hz |

Separating them allows the frontend to subscribe only to what it needs. The preview WebSocket is binary (`send_bytes`). The status WebSocket is text JSON.

**Preview frame downscaling:** Do not send full 4K frames over WebSocket to the browser. Downscale to ~720p or less before encoding. The browser preview does not need 4K.

### REST Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health check (used by Docker) |
| `GET` | `/api/config` | Get full config |
| `PUT` | `/api/config/regions` | Update region list |
| `PUT` | `/api/config/lights` | Update light assignments |
| `PUT` | `/api/config/bridge` | Update Bridge credentials |
| `GET` | `/api/capture/snapshot` | Single JPEG frame (no WS needed) |
| `POST` | `/api/capture/start` | Start capture loop |
| `POST` | `/api/capture/stop` | Stop capture loop |
| `GET` | `/api/capture/status` | Is loop running, fps, latency |
| `GET` | `/api/hue/lights` | List discovered Hue lights |
| `GET` | `/api/hue/groups` | List entertainment groups |

---

## 5. Philips Hue API Integration

### API Strategy

The PROJECT.md constraint is "direct API usage, no wrapper libraries." This is the correct choice for this project because:

1. The Entertainment API requires DTLS which most Python Hue libraries don't implement correctly
2. The REST v2 CLIP API is straightforward REST+JSON
3. Wrapper libraries add a dependency update lag and may not support gradient segment addressing

**Two separate API surfaces:**

| API | Protocol | Purpose | Rate |
|---|---|---|---|
| CLIP v2 REST | HTTPS to port 443 on Bridge | Discovery, config, entertainment group setup | Low (config only) |
| Entertainment API | DTLS/UDP to port 2100 on Bridge | Real-time light color streaming | 25-50Hz |

### Entertainment API: The DTLS Problem

The Entertainment API uses DTLS 1.2 with PSK (TLS_PSK_WITH_AES_128_GCM_SHA256). Python's standard `ssl` module does not support DTLS (only TLS over TCP). Three options:

1. **`hue-entertainment-pykit`** (PyPI) — A Python library specifically built to solve the DTLS handshake problem. Despite the PROJECT.md constraint on "no wrapper libraries," this is specifically a DTLS transport helper, not a Hue API wrapper. It handles the mbedTLS/DTLS complexity that's otherwise nearly impossible to implement correctly in Python without native extensions. Confidence: MEDIUM (library is small, inspectable, actively maintained as of early 2026).

2. **`mbedtls` Python bindings** — Direct DTLS implementation. More control, more complexity.

3. **Subprocess to a small C/Go DTLS relay** — Extreme approach, not recommended.

**Recommended:** Use `hue-entertainment-pykit` for the DTLS transport layer only, implementing all Hue API logic (group setup, color commands, segment addressing) directly. This respects the spirit of the "no wrapper" constraint (no Hue API business logic abstraction) while solving the genuine DTLS transport problem that has no pure-Python stdlib solution.

### Gradient Segment Addressing

For Hue Festavia and Flux (the key differentiators), the Entertainment API packet format supports per-segment RGB values within a single UDP frame. The gradient channel type in the Entertainment API sends up to N segment colors in one packet. This is the core technical advantage over REST API polling (which can't hit 25Hz with 16+ segments due to rate limits).

**Confidence:** MEDIUM — Entertainment API packet format verified against Philips Hue developer documentation; specific gradient segment support confirmed via IoTech blog post cross-referencing API docs.

---

## 6. Configuration Storage: SQLite

**Recommendation: SQLite over JSON files.**

The configuration is structured (regions are polygons with associated light IDs and segment counts), relational (a region references a light which has capabilities), and will be read/written from multiple code paths.

**Use SQLite with a single file at `/app/data/config.db` on a mounted Docker volume.**

Rationale:
- JSON files require reading and writing the entire file atomically. For a single-user local tool this almost never matters, but it adds an extra failure mode (partial write on power loss corrupts all config).
- SQLite provides atomic transactions. Updating one region's color does not risk corrupting the rest.
- `aiosqlite` provides async SQLite access compatible with FastAPI's event loop.
- Schema evolution (adding new fields) is handled with `ALTER TABLE`, not careful JSON surgery.
- Querying specific lights or regions by ID is O(1) with an index, not O(n) JSON scan.

**Schema sketch:**

```sql
CREATE TABLE bridge_config (
    id INTEGER PRIMARY KEY,
    ip TEXT NOT NULL,
    username TEXT NOT NULL,      -- CLIP v2 hue-application-key
    psk TEXT NOT NULL,           -- Entertainment API PSK
    psk_identity TEXT NOT NULL,  -- Entertainment API PSK identity
    entertainment_group_id TEXT
);

CREATE TABLE regions (
    id TEXT PRIMARY KEY,         -- UUID
    name TEXT,
    polygon JSON NOT NULL,       -- [[x,y], [x,y], ...] as JSON array
    order_index INTEGER
);

CREATE TABLE light_assignments (
    region_id TEXT NOT NULL REFERENCES regions(id),
    light_id TEXT NOT NULL,      -- Hue resource ID
    segment_index INTEGER,       -- NULL for single-color lights
    PRIMARY KEY (region_id, light_id, segment_index)
);
```

**For the MVP**, a single JSON file is acceptable if it simplifies initial development. Migrate to SQLite before the feature is considered complete.

**Confidence:** MEDIUM — SQLite recommendation is standard engineering wisdom; `aiosqlite` compatibility with FastAPI confirmed via FastAPI official SQL docs.

---

## 7. Health Checks, Logging, and Error Recovery

### Health Check

Expose a `/health` endpoint that returns 200 if the app is running. Distinguish between liveness (process is alive) and readiness (capture device accessible, Bridge reachable):

```python
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/health/ready")
async def readiness(request: Request):
    state = request.app.state
    issues = []
    if not check_device("/dev/video0"):
        issues.append("capture_device_missing")
    if not await ping_bridge(state.config.bridge_ip):
        issues.append("bridge_unreachable")
    if issues:
        raise HTTPException(503, detail={"issues": issues})
    return {"status": "ready"}
```

Docker healthcheck should use `/health` (liveness only) — if `/health/ready` is used, a temporary Bridge disconnection would cause Docker to restart the container, which is wrong. The readiness endpoint is for the frontend's status display.

### Logging

Use Python's stdlib `logging` module with structured output. Do not print directly. FastAPI/Uvicorn produce access logs automatically. Add application-level logging for:
- Capture loop start/stop events
- Frame processing times (log every N frames if >target latency)
- Bridge connection events (connect, disconnect, reconnect)
- Config changes

Log level via environment variable: `LOG_LEVEL=INFO` (default), set to `DEBUG` for development.

### Error Recovery Patterns

| Failure | Detection | Recovery |
|---|---|---|
| Capture card removed mid-loop | `cap.read()` returns `False` | Wait 2s, attempt `VideoCapture` re-open; if 5 consecutive failures, set loop state to ERROR and notify via `/ws/status` |
| Bridge TCP/UDP unreachable | DTLS send raises exception | Retry with exponential backoff (1s, 2s, 4s, max 30s); continue capturing and buffering last-good colors |
| Bridge credential invalid | CLIP v2 returns 403 | Stop loop, set state to BRIDGE_AUTH_ERROR, require user to re-enter credentials in UI |
| WebSocket client disconnects | send raises exception | Remove from `ws_clients` set; do not crash loop |
| Config write fails (disk full) | SQLite raises exception | Log error, return 500 to REST caller, do not crash loop |

The capture loop must never crash silently. Wrap the entire loop body in `try/except Exception as e` and emit the error to `/ws/status` clients so the UI can display it.

---

## 8. Communication Protocol Summary

| Concern | Protocol | Direction | Format |
|---|---|---|---|
| Region CRUD | REST `PUT /api/config/regions` | Browser → Backend | JSON |
| Light assignment | REST `PUT /api/config/lights` | Browser → Backend | JSON |
| Bridge credentials | REST `PUT /api/config/bridge` | Browser → Backend | JSON |
| Capture toggle | REST `POST /api/capture/start|stop` | Browser → Backend | — |
| Live preview | WebSocket `/ws/preview` | Backend → Browser | Binary (JPEG) |
| Status updates | WebSocket `/ws/status` | Backend → Browser | JSON text |
| Hue config (discovery, group setup) | HTTPS REST (CLIP v2) | Backend → Bridge | JSON |
| Real-time light streaming | DTLS/UDP (Entertainment API) | Backend → Bridge | Binary |

---

## 9. Open Questions / Research Flags

1. **Entertainment API packet format for gradients:** The Philips Hue developer portal documentation on exact byte layout for gradient (multi-segment) channel types needs careful verification against the actual API. The IoTech blog post gives partial detail. Plan a dedicated spike for the Entertainment API packet format before implementing the streaming encoder.

2. **OpenCV blocking on read():** For 4K capture at 30fps, each `cap.read()` may block the asyncio event loop for ~33ms. This is fine if the loop's target rate is ≤25Hz, but test empirically. If it blocks REST handling, wrap with `run_in_executor`.

3. **DTLS library maturity:** `hue-entertainment-pykit` is a small community library (not Philips-official). Verify it handles session re-establishment after bridge reboot/network hiccup before relying on it in production.

4. **nginx proxy_pass with host network backend:** When the backend uses `network_mode: host`, the frontend nginx container can't use the Docker service name to reach it. Verify the `proxy_pass` strategy (host loopback, explicit IP, or shared host network) before finalizing docker-compose.yaml.

5. **udev rules for device stability:** If the deployment machine is also used for other USB devices, the video device node path may shift. Confirm udev rule configuration with the actual capture card vendor/product IDs.

---

## Sources

- [FastAPI WebSockets official documentation](https://fastapi.tiangolo.com/advanced/websockets/)
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)
- [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [FastAPI SQL Databases](https://fastapi.tiangolo.com/tutorial/sql-databases/)
- [Docker Compose devices configuration](https://oneuptime.com/blog/post/2026-02-08-how-to-use-docker-compose-devices-configuration/view)
- [Docker Macvlan network driver docs](https://docs.docker.com/engine/network/drivers/macvlan/)
- [FastAPI WebSocket background tasks pattern — HexShift](https://hexshift.medium.com/implementing-background-tasks-with-websockets-in-fastapi-034cdf803430)
- [FastAPI vs Flask 2025 comparison — Strapi](https://strapi.io/blog/fastapi-vs-flask-python-framework-comparison)
- [hue-entertainment-pykit on GitHub](https://github.com/hrdasdominik/hue-entertainment-pykit)
- [aiohue on PyPI](https://pypi.org/project/aiohue/)
- [Philips Hue Entertainment API — IoTech Blog](https://iotech.blog/posts/philips-hue-entertainment-api/)
- [Docker multi-stage builds — Nick Janetakis](https://nickjanetakis.com/blog/shrink-your-docker-images-by-50-percent-with-multi-stage-builds)
- [OpenCV in Docker — sharing webcams on Linux](https://www.funwithlinux.net/blog/sharing-devices-webcam-usb-drives-etc-with-docker/)
- [FastAPI healthchecks and Docker — BetterStack](https://betterstack.com/community/guides/scaling-python/fastapi-with-docker/)
- [BackgroundTasks stop discussion — FastAPI GitHub #10548](https://github.com/fastapi/fastapi/discussions/10548)
- [Docker networking: bridge vs host — oneuptime](https://oneuptime.com/blog/post/2026-02-08-how-to-choose-between-bridge-and-host-networking-modes/view)
- [fastapi-frame-stream on GitHub](https://github.com/TiagoPrata/fastapi-frame-stream)
