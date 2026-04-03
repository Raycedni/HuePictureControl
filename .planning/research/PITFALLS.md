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
