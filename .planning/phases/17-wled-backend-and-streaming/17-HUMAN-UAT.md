---
status: partial
phase: 17-wled-backend-and-streaming
source: [17-VERIFICATION.md]
started: 2026-04-27T00:00:00Z
updated: 2026-04-27T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Settings panel UI walkthrough at http://localhost:8091
expected: Settings button (top-right) opens modal; paint-canvas placeholder visible (Phase 19 slot, D-20); WledDevicesPanel renders empty state; entering bad IP shows 422 error "Invalid IP or device returned unexpected data"; entering unreachable IP shows 502 error "Unreachable: <ip>" within ~5s; clicking Scan shows "Scanning…" for ~3s and lists candidates if any WLED on LAN.
result: [pending]

### 2. Real WLED hardware smoke test (optional — only if WLED ESP32 on LAN)
expected: Register device by IP via Settings panel → name + LED count populated from /json/info → Connected badge appears once streaming starts → strip color updates within ~100ms of region color changes at 50-60 Hz → Stop streaming → strip goes dark within 2s (explicit blackout + 2s timeout byte) → toggle Enabled OFF → next stream start does not drive that strip → Remove → row disappears, no further packets.
result: [pending]

### 3. /ws/status payload inspection in browser devtools
expected: Browser devtools → Network → WS → click /ws/status connection → frames include `wled_devices` key (may be `{}` when idle, `{device_id: {last_error, last_success_at, in_cooldown}}` when streaming with registered devices). Confirms wire-readiness for Phase 18 (HA status) and Phase 19 (paint UI).
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
