# Phase 16: Zone Persistence Bug Fixes - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-18
**Phase:** 16-zone-persistence-bug-fixes
**Areas discussed:** Persistence location, Streaming-state source on reload, Camera ↔ zone direction

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Persistence location | localStorage vs DB vs both | ✓ |
| Streaming-state source on reload | Extend /ws/status vs new REST vs both | ✓ |
| Camera ↔ zone direction | zone→cam, cam→zone, bidirectional | ✓ |
| Reconciliation rules | Active-streaming conflict, missing zone, live follow | (deferred to Claude's Discretion) |

---

## Persistence Location

### Where should persistence live?
| Option | Description | Selected |
|--------|-------------|----------|
| Backend DB | Authoritative, survives cache clear, shared across tabs/devices | ✓ |
| localStorage only | Zero backend changes, trivial, per-browser | |
| DB + localStorage mirror | DB authoritative, localStorage as write-through cache | |

### Data shape?
| Option | Description | Selected |
|--------|-------------|----------|
| Extend camera_assignments with last_selected_at | Composite PK, timestamp query | |
| New camera_last_zone table | Separate concern, clean isolation | ✓ |
| Add column to known_cameras | Simplest migration, couples UI state with identity | |

### When to write?
| Option | Description | Selected |
|--------|-------------|----------|
| On every zone change (auto-save) | Consistent with Phase 10 D-05 | ✓ |
| Only on streaming start | Reduces noise | |
| Debounced + on start | Belt-and-suspenders | |

### API shape?
| Option | Description | Selected |
|--------|-------------|----------|
| PUT /api/cameras/last-zone/{stable_id} + merged GET /api/cameras | One round-trip, piggyback on zone_health pattern | ✓ |
| Full CRUD with dedicated GET | Isolated, extra round-trip | |
| Embed in camera_assignments endpoints | Muddles existing stable endpoint | |

---

## Streaming-State Source on Reload

### How does the frontend learn active config_id?
| Option | Description | Selected |
|--------|-------------|----------|
| Extend /ws/status snapshot + live pushes | No extra round-trip, consistent channel | ✓ |
| GET /api/capture/status REST only | Clean separation, extra HTTP call | |
| Both WS + REST | HA integration may want REST anyway | |

### Status payload fields?
| Option | Description | Selected |
|--------|-------------|----------|
| active_config_id | Required for BFIX-02 | ✓ |
| active_camera_stable_id | Also reflects camera on reload | |
| active_device_path | Useful for debugging; derivable from stable_id | ✓ |

### Idle value for active_config_id?
| Option | Description | Selected |
|--------|-------------|----------|
| null / absent | Clean semantics, frontend falls back to persisted | ✓ |
| Keep last-streamed value | Simpler frontend, harder to distinguish states | |

### Dropdown behaviour when streaming?
| Option | Description | Selected |
|--------|-------------|----------|
| Reflect live state, disable selector | Matches existing disabled={isStreaming} | ✓ |
| Reflect live state, keep enabled | Live switch = stop+restart (scope creep) | |
| Reflect only on initial load | Frozen, brittle | |

---

## Camera ↔ Zone Direction

### Camera change behaviour?
| Option | Description | Selected |
|--------|-------------|----------|
| Auto-switch to that camera's last zone | Mirror Phase 10 D-06, satisfies BFIX-01 crit #3 | ✓ |
| Keep current zone selection | Fails crit #3 | |
| Prompt toast | Interrupts workflow | |

### Tiebreak on conflict?
| Option | Description | Selected |
|--------|-------------|----------|
| Side just changed wins | Feels natural, symmetric | ✓ |
| Camera primary, zone follows | Can "snap back" surprisingly | |
| Zone primary, camera follows | Fails crit #3 | |

### Initial pre-selection order?
| Option | Description | Selected |
|--------|-------------|----------|
| Camera first → look up last zone | Satisfies crit #1 + #3 together | ✓ |
| Zone first → derive camera | Current Phase 10; fails crit #3 on camera switch | |
| Last-active pair | Not per-camera | |

### How to pick default camera on load?
| Option | Description | Selected |
|--------|-------------|----------|
| Most recently touched camera | Reuses known_cameras.last_seen_at | ✓ |
| First connected camera by path | Deterministic but ignores history | |
| No default, force selection | Extra click | |

---

## Claude's Discretion

- Stale `entertainment_config_id` (deleted from bridge) → fall back to first config, clear stale row
- Missing `camera_stable_id` → ignore row
- SQL upsert form and schema migration approach (follow existing `CREATE TABLE IF NOT EXISTS` pattern)
- Frontend selector/hook shape for consuming `last_entertainment_config_id`

## Deferred Ideas

- Live zone-switch while streaming (future polish)
- REST `GET /api/capture/status` (Phase 18 will add)
- `last_selected_at` on `camera_assignments` (rejected in favor of dedicated table)
- `localStorage` write-through cache (only if flicker measurable)
- Per-user last-active pair (rejected; per-camera memory required)
