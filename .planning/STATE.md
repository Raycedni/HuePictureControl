---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: — Full ambient lighting with gradient device support
status: planning
stopped_at: Completed 04-03-PLAN.md
last_updated: "2026-03-24T21:38:13.793Z"
last_activity: 2026-03-23 — Roadmap created
progress:
  total_phases: 7
  completed_phases: 4
  total_plans: 15
  completed_plans: 14
  percent: 25
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-23)

**Core value:** Accurate, low-latency color synchronization from an HDMI source to Hue lights — especially gradient-capable devices that existing solutions don't properly support.
**Current focus:** Phase 1 — Infrastructure and DTLS Spike

## Current Position

Phase: 1 of 6 (Infrastructure and DTLS Spike)
Plan: 0 of TBD in current phase
Status: Ready to plan
Last activity: 2026-03-23 — Roadmap created

Progress: [███░░░░░░░] 25%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: none yet
- Trend: -

*Updated after each plan completion*
| Phase 01-infrastructure-and-dtls-spike P01 | 3 | 2 tasks | 14 files |
| Phase 01-infrastructure-and-dtls-spike P02 | 8 | 2 tasks | 6 files |
| Phase 01-infrastructure-and-dtls-spike P03 | 5 | 2 tasks | 13 files |
| Phase 02-capture-pipeline-color-extraction P01 | 3m 24s | 2 tasks | 5 files |
| Phase 02-capture-pipeline-color-extraction P02 | 15min | 1 tasks | 4 files |
| Phase 02-capture-pipeline-color-extraction P02 | 20min | 2 tasks | 4 files |
| Phase 03-entertainment-api-streaming-integration P01 | 3min | 2 tasks | 4 files |
| Phase 03-entertainment-api-streaming-integration P02 | 6min | 1 tasks | 2 files |
| Phase 03-entertainment-api-streaming-integration P03 | 10min | 1 tasks | 6 files |
| Phase 03-entertainment-api-streaming-integration P03 | 15min | 2 tasks | 6 files |
| Phase 03.1-auto-mapping-from-entertainment-config P01 | 3min | 2 tasks | 6 files |
| Phase 03.1-auto-mapping-from-entertainment-config P02 | 10min | 1 tasks | 3 files |
| Phase 03.1-auto-mapping-from-entertainment-config P02 | 15min | 2 tasks | 3 files |
| Phase 04-frontend-canvas-editor P01 | 3min | 2 tasks | 5 files |
| Phase 04-frontend-canvas-editor P02 | 7min | 2 tasks | 22 files |
| Phase 04-frontend-canvas-editor P03 | 10min | 2 tasks | 5 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Pre-planning]: DTLS transport must use `hue-entertainment-pykit` — Python `ssl` has no DTLS support
- [Pre-planning]: Python 3.12 pinned — `hue-entertainment-pykit` mbedTLS bindings break on 3.13+
- [Pre-planning]: Backend uses host networking — required for DTLS/UDP and mDNS to Hue Bridge
- [Phase 01-infrastructure-and-dtls-spike]: asyncio_default_fixture_loop_scope=function added to pytest.ini to suppress pytest-asyncio 0.24 deprecation warning
- [Phase 01-infrastructure-and-dtls-spike]: Docker Compose validation done via Python yaml parser (Docker Desktop WSL integration not active in dev environment)
- [Phase 01-infrastructure-and-dtls-spike]: requests for sync pair/metadata calls; httpx.AsyncClient for async discovery (list_entertainment_configs, list_lights)
- [Phase 01-infrastructure-and-dtls-spike]: Single-row bridge_config (id=1 fixed) supports exactly one paired bridge at a time
- [Phase 01-infrastructure-and-dtls-spike]: Test files excluded from tsconfig.app.json to prevent Node global type conflict in browser build
- [Phase 01-infrastructure-and-dtls-spike]: PairingFlow uses 5-step state machine: checking/unpaired/pairing/paired/error for explicit step transitions
- [Phase 02-capture-pipeline-color-extraction]: Inlined Gamut C color math algorithm (20 lines) rather than rgbxy dependency (unmaintained since 2020)
- [Phase 02-capture-pipeline-color-extraction]: asyncio.Lock added to LatestFrameCapture.get_frame() to prevent concurrent read races
- [Phase 02-capture-pipeline-color-extraction]: Lifespan captures RuntimeError from capture.open() and logs warning (non-fatal) — backend runnable without hardware; snapshot returns 503 instead
- [Phase 02-capture-pipeline-color-extraction]: Debug color endpoint uses hard-coded center polygon to satisfy Phase 2 CIE xy success criterion
- [Phase 02-capture-pipeline-color-extraction]: Lifespan catches RuntimeError from capture.open() and logs a warning instead of crashing — backend runnable without hardware; snapshot returns 503
- [Phase 02-capture-pipeline-color-extraction]: Debug color endpoint uses hard-coded center polygon to satisfy Phase 2 CIE xy success criterion
- [Phase 03-entertainment-api-streaming-integration]: update_metrics silently updates internal state (called at 50 Hz from frame loop) — heartbeat delivers to clients at 1 Hz to avoid flooding
- [Phase 03-entertainment-api-streaming-integration]: push_state bypasses 1 Hz rate limit for immediate state transition delivery (streaming/error/idle)
- [Phase 03-entertainment-api-streaming-integration]: deactivate_entertainment_config is best-effort: logs warning on failure, never raises
- [Phase 03-entertainment-api-streaming-integration]: module-scoped service_imports fixture avoids cv2 reimport AttributeError in test suite
- [Phase 03-entertainment-api-streaming-integration]: Start/stop endpoints stay on capture router (/api/capture prefix) rather than new router for cohesive streaming control
- [Phase 03-entertainment-api-streaming-integration]: WebSocket receive loop uses receive_text() so browser ping/pong frames keep connections alive
- [Phase 03-entertainment-api-streaming-integration]: Hardware verification confirmed: lights sync from capture card feed, latency under 100ms (STRM-05 satisfied)
- [Phase 03.1-auto-mapping-from-entertainment-config]: channel_pos_to_screen maps Hue x->screen_x, z->screen_y via (val+1.0)/2.0; region IDs use deterministic auto:{config_id}:{channel_id} pattern for idempotency
- [Phase 03.1-auto-mapping-from-entertainment-config]: Overlay positioning uses clientWidth/clientHeight so divs match the rendered (scaled) image size
- [Phase 03.1-auto-mapping-from-entertainment-config]: Overlay positioning uses clientWidth/clientHeight so overlays match the rendered (scaled) image size
- [Phase 03.1-auto-mapping-from-entertainment-config]: Hardware verification confirmed: auto-map generates correct regions, overlays display on camera preview, streaming works end-to-end (REGN-04, REGN-05 satisfied)
- [Phase 04-frontend-canvas-editor]: ALTER TABLE migration wraps in try/except for portability across aiosqlite versions
- [Phase 04-frontend-canvas-editor]: PUT /api/regions/{id} uses dynamic SET clause for partial updates (only non-None fields applied)
- [Phase 04-frontend-canvas-editor]: DELETE /api/regions/{id} also cleans up light_assignments rows to prevent orphaned data
- [Phase 04-frontend-canvas-editor]: /ws/preview uses JPEG quality 70 (vs 85 in capture snapshot) for streaming throughput
- [Phase 04-frontend-canvas-editor]: Tailwind v4 uses @tailwindcss/vite plugin (not postcss); shadcn init auto-detected v4 and configured accordingly
- [Phase 04-frontend-canvas-editor]: usePreviewWS stores previous ObjectURL in ref and revokes on each new frame to prevent memory leaks
- [Phase 04-frontend-canvas-editor]: useStatusWS uses reconnect-on-close with 2s delay; destroyed flag prevents reconnect after unmount
- [Phase 04-frontend-canvas-editor]: handleEditorDelete exported as standalone function from EditorCanvas so toolbar and keyboard shortcut share logic without circular refs
- [Phase 04-frontend-canvas-editor]: Canvas aspect ratio 4:3 (height = width * 3/4) matches 640x480 capture resolution for accurate region mapping

### Pending Todos

None yet.

### Roadmap Evolution

- Phase 3.1 inserted after Phase 3: Auto-Mapping from Entertainment Config — auto-generate screen regions from channel positions before building manual canvas editor (user decision 2026-03-24)

### Blockers/Concerns

- [Phase 1]: DTLS spike must be verified with physical Hue Bridge before Phase 2/3 begin — this is the single project gate
- [Phase 5]: Festavia entertainment channel count (~5-7) is underdocumented; requires hardware validation before segment UI is finalized

## Session Continuity

Last session: 2026-03-24T21:38:13.773Z
Stopped at: Completed 04-03-PLAN.md
Resume file: None
