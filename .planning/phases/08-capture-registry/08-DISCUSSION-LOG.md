# Phase 8: Capture Registry - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phase:** 08-capture-registry
**Areas discussed:** Registry lifecycle, Reference counting & cleanup, StreamingService wiring, Error isolation
**Mode:** Auto (all decisions auto-selected with recommended defaults)

---

## Registry Lifecycle

| Option | Description | Selected |
|--------|-------------|----------|
| Lazy creation on first get() | Create CaptureBackend when first requested, not at startup | ✓ |
| Eager pre-creation at startup | Open all known devices during lifespan startup | |
| Hybrid (pre-create assigned, lazy others) | Pre-create devices with active assignments | |

**User's choice:** Lazy creation on first get() [auto-selected]
**Notes:** Matches existing pattern where capture opens only when streaming starts. Avoids holding device handles for cameras not in use.

---

## Reference Counting & Cleanup

| Option | Description | Selected |
|--------|-------------|----------|
| Ref counting with release at zero | Track active sessions per device, destroy backend when count hits zero | ✓ |
| Timer-based idle cleanup | Release backends after N seconds of inactivity | |
| Explicit close only | Only release when explicitly told to (e.g., device reassignment) | |

**User's choice:** Ref counting with release at zero [auto-selected]
**Notes:** STATE.md blocker explicitly flagged ref counting edge cases. This approach prevents premature release during stop→reassign→start sequences.

---

## StreamingService Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| Registry lookup at start() time | StreamingService takes registry in constructor, resolves capture in start() | ✓ |
| Capture injection at construction | Caller resolves capture before creating StreamingService | |
| Service locator pattern | StreamingService accesses registry from app.state directly | |

**User's choice:** Registry lookup at start() time [auto-selected]
**Notes:** Minimal change to constructor signature. Registry is passed once, capture resolution happens per-session based on camera_assignments DB lookup.

---

## Error Isolation

| Option | Description | Selected |
|--------|-------------|----------|
| Per-zone error state | Each zone's streaming handles its own camera errors independently | ✓ |
| Global error propagation | Any camera failure stops all streaming | |
| Registry-level health monitoring | Registry watches all backends and reports aggregate health | |

**User's choice:** Per-zone error state [auto-selected]
**Notes:** Already the natural behavior — each CaptureBackend and StreamingService instance has independent error/reconnect handling.

---

## Claude's Discretion

- Thread safety strategy for registry (threading.Lock vs asyncio.Lock)
- Whether CaptureRegistry is standalone class or part of capture_service.py

## Deferred Ideas

None
