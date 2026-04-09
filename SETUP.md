# HuePictureControl Setup Guide

## Prerequisites

- Docker and Docker Compose v2+
- WSL2 (if running on Windows) with usbipd-win installed
- One or more USB HDMI capture cards

## Quick Start

1. Clone the repository
2. Attach your USB capture card (see WSL2 section below if on Windows)
3. Start the stack: `docker compose up -d`
4. Visit http://localhost:8091 to open the web UI
5. Backend API is available at http://localhost:8001

## Multi-Device Passthrough

### Default: cgroup Rules (Recommended)

`docker-compose.yaml` uses `device_cgroup_rules` to grant the backend container access to all V4L2 video devices:

```yaml
device_cgroup_rules:
  - 'c 81:* rw'    # All V4L2 video devices (major 81) — hot-plug capable
group_add:
  - video           # Required: host video group GID for /dev/video* access
```

This configuration:

- Grants container access to **all** V4L2 video devices (Linux major number 81 is the V4L2 subsystem — a static kernel assignment)
- Supports **hot-plug**: new capture cards become accessible inside the container without restarting Docker
- Works alongside `group_add: [video]`, which provides filesystem-level permissions on `/dev/video*`

#### Verify devices are visible inside the container

```bash
docker compose exec backend ls -la /dev/video*
```

#### Verify the backend can enumerate capture devices

```bash
docker compose exec backend python -c "
from services.capture_v4l2 import enumerate_capture_devices
for d in enumerate_capture_devices():
    print(d.device_path, d.card)
"
```

If `enumerate_capture_devices()` returns an empty list but hardware is attached, see the Fallback section below.

### Fallback: Explicit Devices List

**When to switch:** If `docker compose exec backend ls /dev/video*` shows "No such file or directory" despite hardware being attached. This happens when `device_cgroup_rules` sets the cgroup permission but the Docker environment doesn't auto-mount the device node into the container's `/dev`.

**How to switch:** Replace the `device_cgroup_rules` block in `docker-compose.yaml` with an explicit `devices` list:

```yaml
    devices:
      - "/dev/video0:/dev/video0"
      - "/dev/video2:/dev/video2"   # Add one line per capture card
```

**Trade-offs of explicit devices list:**

- Each device path must match the host path exactly
- Adding a new capture card requires updating `docker-compose.yaml` and restarting the container (`docker compose restart backend`)
- No hot-plug support — the device must be listed before container start

## WSL2 / usbipd Walkthrough

On Windows, USB capture cards are attached to the Windows host. You must share them into WSL2 using `usbipd-win` before Docker can access them.

### Step 1 — List attached USB devices

```powershell
# PowerShell (Administrator recommended for bind/attach operations):
usbipd list
```

Example output:

```
Connected:
  BUSID  VID:PID    DEVICE                          STATE
  1-2    1b3f:2008  USB Video, USB Audio             Not shared
  1-5    0bda:8153  Realtek USB GbE                  Not shared
  2-1    1b3f:2008  USB Video, USB Audio             Not shared
```

Identify the BUSID(s) of your capture card(s) — look for "USB Video" or your card's product name.

### Step 2 — Bind the device (one-time per device)

```powershell
usbipd bind --busid 1-2
```

Binding enables sharing for this device. This only needs to be done once per device across reboots.

### Step 3 — Attach to WSL2

```powershell
usbipd attach --wsl --busid 1-2
```

This makes the device accessible inside WSL2. You must repeat this after every `wsl --shutdown` or Windows restart.

### Step 4 — Verify the device is visible in WSL2

```bash
ls /dev/video*
# Expected: /dev/video0  (or /dev/video1, /dev/video2, etc.)
```

### Step 5 — Start Docker and verify inside the container

```bash
docker compose up -d
docker compose exec backend ls /dev/video*
```

### Adding a Second Capture Card

Repeat with the second card's BUSID:

```powershell
usbipd bind --busid 2-1
usbipd attach --wsl --busid 2-1
```

In WSL2:

```bash
ls /dev/video*
# Expected: /dev/video0  /dev/video2  (paths may differ)
```

Both devices should appear in the camera selector dropdown in the web UI at http://localhost:8091.

## Common Gotchas

### Device Path Shifts on Re-attach

When you unplug and re-plug a capture card, or run `usbipd detach` followed by `usbipd attach`, the device path may change — for example, `/dev/video0` may reappear as `/dev/video2`. This is normal Linux V4L2 behavior: minor numbers are assigned sequentially based on what's currently registered.

**What to do:** Open the web UI, go to the camera selector for each zone, and select the new device path from the dropdown. With the `device_cgroup_rules` approach, no Docker restart is needed — the new device path is immediately accessible inside the container.

### WSL Restart Drops USB Attachments

After `wsl --shutdown` or a Windows restart, all `usbipd` attachments are dropped. Re-run `usbipd attach --wsl --busid <busid>` for each capture card before starting the stack.

### Docker Desktop vs. Native Docker Engine

If using Docker Desktop (not Docker Engine installed directly in WSL2), USB devices attached to WSL2 may not be visible inside Docker containers. Docker Desktop runs in a separate lightweight VM — USB devices must reach that VM, not just WSL2.

- **usbipd-win 4.x+** added Docker Desktop integration, which should pass devices through automatically
- Verify with: `docker compose exec backend ls /dev/video*`
- If devices don't appear despite hardware being attached to WSL2, upgrade usbipd-win to 4.x or switch to running Docker Engine natively inside WSL2

### Permission Denied on /dev/video*

If the backend logs "Permission denied" when opening a capture device, verify that `group_add: [video]` is present in `docker-compose.yaml`. The `video` group (GID 44 on standard Linux) provides filesystem-level access to V4L2 device nodes. The `device_cgroup_rules` alone are not sufficient — both settings are required.

### device_cgroup_rules Shows Empty Device List

If `device_cgroup_rules` is active but `enumerate_capture_devices()` returns an empty list:

1. Verify the device is visible inside the container: `docker compose exec backend ls /dev/video*`
2. If `/dev/video*` shows "No such file", the device node is not mounted in the container — switch to the explicit `devices` list (see Fallback section above)
3. If `/dev/video*` exists but `enumerate_capture_devices()` is still empty, the device may not report `V4L2_CAP_VIDEO_CAPTURE` — try a different capture card driver or check the card is a UVC device

## Verifying the Full Stack

```bash
# Health check
curl http://localhost:8001/api/health

# Bridge pairing status
curl http://localhost:8001/api/hue/status

# List detected capture devices
curl http://localhost:8001/api/capture/devices
```

Expected: JSON responses with status information. The `/api/capture/devices` endpoint lists all devices returned by `enumerate_capture_devices()`.
