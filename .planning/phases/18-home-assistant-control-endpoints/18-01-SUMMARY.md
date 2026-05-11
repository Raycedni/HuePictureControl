---
phase: 18-home-assistant-control-endpoints
plan: 01
subsystem: database
tags: [schema, coordinator, foundation, sqlite, ha, aiosqlite]

requires:
  - phase: 17-wled-backend-and-streaming
    provides: StreamingCoordinator.start(config_id, target_hz) API surface and _resolve_device_path chain
  - phase: 16-zone-persistence-bug-fixes
    provides: camera_last_zone table + 3-tier zone selection cascade pattern
provides:
  - ha_state SQLite table (single-row, CHECK id=1) for HA selection persistence
  - StreamingCoordinator.start now accepts device_path_override: str | None = None
  - Foundation for Plan 02 (routers/ha.py) and Plan 03 (HA router + e2e tests)
affects: [18-02, 18-03]

tech-stack:
  added: []
  patterns:
    - "Single-row config table with CHECK (id = 1) constraint (mirrors bridge_config single-row idiom)"
    - "Optional path-override parameter on coordinator entrypoint preserves existing resolution chain when None"

key-files:
  created: []
  modified:
    - Backend/database.py
    - Backend/services/streaming_coordinator.py

key-decisions:
  - "ha_state table created lazily (no INSERT OR IGNORE seed) per D-05 — first PUT /api/ha/zone or PUT /api/ha/camera creates the row via ON CONFLICT DO UPDATE"
  - "StreamingCoordinator.start uses Option C (device_path_override parameter) over Option B (router-side camera_assignments upsert), preserving D-07 (HA does not touch camera_assignments)"
  - "Default value None for device_path_override keeps all existing call sites (routers/capture.py, tests) working unchanged"

patterns-established:
  - "Plan-02-ready coordinator API: coordinator.start(config_id, device_path_override=path_or_None)"
  - "ha_state placement clustered with camera_last_zone (selection-state group), before WLED block in init_db"

requirements-completed: [HASS-01, HASS-03, HASS-04]

duration: 8 min
completed: 2026-05-11
---

# Phase 18 Plan 01: Foundation Schema and Coordinator API Summary

**Added `ha_state` single-row table to SQLite schema and extended `StreamingCoordinator.start` with optional `device_path_override` parameter so Plan 02's `routers/ha.py` can drive streaming via HA-selected camera without touching `camera_assignments`.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-11T20:21:24Z
- **Completed:** 2026-05-11T20:29:41Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `ha_state` table created on `init_db` with exact D-04 columns (`id`, `active_config_id`, `active_camera_stable_id`, `updated_at`) and `CHECK (id = 1)` single-row constraint; no eager seed (D-05 lazy creation)
- `StreamingCoordinator.start` signature extended with `device_path_override: str | None = None`; when non-None it bypasses the `camera_assignments -> known_cameras -> CAPTURE_DEVICE` chain
- All existing 17 streaming_coordinator tests still pass; backend suite green outside pre-existing test_cameras_router.py failures (unrelated, documented in deferred-items.md)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add ha_state table DDL to database.py** — `9cf68cd` (feat)
2. **Task 2: Extend StreamingCoordinator.start with device_path_override parameter** — `279e7f7` (feat)

**Plan metadata:** _(this commit will close out the plan)_

## Files Created/Modified

- `Backend/database.py` — added 11 lines: the `CREATE TABLE IF NOT EXISTS ha_state` block between `camera_last_zone` (line 86–91) and `wled_devices` (line 108+). Lines 92–102 in the post-edit file.
- `Backend/services/streaming_coordinator.py` — modified `start` method (lines 97–117 in pre-edit became lines 97–127 in post-edit): added `device_path_override: str | None = None` parameter, added Phase 18 D-08 docstring paragraph, changed `device_path = await self._resolve_device_path(config_id)` to `device_path = device_path_override or await self._resolve_device_path(config_id)`. `_resolve_device_path` method body unchanged.

### Exact diff — Backend/database.py

After the existing `camera_last_zone` block (`""")` at line 91), inserted:

```python
    # Phase 18 D-04: HA selection state (single-row, lazy-created).
    # No eager INSERT seed — D-05 mandates lazy row creation by the first
    # PUT /api/ha/zone or PUT /api/ha/camera via ON CONFLICT DO UPDATE.
    await db.execute("""
        CREATE TABLE IF NOT EXISTS ha_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_config_id TEXT,
            active_camera_stable_id TEXT,
            updated_at TEXT
        )
    """)
```

### Exact diff — Backend/services/streaming_coordinator.py

Old signature + resolution (lines 97–113):

```python
async def start(self, config_id: str, target_hz: int = DEFAULT_HZ) -> None:
    """Start the streaming loop for the given entertainment config ID.

    No-op if already streaming (state not idle or error).

    Transitions: idle/error -> starting -> streaming (inside run loop).
    """
    if self._state not in ("idle", "error"):
        return
    ...
    device_path = await self._resolve_device_path(config_id)
```

New signature + docstring + resolution (lines 97–125):

```python
async def start(
    self,
    config_id: str,
    target_hz: int = DEFAULT_HZ,
    device_path_override: str | None = None,
) -> None:
    """Start the streaming loop for the given entertainment config ID.

    No-op if already streaming (state not idle or error).

    Transitions: idle/error -> starting -> streaming (inside run loop).

    ``device_path_override`` (Phase 18 D-08): when non-None, bypasses the
    camera_assignments -> known_cameras -> CAPTURE_DEVICE resolution chain and
    uses the provided path directly. The HA router (routers/ha.py) reads
    ``ha_state.active_camera_stable_id`` and resolves it via
    ``known_cameras.last_device_path`` before passing the result here, so D-07
    (HA does not touch camera_assignments) stays clean.
    """
    if self._state not in ("idle", "error"):
        return
    ...
    device_path = device_path_override or await self._resolve_device_path(config_id)
```

## Decisions Made

- **Plan executed exactly as specified** — both tasks followed the planner's prescribed diff verbatim (D-04 SQL block, Option C coordinator change per RESEARCH.md A1).
- **Acceptance-criterion oddity (informational, not a deviation):** Task 1's acceptance criterion stated that `grep -n "CHECK (id = 1)" Backend/database.py` should return "at least two matches (the existing `bridge_config` table plus the new `ha_state` table)". In reality, the pre-existing `bridge_config` table does NOT use `CHECK (id = 1)` — only `id INTEGER PRIMARY KEY` without the CHECK clause (verified at database.py:18). After this plan, the file contains exactly one `CHECK (id = 1)` instance (the new `ha_state` block). The intent of the criterion (ha_state has CHECK (id = 1)) is satisfied; the count expectation in the plan was simply incorrect against the codebase baseline. No code change required.

## Deviations from Plan

None — plan executed exactly as written. The only auto-applied behavior was Rule-3-adjacent
(scope boundary): the 12 pre-existing failures in `test_cameras_router.py` were confirmed
to exist BEFORE this plan via `git stash` baseline run, and were logged to
`.planning/phases/18-home-assistant-control-endpoints/deferred-items.md` without
remediation per the scope rule.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** None.

## Verification Output

### Task 1 — schema-shape Python snippet (verbatim per plan acceptance criteria)

```
$ ./.venv/Scripts/python.exe -c "<schema integrity assertions>"
OK
```

### Task 2 — inspect.signature snippet (verbatim per plan acceptance criteria)

```
$ ./.venv/Scripts/python.exe -c "<sig.parameters['device_path_override'] assertions>"
OK
```

### grep-shape acceptance counts

| Check | Expected | Actual |
|-------|----------|--------|
| `CREATE TABLE IF NOT EXISTS ha_state` in `Backend/database.py` | 1 | 1 |
| `INSERT OR IGNORE INTO ha_state` anywhere in `Backend/` | 0 | 0 |
| `active_config_id` / `active_camera_stable_id` in `Backend/database.py` | ≥1 each | 1 each |
| `device_path_override` in `streaming_coordinator.py` | ≥3 | 3 (signature, docstring, resolution) |
| `device_path = device_path_override or await self._resolve_device_path` | 1 | 1 |
| `device_path_override: str \| None = None` | 1 | 1 |

### Confirmation: no eager ha_state seed

```
$ grep -rn "INSERT OR IGNORE INTO ha_state" Backend/
(no matches)
```

### Confirmation: device_path_override parameter shape

```
$ python -c "from services.streaming_coordinator import StreamingCoordinator
... import inspect; sig = inspect.signature(StreamingCoordinator.start)
... ; assert 'device_path_override' in sig.parameters
... ; p = sig.parameters['device_path_override']
... ; assert p.default is None"
OK
```

### Test command output

- `tests/test_streaming_coordinator.py`: **17 passed in 1.07s**
- Full backend suite excluding pre-existing test_cameras_router failures: **272 passed, 21 skipped**
- Full backend suite including pre-existing failures: **287 passed, 21 skipped, 12 failed**
  - All 12 failures are in `test_cameras_router.py` and existed before Plan 18-01 (verified via `git stash`). Documented in `deferred-items.md`.

## Issues Encountered

None during planned work.

The pre-existing `test_cameras_router.py` failures (12 tests) were discovered but
explicitly out-of-scope per the executor's scope boundary rule and project-skill
guidance. They are likely related to the v1.2 native-Linux migration affecting
`/dev/video*` device detection on the Windows development host.

## User Setup Required

None — internal-only schema and API extension. No external service configuration.

## Next Phase Readiness

- **Ready for Plan 02 (routers/ha.py implementation):** Plan 02 can now `INSERT INTO ha_state ... ON CONFLICT(id) DO UPDATE` from `PUT /api/ha/zone` and `PUT /api/ha/camera`, and can call `coordinator.start(active_config_id, device_path_override=resolved_device_path)` from `POST /api/ha/start` without further coordinator changes.
- **Ready for Plan 03 (e2e tests):** integration-test schema (`_make_db_with_phase18_schema` in PATTERNS.md) can include the same `ha_state` DDL block; tests can assert on the new coordinator signature.

## Self-Check: PASSED

**Files created/modified verification:**

- `Backend/database.py` — FOUND, contains `CREATE TABLE IF NOT EXISTS ha_state` exactly once
- `Backend/services/streaming_coordinator.py` — FOUND, contains `device_path_override` 3 times
- `.planning/phases/18-home-assistant-control-endpoints/deferred-items.md` — FOUND (created, not committed; informational only)
- `.planning/phases/18-home-assistant-control-endpoints/18-01-SUMMARY.md` — FOUND (this file)

**Commit verification:**

```
$ git log --oneline -3
279e7f7 feat(18-01): extend StreamingCoordinator.start with device_path_override
9cf68cd feat(18-01): add ha_state table DDL to database schema
eb38446 docs(18): tighten bridge_paired check to require non-null credentials
```

Both task commits present. Plan acceptance criteria satisfied (modulo the
single grep-count mismatch noted under "Decisions Made", which reflects an
incorrect baseline expectation in the plan, not a missing implementation).

---
*Phase: 18-home-assistant-control-endpoints*
*Completed: 2026-05-11*
