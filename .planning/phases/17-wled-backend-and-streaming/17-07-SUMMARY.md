---
phase: 17-wled-backend-and-streaming
plan: 07
subsystem: api
tags:
  - wled
  - backend
  - router
  - crud
  - fastapi
  - pydantic
  - httpx
  - zeroconf

# Dependency graph
requires:
  - phase: 17-06
    provides: StreamingCoordinator + WledStreamer wiring, coordinator.set_wled_device_enabled
  - phase: 17-03
    provides: services/wled_client.fetch_wled_info, services/wled_discovery.scan_for_wled_devices
  - phase: 17-02
    provides: wled_devices / wled_channels / wled_light_assignments DB schema
provides:
  - "/api/wled/devices CRUD (GET, POST, DELETE)"
  - "/api/wled/devices/{id}/enabled live-gate toggle"
  - "/api/wled/scan zeroconf candidate list"
  - "Pydantic IPv4 regex gate at the request edge (T-17-INPUT mitigation)"
  - "Code-level cascade delete pattern for wled_* tables (T-17-DELETE-ORPHAN)"
affects:
  - 17-08 (Frontend WLED API client + Settings panel — consumes these endpoints)
  - 17-09 (Phase E2E test — drives the cascade delete via this router)
  - 18 (HA REST endpoints — same no-auth router pattern reused)
  - 19 (paint UI — POSTs new channels under registered devices)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pre-INSERT SELECT for duplicate-IP 409 (avoids httpx fire on retry of an existing device)"
    - "httpx error categorisation: TimeoutException/ConnectError/HTTPError -> 502; ValueError/KeyError -> 422"
    - "Code-level cascade delete via subquery (DELETE FROM child WHERE fk IN (SELECT id FROM parent WHERE ...))"
    - "Coordinator-aware mutation handler with DB-only fallback for hermetic tests"
    - "Field(pattern=...) regex gate documented as shape-only (octet validation deferred to OS)"
    - "Mock external services at the router-import path (routers.wled.fetch_wled_info / .scan_for_wled_devices)"

key-files:
  created:
    - Backend/routers/wled.py
    - Backend/tests/test_wled_router.py
    - .planning/phases/17-wled-backend-and-streaming/17-07-SUMMARY.md
  modified:
    - Backend/main.py

key-decisions:
  - "Pre-INSERT duplicate IP check returns 409 cleanly before httpx is invoked; the UNIQUE(ip) constraint remains as a belt-and-suspenders safety net."
  - "Cascade delete uses a single subquery DELETE on wled_light_assignments instead of an in-Python channel-id list — one SQL statement for any cardinality (zero, one, many) and exactly one grep hit per the success criteria."
  - "PUT /enabled routes through coordinator.set_wled_device_enabled when a coordinator is on app.state, with a DB-only fallback for tests that don't mount a coordinator. The fallback path is documented in the docstring as test-mode only."
  - "_row_to_out derives `connected` from health_snapshot's last_success_at < 5.0s, with TypeError/ValueError swallowed so unparseable timestamps surface as connected=False (resolves Research Open Question 2)."
  - "fetch_wled_info exception handlers ordered most-specific first (TimeoutException, ConnectError) before the generic httpx.HTTPError catch — order matters, ConnectError is a subclass of HTTPError."

requirements-completed:
  - WLED-01
  - WLED-02
  - WLED-03
  - WLED-05

# Metrics
duration: ~12min
completed: 2026-04-26
---

# Phase 17 Plan 07: WLED CRUD Router Summary

**Five `/api/wled/*` REST endpoints with Pydantic IPv4 regex gate, httpx /json/info probe, code-level cascade delete, coordinator-routed live-gate toggle, and a 3s zeroconf scan.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-04-26T14:53Z
- **Completed:** 2026-04-26T15:05Z
- **Tasks:** 1 of 1
- **Files modified:** 3 (1 created router, 1 created test, 1 modified main.py)

## Accomplishments

- `Backend/routers/wled.py` (362 lines): six Pydantic models + five async endpoints covering list/register/delete/enable-toggle/scan, with module-docstring documentation of the consciously accepted T-17-SSRF risk.
- `Backend/tests/test_wled_router.py` (~390 lines): 11 integration tests covering Pydantic regex rejection, httpx error mapping (502 vs 422), happy-path persist + auto-seed, list-after-add, duplicate 409, cascade delete (assignments + channels + device), 404 hygiene on DELETE/PUT, PUT-without-coordinator DB fallback, and scan candidate wrapping.
- Router registered in `Backend/main.py` between `cameras_router` and `regions_router`.

## Endpoint Status-Code Matrix

| Method | Path | 2xx | 4xx | 5xx |
|--------|------|-----|-----|-----|
| GET | `/api/wled/devices` | 200 (always — empty array if none) | — | — |
| POST | `/api/wled/devices` | 201 (registered + auto-seeded channel) | 422 (malformed IP), 409 (duplicate), 422 (led_count<=0 or shape error) | 502 (httpx timeout/connect/HTTP error) |
| DELETE | `/api/wled/devices/{id}` | 204 (cascade complete) | 404 (id unknown) | — |
| PUT | `/api/wled/devices/{id}/enabled` | 200 (toggled, returns `{id, enabled}`) | 404 (id unknown), 422 (body shape) | — |
| POST | `/api/wled/scan` | 200 (always — empty candidates if no devices) | — | — |

## Threat Model Sign-Off

| Threat ID | Mitigation Realised |
|-----------|---------------------|
| T-17-INPUT | `Field(pattern=r"^(\d{1,3}\.){3}\d{1,3}$")` rejects CIDR / hostnames / IPv6 / URL-encoded variants at the FastAPI request layer — `test_add_device_rejects_malformed_ip` asserts 422. Octet-range validation deferred to OS socket layer (documented in module docstring). |
| T-17-SSRF | Accepted. Documented in module docstring. `httpx.AsyncClient` does not follow redirects by default in `fetch_wled_info`, and the LAN is the trust boundary per PROJECT.md. |
| T-17-UDP | No UDP traffic flows from `/api/wled/devices` — only DB writes + `/json/info` HTTP fetch. UDP is gated by the existing WledStreamer enabled flag (D-12) + 30-frame cooldown (D-15) shipped in Plan 04. |
| T-17-DUPE | Pre-INSERT `SELECT id FROM wled_devices WHERE ip = ?` returns 409 cleanly before httpx fires — `test_duplicate_ip_returns_409` asserts. UNIQUE(ip) on the table is a belt-and-suspenders safety net. |
| T-17-DELETE-ORPHAN | Three explicit DELETEs in correct order (assignments via subquery on this device's channels → channels → device); `test_delete_cascades_channels_and_assignments` asserts all three table counts are 0. |
| T-17-ENABLE-RACE | When wired, `coordinator.set_wled_device_enabled` (added in Plan 06) holds the WledStreamer `_lock` while flipping the live `enabled` flag; the atomic DB UPDATE + in-memory mutation prevents toggle-vs-frame-loop interleaving. The DB-only fallback only fires when no coordinator is mounted (test mode). |

## Test Trace

11 tests in `Backend/tests/test_wled_router.py`. All use `TestClient` over a `FastAPI(lifespan=...)` that mounts only the wled router with an in-memory aiosqlite DB matching the Plan 17-02 schema. External services are patched at the router-import path (`routers.wled.fetch_wled_info`, `routers.wled.scan_for_wled_devices`).

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_add_device_rejects_malformed_ip` | POST with `{"ip":"not-an-ip"}` → 422 |
| 2 | `test_add_device_unreachable_returns_502` | `httpx.ConnectError` -> 502 with "unreachable" detail |
| 3 | `test_add_device_zero_led_count_returns_422` | `led_count=0` shape -> 422 |
| 4 | `test_add_device_persists_and_auto_seeds_channel` | 201, body fields, single auto-seeded channel `[0..299]` named "Strip" with color `#ffffff` |
| 5 | `test_list_after_add` | GET returns the just-POSTed device |
| 6 | `test_duplicate_ip_returns_409` | Second POST same IP -> 409 |
| 7 | `test_delete_cascades_channels_and_assignments` | After DELETE: 0 devices, 0 channels, 0 assignments |
| 8 | `test_delete_unknown_returns_404` | DELETE unknown id -> 404 with "not found" |
| 9 | `test_put_enabled_toggles_row_without_coordinator` | DB-only fallback path; `enabled` column = 0 after `{"enabled": false}` |
| 10 | `test_put_enabled_unknown_returns_404` | PUT unknown id -> 404 |
| 11 | `test_scan_returns_candidates_list` | Mocked zeroconf returns 2 candidates; response wraps them as `{ip, name}` |

## curl Examples

```bash
# Register a device
curl -sX POST http://localhost:8000/api/wled/devices \
  -H "Content-Type: application/json" \
  -d '{"ip": "192.168.178.50"}'

# List
curl -s http://localhost:8000/api/wled/devices | jq

# Toggle the live UDP gate
curl -sX PUT http://localhost:8000/api/wled/devices/{id}/enabled \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'

# Cascade delete
curl -sX DELETE -o /dev/null -w "%{http_code}\n" \
  http://localhost:8000/api/wled/devices/{id}

# Reject malformed IP at the edge (returns 422 immediately)
curl -sX POST http://localhost:8000/api/wled/devices \
  -H "Content-Type: application/json" \
  -d '{"ip": "not-an-ip"}'

# Scan (3s timeout)
curl -sX POST http://localhost:8000/api/wled/scan | jq
```

## Task Commits

1. **Task 1: Implement routers/wled.py + tests + main.py registration** — `b337269` (feat)

_All three target files committed in a single atomic commit per orchestrator guidance — the plan has one task whose acceptance criteria span all three files; splitting would create a transient broken state where the router exists but isn't registered._

## Files Created/Modified

- **Created** `Backend/routers/wled.py` — Five async endpoints + six Pydantic models + IPv4 regex + module-docstring documenting accepted SSRF + cascade delete + connected-derivation helper.
- **Created** `Backend/tests/test_wled_router.py` — 11 integration tests with in-memory aiosqlite, `routers.wled.fetch_wled_info` / `routers.wled.scan_for_wled_devices` mocked at the router-import path.
- **Modified** `Backend/main.py` — Added `from routers.wled import router as wled_router` import (line 17) and `app.include_router(wled_router)` between cameras_router and regions_router (line 83).

## Decisions Made

See `key-decisions` in the frontmatter. Highlights:

- **Subquery cascade delete** instead of fetching channel ids into Python and re-injecting via `IN (?,?,?)` placeholders. Single statement, correct for zero/one/many channels, and produces exactly one grep hit on `DELETE FROM wled_light_assignments` and `DELETE FROM wled_channels` (matches the plan's acceptance grep counts).
- **Coordinator-routed PUT /enabled with DB-only fallback** so the same handler works in production (live gate flip via WledStreamer lock) and in hermetic tests (no coordinator on `app.state`). The fallback writes `enabled` directly so the tests can still assert DB row state.
- **Exception handler ordering for `fetch_wled_info`:** `TimeoutException` and `ConnectError` are caught before the generic `httpx.HTTPError` because `ConnectError` is a subclass of `HTTPError` in httpx — Python's except chain resolves first match, so the order matters.
- **Connected derivation < 5.0s** per Research Open Question 2 with `TypeError`/`ValueError` swallowed (in addition to the plan's `ValueError`-only catch) — `datetime.fromisoformat` can raise either depending on Python version on malformed input, and `connected=False` is the safe default.

## Deviations from Plan

None - plan executed exactly as written.

The plan's example test code included a vestigial `test_add_device_persists_and_auto_seeds_channel` whose inner `pass` block was a comment-driven stub. The implementation makes that test fully functional (asserts the auto-seeded channel row's `start_led=0`, `end_led=led_count-1`, `name='Strip'`, `color='#ffffff'`) — a clarification, not a deviation, since the plan's `<acceptance_criteria>` explicitly call for D-09 auto-seed verification.

## Issues Encountered

- **No deps in environment.** The Windows worktree host has no `/tmp/hpc-venv` and Python 3.14 system Python lacks `aiosqlite`/`httpx`/`fastapi`/`zeroconf`. Per the prompt's `<critical_rules>` the orchestrator owns the end-of-phase pytest gate, so no pytest was invoked here. A `python3 -c "from main import app; ..."` smoke would also fail without deps and was therefore skipped (the prompt allows but does not require it). Instead, `py_compile.compile(...)` was run on all three modified files — all compile cleanly.

## Verification Performed

| Check | Result |
|-------|--------|
| `py_compile` on Backend/routers/wled.py | OK |
| `py_compile` on Backend/tests/test_wled_router.py | OK |
| `py_compile` on Backend/main.py | OK |
| `grep -c 'prefix="/api/wled"' Backend/routers/wled.py` | 1 |
| `grep -c 'pattern=r"\^(\\d' Backend/routers/wled.py` | 1 |
| `grep -c "INSERT INTO wled_devices" Backend/routers/wled.py` | 1 |
| `grep -c "INSERT INTO wled_channels" Backend/routers/wled.py` | 1 |
| `grep -c "DELETE FROM wled_channels" Backend/routers/wled.py` | 1 |
| `grep -c "DELETE FROM wled_light_assignments" Backend/routers/wled.py` | 1 |
| `grep -c "coordinator.set_wled_device_enabled" Backend/routers/wled.py` | 1 |
| `grep -c "from routers.wled import router as wled_router" Backend/main.py` | 1 |
| `grep -c "app.include_router(wled_router)" Backend/main.py` | 1 |
| Test count (`def test_*`) | 11 |
| Endpoint count (`@router.*`) | 5 |
| Pydantic model count (`class Wled.*\(BaseModel\)`) | 6 |

End-of-phase pytest gate is the orchestrator's responsibility (Plan 17-09).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **Plan 17-08 (Frontend WLED API client + Settings panel)** can consume these endpoints directly. The response shapes are stable: `WledDevicesResponse.devices[]`, `WledDeviceOut` for POST, `WledScanResponse.candidates[]` for scan, `{id, enabled}` for PUT /enabled.
- **Plan 17-09 (E2E phase test)** can drive POST → DELETE through this router and assert cascade via `wled_light_assignments` count.
- **Phase 18 (HA endpoints)** can reuse the no-auth router prefix pattern (`/api/wled` → `/api/ha`) and the same Pydantic regex idiom for inbound `entertainment_config_id` validation.

---
*Phase: 17-wled-backend-and-streaming*
*Plan: 07*
*Completed: 2026-04-26*

## Self-Check: PASSED

- Backend/routers/wled.py — FOUND
- Backend/tests/test_wled_router.py — FOUND
- Backend/main.py (modified, registers wled_router) — FOUND
- .planning/phases/17-wled-backend-and-streaming/17-07-SUMMARY.md — FOUND (this file)
- Commit b337269 — FOUND in `git log --oneline`
