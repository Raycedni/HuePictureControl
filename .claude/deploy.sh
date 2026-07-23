#!/bin/bash
# Deploy HuePictureControl to the production VM (hue-control, 192.168.178.117).
#
# Pushes local master, pulls on the VM via the Proxmox guest agent
# (.claude/vm-exec.sh — SSH is password-only and unusable non-interactively),
# then rebuilds/restarts only the services whose files actually changed:
#   Frontend/ changed  -> npm run build (nginx serves Frontend/dist, no restart)
#   Backend/  changed  -> systemctl restart hpc-backend.service + health poll
#
# Usage: .claude/deploy.sh [--force] [--no-push]
#   --force    rebuild frontend AND restart backend even if nothing changed
#   --no-push  skip the local `git push` (deploy whatever origin/master has)

set -euo pipefail
cd "$(dirname "$0")/.."

VM_EXEC=".claude/vm-exec.sh"
REPO="/home/raycedni/HuePictureControl"

FORCE=false
PUSH=true
for arg in "$@"; do
  case "$arg" in
    --force)   FORCE=true ;;
    --no-push) PUSH=false ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# Run a command on the VM as the repo owner.
vm() { bash "$VM_EXEC" "runuser -u raycedni -- bash -c '$1'" "${2:-60}"; }
# Run a command on the VM as root (systemctl etc.).
vm_root() { bash "$VM_EXEC" "$1" "${2:-60}"; }

if $PUSH; then
  echo "==> Pushing master to origin"
  git push origin master
fi

echo "==> Pulling on VM"
OLD=$(vm "cd $REPO && git rev-parse HEAD" 30)
vm "cd $REPO && git pull --ff-only" 120
NEW=$(vm "cd $REPO && git rev-parse HEAD" 30)
echo "    $OLD -> $NEW"

if [ "$OLD" = "$NEW" ] && ! $FORCE; then
  echo "==> Already up to date — nothing to deploy (use --force to rebuild/restart anyway)"
  exit 0
fi

if $FORCE; then
  CHANGED=$'Frontend/\nBackend/'
else
  CHANGED=$(vm "cd $REPO && git diff --name-only $OLD $NEW" 30)
fi

if echo "$CHANGED" | grep -q '^Frontend/'; then
  if echo "$CHANGED" | grep -Eq '^Frontend/package(-lock)?\.json'; then
    echo "==> Frontend deps changed — npm install"
    vm "cd $REPO/Frontend && npm install --no-audit --no-fund" 600
  fi
  echo "==> Building frontend"
  vm "cd $REPO/Frontend && npm run build" 600
else
  echo "==> Frontend unchanged — skipping build"
fi

if echo "$CHANGED" | grep -q '^Backend/'; then
  if echo "$CHANGED" | grep -q '^Backend/requirements\.txt'; then
    echo "==> Backend deps changed — pip install into /opt/hpc-venv"
    vm_root "/opt/hpc-venv/bin/pip install -r $REPO/Backend/requirements.txt" 600
  fi
  echo "==> Restarting hpc-backend.service (stop can take 60s+, polling instead of waiting)"
  # Fire the restart without blocking: the stop phase can hang on capture/DTLS threads.
  vm_root "systemctl restart hpc-backend.service --no-block" 30
  echo "==> Waiting for backend health"
  for i in $(seq 1 60); do
    sleep 3
    if HEALTH=$(vm_root "curl -sf http://localhost:8000/api/health" 15 2>/dev/null); then
      echo "    healthy after ~$((i * 3))s: $HEALTH"
      exit 0
    fi
  done
  echo "ERROR: backend did not become healthy within 180s" >&2
  vm_root "systemctl status hpc-backend.service --no-pager -l | tail -30" 30 >&2 || true
  exit 1
else
  echo "==> Backend unchanged — skipping restart"
fi
