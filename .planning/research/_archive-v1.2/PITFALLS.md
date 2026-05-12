# Pitfalls Research

**Domain:** Multi-camera video capture in Docker — adding per-zone camera selection to an existing single-camera ambient lighting system
**Researched:** 2026-04-03
**Confidence:** HIGH (findings grounded in existing codebase analysis + verified community sources)

---

## Critical Pitfalls

### Pitfall 1: Device Path Instability — /dev/videoN Shifts on Every Plug/Reboot

**What goes wrong:**
The system stores `/dev/video0` as the configured camera for a zone. After the user unplugs and replugs the USB capture card (or reboots), the kernel assigns a different minor number and the device becomes `/dev/video2`. The stored path silently points at nothing, or worse, at the wrong device (another UVC node from the same physical card, e.g. a metadata node that returns no frames).

This is already documented in project memory (`feedback_docker_native.md`): "capture card device path shifts on USB re-attach." The multi-camera milestone multiplies this problem — with two or more devices, the shift probability is near 100% and the ordering between them is fully non-deterministic.

**Why it happens:**
Linux V4L2 assigns `/dev/videoN` sequentially at device-attach time. No ordering is guaranteed. One physical UVC capture card typically creates two nodes (one for video capture, one for device metadata), so two cards produce four nodes with arbitrary numbering. Docker's `devices:` section maps the path at container-start time; if the path changes on the host, the in-container path still resolves to the old inode, which may now be dead or reassigned.

**How to avoid:**
- Store the camera identity using a stable key: USB vendor ID + product ID + serial number. This is available from `/sys/class/video4linux/videoX/device/` or via `udevadm info`.
- Create a udev rule on the host that assigns a persistent symlink (e.g. `/dev/capture-hdmi-1`) based on `idVendor` + `idProduct` + `serial`.
- In `docker-compose.yaml`, mount the symlink path instead of the raw `/dev/videoN` path. Combine with `device_cgroup_rules: ["c 81:* rmw"]` so the rule follows major number 81 (all V4L2 devices) rather than a specific minor.
- In the enumeration API, return both the stable key and the current resolved path. Save the stable key to the database, resolve to current path at runtime.

**Warning signs:**
- User reports "camera shows no image" after unplugging/replugging without changing any config.
- Enumeration API returns different indices across two calls 30 seconds apart.
- `/dev/video0` and `/dev/video1` swap identity between Docker restarts.

**Phase to address:**
Device enumeration phase (the first implementation phase). Device identity design must be settled before any persistence of camera selection is built.

---

### Pitfall 2: Multiple /dev/videoN Nodes Per Physical Device — Metadata Node Confusion

**What goes wrong:**
The device enumeration routine scans indices 0–9 and reports every found `/dev/videoN` as a valid camera option. The user sees four entries in the dropdown for two physical capture cards. Two of those entries are metadata-capture nodes: opening them succeeds (V4L2 returns no error on open), but `VIDIOC_QUERYCAP` reveals they have `VIDEO_CAPTURE` capability absent. Trying to capture from them either hangs or returns corrupt frames.

The existing `V4L2Capture._setup_device()` already checks `device_caps & 0x01` (VIDEO_CAPTURE flag), but the enumeration layer runs before any capture object is created, so without explicit capability probing the UI will show phantom devices.

**Why it happens:**
Modern UVC capture cards and webcams register one node for video streaming and one for metadata (UVC XU controls, per-frame metadata). Both appear as `/dev/videoX`. The V4L2 architecture explicitly supports multiple nodes per physical device for this reason. The kernel's `VIDIOC_QUERYCAP` `device_caps` field distinguishes them, but only if you ask.

**How to avoid:**
- In the enumeration endpoint, open each candidate device path, issue `VIDIOC_QUERYCAP`, and check `device_caps & V4L2_CAP_VIDEO_CAPTURE (0x1)`. Discard nodes that lack this flag before returning them to the frontend.
- Additionally check `device_caps & V4L2_CAP_STREAMING (0x4000000)` — non-streaming nodes cannot be used with the mmap capture path.
- Use `v4l2-ctl --list-devices` output structure as a reference: it groups sibling nodes under the same physical device name. Reproduce this grouping in the API so the dropdown shows "HDMI Capture Card" with sub-options rather than four raw device paths.
- Alternatively, read `/sys/class/video4linux/videoX/name` and group by device name to collapse siblings.

**Warning signs:**
- Dropdown shows an even number of devices where you expect an odd number of physical cameras.
- Opening a device in enumeration probe succeeds but `get_frame()` immediately raises "No frame available."
- `VIDIOC_DQBUF` hangs indefinitely after successful `VIDIOC_STREAMON`.

**Phase to address:**
Device enumeration phase. The capability check must be part of the enumeration implementation, not a later hardening step.

---

### Pitfall 3: Blocking V4L2/OpenCV Open Calls Stall the asyncio Event Loop

**What goes wrong:**
`V4L2Capture.open()` and `DirectShowCapture.open()` are synchronous blocking calls. Opening a V4L2 device includes device setup ioctls, buffer allocation, and `VIDIOC_STREAMON` — this takes 200–1500ms. When the user switches a zone's camera from the UI, the API handler calls `capture.open()` directly, stalling the FastAPI event loop for up to 1.5 seconds and blocking all concurrent WebSocket frames and API requests.

**Why it happens:**
The existing `StreamingService._capture_reconnect_loop()` already wraps `self._capture.open` with `asyncio.to_thread()` — this was an explicit design decision. However, adding a second capture instance or switching an active capture mid-stream may bypass this discipline if new code paths call `open()` synchronously.

**How to avoid:**
- All calls to `CaptureBackend.open()`, `release()`, and any new `enumerate_devices()` that probes hardware must go through `asyncio.to_thread()`.
- Enumerate via `VIDIOC_QUERYCAP` (lightweight, 1–5ms per device) rather than full open-configure-stream cycles (200–1500ms).
- For the `PUT /api/capture/device` endpoint that switches cameras, the current implementation at `capture.py:99` calls `capture_service.open(body.device_path)` directly — this must be converted to `await asyncio.to_thread(capture_service.open, body.device_path)`.

**Warning signs:**
- UI freezes for 1–2 seconds after selecting a different camera in the zone dropdown.
- WebSocket status frames stop arriving during camera switch.
- FastAPI access log shows a request taking >500ms for what should be a fast response.

**Phase to address:**
Camera-switch API implementation phase. Review every new code path that touches `CaptureBackend.open()`.

---

### Pitfall 4: Shared Single CaptureBackend — Two Zones, One Camera Object, Race Conditions

**What goes wrong:**
Currently `app.state.capture` is a single `CaptureBackend` instance shared by the streaming service, preview WebSocket, and snapshot endpoint. When multi-camera support allows two different zones to select two different devices, the temptation is to manage this with one capture object and call `open(new_path)` when zone B's camera differs from zone A's. This creates a race: zone A's reader thread is writing `_latest_frame` while zone B forces a `release()`, leaving zone A's frame loop calling `get_frame()` on a released device and crashing.

**Why it happens:**
The single-capture architecture is a clean design for single-camera. Extending it by switching the device path in-place rather than maintaining per-device instances is the "least code" approach but violates the one-writer-per-object contract assumed by `_frame_lock`.

**How to avoid:**
- Move from one shared `CaptureBackend` to a `CaptureRegistry` — a dict mapping device path to `CaptureBackend` instance.
- Open a new instance when a zone selects a device not already in the registry; reuse (reference-count) existing instances when multiple zones share a camera.
- Release an instance only when its reference count drops to zero.
- The registry itself must be concurrency-safe: protect mutations with `asyncio.Lock`, not threading locks, since callers are async.
- `StreamingService` becomes a consumer of the registry, not the owner of a capture object.

**Warning signs:**
- Intermittent `RuntimeError("Capture device is not open")` in the frame loop during zone switching.
- `_reader_error` event fires immediately after switching a zone.
- Two zones both configured to `/dev/video0` but one silently gets no frames.

**Phase to address:**
Architecture / capture registry design phase — must be settled before any multi-camera frame loop code is written.

---

### Pitfall 5: Docker compose.yaml Device List Must Be Updated Manually for Each New Camera

**What goes wrong:**
The current `docker-compose.yaml` has the `devices:` section commented out (due to WSL2 limitations) with only `/dev/video0` mentioned in comments. When running on a native Linux host with two capture cards, both device paths must appear in the `devices:` section. Forgetting to add `/dev/video1` means the backend container cannot open the second camera, but the enumeration API (which reads `/dev/`) may still list it — causing a misleading "device found but cannot open" error.

**Why it happens:**
Docker device passthrough is declared statically at compose file creation time. Dynamic hotplug is only possible via `device_cgroup_rules` + mounting `/dev` as a volume (which has its own security and permission surface). Developers test with one camera and forget the compose file when adding a second.

**How to avoid:**
- Switch from static `devices:` entries to `device_cgroup_rules: ["c 81:* rmw"]` + mounting `/dev/v4l` (or `/dev/video*` via a tmpfs bind). This grants access to all major-81 devices without listing them individually.
- Alternatively, document a setup script that auto-generates the `devices:` list by scanning `/dev/video*` on the host before starting the stack.
- The enumeration endpoint should propagate the actual `open()` failure as a device status ("found but not accessible") rather than silently omitting it or treating it identically to a working device.

**Warning signs:**
- `v4l2-ctl --list-devices` inside the container shows fewer devices than on the host.
- `open("/dev/video1", O_RDWR)` returns `ENOENT` inside the container despite the host having the device.
- Adding a second camera works natively but fails inside Docker without explanation.

**Phase to address:**
Docker/infrastructure phase — update `docker-compose.yaml` before any multi-camera testing.

---

### Pitfall 6: Zone Camera Selection Persisted as /dev Path — Breaks After Re-attach

**What goes wrong:**
The zone configuration database stores `camera_device = "/dev/video0"` for zone A. After the user unplugs the HDMI capture card and replugs it, the device reappears as `/dev/video2`. The streaming service opens `/dev/video0` — which now belongs to the built-in webcam — and zone A lights synchronize to the laptop camera instead of the HDMI source. No error is raised because the device opened successfully.

This is a silent correctness failure, harder to detect than an outright crash.

**Why it happens:**
Storing a kernel-assigned path is only safe for a single session. The assumption is that path = identity, but V4L2 provides no such guarantee across attach/detach cycles.

**How to avoid:**
- Store camera identity as `(idVendor, idProduct, serial)` in the database. Resolve to current `/dev/videoN` at startup or when streaming starts.
- If no device matching the stored identity is found, surface a clear error ("Camera for zone A not found — was it disconnected?") rather than silently falling back to `/dev/video0`.
- Provide a "re-scan and reassign" UI action so the user can remap zones without losing other configuration.

**Warning signs:**
- Zone lights react to wrong content (laptop camera instead of HDMI source).
- Log shows capture opened successfully but colors are obviously wrong.
- Changing a zone's camera selection in the UI fixes the problem temporarily, until the next replug.

**Phase to address:**
Database schema design for camera identity (must precede the UI implementation for zone-camera assignment).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Store `/dev/videoN` path directly in DB | Zero schema change | Silent wrong-camera failures after re-attach | Never — affects correctness silently |
| One global `CaptureBackend`, switch device in-place | Minimal refactor | Race conditions when two zones switch cameras concurrently | Never — crashes under concurrent use |
| Skip `VIDIOC_QUERYCAP` check in enumeration | Faster enumeration code | Metadata nodes appear as valid cameras in UI | Never — confuses users immediately |
| Static `devices:` list in compose | Simple compose file | Must manually update for every new capture card | Acceptable for single-camera permanent setups only |
| Probe cameras by iterating indices 0–9 with `cv2.VideoCapture` | Simple Python code | Blocks event loop 200ms per probe × 10 = 2s; opens/closes devices wastefully | Acceptable only in a one-shot CLI tool, not in an API |
| Call `capture.open()` synchronously in API handler | Less wrapper code | Stalls FastAPI event loop during camera switch | Never — existing code already wraps this correctly |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| V4L2 device enumeration | Treat every `/dev/videoN` as a streamable camera | Check `device_caps & 0x1` (VIDEO_CAPTURE) via `VIDIOC_QUERYCAP` before listing |
| Docker device passthrough | Add only `/dev/video0` to compose `devices:` | Use `device_cgroup_rules: ["c 81:* rmw"]` for dynamic multi-device access |
| USB device identity | Store kernel path (`/dev/videoN`) as device key | Store `(idVendor, idProduct, serial)` from sysfs; resolve path at runtime |
| udev symlinks inside Docker | Expect host udev symlinks to appear inside container | udev rules create symlinks on host only; must explicitly mount them or use cgroup rules |
| Multiple `CaptureBackend` instances | Open two instances on same `/dev/videoN` path | V4L2 allows only one exclusive open per node; second open returns `EBUSY` |
| Preview WebSocket with multi-camera | One WebSocket serves frames from a single global capture | Per-zone preview requires routing the WebSocket to the correct `CaptureBackend` instance |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Probing all camera indices on every `/api/cameras` request | API call takes 2–5 seconds; event loop stalls | Cache enumeration results; invalidate on explicit re-scan only | On first call with ≥3 cameras |
| Opening a V4L2 device synchronously in the API path | HTTP 200 response delayed by 500ms–1.5s | Wrap all `open()` calls in `asyncio.to_thread()` | Every camera-switch request |
| One reader thread per camera at 640×480 MJPEG | Two cameras = 2 × 30 fps × ~50KB/frame = ~3 MB/s decode load | Use hardware MJPEG decode path; don't re-encode to JPEG after decode | At 4K resolution or ≥4 cameras |
| Frame sharing between two zones on the same camera | Two `asyncio.to_thread(get_frame)` calls per loop iteration | Use the `CaptureRegistry` reference-count design; one reader thread per device, multiple consumers | Immediately — doubles reader thread overhead if not shared |
| Streaming loop holds a reference to a released capture object | `RuntimeError` on next `get_frame()` mid-stream | `CaptureRegistry` lifecycle must outlive `StreamingService` | On any camera switch during active streaming |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Show raw `/dev/video0`, `/dev/video1`, `/dev/video2`, `/dev/video3` in dropdown | User cannot identify which entry is their HDMI capture card | Show device name from `VIDIOC_QUERYCAP` (e.g. "USB Video: UVC Camera") + device path as secondary label |
| Include metadata nodes in camera list | User selects a camera that produces no frames, confused | Filter to VIDEO_CAPTURE-capable nodes only (see Pitfall 2) |
| No feedback when selected camera is not accessible in Docker | User selects camera, nothing happens, no error shown | Surface a clear "device not accessible — check Docker compose" error message |
| Camera selection lost after replug | User must reconfigure zones after every cable re-attach | Persist camera by stable identity; resolve at runtime; auto-reattach if device returns |
| Zone preview shows wrong camera after switch | User thinks lighting will follow wrong source | Preview WebSocket must immediately reflect the zone's newly selected camera, not the global capture |

---

## "Looks Done But Isn't" Checklist

- [ ] **Camera enumeration:** Does it filter metadata nodes? Verify with `v4l2-ctl --list-devices` and confirm counts match.
- [ ] **Device identity:** Is it stored as stable key (VID/PID/serial) or raw path? Check the DB schema.
- [ ] **Async discipline:** Does every `CaptureBackend.open()` call in new code go through `asyncio.to_thread()`? Grep for direct `capture.open(` calls outside `to_thread`.
- [ ] **Docker compose:** Are all expected capture devices accessible inside the container? Run `ls /dev/video*` from inside the backend container.
- [ ] **Reference counting:** Do two zones selecting the same device create one reader thread or two? Confirm with `ps aux | grep capture-reader`.
- [ ] **Preview routing:** When zone A uses camera 1 and zone B uses camera 2, does the preview WebSocket for zone B show camera 2's frames? Test explicitly.
- [ ] **Error propagation:** If a zone's selected camera is disconnected mid-stream, does the UI show an error or silently continue with stale frames? Verify the stale-frame timeout triggers and surfaces an error.
- [ ] **Reconnect loop:** Does the existing `_capture_reconnect_loop` work correctly when only one of two cameras disconnects? The loop currently calls `self._capture.open()` — with a registry, it must target the correct instance.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Device paths stored as raw `/dev/videoN` in DB | MEDIUM | Add a migration that backfills VID/PID/serial; add a UI "remap cameras" flow |
| Metadata nodes exposed in UI | LOW | Add `VIDIOC_QUERYCAP` filter to enumeration endpoint; no DB changes needed |
| Event loop stall from blocking `open()` | LOW | Wrap call in `asyncio.to_thread()`; no architectural change |
| Two zones competing for one `CaptureBackend` | HIGH | Introduce `CaptureRegistry`; refactor `StreamingService` to use registry; update tests |
| Docker compose missing second device | LOW | Add `device_cgroup_rules` line; rebuild and restart stack |
| Preview WebSocket shows wrong camera | MEDIUM | Add `zone_id` parameter to preview WebSocket; route to registry instance |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Device path instability (Pitfall 1) | Device enumeration + DB schema phase | After phase: replug camera, restart, confirm stored zone still captures from correct device |
| Metadata node confusion (Pitfall 2) | Device enumeration phase | After phase: verify camera list count matches physical device count, not node count |
| Blocking `open()` in event loop (Pitfall 3) | Camera-switch API phase | After phase: switch camera via API while streaming; verify WS frames continue without gap |
| Shared CaptureBackend race (Pitfall 4) | Architecture / CaptureRegistry phase | After phase: two zones on different devices, switch one while streaming; no errors in other |
| Docker compose devices incomplete (Pitfall 5) | Infrastructure / Docker phase | After phase: run `ls /dev/video*` inside container; count matches host |
| Zone camera selection as raw path (Pitfall 6) | DB schema phase | After phase: replug camera, stream; lights follow correct source without UI intervention |

---

## Sources

- Project codebase: `Backend/services/capture_service.py`, `capture_v4l2.py`, `capture_dshow.py`, `streaming_service.py`, `routers/capture.py`
- Project memory: `feedback_docker_native.md` — device path shift on USB re-attach
- [Assign v4l2 device a static name — Formant docs](https://docs.formant.io/docs/assign-v4l2-device-a-static-name) — udev persistent symlinks for V4L2
- [Multiple /dev/video for one physical device — Ubuntu Launchpad](https://answers.launchpad.net/ubuntu/+question/683647) — metadata node behavior
- [V4L2 device internal representation — kernel.org](https://docs.kernel.org/driver-api/media/v4l2-dev.html) — device_caps field, VIDEO_CAPTURE flag
- [How to Share Webcams with Docker — FunWithLinux.net](https://www.funwithlinux.net/blog/sharing-devices-webcam-usb-drives-etc-with-docker/) — device_cgroup_rules for major 81
- [Docker device_cgroup_rules — Baeldung](https://www.baeldung.com/ops/docker-access-host-devices) — cgroup rules format
- [VideoCapture freezes if camera is busy — OpenCV GitHub #15074](https://github.com/opencv/opencv/issues/15074) — blocking open behavior
- [Does cv::VideoCapture have thread lock — OpenCV GitHub #24229](https://github.com/opencv/opencv/issues/24229) — thread-safety behavior
- [Stop trusting /dev/ttyUSB0 — Medium](https://medium.com/@dynamicy/stop-trusting-dev-ttyusb0-using-udev-rules-for-stable-device-naming-on-linux-adc878f19ee9) — udev rule pattern (applies equally to video devices)

---
*Pitfalls research for: multi-camera Docker V4L2 capture — HuePictureControl v1.1*
*Researched: 2026-04-03*

---
---

# Pitfalls Research — Milestone v1.3

**Domain:** WLED UDP streaming, Home Assistant control endpoints, LED strip mapping UI, channel abstraction, zone persistence
**Researched:** 2026-04-14
**Confidence:** HIGH for WLED protocol specifics (verified against official WLED docs + GitHub issues); MEDIUM for HA design and React persistence patterns (verified against official docs + community sources)

---

## Critical Pitfalls (v1.3)

### Pitfall W1: DRGB Packet Hard-Cap — 490 LEDs Maximum Without Protocol Switch

**What goes wrong:**
The DRGB protocol (WLED UDP realtime, type byte `0x02`) sends RGB data for every LED starting from LED 0 with no indexing. The maximum packet size is one UDP datagram, which caps DRGB at 490 LEDs. A 300-LED strip fits, but a common 5m strip of 300 LEDs at 60 LED/m is fine — the problem emerges when users chain strips or use higher-density strips. Any attempt to stream more than 490 LEDs via DRGB silently truncates: WLED processes the packet without error but the last (N - 490) LEDs receive no update and hold their previous colors or go dark.

**Why it happens:**
DRGB assumes one packet covers the entire strip. Developers copy the DRGB example from tutorials, calculate 3 bytes × N LEDs, and don't notice the silent truncation because the first 490 LEDs look correct.

**How to avoid:**
- Use DNRGB (type byte `0x04`) for all strips, not just those exceeding 490 LEDs. DNRGB includes a 2-byte start index, allowing arbitrary strip lengths via multiple packets per frame.
- Packet 1: bytes `[0x04, timeout, 0x00, 0x00, R0, G0, B0, R1, G1, B1, ...]` (up to 489 LEDs)
- Packet 2: bytes `[0x04, timeout, 0x01, 0xDD, R489, G489, B489, ...]` (remainder)
- The start index is big-endian 16-bit: high byte first.
- Adopt DNRGB from the start even for small strips — it is a strict superset of DRGB with two extra header bytes.

**Warning signs:**
- Last N LEDs on strip show wrong color or are stuck at the color from before streaming started.
- Behavior is correct with 100 LEDs but wrong with 300 LEDs.
- No error on the Python side; no error logged by WLED.

**Phase to address:**
WLED UDP sender implementation phase. Lock in DNRGB from the first prototype, not as a later upgrade.

---

### Pitfall W2: UDP Timeout Byte Governs Revert-to-Effect Behavior — Wrong Value Causes Sticky Black Frames

**What goes wrong:**
The second byte of every DRGB/DNRGB packet is a timeout in seconds: after this many seconds with no new packet, WLED exits realtime mode and returns to its previous effect/preset. Two wrong choices cause symptoms that look unrelated:

- **Timeout = 0:** Documented as "immediate exit on stop" in some guides but WLED treats 0 as a no-timeout (stays in realtime forever). When streaming stops, the strip stays at the last-sent color until a user manually changes something.
- **Timeout = 255:** Infinite timeout — same permanent-last-frame behavior. Intentional when you want frames to persist, but fatal if you want the strip to cleanly return to ambient/preset mode on streaming stop.
- **Timeout = 1–2:** Correct for ambient lighting — strip returns to effect mode within 1–2 seconds of stream silence. BUT if the frame loop pauses >2 seconds (CPU spike, container restart), the strip drops out of realtime mode mid-stream and reverts to its preset, creating a jarring effect-interruption even though streaming is still "active."

**Why it happens:**
Developers copy timeout = 255 from examples designed for static color control, not for streaming applications where clean exit matters.

**How to avoid:**
- Use timeout = 2 for ambient streaming. This balances clean exit (reverts to preset within 2s of stop) against brief pauses (the loop runs at 30–60 Hz; a 2s window tolerates brief GIL contention or network hiccup).
- Send a keepalive packet (same frame data or all-black) on `stop()` to force an immediate transition to black before the timeout fires naturally.
- Never use 0 or 255 in a streaming context.

**Warning signs:**
- Strip stays lit with the last frame color after streaming is explicitly stopped.
- Strip randomly reverts to its "sunrise" or "rainbow" preset mid-session.
- Behavior changes after lowering target Hz from 60 to 10 (packet gaps exceed timeout).

**Phase to address:**
WLED UDP sender implementation phase. The timeout value should be a named constant (`WLED_REALTIME_TIMEOUT_S = 2`), not a magic byte.

---

### Pitfall W3: JSON API and UDP Realtime Are Mutually Exclusive While Streaming Is Active

**What goes wrong:**
WLED disables its JSON API (and web UI) while UDP realtime is active. This means calls to `GET /json/state`, `POST /json`, or the WLED HTTP API sent while the streaming loop is running will either be silently ignored or cause a known race condition (WLED GitHub issue #3589): the strip gets stuck on the last UDP frame color, stops reverting on timeout, and ignores all subsequent JSON commands until power-cycled or WLED firmware-reset.

For this project, this affects:
- The WLED device management tab: reading `GET /json/info` to populate the device list will race with the streaming loop.
- Any Home Assistant automation that uses WLED's own HA integration (which calls the JSON API) while HuePictureControl is also streaming to the same device.

**Why it happens:**
WLED's realtime mode takes exclusive control of the LED output. The JSON API path attempts to write to the same LED buffer. The firmware does not queue or serialize these accesses; the result is undefined behavior that looks like a firmware hang.

**How to avoid:**
- Never call WLED's JSON API on a device while that device is in the active streaming target list.
- In the WLED device manager, poll `GET /json/state` only at startup (when streaming is idle) and after streaming stops, not while streaming is running.
- Expose WLED device configuration (LED count, segment layout) as read-once-and-cache data. Do not refresh it mid-stream.
- For the Home Assistant integration: document that HA's WLED integration must be disabled for any device that HuePictureControl is streaming to. They cannot coexist.

**Warning signs:**
- WLED strip stops responding after streaming stops; JSON API calls return nothing.
- WLED web UI shows "Live" badge indefinitely after the Python process exits.
- `GET /json/state` succeeds before streaming but times out after first streaming session.

**Phase to address:**
WLED device management + streaming loop phases. The device manager must be aware of which devices are currently streaming and suppress API calls to them.

---

### Pitfall W4: WLED mDNS Discovery Fails Inside Docker Bridge Network

**What goes wrong:**
WLED devices advertise themselves via mDNS (multicast DNS, UDP port 5353) on the local LAN. Docker's default bridge network (`172.17.0.0/16`) does not forward multicast traffic to the host LAN. A mDNS-based auto-discovery scan from inside the backend container will find zero WLED devices even though all of them are visible from the host machine.

This is the same network topology issue as the Hue Bridge — which is why the project already requires `network_mode: host` for Hue DTLS/UDP streaming. WLED discovery has the same constraint.

**Why it happens:**
Docker bridge networks isolate containers from the host's LAN multicast domain. mDNS relies on `224.0.0.251` multicast, which does not traverse the Docker bridge NAT layer.

**How to avoid:**
- The backend already uses `network_mode: host` for Hue DTLS. WLED discovery benefits from this automatically — no additional change needed.
- Do not offer mDNS auto-discovery as a primary flow. Offer it as a convenience scan, with manual IP entry as the always-available fallback.
- Document that auto-discovery requires `network_mode: host` (already the case).
- If ever moving away from host networking, use `--net=host` on the discovery call or proxy discovery through the host.

**Warning signs:**
- Auto-discovery returns empty list even though WLED devices are reachable by direct IP.
- `ping wled-device.local` fails from inside the container but works from the host.
- Discovery works when tested natively (outside Docker) but not in the container.

**Phase to address:**
WLED device management phase. Do not implement mDNS discovery before confirming it works under host networking.

---

### Pitfall W5: Shared Channel Abstraction Leaks Hue-Specific Concepts Into WLED Code

**What goes wrong:**
The existing streaming pipeline passes `channel_id` (a Hue Entertainment API concept — integer 0–N assigned by the bridge) to the color output layer. When WLED support is added, the temptation is to alias WLED LED indices as "channels." This leaks the assumption that a channel is a Hue DTLS stream slot into WLED code. The divergence becomes critical when:

- Hue channels are sparse (e.g., channel IDs `0, 1, 5, 6`) while WLED indices are always dense and contiguous (0, 1, 2, ..., N-1).
- A canvas zone maps to a Hue channel that the bridge assigned, but to a WLED LED range that the user painted — the data model is fundamentally different.
- The `light_assignments` table uses `channel_id INTEGER` as the key. This works for Hue but requires a different key type for WLED (a start/end range, not a single int).

**Why it happens:**
The existing `_load_channel_map()` method returns `{channel_id: mask}` — a Hue-specific shape. The path of least resistance is to make WLED use the same dict shape, which forces a conceptual mapping that doesn't fit.

**How to avoid:**
- Define a device-agnostic output abstraction: `{output_target: mask}` where `output_target` is a typed union:
  - `HueChannel(id: int)` for Hue DTLS
  - `WledRange(device_ip: str, start_led: int, end_led: int)` for WLED
- The streaming loop iterates `output_targets`, computes color per target, and dispatches to the appropriate sender (DTLS or UDP) based on the type.
- Keep the `light_assignments` table for Hue. Add a separate `wled_assignments` table with columns `(region_id, device_ip, start_led, end_led, entertainment_config_id)`.
- Do not repurpose `channel_id` for WLED.

**Warning signs:**
- WLED LED mapping code has a comment like "channel_id is repurposed as LED index here."
- The same `light_assignments` table stores both Hue and WLED data with a type discriminator column.
- WLED strip shows color from the wrong region because LED index 5 happens to equal Hue channel 5 by coincidence.

**Phase to address:**
Shared abstraction design phase — must precede both the WLED sender and any UI changes to the assignment model. This is the highest-risk architectural decision in v1.3.

---

### Pitfall W6: Paint-on-Strip UI Off-by-One — WLED Uses Zero-Based Exclusive-End Indexing

**What goes wrong:**
WLED's segment and realtime addressing is zero-indexed with exclusive end: a strip of 300 LEDs has valid indices 0–299. Sending data to "LED 300" is a no-op (silently dropped). The UI shows users a 1-to-300 range because humans count from 1. The translation layer computes `start = user_start - 1`, `end = user_end - 1`, which is wrong: it produces an off-by-one where the last LED in a painted range receives no data.

The correct translation is: `start_led = user_start - 1`, `end_led = user_end` (exclusive). Or store zero-based internally and subtract 1 only in the UI display layer.

**Why it happens:**
WLED documentation uses 0-based indices. UI design instinctively uses 1-based for user-facing counts. The boundary between these two worlds is where the off-by-one lives, and it is invisible in testing (a 1-LED difference at the edge is hard to spot visually).

**How to avoid:**
- Store all LED indices zero-based in the database and in-memory.
- Display layer only: add 1 to start and end for user-visible labels.
- DNRGB packet: use stored zero-based start_led directly as the start index field.
- Write a unit test: "if user paints LEDs 1–300 on a 300-LED strip, exactly 300 bytes of RGB data are sent, and the last 3 bytes correspond to LED 299."

**Warning signs:**
- Last LED in a painted range is always the same color as the LED before it (color from the adjacent range bleeds in).
- Painting "all LEDs" (1 to 300) still leaves the last LED uncontrolled.
- Off-by-one only manifests at range boundaries; middle of the strip looks correct.

**Phase to address:**
Paint-on-strip UI implementation phase. Define the index convention as a project constant before any UI or packet code is written.

---

### Pitfall W7: Konva.js Re-render Thrash — Rendering 300 Individual Rect Nodes at 60 Hz

**What goes wrong:**
The paint-on-strip UI uses a Konva `Stage` with one `Rect` per LED (300 rects). Each Konva shape is a React component. On every color update during live preview (showing what color each LED is currently being sent), React renders 300 components → Konva redraws the canvas layer → 300 paint calls per frame at 60 fps = 18,000 draw operations per second. This saturates a mid-range GPU within seconds and pins the browser at 100% CPU.

**Why it happens:**
The existing region editor (EditorCanvas.tsx) already uses Konva for the polygon canvas, and it works fine because polygons are infrequent and user-driven. LED preview is continuous and data-driven — a fundamentally different usage pattern.

**How to avoid:**
- Do not represent each LED as a separate Konva `Rect` node.
- Use a single `Konva.Image` node backed by an offscreen `HTMLCanvasElement`. Write pixel colors to the offscreen canvas using `ImageData` (one `Uint8ClampedArray` write per frame), then call `konvaImage.image(offscreenCanvas)` and `layer.batchDraw()` once per frame.
- This reduces 300 draw calls to 1 canvas write + 1 layer redraw per frame.
- For the interactive paint affordance (drag to assign range), use a separate thin `Konva.Rect` overlay layer that is only redrawn on mouse interaction, not on color data updates.
- Separate concerns: data layer (color updates, fast) vs. interaction layer (drag handles, slow).

**Warning signs:**
- Browser DevTools Profiler shows "Recalculate Style" and "Paint" events every 16ms for 300 items.
- UI becomes sluggish after enabling the live preview toggle on the strip editor.
- CPU usage jumps to 80–100% when the strip editor is open.

**Phase to address:**
Paint-on-strip UI implementation phase. Validate the canvas architecture with a 300-element render benchmark before building the full interaction layer.

---

### Pitfall H1: Home Assistant Endpoint Design — Action Verbs as GET Requests

**What goes wrong:**
The HA control endpoints are implemented as `GET /api/ha/start` and `GET /api/ha/stop` because GET is the simplest to call from HA's `rest_command` or a browser. This violates REST semantics: GET must be idempotent and side-effect-free. Some HA automation engines, HTTP proxies, and caching layers will cache or deduplicate GET requests, causing the stop command to be swallowed.

Additionally, HA's `rest_command` integration uses POST by default. Deviating from this requires extra YAML configuration that users will get wrong.

**Why it happens:**
GET is the path of least resistance for quick testing in a browser. It feels like a "control API" (click a link = trigger an action). The consequences only appear when HA's automation engine starts caching responses.

**How to avoid:**
- Use `POST /api/ha/start`, `POST /api/ha/stop`. Accept a JSON body with optional parameters (camera, zone).
- In HA, configure via `rest_command`:
  ```yaml
  hpc_start:
    url: http://hpc-backend:8000/api/ha/start
    method: POST
    content_type: application/json
    payload: '{"config_id": "{{ config_id }}"}'
  ```
- Return a clear JSON response body (`{"status": "starting", "config_id": "..."}`) so HA automations can condition on the result.
- Document example HA YAML alongside each endpoint — this prevents integration errors from day 1.

**Warning signs:**
- HA `rest_command` reports 405 Method Not Allowed when calling start/stop.
- Clicking "start" twice in quick succession appears to do nothing the second time.
- A reverse proxy in front of the backend caches the GET response and the stop command never reaches the service.

**Phase to address:**
Home Assistant endpoints phase. Establish HTTP method conventions before writing any HA-callable endpoint.

---

### Pitfall H2: HA Long-Lived Access Token Stored in Database — Security Regression

**What goes wrong:**
The Home Assistant endpoint implementation needs to push state updates back to HA (e.g., "streaming started" → update an HA sensor). To call HA's REST API, an outbound HTTP call from the backend needs a Long-Lived Access Token (LLAT). The token gets stored in SQLite alongside Hue credentials, following the existing `bridge_config` pattern. This is a security regression: the Hue `client_key` is a local API key with no external privileges; a HA LLAT grants access to every device and automation in the user's home.

**Why it happens:**
The existing DB pattern (store credentials in `bridge_config`) makes it natural to extend with a `ha_config` table. The difference in privilege scope between the two credential types is not obvious.

**How to avoid:**
- For v1.3, HuePictureControl is a control target for HA, not a HA controller. HA calls HPC's endpoints; HPC does not call HA back. This is the correct direction — it avoids the LLAT problem entirely.
- Do not implement outbound HA calls in v1.3. If bi-directional sync is needed in a future milestone, use webhooks (HA pushes to HPC's webhook) rather than HPC polling HA.
- If a LLAT is ever stored, put it in an environment variable (`HA_TOKEN`), not in the database.

**Warning signs:**
- `ha_config` table appears in `database.py` with a `token` or `api_key` column.
- Backend code contains `httpx.get("http://homeassistant.local:8123/api/states/...")` with a bearer token.

**Phase to address:**
Home Assistant endpoints phase. Establish the integration direction (HA calls HPC, not the reverse) as an explicit design decision before writing any code.

---

### Pitfall P1: Entertainment Zone Persistence Bug — Dropdown Initialized From Stale React State, Not From Backend

**What goes wrong:**
The zone/config dropdown (which entertainment configuration is selected) initializes from React component state or Zustand store. On page reload, the store re-initializes to its defaults (e.g., `selectedConfigId: null`). The actual streaming state — which config the backend is currently streaming to — is never fetched on mount. Result: user reloads, dropdown shows "None selected," but streaming is still active on the backend. The start/stop button is in an incorrect state.

The `useStatusStore` in the codebase stores `isStreaming: false` as a default. On WebSocket reconnect it gets updated, but the `selectedConfigId` (whichever config was streaming) is never restored.

**Why it happens:**
The WebSocket `ws/status` pushes streaming state (`isStreaming`, `fps`, etc.) but does not push `config_id`. The frontend has no way to know which config was selected when it reconnects. The config_id is stored in `StreamingService._config_id` on the backend but never exposed via a REST endpoint.

**How to avoid:**
- Add `GET /api/capture/status` that returns `{"state": "streaming"|"idle", "config_id": "...|null"}`.
- On app mount and WebSocket reconnect, call this endpoint and initialize the Zustand store from it.
- Do not persist `selectedConfigId` to localStorage — derive it from backend state, not from browser storage. localStorage can be stale if the user stopped streaming from another tab or directly via API.

**Warning signs:**
- Reload the page while streaming; the "Start Streaming" button is available instead of "Stop Streaming."
- The dropdown shows the last-selected config from before the reload only if localStorage persists it — but stopping from another session makes this wrong.
- Backend logs show `streaming_service.state = streaming` but frontend shows `isStreaming = false`.

**Phase to address:**
Zone persistence bug fix phase. Add `GET /api/capture/status` before touching any frontend dropdown code.

---

### Pitfall P2: Zustand Persist Middleware Writes selectedConfig to localStorage — Diverges From Backend Truth

**What goes wrong:**
Using `zustand/middleware/persist` on `useStatusStore` or a config store to remember the selected entertainment config across reloads appears to solve the persistence bug. It does not: the persisted value reflects the last UI selection, not the last backend state. If the user stops streaming from the HA integration, from the CLI, or from Docker restart, localStorage still says "streaming to config XYZ" and the UI shows the wrong state.

**Why it happens:**
Zustand persist is well-documented and easy to add. Developers reach for it as the obvious "persist across reload" solution without considering that this data has an authoritative backend source.

**How to avoid:**
- Never use `persist` for streaming state or selected config. These are derived from backend state.
- `persist` is only appropriate for pure UI preferences (e.g., theme, panel layout) that have no backend equivalent.
- Initialize streaming state from `GET /api/capture/status` on mount. Update it from the WebSocket. Never store it in localStorage.

**Warning signs:**
- `localStorage.getItem('hpc-store')` exists in the browser and contains `selectedConfigId`.
- UI shows "streaming" after Docker container restart (because localStorage says so, not because it is true).

**Phase to address:**
Zone persistence bug fix phase. Add the guard "is this state derived from backend?" before adding persist to any store key.

---

## Technical Debt Patterns (v1.3)

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Use DRGB instead of DNRGB | 2 fewer bytes per packet | Silent truncation above 490 LEDs | Never — DNRGB is strictly better |
| Repurpose `channel_id` for WLED LED indices | No new DB tables | Silent wrong-LED mapping when Hue and WLED co-exist | Never — the types are incompatible |
| One Konva `Rect` per LED for live preview | Simple declarative React code | Browser freeze at 60 Hz with 300 LEDs | Never in live preview; acceptable for static assignment display |
| Store HA LLAT in SQLite `ha_config` table | Consistent with Hue credential storage | Exposes full HA admin token in plaintext DB | Never — use env var if LLAT ever needed |
| `GET /api/ha/start` instead of `POST` | Easier to test in browser | HA automations need extra YAML; HTTP caches may swallow idempotent calls | Acceptable only for internal debugging endpoints, not production |
| `zustand/persist` for selectedConfigId | Zero backend change needed | UI diverges from backend state after external stop (HA, CLI, restart) | Never — backend is the source of truth |
| mDNS as only WLED discovery method | "Zero config" UX | Fails in Docker bridge networks; ESP32 mDNS is unreliable | Never as the sole method; combine with manual IP entry |

---

## Integration Gotchas (v1.3)

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| WLED DRGB UDP | Send DRGB for all strips | Use DNRGB; it handles any length with identical overhead for strips ≤ 490 LEDs |
| WLED UDP timeout | Copy `timeout = 255` from examples | Use `timeout = 2` for ambient streaming; send explicit stop packet on stream end |
| WLED JSON API during streaming | Read device state while UDP loop is active | Cache device info at startup; suppress JSON API calls during active streaming |
| WLED mDNS discovery from Docker | Expect mDNS to work in bridge network | Require `network_mode: host`; offer manual IP as fallback |
| HA `rest_command` | Use GET endpoints for state mutations | Use POST; return JSON body; document example HA YAML |
| Entertainment config dropdown | Restore last selection from localStorage | Restore from `GET /api/capture/status` on mount; backend is authoritative |

---

## Performance Traps (v1.3)

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| One Konva `Rect` per LED, React-rendered | Browser CPU at 100%, UI freezes during live preview | Use single `Konva.Image` backed by offscreen canvas; write `ImageData` per frame | Immediately with ≥100 LEDs at 30+ Hz |
| UDP `socket.sendto()` called from `asyncio.to_thread()` for every packet | Thread pool exhaustion at 60 Hz with multiple WLED devices | Use `asyncio.DatagramTransport` (native async UDP); or create one thread per WLED device | At 3+ WLED devices at 60 Hz |
| WLED device list polled on every `/api/wled/devices` call | API latency spikes; WLED JSON API races with streaming | Cache device metadata; invalidate on explicit re-scan | On every page load with ≥2 WLED devices |
| DNRGB multi-packet send not atomic | Color tearing — first half of strip shows new color, second half shows previous frame | Pre-compute all packets for a frame, send in burst without yield; keep burst < 1ms | Any strip > 489 LEDs with visible color gradients |

---

## UX Pitfalls (v1.3)

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| LED range editor shows indices 0–299 | Users count LEDs as 1–300; they paint the wrong range | Display 1-based labels; store 0-based internally; unit-test the boundary |
| WLED device tab does not warn about JSON API conflict | User opens device tab while streaming and triggers the "stuck strip" bug | Disable the device configuration tab while any WLED device is actively streaming; show inline warning |
| Stop button leaves strip at last frame color | User thinks the strip is still "on" even after stopping | Send explicit black-out packet on stop; apply timeout = 2 so strip auto-clears |
| Entertainment config dropdown initializes to "None" on reload | User re-selects config every time they open the UI | Initialize dropdown from `/api/capture/status` on mount |
| Home Assistant automation silently does nothing if config_id is wrong | User sets up HA automation, it never starts streaming | Return `422` with a clear `{"error": "config_id not found"}` body from start endpoint |

---

## "Looks Done But Isn't" Checklist (v1.3)

- [ ] **WLED protocol:** Is DNRGB used (not DRGB)? Check packet byte 0: must be `0x04`, not `0x02`.
- [ ] **WLED timeout:** Is timeout byte set to 2 (not 0 or 255)? Verify by stopping streaming and confirming strip reverts to preset within 3 seconds.
- [ ] **Strip > 490 LEDs:** Does streaming a 500-LED strip send two packets per frame? Confirm with a network capture (`tcpdump -i any udp port 21324`).
- [ ] **JSON API conflict:** Does the WLED device tab suppress config calls while streaming? Open the tab during an active stream and verify no `GET /json` request fires.
- [ ] **Shared abstraction:** Does any WLED code import from `hue_client.py` or reference `channel_id` directly? Grep for this.
- [ ] **HA endpoints:** Are all state-mutating HA endpoints POST? Check with `curl -X GET /api/ha/start` — it must return 405.
- [ ] **Config dropdown on reload:** Reload the page while streaming. Does the dropdown show the correct active config? Does the start/stop button reflect actual backend state?
- [ ] **LED index convention:** Do the DNRGB packets produce the correct pixel output? Test: paint LEDs 1–10 (user-facing), confirm exactly LEDs 0–9 (zero-based) are lit, not 1–10.
- [ ] **Canvas performance:** Open the strip editor with 300 LEDs and enable live preview. Does browser CPU stay below 30%?

---

## Recovery Strategies (v1.3)

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| DRGB used instead of DNRGB, strips > 490 broken | LOW | Swap type byte from `0x02` to `0x04`; add 2-byte index; split packets; no DB change |
| Hue channel_id reused for WLED indices | HIGH | Add `wled_assignments` table; migrate existing WLED assignments; update `_load_channel_map()` |
| Konva per-LED Rect performance | MEDIUM | Refactor preview to `Konva.Image` + `ImageData`; existing assignment UI (static) unaffected |
| selectedConfigId in localStorage diverged | LOW | Remove `persist` middleware key; add `GET /api/capture/status` endpoint; update mount hook |
| Strip stuck in live mode after JSON API call | LOW | Cycle WLED device power or call `POST /json {"live": false}`; then fix the code path that caused the race |
| HA endpoint using GET method | LOW | Rename routes to POST; update HA YAML examples in docs; no DB change |

---

## Pitfall-to-Phase Mapping (v1.3)

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| DRGB 490 LED cap (W1) | WLED UDP sender implementation | Verify with 500-LED test: tcpdump shows 2 UDP packets per frame |
| UDP timeout wrong value (W2) | WLED UDP sender implementation | Stop streaming; strip reverts to preset within 3s |
| JSON API conflict during streaming (W3) | WLED device manager + streaming loop | Open device tab while streaming; no JSON API calls fired |
| mDNS discovery fails in Docker (W4) | WLED device management phase | Discovery scan from inside container finds devices; manual IP entry tested as fallback |
| Leaky Hue/WLED channel abstraction (W5) | Shared abstraction design — before any implementation | No WLED code references `channel_id` or `light_assignments` table |
| Paint-on-strip off-by-one (W6) | Paint-on-strip UI phase | Unit test: paint LEDs 1–300, verify 900 bytes of RGB data sent, LED 0 and LED 299 both receive data |
| Konva 300-Rect render thrash (W7) | Paint-on-strip UI phase | Live preview with 300 LEDs; browser CPU < 30% |
| HA GET vs POST (H1) | HA endpoints phase | `curl -X GET /api/ha/start` returns 405 |
| HA LLAT in DB (H2) | HA endpoints phase | Grep `database.py` for `ha_config` table or `token` column; neither must exist |
| Config dropdown stale on reload (P1) | Zone persistence bug fix phase | Reload while streaming; dropdown and button match backend state |
| Zustand persist for streaming state (P2) | Zone persistence bug fix phase | `localStorage.getItem('hpc-store')` does not contain `selectedConfigId` or `isStreaming` |

---

## Sources (v1.3)

- [WLED UDP Realtime documentation — kno.wled.ge](https://kno.wled.ge/interfaces/udp-realtime/) — DRGB/DNRGB packet format, 490 LED limit, timeout behavior; HIGH confidence
- [WLED UDP Realtime Control — GitHub Wiki](https://github.com/Aircoookie/WLED/wiki/UDP-Realtime-Control) — byte-level packet specification; HIGH confidence
- [WLED DDP documentation — kno.wled.ge](https://kno.wled.ge/interfaces/ddp/) — DDP port 4048, timecode note; HIGH confidence
- [WLED GitHub issue #3589 — JSON API stuck after UDP realtime](https://github.com/wled/WLED/issues/3589) — confirmed JSON API/UDP race condition; HIGH confidence (issue closed, marked fixed in master)
- [WLED GitHub issue #2356 — WLED times out despite live mode](https://github.com/wled-dev/WLED/issues/2356) — timeout behavior edge case; MEDIUM confidence
- [WLED GitHub issue #3770 — No mDNS from ESP32](https://github.com/Aircoookie/WLED/issues/3770) — ESP32-specific mDNS unreliability; MEDIUM confidence
- [WLED GitHub issue #1768 — Realtime brightness option](https://github.com/wled/WLED/issues/1768) — segment brightness during realtime mode; MEDIUM confidence
- [Konva.js performance tips — konvajs.org](https://konvajs.org/docs/performance/All_Performance_Tips.html) — layer caching, image nodes vs. shape nodes; HIGH confidence
- [FastAPI race conditions — datasciocean.com](https://datasciocean.com/en/other/fastapi-race-condition/) — shared mutable state in asyncio; MEDIUM confidence
- [Home Assistant REST API developer docs — developers.home-assistant.io](https://developers.home-assistant.io/docs/api/rest/) — authentication, endpoint format; HIGH confidence
- [Home Assistant RESTful Command integration](https://www.home-assistant.io/integrations/rest_command/) — POST method requirement for `rest_command`; HIGH confidence
- [Zustand persist discussion — pmndrs/zustand #1569](https://github.com/pmndrs/zustand/discussions/1569) — persist middleware behavior on reload; MEDIUM confidence
- Project codebase: `streaming_service.py` — `_config_id` private field not exposed via API; `useStatusStore.ts` — no `selectedConfigId` key; direct codebase analysis

---
*Pitfalls research for: WLED UDP streaming, HA control, LED strip UI, channel abstraction, zone persistence — HuePictureControl v1.3*
*Researched: 2026-04-14*
