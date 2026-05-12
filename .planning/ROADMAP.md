# Roadmap: HuePictureControl

## Milestones

- ✅ **v1.0 Full Ambient Lighting** — Phases 1-6 (shipped 2026-03-24)
- ✅ **v1.1 Multi-Camera Support** — Phases 7-11 (shipped 2026-04-14)
- 🚧 **v1.2 Wireless Input** — Phases 12-15 (planned)
- ✅ **v1.3 (WLED + HA Control)** — Phases 16-18 (shipped 2026-05-12)
- 📋 **v1.3 Home Assistant Integration Polish** — Phases 19-22 (planned)
- 🗂️ **Deferred / Unscheduled** — WLED Strip Paint UI (WMAP-01..05) — formerly Phase 19, now unscheduled pending re-planning

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

## v1.3 WLED Support, HA Control & Bug Fixes (Shipped)

**Milestone Goal:** Expand the system beyond Hue to support WLED ESP32 LED strips via UDP realtime streaming, add Home Assistant control endpoints, and fix the entertainment zone persistence bug.

- [x] **Phase 16: Zone Persistence Bug Fixes** (3/3 plans) — completed 2026-04-20 — Fix entertainment config selection persisting across reloads and dropdown reflecting actual streaming state
- [x] **Phase 17: WLED Backend and Streaming** - WLED device management API, UDP streaming service (DRGB/DNRGB), StreamingCoordinator for concurrent Hue+WLED output (completed 2026-04-27)
- [x] **Phase 18: Home Assistant Control Endpoints** (3/3 plans) — completed 2026-05-12 — REST endpoints for HA to start/stop streaming, select camera, select zone, and query status

## Phase Details (v1.3 shipped)

### Phase 16: Zone Persistence Bug Fixes
**Goal**: The entertainment config selection persists correctly per camera across page reloads, and the dropdown accurately reflects the actual streaming state when the page loads.
**Depends on**: Phase 15 (v1.2 complete)
**Requirements**: BFIX-01, BFIX-02
**Success Criteria** (what must be TRUE):
  1. After selecting an entertainment config and reloading the page, the same config is pre-selected in the dropdown without manual re-selection
  2. If streaming was active when the page was opened in another tab, the dropdown on the new tab shows the streaming state correctly rather than a default/idle state
  3. Selecting different entertainment configs for different cameras persists independently — switching cameras shows the config last used with that camera
**Plans**: 3 plans (3/3 complete — shipped 2026-04-20)
  - [x] 16-01-PLAN.md — Backend DB schema + PUT /api/cameras/last-zone endpoint + GET last_entertainment_config_id field
  - [x] 16-02-PLAN.md — StatusBroadcaster + StreamingService active_config_id/active_device_path wiring
  - [x] 16-03-PLAN.md — Frontend API, Zustand store, WS parser, LightPanel 3-tier initial selection + auto-save on zone change

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
**Plans**: 9 plans
  - [x] 17-01-PLAN.md — Wave 0 fixtures: zeroconf dep + udp_listener + mock_capture
  - [x] 17-02-PLAN.md — DB schema (3 WLED tables) + sub_sample_gradient helper
  - [x] 17-03-PLAN.md — WLED packet builders (DRGB/DNRGB) + wled_client + wled_discovery (TDD)
  - [x] 17-04-PLAN.md — WledStreamer class (lifecycle, per-device lock, cooldown, blackout)
  - [x] 17-05-PLAN.md — StreamingCoordinator extraction + HueStreamer refactor (behavior-preserving)
  - [x] 17-06-PLAN.md — Coordinator↔WLED integration + StatusBroadcaster wled_devices + app.state rewire
  - [x] 17-07-PLAN.md — routers/wled.py CRUD + scan endpoints (with IP regex, cascade delete)
  - [x] 17-08-PLAN.md — Frontend: api/wled + Settings panel + WledDevicesPanel + store/WS extensions
  - [x] 17-09-PLAN.md — E2E integration test + preflight + manual verification checkpoint

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
**Plans**: 3 plans
  - [x] 18-01-PLAN.md — Wave 1 foundation: ha_state table DDL + StreamingCoordinator.start device_path_override (Option C) — completed 2026-05-11
  - [x] 18-02-PLAN.md — Wave 2 router: routers/ha.py with all 7 endpoints (POST start/stop, GET status/zones/cameras, PUT zone/camera) + main.py wiring
  - [x] 18-03-PLAN.md — Wave 3 tests: test_ha_router.py (23 unit tests) + test_ha_e2e.py (full PUT/POST/GET cross-cut) + VALIDATION.md map update

---

---

## v1.3 Home Assistant Integration Polish (Planned)

**Milestone Goal:** Make HuePictureControl a first-class Home Assistant citizen — zero-YAML setup for new users (MQTT auto-discovery) plus a documented YAML fallback. Builds on the unauthenticated REST endpoints shipped in Phase 18.

**Build order (research-mandated, risk-ascending):** YAML docs → WLED health flattening → MQTT discovery (read-only) → MQTT command consumer.

- [ ] **Phase 19: HA YAML Documentation** - Ship `docs/HOME_ASSISTANT.md` with ready-to-paste `rest_command:`, REST `sensor:`, and `input_select:` snippets for the non-MQTT path; explicit warning against mixing MQTT and YAML
- [ ] **Phase 20: WLED Health Flattening in /api/ha/status** - Additive `wled_devices` array on `HaStatusResponse` (per-device `{name, connected, last_error, in_cooldown}`) sourced from existing `broadcaster._metrics["wled_devices"]`
- [ ] **Phase 21: MQTT Auto-Discovery (Read-Only)** - `aiomqtt>=2.5,<3` dep, `HaMqttPublisher` service, `hpc_identity` table, `StatusBroadcaster` subscriber callback hook, LWT/retain/birth trifecta, 11 base entities + per-WLED binary_sensors
- [ ] **Phase 22: MQTT Command Consumer** - Refactor `routers/ha.py` to extract pure async helpers; MQTT switch and select entities drive `start`/`stop`/`zone`/`camera` via the same helpers as the HTTP routes

## Phase Details (v1.3 Polish)

### Phase 19: HA YAML Documentation
**Goal**: Users without an MQTT broker (or who want to verify the integration before enabling discovery) can configure HuePictureControl in Home Assistant entirely from a single Markdown file shipped in the repo.
**Depends on**: Phase 18
**Requirements**: HA-DOCS-01, HA-DOCS-02
**Success Criteria** (what must be TRUE):
  1. A user can paste the snippets from `docs/HOME_ASSISTANT.md` into their `configuration.yaml` and, after an HA restart, see at least one HPC sensor populated and at least one `rest_command:` callable that successfully starts streaming
  2. The same document contains a clearly-marked warning explaining that enabling MQTT auto-discovery (Phase 21) AND the REST `rest_command:` / `sensor:` snippets at the same time will create duplicate entities (HA-DOCS-02)
  3. Every YAML snippet in the document uses defensive Jinja templating (e.g. `value_json.fps | default('unknown')`) so a missing optional field does not break HA template rendering
  4. Every `rest_command:` URL/method pair in the document corresponds to an existing route on the `ha` router (verifiable by a doc-test that parses fenced ``` ```yaml ``` blocks)
**Plans**: TBD

---

### Phase 20: WLED Health Flattening in /api/ha/status
**Goal**: Home Assistant consumers of `GET /api/ha/status` can see per-device WLED connectivity, last error, and cooldown state inline with the existing status payload — without a second REST round-trip and without leaking internal `_metrics` shape changes.
**Depends on**: Phase 19
**Requirements**: HA-STAT-01
**Success Criteria** (what must be TRUE):
  1. With at least one WLED device registered, `GET /api/ha/status` returns a `wled_devices` array where each entry contains exactly `{name, connected, last_error, in_cooldown}` (no `packets_sent`/`packets_dropped`/`last_success_at` leakage from `_metrics`)
  2. With no WLED devices registered, `GET /api/ha/status` returns `wled_devices: []` (empty array, never null) — additive contract amendment, no breaking changes to existing D-09 keys
  3. A WLED device whose last UDP send raised an OSError shows `connected: false` and `last_error: "<error string>"` within one heartbeat tick; on next successful send, `connected: true` and `last_error: null`
  4. The status endpoint completes in under 50 ms even with a WLED device that is hard-down (no synchronous probe — the field is sourced from `broadcaster._metrics["wled_devices"]` populated asynchronously by Phase 17)
**Plans**: TBD

---

### Phase 21: MQTT Auto-Discovery (Read-Only)
**Goal**: With a reachable MQTT broker and `MQTT_BROKER_HOST` set, Home Assistant automatically discovers HuePictureControl as a device with switch, sensors, selects, and per-WLED binary_sensors — no YAML required, no orphan entities across HPC restarts, and entities go `unavailable` when HPC crashes.
**Depends on**: Phase 20
**Requirements**: HA-MQTT-01, HA-MQTT-02, HA-MQTT-04, HA-MQTT-06, HA-MQTT-07, HA-MQTT-08, HA-MQTT-09, HA-MQTT-10
**Success Criteria** (what must be TRUE):
  1. With Mosquitto running and `MQTT_BROKER_HOST` set, HA shows HuePictureControl as a single device with the 11 base entities (Streaming switch, State sensor, Bridge paired binary_sensor, FPS, Latency, Active zone, Active camera, Selected zone select, Selected camera select, Last error, and per-WLED binary_sensors) within 30 seconds of HPC startup (HA-MQTT-02, HA-MQTT-04, HA-MQTT-10)
  2. After restarting HPC, HA shows the same entities — no orphans, no new entity duplicates — because every `unique_id` derives from a persistent `hpc_identity.instance_uuid` SQLite row (HA-MQTT-06)
  3. After killing HPC unexpectedly (`kill -9`), all HPC entities in HA show `unavailable` within the LWT delivery window because availability topic was published with `retain=True` and a `Will` was registered at client construction (HA-MQTT-07)
  4. When `MQTT_BROKER_HOST` is unset, no MQTT connection is attempted at startup, no errors are logged, and `/api/health` reports `mqtt: {enabled: false}`; v1.2 behavior is byte-for-byte unchanged (HA-MQTT-01 graceful degrade)
  5. When the broker is restarted (or HPC's connection drops), HPC reconnects with exponential backoff (1s → 60s cap) and republishes state + discovery; when `homeassistant/status: online` is received (HA birth), discovery republishes immediately (HA-MQTT-08)
  6. Two HPC instances pointed at the same broker coexist without entity collisions — each has a distinct `instance_uuid` in `<node_id>` topic segment and in `device.identifiers` (HA-MQTT-09)
**Plans**: TBD

---

### Phase 22: MQTT Command Consumer
**Goal**: With MQTT enabled, users can flip the HPC `switch.streaming` entity, change the `select.selected_zone`, or change the `select.selected_camera` from Home Assistant and the HPC backend acts on it via the same helpers the HTTP routes use — no duplicate business logic, no auth weakening.
**Depends on**: Phase 21
**Requirements**: HA-MQTT-03, HA-MQTT-05
**Success Criteria** (what must be TRUE):
  1. Toggling the HA `switch.streaming` entity calls the same internal helper as `POST /api/ha/start` / `POST /api/ha/stop` — both surfaces share one implementation and the existing 26 unit tests for the HTTP routes continue to pass unchanged (HA-MQTT-03)
  2. Selecting a different option in the HA `select.selected_zone` entity updates `ha_state.active_config_id` (verifiable in SQLite) and the next `POST /api/ha/start` (whether via REST or MQTT switch) uses that zone (HA-MQTT-05)
  3. Selecting a different option in the HA `select.selected_camera` entity updates `ha_state.active_camera_stable_id` without touching `camera_assignments` (D-07 from Phase 18 CONTEXT.md preserved) (HA-MQTT-05)
  4. Inbound MQTT commands are enqueued on a bounded asyncio queue so a broker disconnect mid-handler never wedges the FastAPI event loop or hangs `/api/ha/start` HTTP callers
**Plans**: TBD

---

## Deferred / Unscheduled

### WLED Strip Paint UI (formerly Phase 19)
**Status**: Deferred — not in v1.3 scope, not yet rescheduled. Will be re-planned when prioritized.
**Requirements**: WMAP-01, WMAP-02, WMAP-03, WMAP-04, WMAP-05
**Goal (carry-over)**: Users can visually paint LED channel ranges directly onto a strip representation in the UI, and the resulting channels appear in the light panel for assignment to canvas regions via the same drag-drop workflow used for Hue segments.
**Notes**: Originally placeholdered as Phase 19 in the v1.3 milestone outline. v1.3 HA Integration Polish (Phases 19-22) reclaimed the Phase 19 number on 2026-05-12. WMAP work moves to "Phase TBD (deferred)" in traceability until re-planned.
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
| 16. Zone Persistence Bug Fixes | v1.3 (shipped) | 3/3 | Complete | 2026-04-20 |
| 17. WLED Backend and Streaming | v1.3 (shipped) | 9/9 | Complete | 2026-04-27 |
| 18. Home Assistant Control Endpoints | v1.3 (shipped) | 3/3 | Complete | 2026-05-12 |
| 19. HA YAML Documentation | v1.3 (polish) | 0/TBD | Not started | - |
| 20. WLED Health Flattening in /api/ha/status | v1.3 (polish) | 0/TBD | Not started | - |
| 21. MQTT Auto-Discovery (Read-Only) | v1.3 (polish) | 0/TBD | Not started | - |
| 22. MQTT Command Consumer | v1.3 (polish) | 0/TBD | Not started | - |
| WLED Strip Paint UI (formerly P19) | Deferred | 0/TBD | Unscheduled | - |

---
*Roadmap created: 2026-03-23*
*v1.1 shipped: 2026-04-14*
*v1.3 (WLED + HA Control, Phases 16-18) shipped: 2026-05-12*
*v1.3 Home Assistant Integration Polish (Phases 19-22) planned: 2026-05-12*
