# Roadmap: HuePictureControl

## Milestones

- ✅ **v1.0 Full Ambient Lighting** — Phases 1-6 (shipped 2026-03-24)
- ✅ **v1.1 Multi-Camera Support** — Phases 7-11 (shipped 2026-04-14)
- 🚧 **v1.2 Wireless Input** — Phases 12-15 (planned)
- 📋 **v1.3 WLED Support, HA Control & Bug Fixes** — Phases 16-19 (planned)

## Phases

<details>
<summary>✅ v1.0 Full Ambient Lighting (Phases 1-6) — SHIPPED 2026-03-24</summary>

- [x] Phase 1: Infrastructure and DTLS Spike (4/4 plans) — completed 2026-03-24
- [x] Phase 2: Capture Pipeline and Color Extraction (2/2 plans) — completed 2026-03-24
- [x] Phase 3: Entertainment API Streaming Integration (3/3 plans) — completed 2026-03-24
- [x] Phase 3.1: Auto-Mapping from Entertainment Config (2/2 plans) — completed 2026-03-24
- [x] Phase 4: Frontend Canvas Editor (4/4 plans) — completed 2026-03-24
- [x] Phase 5: Gradient Device Support and Polish (2/2 plans) — completed 2026-03-24
- [x] Phase 6: Hardening and Deployment (TBD plans) — completed 2026-03-24

Full details: [v1.0 archive](milestones/v1.0-ROADMAP.md) (not yet archived)

</details>

<details>
<summary>✅ v1.1 Multi-Camera Support (Phases 7-11) — SHIPPED 2026-04-14</summary>

- [x] Phase 7: Device Enumeration and Camera Assignment Schema (2/2 plans) — completed 2026-04-03
- [x] Phase 8: Capture Registry (2/2 plans) — completed 2026-04-09
- [x] Phase 9: Preview Routing and Region API (2/2 plans) — completed 2026-04-07
- [x] Phase 10: Frontend Camera Selector (3/3 plans) — completed 2026-04-07
- [x] Phase 11: Docker Multi-Device Infrastructure (1/1 plan) — completed 2026-04-14

Full details: [v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md)

</details>

---

## v1.2 Wireless Input (Planned)

**Milestone Goal:** Enable any Windows or Android device to wirelessly mirror its screen to the system, replacing or supplementing the physical HDMI capture card as an input source.

- [x] **Phase 12: Virtual Device Infrastructure** - v4l2loopback management, FFmpeg pipeline manager with lifecycle safety, capabilities API, session list endpoint (completed 2026-04-16)
- [ ] **Phase 13: scrcpy Android Integration** - ADB WiFi connect, scrcpy --v4l2-sink pipeline, producer_ready gate, supervised watchdog, scrcpy API endpoints
- [ ] **Phase 14: Miracast Windows Integration** - NIC P2P detection, miraclecast daemon lifecycle, FFmpeg RTSP pipeline, Miracast API endpoints (hardware-gated)
- [ ] **Phase 15: Wireless Frontend Tab** - Dedicated wireless tab, scrcpy IP form, Miracast section, wireless sources in camera selector

## Phase Details (v1.2)

### Phase 12: Virtual Device Infrastructure
**Goal**: The backend can create and destroy v4l2loopback virtual camera devices on demand, manage FFmpeg subprocesses with safe lifecycle controls, report system wireless readiness, and list active sessions — ready to host any wireless input without changing downstream pipeline code.
**Depends on**: Phase 11 (v1.1 complete)
**Requirements**: VCAM-01, VCAM-02, VCAM-03, WPIP-01, WPIP-02, WPIP-03, WAPI-01, WAPI-04
**Success Criteria** (what must be TRUE):
  1. The backend creates a v4l2loopback virtual device at a static node (e.g. `/dev/video10`) on demand and the existing `V4L2Capture` can open it without modification
  2. Stopping a virtual session destroys the `/dev/videoN` node within 5 seconds; service shutdown destroys all virtual devices and kills all FFmpeg subprocesses cleanly
  3. An FFmpeg subprocess failure is detected within 3 seconds and triggers a supervised restart with exponential backoff
  4. `CaptureRegistry.acquire()` blocks until the FFmpeg producer has written its first frame into the virtual device (producer_ready gate prevents blank-frame acquisition)
  5. `GET /api/wireless/capabilities` returns NIC P2P support status, installed tool versions (ffmpeg, scrcpy, adb, iw), and a ready/not-ready assessment
  6. `GET /api/wireless/sessions` lists all active wireless sessions with source type and status
**Plans:** 3/3 plans complete
Plans:
- [x] 12-01-PLAN.md — Pydantic models and PipelineManager service with full subprocess lifecycle
- [x] 12-02-PLAN.md — Wireless router endpoints, main.py integration, and router tests
- [x] 12-03-PLAN.md — PipelineManager unit tests and conftest fixtures

---

### Phase 13: scrcpy Android Integration
**Goal**: An Android device connected to the same WiFi network can be mirrored to the system via ADB over WiFi and scrcpy, producing a virtual camera that feeds the existing capture-to-lights pipeline.
**Depends on**: Phase 12
**Requirements**: SCPY-01, SCPY-02, SCPY-03, SCPY-04, WAPI-03
**Success Criteria** (what must be TRUE):
  1. User POSTs an Android device IP; the backend connects via ADB WiFi and starts scrcpy with `--v4l2-sink`, producing a virtual V4L2 device in under 10 seconds
  2. `GET /api/cameras` includes the scrcpy virtual device tagged as a wireless source, selectable in any entertainment zone
  3. Assigning the scrcpy virtual camera to an entertainment zone drives Hue lights from the mirrored Android screen — same latency as physical capture
  4. A brief WiFi interruption (device momentarily unreachable) triggers auto-reconnect; streaming resumes without user intervention
  5. DELETE to stop a scrcpy session disconnects ADB, kills the scrcpy process, and removes the virtual device node
**Plans:** 1/3 plans executed
Plans:
- [x] 13-01-PLAN.md — PipelineManager ADB lifecycle, stale-frame monitor, restart fix, and model updates
- [ ] 13-02-PLAN.md — Scrcpy REST endpoints, wireless camera tagging, and router tests
- [ ] 13-03-PLAN.md — PipelineManager unit tests for ADB, stale-frame, restart, and stop

---

### Phase 14: Miracast Windows Integration
**Goal**: A Windows PC on the same network can project its screen to the system via Miracast (WiFi Direct), and the mirrored display becomes a virtual camera consumable by the lighting pipeline. Gated on NIC P2P capability.
**Depends on**: Phase 12
**Requirements**: MIRA-01, MIRA-02, MIRA-03, MIRA-04, WAPI-02
**Success Criteria** (what must be TRUE):
  1. `GET /api/wireless/capabilities` correctly reports whether the host NIC supports WiFi Direct P2P mode (parsed from `iw list`)
  2. When the Miracast receiver is active, a Windows PC on the same network sees the system as a Cast target in the Win+K project menu
  3. Connecting from Windows delivers a live video stream that appears as a virtual V4L2 device readable by the existing capture pipeline
  4. Assigning the Miracast virtual camera to an entertainment zone drives Hue lights from the wirelessly mirrored Windows screen
  5. Disconnecting the Windows client automatically tears down the FFmpeg pipeline and destroys the virtual device node
**Plans**: TBD

---

### Phase 15: Wireless Frontend Tab
**Goal**: The web UI has a dedicated wireless tab where users can see NIC status, start and stop wireless sessions, and wireless sources appear in the camera selector alongside physical devices.
**Depends on**: Phase 13, Phase 14
**Requirements**: WFNT-01, WFNT-02, WFNT-03, WFNT-04
**Success Criteria** (what must be TRUE):
  1. A "Wireless" tab is present in the navigation; it shows NIC P2P capability status and lists all active wireless sessions with their source type
  2. The scrcpy section has an IP address input field and Connect/Disconnect buttons; submitting starts a session and the tab shows the live session status
  3. The Miracast section shows P2P availability; the Start/Stop receiver buttons are disabled with an explanatory message when the NIC lacks P2P support
  4. Virtual cameras from active wireless sessions appear in the per-zone camera selector dropdown alongside physical USB cameras, indistinguishable to the rest of the pipeline
**Plans**: TBD
**UI hint**: yes

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
| 7. Device Enumeration and Camera Assignment Schema | v1.1 | 2/2 | Complete | 2026-04-03 |
| 8. Capture Registry | v1.1 | 2/2 | Complete | 2026-04-09 |
| 9. Preview Routing and Region API | v1.1 | 2/2 | Complete | 2026-04-07 |
| 10. Frontend Camera Selector | v1.1 | 3/3 | Complete | 2026-04-07 |
| 11. Docker Multi-Device Infrastructure | v1.1 | 1/1 | Complete | 2026-04-14 |
| 12. Virtual Device Infrastructure | v1.2 | 3/3 | Complete   | 2026-04-16 |
| 13. scrcpy Android Integration | v1.2 | 1/3 | In Progress|  |
| 14. Miracast Windows Integration | v1.2 | 0/TBD | Not started | - |
| 15. Wireless Frontend Tab | v1.2 | 0/TBD | Not started | - |
| 16. Zone Persistence Bug Fixes | v1.3 | 0/TBD | Not started | - |
| 17. WLED Backend and Streaming | v1.3 | 0/TBD | Not started | - |
| 18. Home Assistant Control Endpoints | v1.3 | 0/TBD | Not started | - |
| 19. WLED Strip Paint UI | v1.3 | 0/TBD | Not started | - |

---
*Roadmap created: 2026-03-23*
*v1.1 shipped: 2026-04-14*
*v1.2 roadmap updated: 2026-04-14 (research-informed, Docker dropped, native Linux)*
