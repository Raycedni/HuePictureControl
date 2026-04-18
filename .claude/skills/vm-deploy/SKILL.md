---
name: vm-deploy
description: Deploy backend changes to the HueControl VM (Proxmox 192.168.178.201, VM 100, user raycedni) and verify they took effect. Covers push, pull, systemctl restart, test — plus arbitrary shell on the VM via the Proxmox guest-agent API.
disable-model-invocation: true
---

# VM Deploy — HueControl Backend

Deploy code changes to the Linux backend VM that runs `hpc-backend.service`.

## Environment

| Field | Value |
|-------|-------|
| Proxmox host | `192.168.178.201:8006` |
| Proxmox node | `mogli` |
| VM ID | `100` (named `HueControl`) |
| VM hostname | `hue-control` |
| VM IP | `192.168.178.117` |
| Backend user | `raycedni` (uid 1000, in `sudo`, `video`, `docker` groups) |
| Repo path | `/home/raycedni/HuePictureControl` |
| Venv | `/opt/hpc-venv` |
| Service | `hpc-backend.service` (systemd) |
| Backend port | `8000` |
| Git remote | `https://github.com/Raycedni/HuePictureControl.git` |

## Key Tool: `.claude/vm-exec.sh`

Runs arbitrary shell inside the VM as **root** via the QEMU guest agent (no SSH, no password). Uses a Proxmox API token baked into the script (gitignored).

### Usage

```bash
# Single command (quote properly — double quotes inside are fine, the script JSON-escapes)
bash .claude/vm-exec.sh 'systemctl status hpc-backend.service'

# Multi-line script via stdin (recommended for anything complex)
bash .claude/vm-exec.sh - 120 <<'VMSCRIPT'
set -e
cd /home/raycedni/HuePictureControl
git pull
systemctl restart hpc-backend.service
VMSCRIPT
```

Second argument is the timeout in seconds (default 60). Output of the VM command goes to this script's stdout; exit code propagates.

### Running as `raycedni` instead of root
Guest agent runs commands as root. To execute as the backend user:
```bash
bash .claude/vm-exec.sh 'su - raycedni -c "cd /home/raycedni/HuePictureControl && git pull"'
```

## Standard Deploy Flow

When a backend code change needs to go live on the VM, run these in order:

### 1. Verify changes are committed locally
```bash
git status
git log --oneline -3
```

### 2. Push to GitHub
```bash
git push origin master
```

### 3. Pull and restart on the VM
```bash
bash .claude/vm-exec.sh - 120 <<'VMSCRIPT'
set -e
su - raycedni -c "cd /home/raycedni/HuePictureControl && git pull"
systemctl restart hpc-backend.service
sleep 3
systemctl is-active hpc-backend.service
VMSCRIPT
```

### 4. Smoke-test
```bash
curl -s http://192.168.178.117:8000/api/health
# Expect: {"status":"ok","service":"HuePictureControl Backend"}
```

### 5. Tail logs if something looks off
```bash
bash .claude/vm-exec.sh 'journalctl -u hpc-backend.service -n 40 --no-pager'
```

## One-Off VM Operations

### Install system packages
```bash
bash .claude/vm-exec.sh 'apt update && apt install -y <package>' 300
```

### Build and install something from source (long timeout!)
```bash
bash .claude/vm-exec.sh - 600 <<'VMSCRIPT'
set -e
cd /tmp
git clone --depth 1 https://github.com/...
cd ...
make && make install
VMSCRIPT
```

### Add a sudoers rule (minimum privilege, NOPASSWD)
```bash
bash .claude/vm-exec.sh - 30 <<'VMSCRIPT'
cat > /etc/sudoers.d/myrule <<'EOF'
raycedni ALL=(ALL) NOPASSWD: /path/to/binary arg *
EOF
chmod 0440 /etc/sudoers.d/myrule
visudo -cf /etc/sudoers.d/myrule  # syntax check
VMSCRIPT
```

**Important:** `sudo` resolves binaries via its own `secure_path` (defaults to `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`). A rule for `/usr/bin/foo` will NOT match if `sudo` resolves to `/usr/local/bin/foo`. Either:
- List both paths in the rule: `/usr/bin/foo add *, /usr/local/bin/foo add *`
- Or ensure only one binary exists in the search path.

## Troubleshooting Reference

### `sudo: a terminal is required to read the password`
The NOPASSWD rule isn't matching. Check:
```bash
bash .claude/vm-exec.sh 'su - raycedni -c "sudo -n -l" | grep NOPASSWD'
```
Fix the sudoers file to include the exact path `sudo` resolves to.

### `v4l2loopback-ctl: unknown command 'add'`
Ubuntu 24.04's packaged v4l2loopback is 0.12.7, which predates the `add`/`delete` verbs. Build from source — see `docs/deploy-notes.md` (Phase 13 install) or the `Building v4l2loopback 0.15+` section below.

### `scrcpy` runs but prints `Content snap command-chain ... not found: ensure slot is connected`
Snap scrcpy's GPU content slot is broken on headless servers. Build scrcpy from source instead (v2.7+ required for `--no-video-playback`).

### Backend restart kills active sessions
`systemctl restart hpc-backend.service` signals uvicorn, which triggers lifespan shutdown (stops all wireless sessions, releases capture devices). Brief downtime is normal.

### API token revoked or Proxmox unreachable
The token in `.claude/vm-exec.sh` is `claude@pam!claude=<uuid>`. Generate a new one at Proxmox UI → Datacenter → API Tokens, then update the `AUTH` line in `.claude/vm-exec.sh` (file is gitignored).

## Building v4l2loopback 0.15+ from Source (Phase 13 Prerequisite)

```bash
bash .claude/vm-exec.sh - 600 <<'VMSCRIPT'
set -e
KVER=$(uname -r)
apt install -y linux-headers-$KVER build-essential dkms help2man git
rm -rf /tmp/v4l2loopback
git clone --depth 1 https://github.com/umlaeute/v4l2loopback.git /tmp/v4l2loopback
cd /tmp/v4l2loopback
make
make install
make install-utils
depmod -a
modprobe v4l2loopback
ln -sf /usr/local/bin/v4l2loopback-ctl /usr/bin/v4l2loopback-ctl  # compat symlink
v4l2loopback-ctl --version
VMSCRIPT
```

## Building scrcpy 2.7+ from Source (Phase 13 Prerequisite)

```bash
bash .claude/vm-exec.sh - 600 <<'VMSCRIPT'
set -e
apt install -y ffmpeg adb git meson ninja-build pkg-config \
  libavcodec-dev libavdevice-dev libavformat-dev libavutil-dev libswresample-dev \
  libsdl2-dev libusb-1.0-0-dev wget
rm -rf /tmp/scrcpy
git clone --depth 1 --branch v2.7 https://github.com/Genymobile/scrcpy.git /tmp/scrcpy
cd /tmp/scrcpy
mkdir -p server
wget -q https://github.com/Genymobile/scrcpy/releases/download/v2.7/scrcpy-server-v2.7 -O server/scrcpy-server
meson setup build-auto --buildtype=release --strip -Db_lto=true -Dprebuilt_server=/tmp/scrcpy/server/scrcpy-server
ninja -C build-auto
ninja -C build-auto install
scrcpy --version
VMSCRIPT
```

## Related Files

- `.claude/vm-exec.sh` — the exec helper (gitignored, contains API token)
- `.claude/proxmox-api-reference.md` — Proxmox API notes (gitignored)
- `.gitignore` — ensures all Proxmox credential files stay local
