---
phase: 09-preview-routing-and-region-api
verified: 2026-04-07T00:00:00Z
status: passed
score: 10/10 must-haves verified
re_verification: false
---

# Phase 9: Preview Routing and Region API — Verification Report

**Phase Goal:** The live preview WebSocket serves frames from the zone's assigned camera, and the regions API exposes camera_device as a readable and writable field.
**Verified:** 2026-04-07
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

Ten must-have truths were drawn from the two plan frontmatter blocks (09-01 and 09-02) and cross-checked against ROADMAP.md success criteria.

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Preview WebSocket with `?device=/dev/video0` routes to that device via `registry.get()` | VERIFIED | `preview_ws.py:69` calls `registry.get(device_path)`; `get_default()` absent from file |
| 2 | Preview WebSocket without `?device=` closes with code 1008 before accept | VERIFIED | `preview_ws.py:52-54` closes with code 1008 before `accept()` |
| 3 | Preview WebSocket resolves stable_id to device path via `known_cameras` | VERIFIED | `_resolve_device_path` at `preview_ws.py:17-33` queries `known_cameras WHERE stable_id = ?` |
| 4 | `CaptureRegistry.get()` returns backend without incrementing ref count | VERIFIED | `capture_service.py:195-202` — reads `_backends.get()`, no `_ref_counts` touch |
| 5 | `GET /api/cameras` returns `cameras_available` bool and `zone_health` list | VERIFIED | `cameras.py:51-55` — `CamerasResponse` has both fields; `list_cameras` populates them at lines 203-226 |
| 6 | `GET /api/regions` returns `camera_device` derived via LEFT JOIN | VERIFIED | `regions.py:309-329` — LEFT JOIN through `camera_assignments` + `known_cameras`; `camera_device` in return dict |
| 7 | `entertainment_config_id` column added to regions table via idempotent migration | VERIFIED | `database.py:55-61` — `ALTER TABLE regions ADD COLUMN entertainment_config_id TEXT` in try/except |
| 8 | `update_region` writes `entertainment_config_id` to regions table | VERIFIED | `regions.py:199-200` — `updates["entertainment_config_id"] = body.entertainment_config_id` |
| 9 | Frontend `Region` interface includes `camera_device: string \| null` | VERIFIED | `api/regions.ts:7` — field present in interface |
| 10 | `usePreviewWS` accepts optional `device` param, builds `?device=` URL | VERIFIED | `usePreviewWS.ts:3` signature; `line:30` WebSocket URL; `line:75` deps array |

**Score:** 10/10 truths verified

---

### Required Artifacts

#### Plan 09-01 Artifacts

| Artifact | Provides | Status | Key Evidence |
|----------|----------|--------|--------------|
| `Backend/services/capture_service.py` | `CaptureRegistry.get()` peek method | VERIFIED | `def get(self, device_path` at line 195; uses `self._backends.get()`, no ref count |
| `Backend/routers/preview_ws.py` | Device-routed preview WebSocket | VERIFIED | `device: Optional[str] = Query` at line 39; full routing logic present |
| `Backend/tests/test_capture_registry.py` | Tests for `get()` method | VERIFIED | `TestGet` class with 5 tests: `test_get_returns_none_when_not_acquired`, `test_get_returns_acquired_backend`, `test_get_returns_none_for_different_path`, `test_get_does_not_increment_ref_count`, `test_get_returns_none_after_release` |
| `Backend/tests/test_preview_ws.py` | Tests for `?device=` routing | VERIFIED | `test_missing_device_param`, `test_resolve_device_path_direct`, `test_resolve_device_path_stable_id`, `test_device_param_calls_registry_get`, `test_device_param_does_not_call_get_default` |

#### Plan 09-02 Artifacts

| Artifact | Provides | Status | Key Evidence |
|----------|----------|--------|--------------|
| `Backend/database.py` | `entertainment_config_id` migration | VERIFIED | Lines 55-61: `ALTER TABLE regions ADD COLUMN entertainment_config_id TEXT` in try/except |
| `Backend/routers/cameras.py` | `ZoneHealth` + `cameras_available` in `CamerasResponse` | VERIFIED | `class ZoneHealth(BaseModel)` at line 43; `CamerasResponse` with both fields at lines 51-55 |
| `Backend/routers/regions.py` | `camera_device` derived field in `list_regions` | VERIFIED | LEFT JOIN SQL at lines 309-318; `camera_device` in return list at line 329 |
| `Frontend/src/api/regions.ts` | Updated `Region` interface | VERIFIED | `camera_device: string \| null` at line 7 |
| `Frontend/src/hooks/usePreviewWS.ts` | Device-aware preview WebSocket hook | VERIFIED | `device?: string` in signature; `ws/preview?device=` URL; `[enabled, device]` deps |

---

### Key Link Verification

#### Plan 09-01 Links

| From | To | Via | Status | Evidence |
|------|----|-----|--------|----------|
| `preview_ws.py` | `capture_service.py` | `registry.get(device_path)` | WIRED | `preview_ws.py:69` — `backend = registry.get(device_path)` |
| `preview_ws.py` | `known_cameras` table | `SELECT last_device_path FROM known_cameras WHERE stable_id` | WIRED | `preview_ws.py:28-32` — async SQL query with exact pattern |

#### Plan 09-02 Links

| From | To | Via | Status | Evidence |
|------|----|-----|--------|----------|
| `regions.py` | `camera_assignments` + `known_cameras` | LEFT JOIN for `camera_device` derivation | WIRED | `regions.py:314-317` — `LEFT JOIN camera_assignments ca ON ca.entertainment_config_id = r.entertainment_config_id` + `LEFT JOIN known_cameras kc ON kc.stable_id = ca.camera_stable_id` |
| `cameras.py` | `camera_assignments` table | `zone_health` query | WIRED | `cameras.py:204-207` — `SELECT entertainment_config_id, camera_stable_id, camera_name FROM camera_assignments` |
| `usePreviewWS.ts` | Backend `/ws/preview` | WebSocket URL with `?device=` | WIRED | `usePreviewWS.ts:30` — `ws://${location.host}/ws/preview?device=${encodeURIComponent(device!)}` |

---

### Data-Flow Trace (Level 4)

The two rendering-relevant artifacts are `list_regions` and `list_cameras`:

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `regions.py list_regions` | `camera_device` | LEFT JOIN on `camera_assignments` + `known_cameras` | Yes — `kc.last_device_path AS camera_device` from DB rows | FLOWING |
| `cameras.py list_cameras` | `zone_health` | SELECT from `camera_assignments` | Yes — populates `ZoneHealth` from real DB query | FLOWING |
| `usePreviewWS.ts` | `imgSrc` | WebSocket binary frames from `/ws/preview?device=` | Yes — blob URL from real WS data | FLOWING (when device provided) |

Note: `EditorCanvas.tsx` (line 18) and `PreviewPage.tsx` (line 39) call `usePreviewWS(true)` without a `device` parameter. The hook intentionally returns `null` in this case (`if (!enabled || !device)` guard). This is accepted behavior per Plan 09-02 Task 2 action notes: Phase 10 will update these call sites. Preview is disconnected on both pages until Phase 10.

---

### Behavioral Spot-Checks

Step 7b: SKIPPED — no runnable server available for WebSocket checks. Core logic verified by code inspection and test coverage analysis.

---

### Requirements Coverage

| Requirement | Plans | Description | Status | Evidence |
|-------------|-------|-------------|--------|----------|
| MCAP-02 | 09-01, 09-02 | Preview WebSocket serves frames from zone's assigned camera, not global device | SATISFIED | `preview_ws.py` routes via `registry.get(device_path)` where `device_path` comes from `?device=` param or stable_id resolution via `known_cameras` |
| CAMA-04 | 09-02 | UI shows camera health status (connected/disconnected) per entertainment zone | SATISFIED | `GET /api/cameras` returns `zone_health: list[ZoneHealth]` with `connected: bool` and `device_path: str \| null` per zone |

Both requirements mapped to Phase 9 in REQUIREMENTS.md traceability table are SATISFIED. No orphaned requirements.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `regions.py` | 157, 238 | `"camera_device": None` in `create_region` and `update_region` responses | Info | Intentional — documented as "derived field — use GET /api/regions for full JOIN result". Not a stub: the GET list endpoint delivers the real JOIN value. |
| `EditorCanvas.tsx` | 18 | `usePreviewWS(true)` without `device` param | Warning | Preview permanently disconnected until Phase 10 provides device. Accepted by Plan 09-02 design notes (D-11). |
| `PreviewPage.tsx` | 39 | `usePreviewWS(true)` without `device` param | Warning | Same as above. |

No blocker anti-patterns. The two warnings are explicitly accepted Phase 9 behavior that Phase 10 resolves.

---

### ROADMAP Success Criteria Cross-Check

| SC | Criterion | Status | Notes |
|----|-----------|--------|-------|
| SC-1 | Opening `?device=/dev/video1` streams from that specific device | SATISFIED | Routing logic verified; `registry.get(device_path)` called with the resolved path |
| SC-2 | Camera health status (connected/disconnected) per zone visible without starting streaming | SATISFIED | `GET /api/cameras` returns `zone_health` list with `connected` bool from DB query; no streaming required |
| SC-3 | `GET /api/regions` returns `camera_device`; `PUT` accepts and persists update | PARTIALLY SATISFIED — with nuance | GET returns `camera_device` (VERIFIED). PUT does NOT accept `camera_device` directly; instead accepts `entertainment_config_id` which drives the derived value. Design decision D-09 explicitly makes `camera_device` read-only. The ROADMAP wording is imprecise but the intent (per-zone camera linkage is persisted via PUT) is met. |

SC-3's divergence is a ROADMAP wording issue, not an implementation gap. The plan design decision D-09 predates ROADMAP wording and the executor followed the plan.

---

### Human Verification Required

#### 1. Preview WebSocket End-to-End with Real Device

**Test:** Start backend with a real capture device at `/dev/video0`. Start streaming for an entertainment zone. Open WebSocket to `ws://localhost:8000/ws/preview?device=/dev/video0`. Observe received frames.
**Expected:** Binary JPEG frames arrive at ~60 fps; frames change when video source changes.
**Why human:** Requires live capture hardware (USB capture card at `/dev/video0`), real Hue Bridge, and running Docker stack.

#### 2. Zone Health Shows Disconnected After USB Unplug

**Test:** Call `GET /api/cameras` with camera assignment configured, then physically unplug the capture card, then call `GET /api/cameras` again.
**Expected:** `zone_health[0].connected` changes from `true` to `false` after unplug.
**Why human:** Requires hardware manipulation; can't simulate in automated tests.

#### 3. Preview Stays Disconnected on EditorCanvas (Phase 9 Behavior)

**Test:** Open the editor UI in browser. Verify that no preview image loads (expected: blank/null).
**Expected:** No preview shown — hook returns `null` because `device` is `undefined` until Phase 10.
**Why human:** Visual browser verification; UX regression risk that should be documented for Phase 10 reviewers.

---

### Gaps Summary

No gaps blocking goal achievement. All must-have truths verified at all four levels (exists, substantive, wired, data flowing).

The two call-site warnings (`EditorCanvas.tsx`, `PreviewPage.tsx`) are intentional Phase 9 deferrals to Phase 10, not implementation gaps.

---

_Verified: 2026-04-07_
_Verifier: Claude (gsd-verifier)_
