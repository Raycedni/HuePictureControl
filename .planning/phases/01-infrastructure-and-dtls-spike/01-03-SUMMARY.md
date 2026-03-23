---
phase: 01-infrastructure-and-dtls-spike
plan: 03
subsystem: ui
tags: [react, vite, typescript, vitest, nginx, docker, testing-library]

# Dependency graph
requires:
  - phase: 01-infrastructure-and-dtls-spike/01-01
    provides: docker-compose.yaml backend service and project scaffold

provides:
  - React + TypeScript frontend with Vite build tooling
  - PairingFlow component with state machine for bridge pairing
  - nginx reverse proxy for /api/ and /ws to host.docker.internal:8000
  - Multi-stage Frontend Dockerfile (node:20-alpine build + nginx:alpine serve)
  - TypeScript API client for all Hue backend endpoints
  - Vitest test suite for frontend components

affects:
  - Phase 2: all frontend feature work builds on this Vite + nginx scaffold
  - Phase 3: entertainment config selection UI wires into PairingFlow configs list

# Tech tracking
tech-stack:
  added:
    - Vite 8 (React + TypeScript template)
    - React 19 with react-dom
    - Vitest 4 with jsdom environment
    - "@testing-library/react, @testing-library/jest-dom, @testing-library/user-event"
    - nginx:alpine (production serving)
    - node:20-alpine (build stage)
  patterns:
    - TDD with Vitest: write failing tests first, then implement to pass
    - State machine pattern for multi-step UI flows (checking/unpaired/pairing/paired/error)
    - fetch() API client with typed interfaces in src/api/
    - Multi-stage Docker build: node build -> nginx serve
    - nginx proxy_pass with host.docker.internal for host-network backend

key-files:
  created:
    - Frontend/src/components/PairingFlow.tsx
    - Frontend/src/components/PairingFlow.test.tsx
    - Frontend/src/api/hue.ts
    - Frontend/nginx.conf
    - Frontend/Dockerfile
    - Frontend/.dockerignore
    - Frontend/vitest.config.ts
  modified:
    - Frontend/src/App.tsx
    - Frontend/src/App.css
    - Frontend/package.json
    - Frontend/tsconfig.app.json
    - docker-compose.yaml

key-decisions:
  - "Test files excluded from tsconfig.app.json to prevent global (Node.js) type conflicts in browser build"
  - "PairingFlow uses React state machine with 5 steps: checking, unpaired, pairing, paired, error"
  - "nginx proxies /api/ and /ws to host.docker.internal:8000 (backend on host network)"
  - "docker-compose frontend service uses build context ./Frontend (replaces image: nginx:alpine placeholder)"

patterns-established:
  - "API client pattern: all fetch calls in src/api/ with typed interfaces and status-based error objects"
  - "Component test pattern: mock global.fetch per test case, use waitFor for async state transitions"

requirements-completed: [UI-02]

# Metrics
duration: 5min
completed: 2026-03-23
---

# Phase 1 Plan 03: React Frontend Skeleton Summary

**Vite + React 19 frontend with PairingFlow state machine, nginx /api/ proxy to host network backend, and multi-stage Docker build**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-23T21:52:05Z
- **Completed:** 2026-03-23T21:57:10Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments

- PairingFlow component guides user through bridge pairing with step-by-step instructions, IP input, 403 link-button error handling, and paired status with entertainment config list
- nginx reverse proxy forwards /api/ and WebSocket /ws to host.docker.internal:8000, bridging the frontend container to the host-network backend
- Multi-stage Dockerfile (node:20-alpine build + nginx:alpine serve) added; docker-compose.yaml updated to build Frontend/ instead of using plain nginx image
- All 4 Vitest tests pass covering: link button instructions display, IP input rendering, paired status with bridge name, and 403 error flow

## Task Commits

Each task was committed atomically:

1. **Task 1: Vite + React + TypeScript scaffold with Vitest** - `eb5e546` (feat)
2. **Task 2 TDD RED: PairingFlow failing tests + API client** - `216477f` (test)
3. **Task 2 TDD GREEN: PairingFlow implementation + nginx + Dockerfile** - `fa2a985` (feat)

**Plan metadata:** _(docs commit follows)_

_Note: TDD task has two commits — failing tests (RED) then implementation (GREEN)._

## Files Created/Modified

- `Frontend/src/components/PairingFlow.tsx` - State machine component: checking/unpaired/pairing/paired/error steps
- `Frontend/src/components/PairingFlow.test.tsx` - 4 Vitest tests with fetch mocking
- `Frontend/src/api/hue.ts` - Typed fetch wrappers for pairBridge, getBridgeStatus, getEntertainmentConfigs, getLights
- `Frontend/src/App.tsx` - Minimal shell: app title + PairingFlow render
- `Frontend/src/App.css` - Max-width 1200px centered layout with system font stack
- `Frontend/nginx.conf` - SPA fallback + /api/ proxy + /ws WebSocket proxy to host.docker.internal:8000
- `Frontend/Dockerfile` - Multi-stage: node:20-alpine build, nginx:alpine serve
- `Frontend/.dockerignore` - Excludes node_modules, dist, .env
- `Frontend/package.json` - Added test script: vitest run
- `Frontend/vitest.config.ts` - jsdom environment, globals: true, @vitejs/plugin-react
- `Frontend/tsconfig.app.json` - Added exclude for test files to prevent global type conflict
- `docker-compose.yaml` - Replaced placeholder nginx image with build context ./Frontend

## Decisions Made

- Excluded test files from tsconfig.app.json: `global.fetch = mockFetch` in test files caused TypeScript error ("Cannot find name 'global'") because browser tsconfig doesn't include Node types. Excluding test files from the app tsconfig resolves this while Vitest still compiles tests through its own config.
- State machine pattern chosen over boolean flags: makes step transitions explicit and prevents impossible states (e.g., showing IP input while pairing is in progress).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Excluded test files from tsconfig.app.json**
- **Found during:** Task 2 (build verification after implementing PairingFlow)
- **Issue:** `global.fetch = mockFetch` in PairingFlow.test.tsx caused TypeScript error `Cannot find name 'global'` because tsconfig.app.json targets browser environment with no Node.js types
- **Fix:** Added `"exclude": ["src/**/*.test.tsx", "src/**/*.test.ts"]` to tsconfig.app.json; Vitest compiles tests through vitest.config.ts independently
- **Files modified:** Frontend/tsconfig.app.json
- **Verification:** `npm run build` succeeds, `npm run test` still passes all 4 tests
- **Committed in:** fa2a985

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Auto-fix necessary for build to succeed. No scope creep.

## Issues Encountered

None - all implementation proceeded as planned after the TypeScript tsconfig fix.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Frontend container ready for Phase 2 feature work (entertainment config selection, light control UI)
- PairingFlow displays entertainment configs list when paired (BRDG-05 display wired, selection comes in Phase 3)
- nginx WebSocket proxy configured for future /ws streaming endpoint
- DTLS spike (01-04) is the remaining Phase 1 gate before Phase 2/3 can begin

---
*Phase: 01-infrastructure-and-dtls-spike*
*Completed: 2026-03-23*

## Self-Check: PASSED

All files found and all commits verified:
- eb5e546: feat(01-03) scaffold
- 216477f: test(01-03) RED phase
- fa2a985: feat(01-03) GREEN phase + implementation
