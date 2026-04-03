# Phase 7: Device Enumeration and Camera Assignment Schema - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phase:** 07-device-enumeration-and-camera-assignment-schema
**Areas discussed:** Device identity & stability, Reconnect behavior, DB schema design

---

## Device Identity & Stability

### Camera identification strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Sysfs first, QUERYCAP fallback | Try sysfs VID/PID/serial, fall back to QUERYCAP card name | ✓ |
| QUERYCAP card name only | Skip sysfs, use V4L2 card name only | |
| Device path only | Store /dev/videoN directly | |

**User's choice:** Sysfs first, QUERYCAP fallback
**Notes:** Recommended approach — stable identity with graceful degradation.

### Sysfs failure behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Silent fallback with log warning | Log warning, use card name internally | |
| UI alert on degraded identity | Show notice in camera selector | ✓ |

**User's choice:** UI alert on degraded identity
**Notes:** User wants transparency about identity limitations.

### API response contents

| Option | Description | Selected |
|--------|-------------|----------|
| Both path and stable ID | Return device_path, stable_id, and display_name | ✓ |
| Stable ID + name only | Hide raw device path from API | |

**User's choice:** Both path and stable ID
**Notes:** Recommended — useful for debugging and the path is needed internally.

---

## Reconnect Behavior

### Manual reconnect mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Re-scan + re-match by identity | Full device re-scan, match by stable ID, update path | ✓ |
| Re-open same path | Try to reopen last known /dev/videoN | |
| Re-scan + user confirms | Re-scan and ask user to pick if ambiguous | |

**User's choice:** Re-scan + re-match by identity
**Notes:** Recommended — handles kernel path reassignment automatically.

### Reconnect API design

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated reconnect endpoint | POST /api/cameras/reconnect with stable_id | ✓ |
| Re-scan via GET /api/cameras | No new endpoint, frontend detects device reappearance | |

**User's choice:** Dedicated reconnect endpoint
**Notes:** Clear intent, easy to wire to a UI button.

### Disconnected camera behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Show disconnected, no fallback | Zone shows camera as disconnected, assignment preserved | ✓ |
| Auto-fallback to default | Silently switch to default camera | |

**User's choice:** Show disconnected, no fallback, but show the name of the previously connected camera
**Notes:** User specifically requested that the previously assigned camera's display name remain visible in disconnected state.

---

## DB Schema Design

### Assignment storage

| Option | Description | Selected |
|--------|-------------|----------|
| New camera_assignments table | Separate table with config_id PK | ✓ |
| Column on entertainment_configs | Add columns to existing table | |
| Column on regions table | Add camera_device to regions | |

**User's choice:** New camera_assignments table
**Notes:** Clean separation from bridge-synced tables.

### Last seen timestamp

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, store last_seen | Add last_seen_at column | ✓ |
| No, keep it simple | Determine connection status live only | |

**User's choice:** Yes, store last_seen
**Notes:** Helps distinguish "just unplugged" from "gone for days".

### Known cameras table

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, separate known_cameras table | Track all cameras ever seen with history | ✓ |
| No, discovery is ephemeral | Camera list from live scans only | |

**User's choice:** Yes, separate known_cameras table
**Notes:** Enables dropdown to show previously seen but disconnected cameras.

---

## Claude's Discretion

- Default camera fallback strategy (CAMA-03)
- linuxpy vs extending existing ctypes for enumeration

## Deferred Ideas

None — discussion stayed within phase scope.
