# Phase 11: Docker Multi-Device Infrastructure - Research

**Researched:** 2026-04-09
**Domain:** Docker Compose device passthrough + WSL2/usbipd documentation
**Confidence:** HIGH

## Summary

This phase is purely infrastructure configuration and documentation — no backend code changes. The backend (CaptureRegistry from Phase 8, camera APIs from Phase 7) is already multi-camera-ready. The only work is:

1. Enabling `device_cgroup_rules: 'c 81:* rw'` in `docker-compose.yaml` (replacing the commented-out `devices` list) so all V4L2 capture cards become accessible inside the container without restarting Docker.
2. Authoring `SETUP.md` at the project root with a complete walkthrough of the WSL2/usbipd workflow, both passthrough approaches, and troubleshooting.

The current `docker-compose.yaml` already has `group_add: [video]` and commented usbipd notes — this is an extension, not a rewrite.

**Primary recommendation:** Use `device_cgroup_rules: 'c 81:* rw'` as the default passthrough strategy (hot-plug support, no container restart required). Document the explicit `devices` list as a fallback.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Default approach uses `device_cgroup_rules: 'c 81:* rw'` in docker-compose.yaml — new capture cards become accessible inside the container without restarting Docker.
- **D-02:** Explicit `devices` list is documented as a fallback in SETUP.md for users who encounter cgroup rules instability on specific Docker/Compose versions.
- **D-03:** `group_add: [video]` remains (already present) — required for device access regardless of passthrough approach.
- **D-04:** Multi-device documentation lives in a separate `SETUP.md` file at the project root. Docker-compose.yaml gets brief inline comments pointing to SETUP.md.
- **D-05:** SETUP.md includes a full WSL2/usbipd walkthrough with step-by-step commands (`usbipd list`, `usbipd bind`, `usbipd attach`), example output, and common gotchas (device path shifts on re-attach, need to re-attach after WSL restart).
- **D-06:** SETUP.md documents both passthrough approaches (cgroup rules default + explicit devices fallback) with guidance on when to switch.

### Claude's Discretion
- Docker-compose.yaml comment style and level of detail (brief pointers to SETUP.md)
- SETUP.md structure and section ordering
- Whether to include a troubleshooting section in SETUP.md

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DOCK-01 | Docker Compose supports multiple video device passthrough | `device_cgroup_rules: 'c 81:* rw'` grants access to all `/dev/video*` nodes (major 81 = V4L2) inside the container without listing each device explicitly. The existing `group_add: [video]` already handles GID permissions. |
| DOCK-02 | Documentation for adding/configuring multiple capture devices | `SETUP.md` at project root covers: usbipd workflow, cgroup rules vs explicit devices, device path shift gotcha, WSL2-specific notes. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Docker Compose | v2.x (already in use) | Container orchestration | Already the project deployment mechanism |
| usbipd-win | already installed (`/usr/bin/usbipd` present in WSL) | USB device sharing from Windows host to WSL2 | Required for WSL2 USB passthrough; already used in project |

### No New Libraries Required
This phase adds zero new packages. All changes are YAML configuration and Markdown documentation.

## Architecture Patterns

### Current docker-compose.yaml State
The backend service currently has:
- `devices:` stanza commented out with single `/dev/video0:/dev/video0`
- `group_add: [video]` active
- Commented usbipd commands (`usbipd list`, `usbipd bind`, `usbipd attach`) as inline notes

### Recommended Change: cgroup Rules Approach [VERIFIED: Docker Compose docs]
Replace the commented `devices` block with `device_cgroup_rules`:

```yaml
services:
  backend:
    # ... existing config ...
    device_cgroup_rules:
      - 'c 81:* rw'     # Grant access to all V4L2 video devices (major 81)
    group_add:
      - video            # Required: host GID 44 for /dev/video* access
    # See SETUP.md for multi-device passthrough and WSL2/usbipd walkthrough
```

**Why `c 81:* rw`:**
- Linux device major number 81 is the V4L2 video subsystem [VERIFIED: kernel docs]
- `c` = character device, `*` = any minor number, `rw` = read+write
- This grants access to all `/dev/video0`, `/dev/video1`, etc. present on the host — including devices attached after container start (hot-plug)
- `group_add: [video]` must co-exist: cgroup rules control kernel-level device access; the `video` group controls filesystem permission on `/dev/video*`

### Fallback: Explicit Devices List
For SETUP.md documentation as a fallback:
```yaml
# Fallback: explicit device list (no hot-plug; restart required to add new card)
devices:
  - "/dev/video0:/dev/video0"
  - "/dev/video2:/dev/video2"   # Second capture card
```

Note: The commented-out `devices` block already in docker-compose.yaml uses this syntax — it becomes the documented fallback, not the primary approach.

### V4L2 Device Major Number Stability [VERIFIED: kernel source]
Linux always assigns major number 81 to V4L2 character devices. This is a static assignment in the kernel's `char_dev.c` — not dynamically assigned. The cgroup rule `c 81:* rw` is stable across kernel versions.

### WSL2 Device Path Behavior [ASSUMED based on project history + usbipd docs]
When a USB device is detached and re-attached via usbipd:
- Device path may shift (e.g., `/dev/video0` → `/dev/video2`) if other video nodes exist
- Container does NOT need restart when using `device_cgroup_rules` — new device paths are immediately accessible
- WSL2 reboots (e.g., `wsl --shutdown`) drop usbipd attachments — user must re-attach

The existing inline comment in docker-compose.yaml already captures this behavior — SETUP.md formalizes it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Video device access | Custom cgroup configuration scripts | Docker Compose `device_cgroup_rules` | Compose handles the Linux cgroup v2 device controller setup automatically |
| Device listing validation | Manual `/dev/video*` probe script | `enumerate_capture_devices()` already in `capture_v4l2.py` | Existing function uses VIDIOC_QUERYCAP to filter real capture nodes |

**Key insight:** All the hard work (device enumeration, multi-camera capture, camera assignment DB) was done in Phases 7 and 8. This phase is purely exposing those existing capabilities through the Docker layer.

## Common Pitfalls

### Pitfall 1: cgroup Rules Require Devices to Be Mounted in Volume Namespace
**What goes wrong:** `device_cgroup_rules` grants permission but `/dev/video*` nodes may not exist inside the container's `/dev` if Docker doesn't mount the host devtmpfs.
**Why it happens:** Compose uses `--device-cgroup-rule` flag on `docker run`, which only sets the cgroup permission. The device node itself must be present in the container's `/dev`.
**How to avoid:** Verify the device appears inside the container with `docker compose exec backend ls /dev/video*`. If nodes are missing, fall back to explicit `devices` list — it both sets cgroup rules AND creates the device node in the container namespace.
**Warning signs:** `enumerate_capture_devices()` returns empty list despite physical hardware being attached.

### Pitfall 2: Docker Desktop WSL2 Integration vs. Native WSL Docker
**What goes wrong:** The project's existing note says "host networking doesn't work on WSL2 Docker Desktop." `device_cgroup_rules` behavior may differ between Docker Desktop (runs in a separate VM inside WSL2) and Docker Engine running natively in WSL2.
**Why it happens:** Docker Desktop uses a lightweight VM (linuxkit) separate from the WSL2 distro — USB devices attached to WSL2 are NOT automatically visible to Docker Desktop's VM.
**How to avoid:** Document in SETUP.md that the USB capture card must be attached to the Docker VM's namespace, not just WSL2. With Docker Desktop, usbipd attaches to the entire Docker VM. Verify with `docker compose exec backend ls /dev/video*`.
**Warning signs:** usbipd shows device as attached to WSL, but `docker compose exec backend ls /dev/video*` shows nothing.

### Pitfall 3: `group_add: [video]` Uses Host GID Not Container GID
**What goes wrong:** The GID for the `video` group inside the container (python:3.12-slim) may differ from the host GID 44 referenced in the docker-compose comment.
**Why it happens:** The `video` group may not exist in `python:3.12-slim` at all, or may have a different GID.
**How to avoid:** The `group_add: [video]` in docker-compose uses the **string** "video" — Docker resolves this to the host's video GID (44 on standard Linux). The string form works correctly. If switching to numeric form, use `44` not the container's internal GID.
**Warning signs:** `Permission denied` when opening `/dev/video*` inside the container despite cgroup rules being set.

### Pitfall 4: WSL2 Device Path Shift After Re-attach
**What goes wrong:** After unplugging and re-plugging a capture card (or running `usbipd detach` + `attach`), the device path changes from `/dev/video0` to `/dev/video2` or similar.
**Why it happens:** Linux assigns V4L2 minor numbers sequentially. If a virtual device (v4l2loopback at `/dev/video10`) is present, or if a previous device left a stale node, the new device gets the next available minor.
**How to avoid:** Document in SETUP.md. The backend's `enumerate_capture_devices()` + camera re-assignment UI handles this gracefully — user selects the new path from the dropdown. This is a known project gotcha (already in MEMORY.md).
**Warning signs:** Camera shows as "disconnected" after physically re-plugging.

## Code Examples

### Verified docker-compose.yaml Pattern [CITED: docs.docker.com/reference/compose-file/services/]
```yaml
services:
  backend:
    build:
      context: ./Backend
      dockerfile: Dockerfile
    ports:
      - "8001:8000"
      - "2100:2100/udp"
    device_cgroup_rules:
      - 'c 81:* rw'    # All V4L2 video capture devices — see SETUP.md
    group_add:
      - video           # Host video group GID (44) for /dev/video* access
    volumes:
      - hue_data:/app/data
    # ... rest of config unchanged ...
```

### Verification Command (inside container)
```bash
# Verify all video devices are visible inside the container
docker compose exec backend ls -la /dev/video*

# Verify enumerate_capture_devices() finds them
docker compose exec backend python -c "
from services.capture_v4l2 import enumerate_capture_devices
for d in enumerate_capture_devices():
    print(d.device_path, d.card)
"
```

### WSL2 usbipd Workflow (for SETUP.md)
```bash
# On Windows (PowerShell as Administrator or with usbipd-win installed):
usbipd list                          # Find your capture cards
usbipd bind --busid <busid>          # One-time: bind device for sharing
usbipd attach --wsl --busid <busid>  # Attach to WSL2 (repeat after wsl --shutdown)

# In WSL2 — verify device appeared:
ls /dev/video*

# Verify inside Docker container:
docker compose exec backend ls /dev/video*
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `devices:` list (explicit per-device) | `device_cgroup_rules: 'c 81:* rw'` (wildcard) | Compose v2.x | Hot-plug support; no restart needed when adding cards |
| Comments in docker-compose.yaml | Separate SETUP.md with full walkthrough | Phase 11 | Cleaner compose file; findable docs |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | WSL2 Docker Desktop USB device path shift behavior (device lands at different /dev/videoN on re-attach) | Pitfall 4 / Common Pitfalls | Low: this is already documented in project MEMORY.md from hardware testing; docs would just be wrong about the gotcha |
| A2 | `device_cgroup_rules` causes Docker to mount device nodes in container's /dev namespace (Pitfall 1 describes the risk if this assumption is wrong) | Architecture Patterns | Medium: if cgroup rules don't auto-mount nodes, the fallback `devices` list must be the primary approach. SETUP.md should tell user to verify with `ls /dev/video*` inside container. |

## Open Questions

1. **Does `device_cgroup_rules` alone create `/dev/video*` nodes inside the container, or only set permissions?**
   - What we know: Docker docs state the flag maps to `--device-cgroup-rule` on `docker run`. The Compose `devices:` key both creates the node and sets permissions.
   - What's unclear: Whether cgroup rules alone (without explicit `devices:`) result in the device file appearing in the container's `/dev`. This is environment-specific (Docker Desktop vs. native Docker Engine).
   - Recommendation: SETUP.md should include a verification step (`docker compose exec backend ls /dev/video*`). If nodes are absent, the planner should note that the fallback explicit `devices` list may need to be the primary in some environments. This is already captured in Pitfall 1.

2. **Does Docker Desktop's WSL2 integration intercept usbipd attachment transparently?**
   - What we know: Docker Desktop uses its own lightweight VM separate from the WSL2 distro. usbipd-win 4.x added Docker Desktop integration.
   - What's unclear: Whether the current usbipd version on the user's machine supports Docker Desktop passthrough automatically.
   - Recommendation: SETUP.md should explain the Docker Desktop vs. native Docker Engine distinction and instruct user to verify inside container.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|---------|
| Docker | docker-compose.yaml changes | Available (Docker Desktop detected via /mnt/c/Program Files/Docker/) | Unknown (CLI not in WSL PATH — uses Docker Desktop integration) | — |
| usbipd | WSL2 USB passthrough | Available (`/usr/bin/usbipd` present) | Unknown (binary present; version not returned) | — |
| `/dev/video*` devices | Capture card passthrough | Not currently attached (no devices in WSL at research time) | — | Hardware must be plugged in for runtime verification |

**Missing dependencies with no fallback:**
- Physical capture cards must be attached via usbipd to verify the DOCK-01 success criterion (`ls /dev/video*` inside container shows all cards). This is a runtime verification dependency, not a build dependency.

**Missing dependencies with fallback:**
- Docker CLI not in WSL PATH — Docker Desktop manages the daemon via Windows integration. This is the established project workflow per MEMORY.md (always run through Docker, not natively).

## Validation Architecture

> `nyquist_validation` key is absent from config.json — treated as enabled.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (Backend), vitest (Frontend) |
| Config file | `Backend/pytest.ini` |
| Quick run command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |
| Full suite command | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest && cd ../Frontend && npx vitest run` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DOCK-01 | Multiple video devices accessible in container | Manual smoke test | `docker compose exec backend ls /dev/video*` | N/A — runtime verification |
| DOCK-02 | SETUP.md exists and covers required topics | Manual review | N/A — documentation only | ❌ Wave 0 (new file) |

### Sampling Rate
- **Per task commit:** Run `python -m pytest` (existing tests must remain green — no backend code changes, so all 167+ tests should pass unchanged)
- **Per wave merge:** Full suite: `python -m pytest && npx vitest run`
- **Phase gate:** Full suite green before `/gsd-verify-work`; plus manual container verification with physical hardware

### Wave 0 Gaps
- No new test files required (config + docs only phase)
- If any test mock references the old commented-out `devices:` key in docker-compose.yaml, verify it still passes after the key moves to `device_cgroup_rules:`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | yes | `device_cgroup_rules` scoped to V4L2 only (major 81) — NOT `privileged: true` |
| V5 Input Validation | no | — |
| V6 Cryptography | no | — |

### Known Threat Patterns for Docker Device Passthrough

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Excessive device access via `privileged: true` | Elevation of Privilege | Use `device_cgroup_rules: 'c 81:* rw'` scoped to major 81 only — not full host access |
| Container escape via writable device node | Tampering | V4L2 devices (major 81) are capture-only hardware; no kernel exploit surface for container escape |

**Security note from CLAUDE.md:** The project explicitly lists `privileged: true` as forbidden: "Security: grants host-level access far beyond what video capture needs." Use explicit `device_cgroup_rules` + `group_add: [video]` instead.

## Sources

### Primary (HIGH confidence)
- [Docker Compose services reference](https://docs.docker.com/reference/compose-file/services/) — `devices`, `device_cgroup_rules`, `group_add` syntax [CITED: docs.docker.com/reference/compose-file/services/]
- `/mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/docker-compose.yaml` — current state of compose file [VERIFIED: file read]
- `/mnt/c/Users/Lukas/IdeaProjects/HuePictureControl/Backend/services/capture_v4l2.py` — `enumerate_capture_devices()` implementation [VERIFIED: file read]
- `CLAUDE.md` §Docker Compose — Multiple Device Passthrough — project-specified recommended approach [VERIFIED: file read]
- `.planning/phases/11-docker-multi-device-infrastructure/11-CONTEXT.md` — locked decisions D-01 through D-06 [VERIFIED: file read]

### Secondary (MEDIUM confidence)
- [docker/compose #9059](https://github.com/docker/compose/issues/9059) — `device_cgroup_rules` instability history [CITED: 11-CONTEXT.md canonical refs]
- [Linux kernel V4L2 major number 81](https://www.kernel.org/doc/html/latest/userspace-api/media/v4l/vidioc-querycap.html) — V4L2 device major assignment [CITED: CLAUDE.md §Sources]
- Project MEMORY.md — device path shift on USB re-attach behavior [VERIFIED: known project gotcha]

### Tertiary (LOW confidence)
- A1, A2 in Assumptions Log above — runtime behavior of `device_cgroup_rules` node mounting requires hardware verification

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all config uses established Docker Compose syntax
- Architecture: HIGH — `device_cgroup_rules` is documented Docker Compose syntax; current file state verified
- Pitfalls: MEDIUM — Pitfall 1 (cgroup rules + node mounting) is a known Docker behavior that needs hardware verification; Pitfalls 2-4 are HIGH based on project history

**Research date:** 2026-04-09
**Valid until:** 2026-05-09 (Docker Compose syntax is stable; WSL2 usbipd behavior may change with usbipd-win updates)
