# Phase 12: Virtual Device Infrastructure - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-14
**Phase:** 12-virtual-device-infrastructure
**Areas discussed:** Session persistence, Sudoers approach, Capabilities API depth, Error reporting
**Mode:** --auto (all decisions auto-selected)

---

## Session Persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Ephemeral only | Memory-only sessions, no DB persistence | ✓ |
| DB-persisted | Store sessions in SQLite, survive restarts | |
| Hybrid | Ephemeral runtime + DB for session history/audit | |

**User's choice:** [auto] Ephemeral only (recommended default)
**Notes:** Virtual devices and FFmpeg subprocesses don't survive process death. DB persistence would create stale records needing cleanup.

---

## Sudoers Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Sudoers NOPASSWD | Two narrow rules for v4l2loopback-ctl add/delete | ✓ |
| Run as root | Backend runs as root (broad permissions) | |
| Polkit rules | Desktop-oriented privilege escalation | |

**User's choice:** [auto] Sudoers NOPASSWD (recommended default)
**Notes:** Minimal privilege escalation. Documented in setup instructions.

---

## Capabilities API Depth

| Option | Description | Selected |
|--------|-------------|----------|
| Tool presence + version + hardware | Full introspection: versions, NIC P2P, ready/not-ready | ✓ |
| Tool presence only | Just check if binaries exist on PATH | |
| Version only | Tool presence + version, no hardware check | |

**User's choice:** [auto] Tool presence + version + hardware (recommended default)
**Notes:** Frontend needs P2P support info to gate Miracast UI in Phase 15.

---

## Error Reporting

| Option | Description | Selected |
|--------|-------------|----------|
| Status field on session | Polling via GET /api/wireless/sessions, status + error_message | ✓ |
| WebSocket events | Real-time push via StatusBroadcaster | |
| Both polling + WebSocket | Status field + optional WebSocket subscription | |

**User's choice:** [auto] Status field on session (recommended default)
**Notes:** Polling-friendly, no WebSocket complexity for infrastructure phase. Can extend later.

---

## Claude's Discretion

- PipelineManager class structure
- Exponential backoff parameters
- subprocess_exec vs subprocess_shell choice

## Deferred Ideas

None — auto mode stayed within phase scope.
