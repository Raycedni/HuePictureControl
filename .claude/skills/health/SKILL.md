---
name: health
description: Check full stack health — backend API, frontend, Hue Bridge connectivity, and WebSocket endpoints
disable-model-invocation: true
---

# Full Stack Health Check

Run all health checks in parallel where possible, then report a status table.

## Checks to Run (in parallel)

### 1. Backend API
```bash
curl -sf http://localhost:8000/api/health
```

### 2. Hue Bridge Pairing
```bash
curl -sf http://localhost:8000/api/hue/status
```

### 3. Light Discovery
```bash
curl -sf http://localhost:8000/api/hue/lights
```

### 4. Entertainment Configs
```bash
curl -sf http://localhost:8000/api/hue/configs
```

### 5. Regions
```bash
curl -sf http://localhost:8000/api/regions
```

### 6. Frontend Dev Server
```bash
curl -sf -o /dev/null -w "%{http_code}" http://localhost:8091
```

### 7. WebSocket Status Endpoint
```bash
curl -sf -o /dev/null -w "%{http_code}" --header "Upgrade: websocket" --header "Connection: Upgrade" http://localhost:8000/ws/status
```

## Output Format
Report as a status table:
```
Backend API:      OK / DOWN
Bridge Paired:    Yes (name) / No / Unreachable
Lights Found:     N lights
Entertainment:    N configs (names)
Regions:          N configured
Frontend:         OK / DOWN
WebSocket:        OK / DOWN
```

Flag any service that is down and suggest how to start it.
