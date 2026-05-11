"""StreamingCoordinator: capture-to-sink frame loop owner.

Refactored from the former ``StreamingService`` (Phase 17 Plan 05). Owns the
per-frame orchestration of capture acquire/release, broadcaster state
transitions + heartbeat, sub-region gradient computation, and fan-out to one
or more sinks (Hue, WLED).

Per D-01 / D-02:
  * Coordinator: capture lifecycle + 60 Hz frame loop + broadcaster.
  * HueStreamer: bridge / DTLS / set_input.
  * WledStreamer: per-device UDP DRGB/DNRGB sends.

The coordinator is sink-agnostic: it computes ``region_gradients`` once per
frame and hands the same dict to each sink's ``render(...)``. Each sink
decides what to do with the per-region (N_region, 3) ndarray.

Exports:
    StreamingCoordinator -- main entry point used by routers/capture.py (Plan 07
    will swap the wiring; Plan 05 leaves the StreamingService import shim in
    streaming_service.py so existing wiring keeps working).
"""
import asyncio
import json
import logging
import time

import numpy as np

from services.capture_service import CAPTURE_DEVICE
from services.color_math import build_polygon_mask, sub_sample_gradient
from services.streaming_service import HueStreamer
from services.wled_streamer import WledStreamer

logger = logging.getLogger(__name__)


class StreamingCoordinator:
    """Owns the capture pipeline + frame loop and fans out to Hue/WLED sinks.

    Lifecycle::

        coord = StreamingCoordinator(db, capture_registry, broadcaster)
        await coord.start(config_id)   # idle -> starting -> streaming
        await coord.stop()             # streaming -> stopping -> idle

    The frame loop runs as an ``asyncio.Task`` started by ``start()``. It can
    be stopped by calling ``stop()`` which clears the run event and awaits
    the task. Bridge / capture errors trigger sink-specific reconnect; WLED
    errors are isolated per-device inside ``WledStreamer`` and never reach the
    coordinator.
    """

    DEFAULT_HZ = 60

    def __init__(
        self,
        db,
        capture_registry,
        broadcaster,
        hue_streamer=None,
        wled_streamer=None,
    ) -> None:
        self._db = db
        self._capture_registry = capture_registry
        self._capture = None        # Set by start() via registry.acquire()
        self._device_path = None    # Track for release in stop()
        self._broadcaster = broadcaster
        # Phase 17 Plan 06 removed the bottom-of-file StreamingService shim
        # in services/streaming_service.py, so the previous deferred local
        # import is no longer required — HueStreamer is now imported at the
        # module top level (no cycle).
        self._hue = hue_streamer if hue_streamer is not None else HueStreamer(db)
        # Phase 17 Plan 06: WLED is no longer optional. Default-construct a
        # production WledStreamer (UDP port 21324 per D-14) when not injected;
        # tests pass a real WledStreamer(udp_port=41324) bound to a loopback
        # listener (see test_streaming_coordinator.py fan-out test) or a
        # MagicMock with AsyncMock start/stop/render + MagicMock
        # health_snapshot. The streamer is started inside _run_loop with the
        # device_rows produced by _load_wled_device_rows.
        self._wled = wled_streamer if wled_streamer is not None else WledStreamer()
        self._run_event: asyncio.Event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._state: str = "idle"
        self._config_id: str | None = None
        self._target_hz: int = self.DEFAULT_HZ
        self._period: float = 1.0 / self.DEFAULT_HZ

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Current streaming state: idle | starting | streaming | stopping | error."""
        return self._state

    async def start(
        self,
        config_id: str,
        target_hz: int = DEFAULT_HZ,
        device_path_override: str | None = None,
    ) -> None:
        """Start the streaming loop for the given entertainment config ID.

        No-op if already streaming (state not idle or error).

        Transitions: idle/error -> starting -> streaming (inside run loop).

        ``device_path_override`` (Phase 18 D-08): when non-None, bypasses the
        camera_assignments -> known_cameras -> CAPTURE_DEVICE resolution chain and
        uses the provided path directly. The HA router (routers/ha.py) reads
        ``ha_state.active_camera_stable_id`` and resolves it via
        ``known_cameras.last_device_path`` before passing the result here, so D-07
        (HA does not touch camera_assignments) stays clean.
        """
        if self._state not in ("idle", "error"):
            return
        self._target_hz = max(1, min(100, target_hz))
        self._period = 1.0 / self._target_hz
        self._config_id = config_id
        self._state = "starting"

        # Resolve device path BEFORE broadcasting "starting" so the WS payload
        # carries the resolved active_device_path (Phase 16 D-05/D-06).
        device_path = device_path_override or await self._resolve_device_path(config_id)
        self._device_path = device_path

        await self._broadcaster.push_state(
            self._state,
            active_config_id=config_id,
            active_device_path=device_path,
        )

        # Acquire capture backend from registry
        try:
            self._capture = await asyncio.to_thread(
                self._capture_registry.acquire, device_path
            )
        except RuntimeError as exc:
            self._state = "error"
            await self._broadcaster.push_state(
                "error",
                error=str(exc),
                active_config_id=None,
                active_device_path=None,
            )
            return

        self._run_event.set()
        self._task = asyncio.create_task(self._run_loop(config_id))

    async def stop(self) -> None:
        """Stop the streaming loop cleanly.

        No-op if already idle. Clears the run event and awaits the task.
        The task's cleanup routine handles the locked stop sequence:
        sink stop -> capture.release.
        """
        if self._state == "idle":
            return
        self._state = "stopping"
        # "stopping" still carries the active config/device — we're still on it
        # until teardown completes (Phase 16 D-06).
        await self._broadcaster.push_state(
            self._state,
            active_config_id=self._config_id,
            active_device_path=self._device_path,
        )
        self._run_event.clear()
        if self._task:
            await self._task
        self._state = "idle"
        # Clear active config/device on idle (D-06).
        await self._broadcaster.push_state(
            self._state,
            active_config_id=None,
            active_device_path=None,
        )

    async def set_wled_device_enabled(self, device_id: str, enabled: bool) -> None:
        """Toggle a WLED device's enabled flag (D-12). Updates DB + live streamer.

        Per D-12 the ``enabled`` column is a per-frame UDP-send gate, not an
        attachment gate. Devices stay in the streamer's view; toggling
        enabled/disabled simply skips them in the next render() call. Safe to
        call at any lifecycle state — when streaming, the live gate takes
        effect on the next frame; when idle, only the DB row changes and the
        streamer picks up the new value on next start.
        """
        await self._db.execute(
            "UPDATE wled_devices SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, device_id),
        )
        await self._db.commit()
        self._wled.set_enabled(device_id, enabled)

    async def add_wled_device_to_live(self, device_id: str) -> bool:
        """Attach a newly-registered enabled device to an already-running stream.

        No-op when not streaming. ``WledStreamer.start`` raises if called twice
        without an intervening ``stop()`` so we cannot simply re-load the
        device rows mid-stream. For Plan 06 this is a logged no-op — the device
        becomes active on the next stream start. Phase 19 (or a follow-up)
        may add a true ``WledStreamer.attach_device`` for hot-add.

        Returns True if attached live, False otherwise. Plan 06 always returns
        False; Plan 07 routers call this after INSERT and surface the result.
        """
        if self._state != "streaming" or self._config_id is None:
            return False
        logger.info(
            "WLED device %s registered mid-stream; it will be active on next stream start.",
            device_id,
        )
        return False

    # ------------------------------------------------------------------
    # Internal: device resolution
    # ------------------------------------------------------------------

    async def _resolve_device_path(self, config_id: str) -> str:
        """Resolve the device path for the given entertainment config.

        Looks up camera_assignments for the config_id, then finds the
        last_device_path in known_cameras. Falls back to CAPTURE_DEVICE
        if no assignment exists or the camera is unknown.
        """
        async with await self._db.execute(
            "SELECT camera_stable_id FROM camera_assignments WHERE entertainment_config_id = ?",
            (config_id,),
        ) as cursor:
            assign_row = await cursor.fetchone()

        if assign_row is None:
            return CAPTURE_DEVICE

        stable_id = assign_row["camera_stable_id"]

        async with await self._db.execute(
            "SELECT last_device_path FROM known_cameras WHERE stable_id = ?",
            (stable_id,),
        ) as cursor:
            cam_row = await cursor.fetchone()

        if cam_row is None or not cam_row["last_device_path"]:
            return CAPTURE_DEVICE

        return cam_row["last_device_path"]

    # ------------------------------------------------------------------
    # Internal: WLED device + channel loader (Phase 17 Plan 06 / D-11, D-12)
    # ------------------------------------------------------------------

    async def _load_wled_device_rows(self, config_id: str) -> list[dict]:
        """Load enabled WLED devices with their channel + region assignments.

        Returns the ``device_rows`` list ``WledStreamer.start`` expects:
        ``[{"id", "ip", "led_count", "enabled", "channels": [{"id",
        "region_id", "start_led", "end_led"}, ...]}, ...]``.

        Per D-11 the global ``/api/capture/start`` attaches all
        ``wled_devices WHERE enabled = 1`` as UDP sinks. Per the
        T-17-DB-JOIN mitigation, the channel-side LEFT JOIN scopes
        ``wla.entertainment_config_id`` so channels not assigned for the
        active config surface ``region_id = NULL`` and WledStreamer.render
        skips them.

        Returns an empty list if no devices are registered or all are
        disabled. Falls back to ``[]`` if the wled_* tables don't yet exist
        (DB schema may lag in some test paths).
        """
        rows: list[dict] = []
        try:
            async with await self._db.execute(
                "SELECT id, ip, led_count, enabled FROM wled_devices WHERE enabled = 1"
            ) as cur:
                device_rows = await cur.fetchall()
        except Exception as exc:
            logger.warning(
                "WLED device query failed (returning empty rows): %s", exc
            )
            return []

        for dev in device_rows:
            try:
                dev_id = dev["id"]
                dev_ip = dev["ip"]
                dev_led_count = dev["led_count"]
                dev_enabled = dev["enabled"]
            except Exception:
                # Defensive: row may be a tuple in some mocks
                dev_id, dev_ip, dev_led_count, dev_enabled = (
                    dev[0], dev[1], dev[2], dev[3]
                )
            try:
                async with await self._db.execute(
                    """
                    SELECT wc.id AS channel_id, wc.start_led, wc.end_led, wla.region_id
                    FROM wled_channels wc
                    LEFT JOIN wled_light_assignments wla
                        ON wla.wled_channel_id = wc.id
                        AND wla.entertainment_config_id = ?
                    WHERE wc.device_id = ?
                    """,
                    (config_id, dev_id),
                ) as cur:
                    ch_rows = await cur.fetchall()
            except Exception as exc:
                logger.warning(
                    "WLED channel query failed for device %s: %s", dev_id, exc
                )
                ch_rows = []
            channels = []
            for c in ch_rows:
                try:
                    channels.append({
                        "id": c["channel_id"],
                        "region_id": c["region_id"],
                        "start_led": int(c["start_led"]),
                        "end_led": int(c["end_led"]),
                    })
                except Exception:
                    channels.append({
                        "id": c[0],
                        "region_id": c[3] if len(c) > 3 else None,
                        "start_led": int(c[1]),
                        "end_led": int(c[2]),
                    })
            rows.append({
                "id": dev_id,
                "ip": dev_ip,
                "led_count": int(dev_led_count),
                "enabled": bool(dev_enabled),
                "channels": channels,
            })
        return rows

    # ------------------------------------------------------------------
    # Internal: region plan (sub-sample N per region)
    # ------------------------------------------------------------------

    async def _build_region_plan(self, config_id: str) -> dict:
        """Build {region_id: (RegionMask, N_region)} for sub-sample fan-out.

        The query joins ``regions`` with both Hue (``light_assignments``) and
        WLED (``wled_light_assignments`` -> ``wled_channels``) sides and computes
        ``N_region = COALESCE(MAX(end_led - start_led + 1), 1)``. In Plan 05
        (no WLED rows yet) the WLED JOIN returns zero rows so N_region defaults
        to 1 — fan-out is numerically identical to the old per-channel-average
        path. Plan 06 will populate WLED tables and the same query starts
        returning N_region > 1 for strip-assigned regions.

        N.B. This query is for gradient sub-sampling ONLY. The Hue
        channel_id -> region_id mapping is HueStreamer's responsibility inside
        ``_load_channel_to_region``, which runs independently in
        ``HueStreamer.start()``. See ``17-05-PLAN.md`` ``<query_responsibilities>``.
        """
        sql = """
            SELECT DISTINCT r.id AS region_id, r.polygon,
                   COALESCE(MAX(wc.end_led - wc.start_led + 1), 1) AS n_region
            FROM regions r
            LEFT JOIN light_assignments la ON la.region_id = r.id AND la.entertainment_config_id = :cfg
            LEFT JOIN wled_light_assignments wla ON wla.region_id = r.id AND wla.entertainment_config_id = :cfg
            LEFT JOIN wled_channels wc ON wc.id = wla.wled_channel_id
            WHERE la.region_id IS NOT NULL OR wla.region_id IS NOT NULL
            GROUP BY r.id, r.polygon
        """
        try:
            async with await self._db.execute(sql, {"cfg": config_id}) as cursor:
                rows = await cursor.fetchall()
        except Exception as exc:
            # In Plan 05 the wled_* tables may not yet exist on a freshly
            # migrated DB during certain test paths — log and return an empty
            # plan so the frame loop just sends zero per-region gradients.
            logger.warning(
                "Region plan query failed (returning empty plan): %s", exc
            )
            return {}

        plan: dict[str, tuple] = {}
        for row in rows:
            try:
                region_id = row["region_id"]
                polygon = row["polygon"]
                n_region = row["n_region"]
            except Exception:
                # Defensive: row may be a tuple in some test mocks
                region_id, polygon, n_region = row[0], row[1], row[2]
            if not polygon:
                continue
            try:
                points = json.loads(polygon)
            except Exception:
                logger.warning(
                    "Region %s has invalid polygon JSON, skipping", region_id
                )
                continue
            mask = build_polygon_mask(points)
            plan[region_id] = (mask, int(n_region or 1))
        return plan

    # ------------------------------------------------------------------
    # Internal: run loop
    # ------------------------------------------------------------------

    async def _run_loop(self, config_id: str) -> None:
        """Main streaming orchestration: sink start, frame loop, teardown."""
        try:
            # 1. Start the Hue sink (bridge + DTLS + channel map). HueStreamer
            #    manages its own _load_channel_map / _load_channel_to_region.
            await self._hue.start(config_id)

            # 2. Phase 17 Plan 06: Load enabled WLED devices + their channel/
            #    region assignments and start the WledStreamer (D-11 global
            #    start attaches all enabled devices). Empty list is fine — the
            #    streamer enters the "started, no devices" state and render()
            #    is a no-op.
            wled_rows = await self._load_wled_device_rows(config_id)
            await self._wled.start(wled_rows)

            # 3. Transition to streaming state — carry active config/device (D-06).
            self._state = "streaming"
            await self._broadcaster.push_state(
                self._state,
                active_config_id=self._config_id,
                active_device_path=self._device_path,
            )

            # 4. Start broadcaster heartbeat
            await self._broadcaster.start_heartbeat()

            # 5. Build region plan (one mask + N per region)
            region_plan = await self._build_region_plan(config_id)

            # 6. Run the frame loop
            await self._frame_loop(region_plan)

        except RuntimeError as exc:
            logger.error("Capture error in run loop: %s", exc)
            self._run_event.clear()
            self._state = "error"
            await self._broadcaster.push_state(
                "error",
                error=str(exc),
                active_config_id=None,
                active_device_path=None,
            )
        except Exception as exc:
            logger.error("Unexpected error in run loop: %s", exc)
            self._run_event.clear()
            self._state = "error"
            await self._broadcaster.push_state(
                "error",
                error=str(exc),
                active_config_id=None,
                active_device_path=None,
            )
        finally:
            # Locked teardown: heartbeat -> Hue stop -> WLED stop -> capture release
            await self._broadcaster.stop_heartbeat()
            try:
                await self._hue.stop()
            except Exception:
                logger.warning("HueStreamer.stop failed (best-effort)")
            try:
                await self._wled.stop()
            except Exception:
                logger.warning("WledStreamer.stop failed (best-effort)")
            if self._device_path:
                try:
                    await asyncio.to_thread(
                        self._capture_registry.release, self._device_path
                    )
                except Exception:
                    logger.warning("Registry release failed (best-effort)")
                self._device_path = None
                self._capture = None
            if self._state not in ("error",):
                self._state = "idle"

    async def _frame_loop(self, region_plan: dict) -> None:
        """60 Hz frame loop: extract per-region gradients and fan out to sinks.

        For each frame:
          * grab frame from capture
          * for each (region_id, (mask, N_region)) in region_plan,
            compute sub_sample_gradient(frame, mask, N_region)
          * await self._hue.render(region_gradients)
          * await self._wled.render(region_gradients) — always called now
            (Plan 06). With no enabled devices the call is a cheap no-op.
        Bridge errors call ``self._hue.handle_bridge_error(exc)``; capture
        errors trigger ``_capture_reconnect_loop``. Per D-06 WLED errors are
        isolated per-device inside ``WledStreamer`` and never escape its
        ``render`` — they cannot reach the bridge-reconnect path.
        """
        seq = 0
        prev_t0 = time.monotonic()

        while self._run_event.is_set():
            t0 = time.monotonic()
            try:
                frame = await self._capture.wait_for_new_frame()
            except RuntimeError as exc:
                logger.warning(
                    "Capture device error: %s, starting reconnect", exc
                )
                ok = await self._capture_reconnect_loop()
                if ok:
                    continue
                self._state = "error"
                await self._broadcaster.push_state(
                    "error",
                    error=str(exc),
                    active_config_id=None,
                    active_device_path=None,
                )
                return

            region_gradients: dict[str, np.ndarray] = {
                rid: sub_sample_gradient(frame, mask, n_region)
                for rid, (mask, n_region) in region_plan.items()
            }

            try:
                await self._hue.render(region_gradients)
                await self._wled.render(region_gradients)
            except Exception as exc:
                # Per D-06: Hue errors trigger Hue reconnect; WLED errors are
                # isolated per-device inside WledStreamer and never reach here.
                ok = await self._hue.handle_bridge_error(exc)
                if not ok:
                    return

            seq += 1
            cycle_time = t0 - prev_t0
            prev_t0 = t0
            fps = (
                round(1.0 / max(cycle_time, 1e-6), 1)
                if seq > 1
                else self._target_hz
            )
            latency_ms = (time.monotonic() - t0) * 1000.0
            metrics: dict = {
                "fps": fps,
                "latency_ms": round(latency_ms, 1),
                "seq": seq,
            }
            try:
                metrics["wled_devices"] = self._wled.health_snapshot()
            except Exception:
                metrics["wled_devices"] = {}
            self._broadcaster.update_metrics(metrics)

    # ------------------------------------------------------------------
    # Internal: capture reconnect
    # ------------------------------------------------------------------

    async def _capture_reconnect_loop(self) -> bool:
        """Reconnect the capture device with exponential backoff.

        Called when get_frame() raises RuntimeError (device disconnected).
        Retries indefinitely while run_event is set.
        Delays: 1s, 2s, 4s, 8s, 16s, 30s (capped).

        capture.open() is called via asyncio.to_thread because cv2.VideoCapture
        is a blocking operation.
        """
        self._state = "reconnecting"
        await self._broadcaster.push_state(
            self._state,
            active_config_id=self._config_id,
            active_device_path=self._device_path,
        )

        delay = 1
        max_delay = 30

        while self._run_event.is_set():
            try:
                self._capture.release()
                await asyncio.to_thread(self._capture.open)
                # Wait for the reader thread to produce a first frame
                for _ in range(20):
                    await asyncio.sleep(0.2)
                    try:
                        await self._capture.get_frame()
                        break
                    except RuntimeError:
                        pass
                else:
                    raise RuntimeError("Device opened but no frames produced")
                logger.info("Capture device reconnection succeeded")
                self._state = "streaming"
                await self._broadcaster.push_state(
                    self._state,
                    active_config_id=self._config_id,
                    active_device_path=self._device_path,
                )
                return True
            except Exception as exc:
                logger.warning(
                    "Capture reconnect failed: %s, retrying in %ds", exc, delay
                )
                try:
                    self._capture.release()
                except Exception:
                    pass
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

        return False
