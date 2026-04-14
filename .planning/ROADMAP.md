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
| 7. Device Enumeration and Camera Assignment Schema | v1.1 | 2/2 | Complete | 2026-04-03 |
| 8. Capture Registry | v1.1 | 2/2 | Complete | 2026-04-09 |
| 9. Preview Routing and Region API | v1.1 | 2/2 | Complete | 2026-04-07 |
| 10. Frontend Camera Selector | v1.1 | 3/3 | Complete | 2026-04-07 |
| 11. Docker Multi-Device Infrastructure | v1.1 | 1/1 | Complete | 2026-04-14 |
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
*v1.1 shipped: 2026-04-14*
