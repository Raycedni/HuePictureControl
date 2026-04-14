# Roadmap: HuePictureControl

## Milestones

- **v1.0 Full Ambient Lighting** - Phases 1-6 (completed 2026-03-24)
- **v1.1 Multi-Camera Support** - Phases 7-11 (in progress)
- **v1.2 Wireless Input** - Phases 12-15 (planned)
- **v1.3 WLED Support, HA Control & Bug Fixes** - Phases 16-19 (planned)

## Phases

<details>
<summary>v1.0 Full Ambient Lighting (Phases 1-6) - COMPLETED 2026-03-24</summary>

- [x] **Phase 1: Infrastructure and DTLS Spike** - Prove DTLS transport works; establish Docker environment and bridge pairing (completed 2026-03-24)
- [x] **Phase 2: Capture Pipeline and Color Extraction** - Capture frames from USB capture card and extract per-region colors (completed 2026-03-24)
- [x] **Phase 3: Entertainment API Streaming Integration** - Wire capture output into DTLS stream; deliver first end-to-end color sync (completed 2026-03-24)
- [x] **Phase 3.1: Auto-Mapping from Entertainment Config** - Auto-generate screen regions from channel positions (INSERTED) (completed 2026-03-24)
- [x] **Phase 4: Frontend Canvas Editor** - Interactive polygon region editor with live preview and light assignment (completed 2026-03-24)
- [x] **Phase 5: Gradient Device Support and Polish** - Per-segment control of Festavia, Flux, and Play Gradient devices (completed 2026-03-24)
- [x] **Phase 6: Hardening and Deployment** - Production-quality Docker deployment with nginx, health checks, and error recovery (completed 2026-03-24)

### Phase 1: Infrastructure and DTLS Spike
**Goal**: Prove the DTLS transport layer works against the physical Hue Bridge and establish the Docker environment that everything else builds on.
**Depends on**: Nothing (first phase)
**Requirements**: BRDG-01, BRDG-02, BRDG-03, BRDG-05, UI-02, INFR-01, INFR-02, INFR-03, INFR-05

**Success Criteria** (what must be TRUE):
  1. User can press the bridge link button, click "Pair" in the UI, and see "Paired" status without restarting the container
  2. Bridge credentials survive a `docker compose restart` and the app reconnects without re-pairing
  3. The UI lists all entertainment configurations discovered from the paired bridge
  4. A developer can run a CLI spike script that opens a DTLS session and changes a real light's color, with no code changes required to the bridge or network
  5. Docker Compose starts both containers cleanly with `docker compose up`; backend is reachable at `/api/health`

**Plans**: 4 plans

Plans:
- [x] 01-01-PLAN.md — Docker Compose + FastAPI skeleton + SQLite schema + test scaffold
- [x] 01-02-PLAN.md — Bridge pairing, credential persistence, entertainment config/light discovery
- [x] 01-03-PLAN.md — Frontend React skeleton + PairingFlow UI + nginx reverse proxy
- [x] 01-04-PLAN.md — DTLS spike CLI script + physical hardware verification (Phase 1 gate)

---

### Phase 2: Capture Pipeline and Color Extraction
**Goal**: Capture live frames from the USB HDMI capture card and extract average colors from configurable polygon regions, testable without the Hue Bridge.
**Depends on**: Phase 1
**Requirements**: CAPT-01, CAPT-02, CAPT-05

**Success Criteria** (what must be TRUE):
  1. `GET /api/capture/snapshot` returns a valid JPEG from the physical capture card within 200ms
  2. Configuring a different device path (e.g. `/dev/video1`) takes effect without restarting the container
  3. A debug log or endpoint shows the extracted CIE xy color value for at least one hard-coded test region, confirming the color math is running

**Plans**: 2 plans

Plans:
- [x] 02-01-PLAN.md — Capture service + color math module with TDD tests
- [x] 02-02-PLAN.md — Capture REST endpoints + lifespan wiring + hardware verification

---

### Phase 3: Entertainment API Streaming Integration
**Goal**: Connect the capture pipeline output to the DTLS streaming session and deliver measurable end-to-end color synchronization under 100ms.
**Depends on**: Phase 1, Phase 2
**Requirements**: CAPT-03, CAPT-04, STRM-01, STRM-02, STRM-03, STRM-04, STRM-05, STRM-06, GRAD-05

**Success Criteria** (what must be TRUE):
  1. Pressing "Start" in the UI causes real Hue lights to update color within 100ms of the capture card frame (measurable via `/ws/status` latency field)
  2. Pressing "Stop" causes lights to return to their pre-streaming state and the capture card device is fully released (re-openable immediately)
  3. A single UDP packet per frame drives all configured channels simultaneously at 25-50 Hz
  4. `/ws/status` shows FPS in the 25-50 range and latency under 100ms during normal operation
  5. The system supports a configuration with 16 channels without packet fragmentation or missed updates

**Plans**: 3 plans

Plans:
- [x] 03-01-PLAN.md — StatusBroadcaster service + hue_client activate/deactivate helpers
- [x] 03-02-PLAN.md — StreamingService core with frame loop, lifecycle, and reconnect (TDD)
- [x] 03-03-PLAN.md — REST/WebSocket endpoints + lifespan wiring + hardware verification

---

### Phase 3.1: Auto-Mapping from Entertainment Config (INSERTED)
**Goal**: Automatically generate screen sampling regions from entertainment configuration channel positions, delivering a fully functional end-to-end system without manual polygon drawing.
**Depends on**: Phase 3
**Requirements**: REGN-04, REGN-05

**Success Criteria** (what must be TRUE):
  1. Selecting an entertainment config auto-generates region polygons based on channel positions without manual drawing
  2. Auto-generated regions persist in SQLite and survive container restart
  3. Starting streaming with auto-mapped regions causes real lights to display colors matching their assigned screen area
  4. A simple preview page shows the camera feed with auto-generated region overlays

**Plans**: 2 plans

Plans:
- [x] 03.1-01-PLAN.md — Auto-mapping service + hue_client extension + regions router with TDD tests
- [x] 03.1-02-PLAN.md — Frontend preview page with region overlays + hardware verification

---

### Phase 4: Frontend Canvas Editor
**Goal**: Deliver a fully interactive web UI where users can draw polygon regions on a live camera preview and assign each region to a Hue light or gradient segment.
**Depends on**: Phase 1, Phase 3, Phase 3.1
**Requirements**: REGN-01, REGN-02, REGN-03, REGN-04, REGN-05, REGN-06, UI-01, UI-03, UI-04, UI-05, UI-06

**Success Criteria** (what must be TRUE):
  1. User can draw a freeform polygon on the canvas, assign it to a light, and see the light's color update in real time without any page reload
  2. The camera preview updates live at >=10 fps in the browser while streaming is active
  3. Region shapes and light assignments survive a full `docker compose restart`
  4. The status bar shows current FPS, latency, and bridge connection state updated at least once per second
  5. The light panel lists all lights discovered from the bridge with correct names, types, and segment counts

**Plans**: 4 plans

Plans:
- [x] 04-01-PLAN.md — Backend region CRUD + /ws/preview WebSocket endpoint
- [x] 04-02-PLAN.md — Frontend deps (Konva, Zustand, Tailwind, shadcn) + stores + hooks + StatusBar + 3-tab layout
- [x] 04-03-PLAN.md — EditorPage + Konva canvas + drawing tools + vertex editing + live preview
- [x] 04-04-PLAN.md — LightPanel + drag-to-assign + streaming control + hardware verification

---

### Phase 5: Gradient Device Support and Polish
**Goal**: Deliver full per-segment independent control of gradient-capable devices (Festavia, Flux, Play Gradient Lightstrip) and enforce the 20-channel limit.
**Depends on**: Phase 3, Phase 4
**Requirements**: BRDG-04, GRAD-01, GRAD-02, GRAD-03, GRAD-04

**Success Criteria** (what must be TRUE):
  1. Each segment of a Festavia or Flux strip can be independently assigned to a different screen region and shows a distinct color matching that region
  2. Assigning more than 20 total channels displays a visible warning in the UI identifying which configuration exceeds the limit
  3. The gradient device's segment count shown in the light panel matches the actual channel count observed in the entertainment configuration
  4. Unplugging and replugging the capture card causes the capture loop to reconnect automatically without manual intervention

**Plans**: 2 plans

Plans:
- [x] 05-01-PLAN.md — Backend gradient detection, channel-to-light mapping endpoint, capture reconnect
- [x] 05-02-PLAN.md — Frontend per-segment LightPanel, channel counter, warning banner, hardware verification

---

### Phase 6: Hardening and Deployment
**Goal**: Produce a production-quality Docker deployment that a user can install with a single `docker compose up` and rely on for daily use.
**Depends on**: Phase 5
**Requirements**: INFR-04

**Success Criteria** (what must be TRUE):
  1. `docker compose up -d` on a clean machine with the capture card plugged in results in a fully functional system reachable at `http://localhost` within 60 seconds
  2. `GET /health/ready` returns HTTP 200 only when the bridge is paired and the capture device is accessible
  3. A container restart triggered by `docker compose restart` recovers to operational state automatically without user intervention
  4. The Docker image builds successfully from scratch in under 5 minutes on a standard developer machine

**Plans**: TBD

</details>

---

## v1.1 Multi-Camera Support (In Progress)

**Milestone Goal:** Replace the single static camera with a per-entertainment-zone camera selector, enabling each zone to independently use a different video capture device.

- [x] **Phase 7: Device Enumeration and Camera Assignment Schema** - Enumerate all V4L2 capture devices and persist camera-to-zone assignments in the database (completed 2026-04-03)
- [x] **Phase 8: Capture Registry** - Replace the global CaptureBackend singleton with a per-device registry that supports concurrent multi-zone capture (completed 2026-04-09)
- [x] **Phase 9: Preview Routing and Region API** - Route preview WebSocket to the zone's assigned camera; expose camera_device in region CRUD (completed 2026-04-07)
- [x] **Phase 10: Frontend Camera Selector** - Per-zone camera dropdown in the editor UI with live preview switching (completed 2026-04-07)
- [x] **Phase 11: Docker Multi-Device Infrastructure** - Docker Compose configuration and documentation for multiple video device passthrough (completed 2026-04-14)

## Phase Details

### Phase 7: Device Enumeration and Camera Assignment Schema
**Goal**: Users can query all available video capture devices from the backend API, and the system can persist a camera assignment per entertainment zone in the database — the foundation all subsequent multi-camera work depends on.
**Depends on**: Phase 6 (v1.0 complete)
**Requirements**: DEVC-01, DEVC-02, DEVC-03, DEVC-04, DEVC-05, CAMA-01, CAMA-02, CAMA-03
**Success Criteria** (what must be TRUE):
  1. `GET /api/cameras` returns a list of only capture-capable video devices (metadata nodes excluded) with each device's path and human-readable name
  2. Re-calling `GET /api/cameras` after plugging in a second capture card returns the updated device list without restarting the backend
  3. User can trigger a manual reconnect for a camera device that has become disconnected
  4. Camera selection persists to the database per entertainment zone and survives a `docker compose restart`
  5. Zones with no explicit camera assignment fall back to the default capture device without error
**Plans**: 2 plans

Plans:
- [x] 07-01-PLAN.md — Device enumeration service, stable identity module, DB schema + tests
- [x] 07-02-PLAN.md — Cameras REST router, main.py wiring, frontend sysfs alert banner

---

### Phase 8: Capture Registry
**Goal**: The backend manages a pool of independent CaptureBackend instances keyed by device path, so multiple zones can capture from different cameras concurrently without race conditions or event loop blocking.
**Depends on**: Phase 7
**Requirements**: MCAP-01, MCAP-03
**Success Criteria** (what must be TRUE):
  1. Starting streaming on two entertainment zones that use different camera devices causes both capture backends to open and stream simultaneously without errors
  2. Stopping streaming fully releases all device handles so each camera can be opened by another process immediately after
  3. Switching a zone's camera assignment mid-stream (stop → reassign → start) opens the new device and closes the old one without restarting the backend
**Plans**: 2 plans

Plans:
- [x] 08-01-PLAN.md - CaptureRegistry class with ref-counted acquire/release/shutdown
- [x] 08-02-PLAN.md - StreamingService registry integration + lifespan wiring + router backward compat

---

### Phase 9: Preview Routing and Region API
**Goal**: The live preview WebSocket serves frames from the zone's assigned camera, and the regions API exposes camera_device as a read-only derived field.
**Depends on**: Phase 8
**Requirements**: MCAP-02, CAMA-04
**Success Criteria** (what must be TRUE):
  1. Opening the preview WebSocket with `?device=/dev/video1` streams frames from that specific device, not the default device
  2. The camera health status (connected/disconnected) for each entertainment zone is visible without starting streaming
  3. `GET /api/regions` returns the `camera_device` field for each region; `PUT /api/regions/{id}` accepts and persists a `camera_device` update
**Plans**: 2 plans

Plans:
- [x] 09-01-PLAN.md — CaptureRegistry.get() peek method + preview WebSocket ?device= routing
- [x] 09-02-PLAN.md — DB migration + cameras zone_health + regions camera_device join + frontend types

---

### Phase 10: Frontend Camera Selector
**Goal**: Users can select a camera per entertainment zone from a dropdown in the editor UI, and the live preview immediately updates to show the selected camera's feed.
**Depends on**: Phase 9
**Requirements**: CMUI-01, CMUI-02, CMUI-03
**Success Criteria** (what must be TRUE):
  1. The editor UI shows a camera dropdown for each entertainment zone populated with device name and path for every available camera
  2. Selecting a different camera in the dropdown updates the live preview within 2 seconds without a page reload
  3. The selected camera assignment is saved and the correct camera is shown pre-selected when the user reopens the editor after a restart
**Plans**: 3 plans

- [x] 10-00-PLAN.md — Wave 0 test scaffolds (cameras.test.ts, LightPanel.test.tsx)
Plans:
- [x] 10-01-PLAN.md — Camera API types, fetch wrappers, useCameras hook, usePreviewWS test fix
- [x] 10-02-PLAN.md — EditorPage state lift, LightPanel zone+camera dropdowns, EditorCanvas device wiring
**UI hint**: yes

---

### Phase 11: Docker Multi-Device Infrastructure
**Goal**: The Docker Compose configuration passes multiple video capture devices into the backend container, and documentation explains how to add or configure additional capture cards.
**Depends on**: Phase 8
**Requirements**: DOCK-01, DOCK-02
**Success Criteria** (what must be TRUE):
  1. Running `ls /dev/video*` inside the backend container shows all physically connected capture cards (not just the first one)
  2. `docker compose up` with two capture cards plugged in results in both devices accessible to the backend without manual container changes
  3. Documentation (inline comments or README) explains how to add a second capture device to the Compose configuration
**Plans**: 1 plan

Plans:
- [x] 11-01-PLAN.md -- Docker Compose cgroup rules + SETUP.md multi-device documentation

---

---

## v1.2 Wireless Input (Planned)

**Milestone Goal:** Enable any Windows or Android device to wirelessly mirror its screen to the system, replacing or supplementing the physical HDMI capture card as an input source.

- [ ] **Phase 12: Virtual Camera & Pipeline Infrastructure** - v4l2loopback management, FFmpeg pipeline manager, wireless API skeleton, virtual device integration with camera system
- [ ] **Phase 13: Miracast Receiver Integration** - MiracleCast WiFi Direct sink, NIC capability detection, Miracast → FFmpeg → v4l2loopback pipeline
- [ ] **Phase 14: scrcpy Android Fallback & Wireless UI** - ADB wireless management, scrcpy → v4l2loopback pipeline, frontend wireless source controls
- [ ] **Phase 15: Wireless Docker & Polish** - Docker image with wireless dependencies, container capabilities, WiFi adapter passthrough, documentation

## Phase Details (v1.2)

### Phase 12: Virtual Camera & Pipeline Infrastructure
**Goal**: The backend can create and destroy v4l2loopback virtual camera devices on demand and manage FFmpeg subprocesses that pipe arbitrary input streams into them. Virtual cameras appear in the existing camera API alongside physical devices.
**Depends on**: Phase 11 (v1.1 Docker multi-device complete)
**Requirements**: VCAM-01, VCAM-02, VCAM-03, WPIP-01, WPIP-02, WPIP-03, WAPI-01, WAPI-04
**Success Criteria** (what must be TRUE):
  1. Starting a wireless source creates a virtual V4L2 device (e.g. `/dev/video10`) that is readable by the existing `V4L2Capture` backend
  2. `GET /api/cameras` returns virtual devices alongside physical ones, each tagged with `source_type: "wireless"`
  3. Stopping a wireless source kills the FFmpeg pipeline and removes the virtual device within 5 seconds
  4. `GET /api/wireless/capabilities` reports installed dependency versions and system readiness
  5. Service shutdown cleanly destroys all virtual devices and kills all FFmpeg subprocesses
**Plans**: TBD

---

### Phase 13: Miracast Receiver Integration
**Goal**: Windows PCs and older Android devices can discover and connect to the system via Miracast (WiFi Direct), and the mirrored display feeds into the existing capture pipeline as a virtual camera.
**Depends on**: Phase 12
**Requirements**: MIRA-01, MIRA-02, MIRA-03, MIRA-04, WAPI-02
**Success Criteria** (what must be TRUE):
  1. A Windows PC on the same network sees "HuePictureControl" (or configured name) in its Cast/Project menu (Win+K)
  2. Connecting from Windows delivers a live video stream that appears as a virtual V4L2 device consumable by the streaming pipeline
  3. `GET /api/wireless/capabilities` correctly reports whether the WiFi adapter supports P2P/WiFi Direct mode
  4. Starting streaming with the Miracast virtual camera assigned to an entertainment zone drives Hue lights from the wirelessly mirrored content
  5. Disconnecting the Miracast client cleans up the FFmpeg pipeline and virtual device automatically
**Plans**: TBD

---

### Phase 14: scrcpy Android Fallback & Wireless UI
**Goal**: Newer Android devices that lack Miracast can mirror their screen via scrcpy over WiFi, and the frontend provides controls to start/stop all wireless input sources.
**Depends on**: Phase 12
**Requirements**: SCPY-01, SCPY-02, SCPY-03, WAPI-03, WFNT-01, WFNT-02
**Success Criteria** (what must be TRUE):
  1. User provides an Android device IP via the API; the backend connects via ADB and starts scrcpy, producing a virtual V4L2 device
  2. The mirrored Android screen drives Hue lights when assigned to an entertainment zone — same pipeline as physical capture
  3. The frontend camera selector shows wireless sources alongside physical cameras
  4. The frontend provides start/stop controls for Miracast and scrcpy sessions
  5. Stopping a scrcpy session disconnects ADB and cleans up the virtual device
**Plans**: TBD
**UI hint**: yes

---

### Phase 15: Wireless Docker & Polish
**Goal**: The Docker Compose configuration includes all wireless dependencies and capabilities so wireless input works out of the box with `docker compose up`.
**Depends on**: Phase 13, Phase 14
**Requirements**: WDCK-01, WDCK-02, WDCK-03
**Success Criteria** (what must be TRUE):
  1. The Docker image builds successfully with MiracleCast, scrcpy, FFmpeg, ADB, v4l2loopback-dkms, and `iw` installed
  2. The container starts with `NET_ADMIN` and `SYS_MODULE` capabilities and can load the v4l2loopback kernel module
  3. A USB WiFi adapter passed through to the container is usable for WiFi Direct / Miracast receiving
  4. Documentation explains WiFi adapter requirements, NIC compatibility, and how to verify P2P support
**Plans**: TBD

---

---

## v1.3 WLED Support, HA Control & Bug Fixes (Planned)

**Milestone Goal:** Expand the system beyond Hue to support WLED ESP32 LED strips via UDP realtime streaming, add Home Assistant control endpoints, and fix the entertainment zone persistence bug.

- [ ] **Phase 16: Zone Persistence Bug Fixes** - Fix entertainment config selection persisting across reloads and dropdown reflecting actual streaming state
- [ ] **Phase 17: WLED Backend and Streaming** - WLED device management API, UDP streaming service (DRGB/DNRGB), StreamingCoordinator for concurrent Hue+WLED output
- [ ] **Phase 18: Home Assistant Control Endpoints** - REST endpoints for HA to start/stop streaming, select camera, select zone, and query status
- [ ] **Phase 19: WLED Strip Paint UI** - Visual strip painter for defining LED channel ranges, channel assignment via existing drag-drop workflow

## Phase Details (v1.3)

### Phase 16: Zone Persistence Bug Fixes
**Goal**: The entertainment config selection persists correctly per camera across page reloads, and the dropdown accurately reflects the actual streaming state when the page loads.
**Depends on**: Phase 15 (v1.2 complete)
**Requirements**: BFIX-01, BFIX-02
**Success Criteria** (what must be TRUE):
  1. After selecting an entertainment config and reloading the page, the same config is pre-selected in the dropdown without manual re-selection
  2. If streaming was active when the page was opened in another tab, the dropdown on the new tab shows the streaming state correctly rather than a default/idle state
  3. Selecting different entertainment configs for different cameras persists independently — switching cameras shows the config last used with that camera
**Plans**: TBD

---

### Phase 17: WLED Backend and Streaming
**Goal**: The backend can register WLED devices, persist their configuration, and stream color data to them concurrently with Hue at up to 60 Hz via UDP, with automatic DRGB/DNRGB protocol selection based on LED count.
**Depends on**: Phase 16
**Requirements**: WLED-01, WLED-02, WLED-03, WLED-04, WLED-05, WSTR-01, WSTR-02, WSTR-03, WSTR-04
**Success Criteria** (what must be TRUE):
  1. User can add a WLED device by IP, see its name and LED count fetched from the device, and remove it — all changes persist across restarts
  2. A WLED device can be enabled or disabled without being removed; disabled devices receive no UDP packets
  3. With a WLED device enabled and channels assigned to regions, the LED strip updates color in sync with the captured frame at 50-60 Hz
  4. Strips with more than 490 LEDs automatically use DNRGB chunked packets; strips with 490 or fewer use DRGB — no user configuration required
  5. When streaming stops, the UDP timeout byte causes the strip to release the last color within the configured timeout rather than staying frozen
  6. Hue and WLED devices stream simultaneously from the same captured frame without interference or frame-rate degradation
**Plans**: TBD

---

### Phase 18: Home Assistant Control Endpoints
**Goal**: Home Assistant can start and stop streaming, select the active camera and entertainment zone, and query current streaming status via REST endpoints — without requiring access to the web UI.
**Depends on**: Phase 17
**Requirements**: HASS-01, HASS-02, HASS-03, HASS-04, HASS-05
**Success Criteria** (what must be TRUE):
  1. `POST /api/ha/start` starts streaming from HA with the currently configured zone and camera; `POST /api/ha/stop` stops it cleanly
  2. `GET /api/ha/status` returns current streaming state, active zone, and active camera in a machine-readable format
  3. HA can select a specific camera via REST and a subsequent start uses that camera
  4. HA can select a specific entertainment zone via REST and a subsequent start activates that zone
  5. All HA endpoints are unauthenticated and accessible from within the local network, consistent with the rest of the API
**Plans**: TBD

---

### Phase 19: WLED Strip Paint UI
**Goal**: Users can visually paint LED channel ranges directly onto a strip representation in the UI, and the resulting channels appear in the light panel for assignment to canvas regions via the same drag-drop workflow used for Hue segments.
**Depends on**: Phase 17
**Requirements**: WMAP-01, WMAP-02, WMAP-03, WMAP-04, WMAP-05
**Success Criteria** (what must be TRUE):
  1. The WLED tab shows a visual horizontal strip for each device; user can click and drag to paint a named channel range onto the strip
  2. Each painted channel appears in the light panel dropdown with a distinct color, assignable to canvas regions by drag-and-drop — identical workflow to Hue gradient segments
  3. Adjacent channel zones are visually separated by color and the boundary handle can be dragged to resize them
  4. Painted channel assignments persist across restarts; reopening the editor shows the same strip layout and region assignments
  5. Removing a painted channel unassigns it from any regions it was linked to and updates the canvas immediately
**Plans**: TBD
**UI hint**: yes

---

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Infrastructure and DTLS Spike | v1.0 | 4/4 | Complete | 2026-03-24 |
| 2. Capture Pipeline and Color Extraction | v1.0 | 2/2 | Complete | 2026-03-24 |
| 3. Entertainment API Streaming Integration | v1.0 | 3/3 | Complete | 2026-03-24 |
| 3.1 Auto-Mapping from Entertainment Config | v1.0 | 2/2 | Complete | 2026-03-24 |
| 4. Frontend Canvas Editor | v1.0 | 4/4 | Complete | 2026-03-24 |
| 5. Gradient Device Support and Polish | v1.0 | 2/2 | Complete | 2026-03-24 |
| 6. Hardening and Deployment | v1.0 | TBD | Complete | 2026-03-24 |
| 7. Device Enumeration and Camera Assignment Schema | v1.1 | 2/2 | Complete   | 2026-04-03 |
| 8. Capture Registry | v1.1 | 2/2 | Complete   | 2026-04-09 |
| 9. Preview Routing and Region API | v1.1 | 2/2 | Complete   | 2026-04-07 |
| 10. Frontend Camera Selector | v1.1 | 3/3 | Complete    | 2026-04-07 |
| 11. Docker Multi-Device Infrastructure | v1.1 | 1/1 | Complete    | 2026-04-14 |
| 12. Virtual Camera & Pipeline Infrastructure | v1.2 | 0/TBD | Not started | - |
| 13. Miracast Receiver Integration | v1.2 | 0/TBD | Not started | - |
| 14. scrcpy Android Fallback & Wireless UI | v1.2 | 0/TBD | Not started | - |
| 15. Wireless Docker & Polish | v1.2 | 0/TBD | Not started | - |
| 16. Zone Persistence Bug Fixes | v1.3 | 0/TBD | Not started | - |
| 17. WLED Backend and Streaming | v1.3 | 0/TBD | Not started | - |
| 18. Home Assistant Control Endpoints | v1.3 | 0/TBD | Not started | - |
| 19. WLED Strip Paint UI | v1.3 | 0/TBD | Not started | - |

---
*Roadmap created: 2026-03-23*
*v1.1 phases added: 2026-04-03*
*v1.2 phases added: 2026-04-03*
*v1.3 phases added: 2026-04-14*
