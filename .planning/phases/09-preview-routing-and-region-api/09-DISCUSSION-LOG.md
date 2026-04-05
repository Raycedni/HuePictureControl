# Phase 9: Preview Routing and Region API - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 09-preview-routing-and-region-api
**Areas discussed:** Preview WebSocket routing, Camera health endpoint, Region camera_device field, Frontend API changes, Region-to-zone linking, Preview device param format, Backward compatibility, No cameras indicator

---

## Preview WebSocket Routing

### Frame Acquisition Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only peek | Preview calls registry.get() to read frames but does NOT acquire/release (no ref counting). Passive observer. | ✓ |
| Full acquire/release | Preview acquires from registry (increments ref count) on connect, releases on disconnect. | |
| You decide | Claude picks during planning. | |

**User's choice:** Read-only peek
**Notes:** Simpler, no risk of preview holding a device open.

### Unavailable Device Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Keep alive, retry | Connection stays open, retries every 1s. Matches existing pattern. | ✓ |
| Close with error code | Close WebSocket with specific close code. Client must reconnect. | |
| Fall back to default | Silently serve frames from default device. | |

**User's choice:** Keep alive, retry
**Notes:** None

---

## Camera Health Endpoint

| Option | Description | Selected |
|--------|-------------|----------|
| Extend /api/cameras | Add zone_health section to existing GET /api/cameras response. | ✓ |
| New /api/cameras/health | Dedicated endpoint for per-zone health only. | |
| Per-zone on /api/hue/configs | Attach camera health to entertainment configs endpoint. | |

**User's choice:** Extend /api/cameras
**Notes:** None

---

## Region camera_device Field

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only, derived | camera_device NOT stored in regions table. Joined from camera_assignments. | ✓ |
| Stored column, writable | Add camera_device TEXT column to regions. Contradicts CAMA-01. | |
| You decide | Claude picks during planning. | |

**User's choice:** Read-only, derived
**Notes:** None

---

## Frontend API Changes

| Option | Description | Selected |
|--------|-------------|----------|
| API types only | Update TypeScript types and API functions. No UI components. | ✓ |
| Types + preview hook wiring | Also wire preview hook's device param into EditorCanvas. | |
| Minimal backend only | No frontend changes at all in Phase 9. | |

**User's choice:** API types only
**Notes:** None

---

## Region-to-Zone Linking

| Option | Description | Selected |
|--------|-------------|----------|
| Via light_assignments | Join region -> light_assignments.entertainment_config_id -> camera_assignments. | |
| Add entertainment_config_id to regions | Store config_id directly on each region row. Simpler join. | ✓ |
| You decide | Claude picks during planning. | |

**User's choice:** Add entertainment_config_id to regions
**Notes:** User preferred the simpler direct column over the multi-table join.

---

## Preview Device Param Format

| Option | Description | Selected |
|--------|-------------|----------|
| Device path | ?device=/dev/video0 — matches registry key directly. | |
| Stable ID | ?device=vid:pid:serial — survives USB re-plugs. | |
| Accept both | If param looks like /dev/* use directly, otherwise resolve as stable_id. | ✓ |

**User's choice:** Accept both
**Notes:** None

---

## Backward Compatibility

| Option | Description | Selected |
|--------|-------------|----------|
| Fall back to default | No ?device= → use registry.get_default(). Maintains backward compatibility. | |
| Return error | Require ?device= param. Breaking change for existing frontend. | ✓ |
| You decide | Claude picks based on analysis. | |

**User's choice:** Return error
**Notes:** Intentional breaking change — Phase 9 frontend updates will account for this.

---

## No Cameras Indicator

| Option | Description | Selected |
|--------|-------------|----------|
| Empty devices + flag | GET /api/cameras returns cameras_available: false. Frontend shows banner. | ✓ |
| Health endpoint only | Frontend infers from empty devices array. No explicit flag. | |
| Dedicated /api/cameras/status | New lightweight endpoint for polling. | |

**User's choice:** Empty devices + flag
**Notes:** User specifically requested showing when backend has no cameras available.

---

## Claude's Discretion

- entertainment_config_id migration strategy for existing regions (nullable column, backfill)
- Exact WebSocket close code when ?device= is missing
- Whether zone_health includes zones with no camera assignment

## Deferred Ideas

None — discussion stayed within phase scope
