---
status: partial
phase: 13-scrcpy-android-integration
source: [13-VERIFICATION.md]
started: 2026-04-18T00:00:00Z
updated: 2026-04-18T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. ADB session start on real Android device
expected: POST /api/wireless/scrcpy with a real Android device IP returns 200 with session_id, and /dev/video11 appears as a V4L2 device within 10 seconds (SC-1, SCPY-01).
result: [pending]

### 2. Virtual camera visibility in cameras API
expected: GET /api/cameras lists the scrcpy virtual device with `is_wireless: true` while a session is active (SC-2, SCPY-02).
result: [pending]

### 3. Hue lights driven from mirrored Android screen
expected: Assigning the scrcpy virtual camera to an entertainment zone drives Hue lights in sync with the Android screen content at the same latency as physical USB capture (SC-3).
result: [pending]

### 4. WiFi interruption auto-reconnect
expected: Disabling the Android device's WiFi for 3-5 seconds triggers the stale-frame watchdog; streaming resumes automatically without user intervention once WiFi returns (SC-4, SCPY-04).
result: [pending]

### 5. Clean session stop
expected: DELETE /api/wireless/scrcpy/{session_id} returns 204 (or 200), /dev/video11 is removed, and `adb devices` no longer shows the device (SC-5, SCPY-03).
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
