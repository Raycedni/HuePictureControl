---
phase: 17
slug: wled-backend-and-streaming
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-20
updated: 2026-04-20
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Invariants are mapped from `17-RESEARCH.md` §Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (backend)** | pytest ≥ 7 (existing — 167+ tests in Backend/tests/) |
| **Framework (frontend)** | vitest (existing — 30+ tests in Frontend/src/) |
| **Config file (backend)** | Backend/pytest.ini (existing) |
| **Config file (frontend)** | Frontend/vite.config.ts (existing) |
| **Quick run (backend)** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest -x -q tests/ -k "wled or coordinator or broadcaster"` |
| **Quick run (frontend)** | `cd Frontend && npx vitest run src/components/Settings src/api/wled` |
| **Full suite (backend)** | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest` |
| **Full suite (frontend)** | `cd Frontend && npx vitest run` |
| **Estimated runtime** | ~20s (backend quick) / ~60s (backend full) / ~5s (frontend quick) / ~15s (frontend full) |

---

## Sampling Rate

- **After every task commit:** Run the relevant quick command for that surface (backend or frontend).
- **After every plan wave:** Run the full backend+frontend suites in parallel.
- **Before `/gsd-verify-work`:** Both full suites must be green.
- **Max feedback latency:** 60 seconds (full backend suite).

---

## Per-Task Verification Map

> One row per `<task>` across all nine PLAN.md files (20 tasks total). `Automated Command` is lifted verbatim from each task's `<verify><automated>` block; checkpoint tasks with no automated verify are marked `—`. `File Exists` tracks whether the target test/fixture file already exists (❌ W0 = Wave 0 must create it).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 17-01-01 | 17-01 | 0 | WLED-01, WSTR-01..04 | T-17-DEP | zeroconf supply-chain pin (>=0.148,<2, 1.0.0 yanked) | integration | `source /tmp/hpc-venv/bin/activate && cd Backend && python -c "import zeroconf; from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf; print('ok', zeroconf.__version__)" && python -m pytest -q` | ❌ W0 | ⬜ pending |
| 17-01-02 | 17-01 | 0 | WSTR-01..04 (observation fixture) | — | Fixture binds loopback only (SOCK_DGRAM, 127.0.0.1, SO_REUSEADDR) | unit | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_loopback_fixture.py -x -q` | ❌ W0 | ⬜ pending |
| 17-01-03 | 17-01 | 0 | WSTR-03 (coordinator fixture) | — | Deterministic ndarray; no real capture device touched | unit | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_mock_capture_fixture.py -x -q` | ❌ W0 | ⬜ pending |
| 17-02-01 | 17-02 | 1 | WLED-01, WLED-02, WLED-05 | T-17-SCHEMA, T-17-CASCADE | UNIQUE(ip) + composite PK enforce input hygiene; no PRAGMA FK (cascade in code per A5) | integration | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_database.py -x -q` | ✅ extend | ⬜ pending |
| 17-02-02 | 17-02 | 1 | WSTR-03 | — | Sub-sample clamps to longest-axis length; deterministic ordering | unit | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_color_math.py tests/test_database.py -x -q` | ✅ extend | ⬜ pending |
| 17-03-01 | 17-03 | 1 | WSTR-01, WSTR-02, WSTR-04 | T-17-UDP | Byte-exact layouts; timeout byte 0x02 in every packet (D-14); 489 cap prevents MTU overflow | unit | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_packet.py -x -q` | ❌ W0 | ⬜ pending |
| 17-03-02 | 17-03 | 1 | WLED-01, WLED-03 | T-17-SSRF, T-17-RESP | httpx timeout=5s default; `data.get(...)` defensive parse; HTTP (no TLS) documented | unit | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_client.py -x -q` | ❌ W0 | ⬜ pending |
| 17-03-03 | 17-03 | 1 | WLED-01 (scan), WLED-03 | — | AsyncServiceBrowser canceled + AsyncZeroconf closed in finally; bounded timeout | unit | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_packet.py tests/test_wled_client.py tests/test_wled_discovery.py -x -q` | ❌ W0 | ⬜ pending |
| 17-04-01 | 17-04 | 2 | WLED-05, WSTR-01..04 | T-17-RACE, T-17-SOCKET-LEAK | threading.Lock guards _devices; start() raises if already started; non-blocking sockets | unit | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_streamer.py -x -q -k "start or stop or enabled or snapshot or lock_discipline"` | ❌ W0 | ⬜ pending |
| 17-04-02 | 17-04 | 2 | WSTR-01, WSTR-02, WSTR-03, WSTR-04, WLED-05 | T-17-UDP-FLOOD, T-17-BLACKOUT-MISS | 30-frame cooldown caps bad-device traffic; blackout before close (D-13); asyncio.gather for per-device isolation (D-06) | integration | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_streamer.py tests/test_wled_packet.py -x -q` | ❌ W0 | ⬜ pending |
| 17-05-01 | 17-05 | 2 | WSTR-03, WSTR-04 | T-17-REFACTOR-BEHAVIOR | Behavior-preserving extract; full suite must stay green | integration | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_streaming_coordinator.py -x -q` | ❌ W0 | ⬜ pending |
| 17-05-02 | 17-05 | 2 | WSTR-03, WSTR-04 | T-17-REFACTOR-BEHAVIOR | Compatibility shim keeps main.py wiring alive; N=1 gradient.mean matches extract_region_color | integration | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest -x -q` | ✅ extend | ⬜ pending |
| 17-06-01 | 17-06 | 3 | WSTR-03, WSTR-04, WLED-05 | — | `_UNSET` sentinel preserves existing payload keys; additive field only | unit | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_status_broadcaster.py -x -q` | ✅ extend | ⬜ pending |
| 17-06-02 | 17-06 | 3 | WSTR-03, WSTR-04, WLED-05 | T-17-DB-JOIN | wled_light_assignments filtered by entertainment_config_id; set_wled_device_enabled under WledStreamer lock; `monkeypatch.setattr` for test isolation; WledStreamer accepts `udp_port` kwarg for loopback redirection | integration | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_streaming_coordinator.py tests/test_status_broadcaster.py -x -q` | ✅ extend | ⬜ pending |
| 17-06-03 | 17-06 | 3 | WSTR-03, WSTR-04, WLED-05 | T-17-WIRING | Atomic single-commit rename sweep (5 files); compatibility shim removed; full backend suite gates merge | integration | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest -x -q` | ✅ extend | ⬜ pending |
| 17-07-01 | 17-07 | 4 | WLED-01, WLED-02, WLED-03, WLED-05 | T-17-INPUT, T-17-SSRF, T-17-UDP, T-17-DUPE, T-17-DELETE-ORPHAN, T-17-ENABLE-RACE | IP regex at edge; 409 duplicate pre-INSERT; explicit cascade (assignments→channels→device); PUT /enabled goes through coordinator lock | integration | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_wled_router.py -x -q` | ❌ W0 | ⬜ pending |
| 17-08-01 | 17-08 | 4 | WLED-01..05 | — | WledApiError exposes HTTP status for UI branching; encodeURIComponent on id path params | unit | `cd Frontend && npx vitest run src/api/wled.test.ts src/store src/hooks` | ❌ W0 | ⬜ pending |
| 17-08-02 | 17-08 | 4 | WLED-01, WLED-02, WLED-03, WLED-04, WLED-05 | T-17-FE-INPUT, T-17-FE-XSS | React escapes all text children; no dangerouslySetInnerHTML; server-side validation is the source of truth | unit | `cd Frontend && npx vitest run` | ❌ W0 | ⬜ pending |
| 17-09-01 | 17-09 | 5 | WLED-01..05, WSTR-01..04 | T-17-E2E-FLAKE | Phase gate — fps ≥ 40 Hz floor, ≥ 50 packets in 2s, blackout on stop, cascade delete via router | integration | `source /tmp/hpc-venv/bin/activate && cd Backend && python -m pytest tests/test_phase17_e2e.py -x -v && cd ../Frontend && npx vitest run` | ❌ W0 | ⬜ pending |
| 17-09-02 | 17-09 | 5 | WLED-01, WLED-03, WLED-05, WSTR-01, WSTR-03 | T-17-MANUAL-GAP | Hardware-dependent invariants (strip update, zeroconf LAN find, timeout release) — `approved-no-hardware` resume signal allowed | checkpoint:human-verify | — | n/a (manual) | ⬜ pending |

---

## Observable Invariants (from RESEARCH.md §Validation Architecture)

Every invariant below MUST be asserted by at least one test, OR captured as a manual verification with a recorded command.

| # | Invariant | Requirement | Assertion Surface |
|---|-----------|-------------|-------------------|
| 1 | `POST /api/wled/devices` returns 200 with fetched `name` + `led_count` after httpx `/json/info` | WLED-01 | Integration test with mocked httpx |
| 2 | Registered WLED device persists across app restart (row stays in `wled_devices`) | WLED-01 | Integration test: insert → restart lifespan → GET /api/wled/devices |
| 3 | `PUT /api/wled/devices/{id}/enabled` toggles row without deleting it | WLED-02 | Unit test on router |
| 4 | When `enabled=false`, coordinator frame loop sends **zero** UDP packets to that device | WLED-02 | Integration test with UDP loopback listener — assert `recv_count == 0` |
| 5 | With `enabled=true` + channel assigned, loopback listener receives packets at ≥50 Hz for ≥2s window | WLED-03 / WSTR-01 | Integration test: start coordinator, mock capture frame, count packets |
| 6 | Strip with `led_count=490` → DRGB packets (protocol byte `0x02`, single packet) | WLED-04 / WSTR-02 | Unit test on packet builder |
| 7 | Strip with `led_count=491` → DNRGB packets (protocol byte `0x04`, chunked) | WLED-04 / WSTR-02 | Unit test on packet builder |
| 8 | Strip with `led_count=980` → exactly 3 DNRGB packets per frame (489+489+2 LEDs) | WLED-04 / WSTR-02 | Unit test: packet count |
| 9 | DRGB payload ≤ 1472 bytes (2 header + 3·490 = 1472) | WSTR-02 | Unit test: len(payload) assertion |
| 10 | DNRGB payload ≤ 1471 bytes (4 header + 3·489 = 1471) | WSTR-02 | Unit test: len(payload) assertion |
| 11 | Header byte 2 (DRGB) or 2 (DNRGB) = timeout seconds = `0x02` | WLED-05 / WSTR-03 | Unit test: inspect header bytes |
| 12 | On `/api/capture/stop`, coordinator sends 1 blackout packet (all zero RGB) per enabled device before closing sockets | WLED-05 / WSTR-03 | Integration test: UDP listener records final packet, verifies payload is zeroed |
| 13 | After blackout + 2s silence, no packets observed on loopback listener | WLED-05 / WSTR-03 | Integration test |
| 14 | Concurrent Hue + WLED streaming: Hue `packets_sent` increases AND WLED loopback `recv_count` increases in the same 1s window | WSTR-04 | Integration test with both sinks active |
| 15 | Concurrent mode sustains frame rate ≥ 50 Hz (measured from StatusBroadcaster `fps` metric) | WSTR-04 | Integration test reads WS metrics for ≥2s |
| 16 | After N consecutive send failures per device, `StatusBroadcaster._metrics.wled_devices[id].in_cooldown == True` | (internal resilience) | Integration test: inject `OSError` into stub socket, observe state |
| 17 | After 30s cooldown, device auto-probes and `in_cooldown` returns to False | (internal resilience) | Integration test with `time.sleep` mocked |

---

## Wave 0 Requirements

- [ ] `Backend/tests/fixtures/wled_loopback.py` — UDP loopback listener fixture (records packets per device)
- [ ] `Backend/tests/fixtures/mock_capture.py` — reusable MockCapture stub for coordinator tests (returns a fixed ndarray frame)
- [ ] `Backend/tests/test_wled_packet.py` — unit tests for DRGB/DNRGB builders (invariants 6–11)
- [ ] `Backend/tests/test_wled_streamer.py` — unit tests with mocked socket (invariants 4, 11, 16, 17)
- [ ] `Backend/tests/test_streaming_coordinator.py` — integration tests for concurrent Hue+WLED (invariants 5, 12, 13, 14, 15)
- [ ] `Backend/tests/test_wled_router.py` — REST API tests (invariants 1–3)
- [ ] `Frontend/src/api/wled.test.ts` — client API tests
- [ ] `Frontend/src/components/Settings/WledDevicesPanel.test.tsx` — component tests for add/remove/enable toggle

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real WLED strip visibly updates at 50-60 Hz from captured frame | WLED-03 / WSTR-01 | Hardware-dependent — requires physical WLED ESP32 on LAN | 1) Register device via Settings panel, 2) Assign seed Strip channel to a region, 3) `POST /api/capture/start`, 4) Point camera at colored test pattern, 5) Observe strip color matches region 6) Check StatusBar FPS reads ≥50 |
| zeroconf scan finds live WLED device within 3s | WLED-01 | mDNS requires LAN device to broadcast | 1) Plug in WLED device on same subnet, 2) Click "Scan network" in Settings, 3) Device appears in results within 3s |
| Timeout byte releases strip after /api/capture/stop | WLED-05 / WSTR-03 | Firmware behavior — validated by watching physical strip | 1) Start streaming, 2) Confirm strip is colored, 3) Stop streaming, 4) Observe: strip goes dark within 2s (from explicit blackout + timeout byte) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (see Per-Task Verification Map above — 19/20 automated, 1 manual checkpoint with documented instructions)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (only 17-09-02 lacks automated; its predecessor 17-09-01 runs the full E2E suite)
- [x] Wave 0 covers all MISSING references (fixtures + empty test files listed in Wave 0 Requirements)
- [x] No watch-mode flags in any quick/full command
- [x] Feedback latency < 60s (full backend suite)
- [x] `nyquist_compliant: true` set in frontmatter after planner filled Per-Task Verification Map

**Approval:** planner-complete; `wave_0_complete` flips to true once Wave 0 tasks (17-01-01, 17-01-02, 17-01-03) ship green.
