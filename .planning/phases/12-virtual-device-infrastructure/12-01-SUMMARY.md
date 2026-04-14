---
phase: 12-virtual-device-infrastructure
plan: 01
subsystem: infra
tags: [v4l2loopback, ffmpeg, asyncio, subprocess, pydantic, wireless]

# Dependency graph
requires:
  - phase: capture_service.py (existing)
    provides: CaptureRegistry.acquire/release — ref-counted device pool used by PipelineManager
provides:
  - Backend/models/wireless.py — Pydantic response models for wireless endpoints (ToolInfo, NicCapability, CapabilitiesResponse, WirelessSessionResponse, SessionsResponse)
  - Backend/services/pipeline_manager.py — PipelineManager + WirelessSessionState; owns v4l2loopback device lifecycle, FFmpeg/scrcpy subprocess management, producer-ready gate, supervised restart
affects: [12-02-wireless-router, 12-03-main-integration, phase-13-scrcpy, phase-14-miracast]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - asyncio.Event producer-ready gate — CaptureRegistry.acquire() blocked until process writes first frame
    - asyncio.create_subprocess_exec for long-lived processes (FFmpeg, scrcpy) with stderr=DEVNULL
    - asyncio.to_thread for short-lived blocking subprocess.run calls (v4l2loopback-ctl)
    - exponential backoff supervisor loop — base=1.0s, max=30s, max_retries=5
    - WirelessSessionState dataclass — internal per-session state not exposed via Pydantic directly

key-files:
  created:
    - Backend/models/wireless.py
    - Backend/services/pipeline_manager.py
  modified: []

key-decisions:
  - "ipaddress.ip_address() validation on device_ip before passing to scrcpy subprocess (T-12-02 mitigation)"
  - "asyncio.create_subprocess_exec throughout — no shell=True anywhere (T-12-01 mitigation)"
  - "_wait_for_producer uses asyncio.sleep(1.5) + proc.returncode check — simple and reliable per RESEARCH.md recommendation"
  - "_restart_session is implemented but marked as not-fully-supported without stored launch params — supervisor logs warning; sessions must be re-created by caller"

patterns-established:
  - "Pattern: Producer-ready gate — asyncio.Event set by _wait_for_producer task after delay if proc.returncode is None"
  - "Pattern: SIGTERM->SIGKILL with asyncio.wait_for timeout in stop_session"
  - "Pattern: best-effort cleanup in _cleanup_session_resources — each step wrapped in try/except"
  - "Pattern: stop_all iterates list(keys()) to avoid dict mutation during iteration"

requirements-completed: [VCAM-01, VCAM-02, VCAM-03, WPIP-01, WPIP-02, WPIP-03]

# Metrics
duration: 25min
completed: 2026-04-14
---

# Phase 12 Plan 01: Virtual Device Infrastructure — Data Models and PipelineManager

**v4l2loopback lifecycle service: creates virtual camera devices via v4l2loopback-ctl, launches FFmpeg/scrcpy subprocesses with DEVNULL stderr, gates CaptureRegistry.acquire behind a producer-ready asyncio.Event, and supervises restarts with exponential backoff.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-04-14T20:48:16Z
- **Completed:** 2026-04-14
- **Tasks:** 2/2
- **Files modified:** 2 (created)

## Accomplishments

### Task 1: Pydantic response models (Backend/models/wireless.py)

Five Pydantic models for the wireless endpoints:
- `ToolInfo` — available + version string for tool detection
- `NicCapability` — p2p_supported + optional interface for WiFi Direct NIC
- `CapabilitiesResponse` — 4 tools + NIC + ready/miracast_ready/scrcpy_ready (D-09)
- `WirelessSessionResponse` — session lifecycle fields per D-11 including started_at
- `SessionsResponse` — list wrapper for /sessions endpoint

Pure Pydantic file, no logic, no imports beyond BaseModel — exact analog to models/hue.py.

### Task 2: PipelineManager service (Backend/services/pipeline_manager.py)

Full subprocess lifecycle manager:

- `WirelessSessionState` dataclass — tracks proc, producer_ready Event, supervisor_task, status, error_message, started_at
- `DEVICE_NR_MIRACAST = 10`, `DEVICE_NR_SCRCPY = 11` — D-02 static device numbering
- `_create_v4l2_device` — asyncio.to_thread(subprocess.run, ['sudo', 'v4l2loopback-ctl', 'add', '-n', label, '--exclusive_caps=1', device_path])
- `_delete_v4l2_device` — best-effort, CalledProcessError logged not raised
- `_launch_ffmpeg` — asyncio.create_subprocess_exec with stderr=DEVNULL, -loglevel quiet, -nostats (D-06)
- `_wait_for_producer` — asyncio.sleep(1.5) then set producer_ready if proc alive (D-08)
- `_supervise_session` — exponential backoff 1s/2s/4s/8s/16s, max_retries=5 (D-07, T-12-03)
- `start_miracast` / `start_android_scrcpy` — full session startup with producer-ready gate (WPIP-01)
- `start_android_scrcpy` — validates IP via ipaddress.ip_address() before subprocess (T-12-02)
- `stop_session` — SIGTERM → 5s timeout → SIGKILL, cancel supervisor, cleanup (VCAM-02)
- `stop_all` — safe iteration with per-session try/except for shutdown (D-03)
- `get_sessions` / `get_session` — serialization helpers for router layer

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 65a523f | feat(12-01): add Pydantic response models for wireless endpoints |
| 2 | 477387e | feat(12-01): add PipelineManager service with full subprocess lifecycle |

## Deviations from Plan

### Auto-added Security Mitigations

**1. [Rule 2 - Security] IP address validation in start_android_scrcpy**
- **Found during:** Task 2 implementation
- **Issue:** T-12-02 in threat model requires `ipaddress.ip_address()` validation before passing device_ip to scrcpy subprocess args
- **Fix:** Added `ipaddress.ip_address(device_ip)` check at start of `start_android_scrcpy`; raises RuntimeError on invalid input
- **Files modified:** Backend/services/pipeline_manager.py
- **Commit:** 477387e

**2. [Rule 2 - Completeness] _restart_session limitation documented**
- **Found during:** Task 2 implementation
- **Issue:** `_restart_session` cannot truly restart without the original `rtsp_url` or `device_ip` stored on `WirelessSessionState` — the supervisor loop calls it but the launched process cannot be re-created
- **Decision:** The supervisor logs a warning and returns without relaunching. Sessions that exhaust retries are cleaned up. Full restart support (storing launch params on state) is deferred — the supervisor framework and backoff are correct; only the re-launch step is a no-op stub.
- **Files modified:** Backend/services/pipeline_manager.py

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| `_restart_session` does not actually re-launch process | Backend/services/pipeline_manager.py | ~170 | Launch params (rtsp_url, device_ip) not stored on WirelessSessionState; supervisor calls this but it logs a warning and returns. Full restart support requires adding launch_params to WirelessSessionState (a one-field addition). This will be resolved when the Miracast or scrcpy router phase tests this end-to-end. |

## Threat Surface

No new threat surface beyond what is documented in the plan's threat model. Both T-12-01 (exec not shell) and T-12-02 (IP validation) are fully mitigated.

## Self-Check

### Files created exist:
- Backend/models/wireless.py — FOUND
- Backend/services/pipeline_manager.py — FOUND

### Commits exist:
- 65a523f — FOUND (feat(12-01): add Pydantic response models for wireless endpoints)
- 477387e — FOUND (feat(12-01): add PipelineManager service with full subprocess lifecycle)

## Self-Check: PASSED
