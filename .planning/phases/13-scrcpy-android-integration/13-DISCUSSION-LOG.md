# Phase 13: scrcpy Android Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-16
**Phase:** 13-scrcpy-android-integration
**Areas discussed:** Reconnect strategy, Error surface

---

## Reconnect Strategy

### Q1: WiFi interruption detection

| Option | Description | Selected |
|--------|-------------|----------|
| Stale-frame detection (Recommended) | Monitor virtual device for new frames. If no frame in ~3 seconds, force-kill scrcpy and restart. Reuses D-07 pattern. More responsive. | ✓ |
| Process exit only | Wait for scrcpy to exit on its own when WiFi drops, then restart via existing supervisor. Simpler but slower (30+ seconds). | |

**User's choice:** Stale-frame detection
**Notes:** Reuses existing pattern from Phase 12, provides sub-5-second detection.

### Q2: ADB state on reconnect

| Option | Description | Selected |
|--------|-------------|----------|
| Full reconnect (Recommended) | Run adb disconnect + adb connect before relaunching scrcpy. Ensures clean ADB state. Slightly slower but more reliable. | ✓ |
| Relaunch scrcpy only | Just restart scrcpy with --tcpip. Faster but ADB state may be stale. | |

**User's choice:** Full reconnect
**Notes:** Clean ADB state is worth the minor latency cost.

---

## Error Surface

### Q1: Error reporting granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Error codes + messages (Recommended) | Add error_code field alongside error_message. Structured codes for frontend-specific guidance. Backward-compatible. | ✓ |
| Plain error messages only | Keep current status + error_message pattern. Simpler but frontend can't distinguish failure types. | |

**User's choice:** Error codes + messages
**Notes:** Enables Phase 15 frontend to show actionable guidance per failure type.

### Q2: Endpoint response behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Wait for producer-ready (Recommended) | POST blocks until scrcpy produces frames (~15s timeout). Returns 200 on success, error on failure. Caller knows immediately. | ✓ |
| Return immediately (async) | POST returns 202 with session_id. Caller polls GET /sessions. Faster response but requires polling. | |

**User's choice:** Wait for producer-ready
**Notes:** Matches Phase 12 pattern. Synchronous feedback preferred over polling.

---

## Areas Not Discussed (user skipped)

- **Wireless source tagging** — How scrcpy devices appear in GET /api/cameras (Claude's discretion)
- **ADB auth handling** — How first-time ADB authorization is surfaced (Claude's discretion)

## Claude's Discretion

- Wireless source tagging approach in cameras API
- ADB first-time authorization UX (error code approach covers this via `adb_unauthorized`)
- Stale-frame monitoring implementation details
- ADB timeout values and retry parameters

## Deferred Ideas

None — discussion stayed within phase scope.
