# HuePictureControl

Real-time screen-to-Hue-light color sync. Captures video from a USB capture card, extracts dominant colors from user-defined screen regions, and streams them to Philips Hue lights via the Entertainment API (DTLS).

## Prerequisites

| Dependency | Version | Notes |
|---|---|---|
| Python | 3.12 | hue-entertainment-pykit is incompatible with 3.13+ |
| Node.js | 20+ | For frontend build and dev server |
| Docker + Compose | Latest | For containerized deployment |
| Philips Hue Bridge | v2 | With an Entertainment configuration set up in the Hue app |
| USB Capture Card | Any V4L2/DirectShow compatible | Tested with HDMI capture cards |

## Quick Start (Docker)

The fastest way to get running. Works on Linux and WSL2.

```bash
docker compose up -d
```

- Frontend: http://localhost:8091
- Backend API: http://localhost:8000
- Health check: http://localhost:8000/api/health

### USB Capture Card in WSL2

If running Docker via WSL2, the capture card must be forwarded into WSL first:

```powershell
# In PowerShell (admin) — install usbipd if not already
winget install usbipd

# List USB devices to find your capture card
usbipd list

# Bind and attach to WSL (replace <busid> with your device, e.g. 1-3)
usbipd bind --busid <busid>
usbipd attach --wsl --busid <busid>
```

Verify inside WSL:
```bash
ls /dev/video*
```

> **Note:** The device path (e.g. `/dev/video0`) can shift on USB re-attach. If capture stops working, check the current path and update `CAPTURE_DEVICE` in `docker-compose.yaml`.

---

## Native Setup (No Docker)

Running natively avoids WSL2 virtualization overhead and gives the lowest latency. Choose the section for your OS.

### Backend on Windows

This is the recommended setup for lowest latency when your PC runs Windows.

```powershell
# 1. Install Python 3.12 (NOT 3.13+)
#    Download from https://www.python.org/downloads/release/python-3129/
#    Or: winget install Python.Python.3.12

# 2. Create and activate a virtual environment
cd Backend
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set capture device (find index via Device Manager > Cameras)
#    "0" = first camera, "1" = second, etc.
$env:CAPTURE_DEVICE = "0"

# 5. Start the backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The DirectShow backend is used automatically on Windows. It accesses the capture card directly via `cv2.VideoCapture` with the `CAP_DSHOW` backend — no WSL USB passthrough overhead.

### Backend on Linux

```bash
# 1. Create and activate a virtual environment
cd Backend
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Ensure your user has access to the video device
sudo usermod -aG video $USER
# Log out and back in for group change to take effect

# 4. Set capture device (optional, defaults to /dev/video0)
export CAPTURE_DEVICE=/dev/video0

# 5. Start the backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The V4L2 backend is used automatically on Linux. It reads MJPEG frames directly via kernel ioctls + mmap for minimal latency.

### Backend on WSL2

Same as the Linux steps above, but with the USB passthrough step from the Docker section first. Note that WSL2 adds virtualization overhead to every V4L2 ioctl and network packet — if latency matters, run natively on Windows instead.

### Frontend (All Platforms)

```bash
cd Frontend
npm install
npm run dev
```

Dev server runs at http://localhost:5173 with hot reload. API calls are proxied to `http://localhost:8000` by Vite.

For a production build:
```bash
npm run build
# Serve the dist/ folder with any static file server
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CAPTURE_DEVICE` | `/dev/video0` (Linux) or `0` (Windows) | Video capture device path or index |
| `DATABASE_PATH` | `data/config.db` | SQLite database file location |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `MIN_REGION_AREA` | `0.001` | Minimum polygon area (normalized 0-1) to keep |

---

## Running Tests

### Backend

```bash
cd Backend

# Linux / WSL
source .venv/bin/activate
python -m pytest

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
python -m pytest
```

Platform-specific capture tests run only on the matching OS:
- `test_capture_service.py` — Base class + V4L2 tests (Linux/WSL only)
- `test_capture_dshow.py` — DirectShow tests (Windows only, skipped on Linux)

### Frontend

```bash
cd Frontend
npx vitest run
```

---

## Architecture

```
Capture Card ─► V4L2 / DirectShow ─► Background Reader Thread
                                          │
                              ┌───────────┴───────────┐
                              │                       │
                         get_frame()              get_jpeg()
                              │                       │
                    Streaming Service          Preview WebSocket
                              │                  (raw MJPEG bytes)
                    ┌─────────┴─────────┐
                    │ per-region:        │
                    │  extract_region_color
                    │  rgb_to_xy (Gamut C)
                    │  compute brightness │
                    └─────────┬─────────┘
                              │
                     asyncio.gather(set_input × N channels)
                              │
                    DTLS/UDP ─► Hue Bridge ─► Lights
```

- **Backend:** FastAPI + aiosqlite + hue-entertainment-pykit
- **Frontend:** React 19 + TypeScript + Konva.js canvas + Zustand + shadcn/ui
- **Capture:** Platform-adaptive — V4L2 ioctls on Linux, DirectShow on Windows
- **Streaming:** Configurable update rate (1-100 Hz, default 50) via UI slider

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Service health |
| GET | `/api/hue/status` | Bridge pairing status |
| GET | `/api/hue/lights` | Discover lights |
| GET | `/api/hue/configs` | Entertainment configurations |
| GET | `/api/regions` | Configured screen regions |
| POST | `/api/capture/start` | Start streaming (`config_id`, optional `target_hz`) |
| POST | `/api/capture/stop` | Stop streaming |
| WS | `/ws/status` | Streaming metrics (FPS, latency) |
| WS | `/ws/preview` | Live JPEG frames from capture card |

---

## Troubleshooting

### Lights lag behind the screen
- Lower the update rate slider (fewer Hz = less processing per second, but the Hue bridge may handle it more smoothly)
- Or raise it if your hardware can keep up — the bottleneck is usually the bridge, not the PC
- Running natively on Windows instead of through WSL2 eliminates ~200-500ms of virtualization overhead

### Capture device not found
- **WSL2:** Re-attach the USB device with `usbipd attach --wsl --busid <busid>` — the device path can shift
- **Windows:** Check Device Manager > Cameras for the correct device index (0, 1, 2...)
- **Linux:** Check `ls /dev/video*` and ensure your user is in the `video` group

### Bridge pairing fails
- The Hue Bridge must be on the same LAN subnet
- Press the physical button on the bridge before initiating pairing
- Docker bridge networking has LAN access on most setups; if not, try `network_mode: host` (Linux only)

### DTLS streaming errors
- UDP port 2100 must be reachable between the backend and the Hue Bridge
- In Docker, this is mapped via `ports: "2100:2100/udp"`
- Firewalls (Windows Defender, iptables) may block UDP — add an exception for port 2100
