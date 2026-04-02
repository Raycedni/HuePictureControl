# HuePictureControl — Development Guide

## Test Commands

### Backend (Python 3.12)
```bash
source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest
```
If venv doesn't exist:
```bash
python3 -m venv /tmp/hpc-venv && source /tmp/hpc-venv/bin/activate && pip install -r Backend/requirements.txt
```

### Frontend (Node 20+)
```bash
cd Frontend && npx vitest run
```

### Full Stack (Docker)
```bash
docker compose up -d
```

## Dev Servers
- Backend: http://localhost:8000 (runs via Docker or `uvicorn main:app --reload --port 8000`)
- Frontend: http://localhost:8091 (`npm run dev` in Frontend/)
- Backend health: `curl http://localhost:8000/api/health`

## Key API Endpoints
- `GET /api/health` — service health
- `GET /api/hue/status` — bridge pairing status
- `GET /api/hue/lights` — discover lights on bridge
- `GET /api/hue/configs` — entertainment configurations
- `GET /api/regions` — configured screen regions
- `POST /api/capture/start` — start streaming to lights
- `POST /api/capture/stop` — stop streaming
- `GET /ws/status` — WebSocket for streaming metrics
- `GET /ws/preview` — WebSocket for live JPEG frames

## Architecture
- Backend: FastAPI + aiosqlite + hue-entertainment-pykit (DTLS streaming)
- Frontend: React 19 + TypeScript + Konva.js canvas + Zustand + shadcn/ui
- Python 3.12 pinned (hue-entertainment-pykit incompatible with 3.13+)
- Backend needs host network for DTLS/UDP port 2100 access to Hue Bridge

## Hardware
- Hue Bridge v2 at 192.168.178.23 (paired)
- USB capture card at /dev/video0 (or virtual via v4l2loopback at /dev/video10)
- Entertainment config "TV-Bereich" (6 channels)

## Autonomous Testing Checklist
Before making changes, verify:
1. `python -m pytest` — all backend tests pass (167+)
2. `npx vitest run` — all frontend tests pass (30+)
3. `curl localhost:8000/api/health` — backend is reachable
4. Use Playwright MCP to visually verify frontend changes at http://localhost:8091
