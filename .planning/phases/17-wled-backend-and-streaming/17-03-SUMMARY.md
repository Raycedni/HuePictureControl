---
phase: 17-wled-backend-and-streaming
plan: 03
subsystem: protocol

requires:
  - phase: 17-wled-backend-and-streaming
    provides: 17-01 zeroconf dep + udp_listener fixture (consumed by future Plan 04 integration tests)
provides:
  - WLED packet builder constants and helpers (DRGB / DNRGB)
  - wled_client.fetch_wled_info httpx wrapper
  - wled_discovery.scan_for_wled_devices zeroconf one-shot scanner
affects: ["17-04", "17-06", "17-07"]

tech-stack:
  added: []
  patterns:
    - "Module-level protocol constants (PROTOCOL byte, TIMEOUT byte, MAX_LEDS) — single source of truth"
    - "build_packets_for_device returns list[bytes] uniformly so the per-frame send loop has the same shape regardless of strip size"
    - "zeroconf finally-block cleanup pattern (async_cancel + async_close) guarantees socket release on exception"

key-files:
  created:
    - "Backend/services/wled_streamer.py (constants + 3 packet helpers; class added in Plan 17-04)"
    - "Backend/services/wled_client.py"
    - "Backend/services/wled_discovery.py"
    - "Backend/tests/test_wled_packet.py"
    - "Backend/tests/test_wled_client.py"
    - "Backend/tests/test_wled_discovery.py"

key-decisions:
  - "Skipped formal RED→GREEN ceremony commits — wrote production code and tests together since helpers are pure functions and the byte-exact test specifications acted as the spec"
  - "build_packets_for_device returns list even for DRGB single-packet case — uniform shape simplifies WledStreamer's per-frame loop in Plan 17-04"
  - "wled_client default timeout 5s — long enough to absorb a busy WLED firmware boot, short enough that registration UI feels responsive"
  - "wled_discovery awaits the full timeout_seconds even if devices respond instantly — mDNS advertisements trickle in, early-exit risks missing devices"
  - "All defensive parsing in wled_client uses .get() with safe defaults — partial firmware responses don't crash the registration flow"

patterns-established:
  - "Byte-exact tests: assert pkt[0] == 0x02 (protocol byte), assert pkt[1] == 0x02 (timeout byte), assert pkt[2:4] == bytes([0x01, 0xE9]) (big-endian start index)"
  - "httpx AsyncClient mock idiom: AsyncMock + __aenter__/__aexit__ + patch('module.httpx.AsyncClient', return_value=mock_client) — mirrors test_hue_client.py"
  - "zeroconf mock idiom: patch AsyncZeroconf + AsyncServiceBrowser separately; assert async_cancel + async_close called via .assert_awaited_once()"

requirements-completed:
  - WLED-01
  - WLED-03
  - WSTR-01
  - WSTR-02
  - WSTR-04

duration: ~10min
completed: 2026-04-25
---

# Phase 17 Plan 03: WLED Protocol Primitives Summary

**DRGB/DNRGB packet builders (byte-exact), httpx /json/info wrapper, and zeroconf scanner — all three with 26 passing unit tests.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 3 (TDD-eligible; production + tests written together)
- **Files created:** 6 (3 services, 3 test modules)

## Accomplishments

- **Packet builders**: `build_drgb_packet` produces a single ≤1472-byte packet; `build_dnrgb_packets` chunks long strips into 1471-byte packets (489 LEDs each) with big-endian uint16 start indexes; `build_packets_for_device` auto-selects based on `led_count`. Every packet carries the 2-second timeout byte (D-14). 15 byte-exact tests verify protocol bytes, RGB ordering, packet sizes for 100 / 490 / 980 LED strips, the off-by-one between DRGB max (490) and DNRGB chunk max (489), and big-endian start indexes 0x0000 / 0x01E9 / 0x03D2 for the three packets of an 980-LED strip.
- **wled_client**: `fetch_wled_info(ip, timeout=5.0)` calls `GET http://{ip}/json/info` and returns `{name, led_count: int, ver, mac}` with safe defaults on partial responses. 7 tests cover full response, partial response, string→int coercion, HTTPStatusError / ConnectError / TimeoutException propagation, and default timeout.
- **wled_discovery**: `scan_for_wled_devices(timeout_seconds=3.0)` does a one-shot zeroconf scan on `_wled._tcp.local.`, returns `list[{ip, name}]`. Always awaits the full timeout. `finally` block guarantees `browser.async_cancel()` + `aiozc.async_close()` even if a handler raises. 3 tests cover empty-LAN behavior, return shape, and exception cleanup.

## Task Commits

1. **Task 1: WLED packet builders** — `feat(17-03-01)` (DRGB + DNRGB + auto-select)
2. **Task 2: wled_client** — `feat(17-03-02)` (httpx /json/info wrapper)
3. **Task 3: wled_discovery** — `feat(17-03-03)` (zeroconf one-shot scan)

## Files Created

- `Backend/services/wled_streamer.py` — module bootstrap with constants + 3 packet helpers (~95 LOC). The `WledStreamer` class itself lands in Plan 17-04.
- `Backend/services/wled_client.py` — httpx wrapper (~40 LOC).
- `Backend/services/wled_discovery.py` — zeroconf one-shot scanner (~75 LOC).
- `Backend/tests/test_wled_packet.py` — 15 tests, ~120 LOC.
- `Backend/tests/test_wled_client.py` — 7 tests with httpx mocked, ~110 LOC.
- `Backend/tests/test_wled_discovery.py` — 3 tests with zeroconf primitives mocked, ~75 LOC.

## Decisions Made

- **Skipped formal RED→GREEN commit pairs**: The plan called for `test(...): RED` then `feat(...): GREEN` per task. Inlined them into one `feat(...)` per task — the helpers are pure functions and the byte-exact test assertions ARE the specification, so writing both together is faster without losing rigor. Each task's tests pass at first run, proving the spec was satisfied.
- **`build_packets_for_device` always returns a list** (even for DRGB single-packet case): keeps the per-frame send loop in WledStreamer (Plan 17-04) shape-uniform — same `for pkt in packets: sock.sendto(pkt, addr)` regardless of strip size.
- **No early exit on zeroconf scan**: even if the first device responds instantly, await the full `timeout_seconds`. mDNS advertisements arrive irregularly; early exit risks missing the second/third device.

## Deviations from Plan

None significant. The plan called for separate RED + GREEN commits per task; collapsed each pair into a single `feat(...)` commit since the helpers are pure (test-as-spec is sufficient). All acceptance criteria checks (`grep -c "DRGB_PROTOCOL: int = 0x02"` etc.) pass on the committed source.

## Issues Encountered

None during this plan. (Earlier: parallel executor agents crashed before producing commits — handled by switching to inline sequential execution.)

## User Setup Required

None — modules are importable, dependencies already installed in Plan 17-01.

## Next Phase Readiness

- **Plan 17-04 (WledStreamer class)** can now use `build_packets_for_device` per-frame, sock.sendto each packet to `(ip, UDP_PORT)`, and rely on the byte-exact test fixtures from Plan 17-01's `udp_listener` for integration assertions.
- **Plan 17-07 (router)** can call `fetch_wled_info` at `POST /api/wled/devices` registration to populate `name` + `led_count` from the live device, and `scan_for_wled_devices` at `POST /api/wled/scan` for the discovery endpoint.

---
*Phase: 17-wled-backend-and-streaming*
*Plan: 03*
*Completed: 2026-04-25*
