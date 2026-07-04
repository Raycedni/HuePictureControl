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
from services.color_math import (
    boost_saturation_rgb,
    build_polygon_mask,
    sub_sample_gradient,
)
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
        app_state=None,
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
        # quick-task 260516-kra: per-frame brightness cutoff. The streamers
        # read `app_state.brightness_cutoff_threshold` on every render() call
        # so PUT /api/settings/brightness_cutoff_threshold takes effect on
        # the next frame WITHOUT a stream restart. Attribute is set on the
        # sink instance AFTER construction so MagicMock injections in
        # test_streaming_coordinator.py (which don't accept an app_state
        # kwarg) keep working — sinks read `_app_state` defensively via
        # getattr() inside render().
        self._app_state = app_state
        if app_state is not None:
            try:
                self._hue._app_state = app_state
            except (AttributeError, TypeError):
                pass
            try:
                self._wled._app_state = app_state
            except (AttributeError, TypeError):
                pass
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

    async def start(self, config_id: str, target_hz: int = DEFAULT_HZ) -> None:
        """Start the streaming loop for the given entertainment config ID.

        No-op if already streaming (state not idle or error).

        Transitions: idle/error -> starting -> streaming (inside run loop).
        """
        if self._state not in ("idle", "error"):
            return
        self._target_hz = max(1, min(100, target_hz))
        self._period = 1.0 / self._target_hz
        self._config_id = config_id
        self._state = "starting"

        # Resolve device path BEFORE broadcasting "starting" so the WS payload
        # carries the resolved active_device_path (Phase 16 D-05/D-06).
        device_path = await self._resolve_device_path(config_id)
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
        """Load enabled WLED devices with their cached segment + region assignments.

        Returns the ``device_rows`` list ``WledStreamer.start`` expects:
        ``[{"id", "ip", "led_count", "enabled", "channels": [{"id",
        "region_id", "start_led", "end_led"}, ...]}, ...]``.

        Per D-11 the global ``/api/capture/start`` attaches all
        ``wled_devices WHERE enabled = 1`` as UDP sinks. Per Phase 19.1 D-22
        the per-channel rows come from ``wled_seg_cache`` (mirroring the
        device's ``/json/state seg[]``) joined against
        ``wled_light_assignments`` on the composite
        ``(wled_device_id, seg_index)`` key — segments not assigned for the
        active config surface ``region_id = NULL`` and WledStreamer.render
        skips them.

        Per RESEARCH.md Open Question #1 the emitted ``id`` is
        ``str(seg_index)`` — this is the minimum diff that preserves the
        ``WledStreamer.start`` channel-dict contract (which keys per-device
        state on the channel ``id``).

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
                # Phase 19.1 D-22 + RESEARCH.md Open Question #1: read segment
                # ranges from wled_seg_cache (mirrors WLED /json/state) joined
                # against the composite (wled_device_id, seg_index) key on
                # wled_light_assignments. ``id`` emitted as ``str(seg_index)``
                # keeps the WledStreamer.start channel-dict contract stable
                # with the minimum diff.
                async with await self._db.execute(
                    """
                    SELECT wsc.seg_index, wla.region_id, wsc.start_led, wsc.stop_led
                    FROM wled_seg_cache wsc
                    LEFT JOIN wled_light_assignments wla
                        ON wla.wled_device_id = wsc.device_id
                       AND wla.seg_index = wsc.seg_index
                       AND wla.entertainment_config_id = ?
                    WHERE wsc.device_id = ?
                    ORDER BY wsc.seg_index
                    """,
                    (config_id, dev_id),
                ) as cur:
                    ch_rows = await cur.fetchall()
            except Exception as exc:
                logger.warning(
                    "WLED segment query failed for device %s: %s", dev_id, exc
                )
                ch_rows = []
            channels = []
            for c in ch_rows:
                try:
                    channels.append({
                        "id": str(c["seg_index"]),
                        "region_id": c["region_id"],
                        "start_led": int(c["start_led"]),
                        # ``wsc.stop_led`` is INCLUSIVE (Plan 02 enforced
                        # EXCLUSIVE->INCLUSIVE at the parse boundary).
                        # WledStreamer treats ``end_led`` as INCLUSIVE too,
                        # so we pass it through unchanged.
                        "end_led": int(c["stop_led"]),
                    })
                except Exception:
                    channels.append({
                        "id": str(c[0]),
                        "region_id": c[1] if len(c) > 1 else None,
                        "start_led": int(c[2]),
                        "end_led": int(c[3]),
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
        """Build {region_id: (RegionMask, N_region, orientation)} for sub-sample fan-out.

        Per Phase 19 CONTEXT.md D-16/D-22 (per-region narrowing): orientation is
        region-scoped, not channel-scoped. ALL wled_light_assignments rows for
        a given (region_id, entertainment_config_id) carry the same orientation
        value (enforced at the API layer by PATCH /api/wled/regions/{rid}/orientation).
        MAX(wla.orientation) is therefore deterministic; NULL coerces to 'auto'
        for Hue-only regions.

        The query joins ``regions`` with both Hue (``light_assignments``) and
        WLED (``wled_light_assignments`` -> ``wled_seg_cache``) sides and computes
        ``N_region = COALESCE(MAX(stop_led - start_led + 1), 1)`` against the
        Phase 19.1 segment cache (D-22). Both ``start_led`` and ``stop_led`` are
        INCLUSIVE (Plan 02 converts WLED's EXCLUSIVE ``seg.stop`` at the parse
        boundary), so the ``+ 1`` produces the correct LED count.

        N.B. This query is for gradient sub-sampling ONLY. The Hue
        channel_id -> region_id mapping is HueStreamer's responsibility inside
        ``_load_channel_to_region``, which runs independently in
        ``HueStreamer.start()``. See ``17-05-PLAN.md`` ``<query_responsibilities>``.
        """
        # Phase 19.1 D-22 + Plan 05 SQL rewrite: JOIN wled_seg_cache (the
        # /json/state mirror) on the composite (wled_device_id, seg_index)
        # key instead of the dropped per-channel UUID surrogate. The Hue
        # branch (light_assignments) and the COALESCE / GROUP BY shape are
        # unchanged so the gradient contract {region_id: gradient_array}
        # remains intact for Hue-only regions.
        sql = """
            SELECT DISTINCT r.id AS region_id, r.polygon,
                   COALESCE(MAX(wsc.stop_led - wsc.start_led + 1), 1) AS n_region,
                   COALESCE(MAX(wla.orientation), 'auto') AS orientation
            FROM regions r
            LEFT JOIN light_assignments la
                ON la.region_id = r.id AND la.entertainment_config_id = :cfg
            LEFT JOIN wled_light_assignments wla
                ON wla.region_id = r.id AND wla.entertainment_config_id = :cfg
            LEFT JOIN wled_seg_cache wsc
                ON wsc.device_id = wla.wled_device_id
               AND wsc.seg_index = wla.seg_index
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
                orientation = row["orientation"]
            except Exception:
                # Defensive: row may be a tuple in some test mocks
                region_id, polygon, n_region, orientation = (
                    row[0], row[1], row[2], row[3]
                )
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
            plan[region_id] = (mask, int(n_region or 1), str(orientation or "auto"))
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

    def _read_live_setting(self, key: str, default: float = 0.0) -> float:
        """Defensively read a live float setting off ``self._app_state``.

        Mirrors the sinks' ``getattr(app_state, key, default)`` + try/except
        pattern (quick-task 260516-kra) — ``self._app_state`` may be None in
        tests, and a stale/malformed attribute value should never crash the
        frame loop, so any lookup or coercion failure falls back to
        ``default``.
        """
        if self._app_state is None:
            return default
        try:
            return float(getattr(self._app_state, key, default))
        except (TypeError, ValueError):
            return default

    async def _frame_loop(self, region_plan: dict) -> None:
        """60 Hz frame loop: extract per-region gradients and fan out to sinks.

        For each frame:
          * grab frame from capture
          * compute ``hue_gradients`` with ``n=1`` per region on the event
            loop (cheap: ``sub_sample_gradient(n=1)`` returns the
            full-region mean via ``extract_region_color``, byte-identical
            to ``HueStreamer.render`` taking ``gradient.mean(axis=0)`` over
            the (N, 3) WLED-sized gradient)
          * spawn ``_wled_pipeline`` that computes ``wled_gradients`` with
            full ``n=N_region`` inside ``asyncio.to_thread`` BEFORE awaiting
            ``self._wled.render(...)`` -- keeps the heavy cv2.mean loop
            off the event loop so it cannot delay the Hue per-frame DTLS
            send
          * ``asyncio.gather(hue.render, _wled_pipeline)`` so the two run
            concurrently with the same return_exceptions=True contract as
            before

        Why split: when ``n_region`` jumps from 1 (Hue-only) to N (WLED
        assigned, 30-300+ LEDs), the shared ``region_gradients`` dict
        comprehension and the synchronous numpy work inside
        ``WledStreamer._render_one_device`` both run on the event loop and
        serialize with the ``HueStreamer.render`` DTLS message pack. The
        orchestrator measured Hue per-frame event-loop time inflating from
        0.15 ms to 0.89 ms (6x) with 4 WLED devices at 300 LEDs each.
        Splitting the gradient compute by-sink and pushing the WLED-sized
        compute into a worker thread keeps the Hue per-frame event-loop
        time at the no-WLED baseline regardless of WLED LED count or
        device count. Hue output remains byte-identical because
        ``sub_sample_gradient(frame, mask, n=1)`` short-circuits to
        ``extract_region_color`` (full-region mean) and
        ``HueStreamer.render`` mean-reduces back to a single RGB anyway
        (D-05).

        Bridge errors call ``self._hue.handle_bridge_error(exc)``; capture
        errors trigger ``_capture_reconnect_loop``. Per D-06 WLED errors
        are isolated per-device inside ``WledStreamer`` and never escape
        its ``render`` -- they cannot reach the bridge-reconnect path.
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

            # quick-task 260704-iss: read the live vibrancy + boost settings
            # ONCE per frame so PUT /api/settings/{color_vibrancy,
            # saturation_boost} takes effect on the NEXT frame without a
            # stream restart. self._app_state may be None in tests -> both
            # default to 0.0 (identity — byte-identical to pre-feature
            # behavior).
            vibrancy = self._read_live_setting("color_vibrancy")
            boost = self._read_live_setting("saturation_boost")
            # quick-task 260704-w88: read the live hdr_input toggle ONCE per
            # frame so PUT /api/settings/hdr_input takes effect on the NEXT
            # frame without a stream restart. hdr=False is a true identity
            # pass-through (zero cost, byte-identical to pre-feature
            # behavior).
            hdr = self._read_live_setting("hdr_input") >= 0.5

            # Phase 19 D-22 (per-region narrowing): orientation comes from
            # the region's resolved value in region_plan. The Hue sink
            # gets n=1 (full-region mean via extract_region_color) -- cheap
            # to compute on the event loop and byte-identical to the
            # pre-split path's ``gradient.mean(axis=0)`` reduction inside
            # HueStreamer.render (D-05). The WLED sink gets the full
            # n=N_region gradient built INSIDE ``asyncio.to_thread`` below
            # so the cv2.mean loop never blocks the event loop.
            #
            # quick-task 260704-wy5 (HDR v2): HDR expansion + linear-light
            # averaging happens INSIDE sub_sample_gradient via hdr=, so a
            # bright area dominates the region mean the way it dominates
            # perceptually (no more post-hoc convert-after-average).
            # boost_saturation_rgb is still applied after, unchanged.
            hue_gradients: dict[str, np.ndarray] = {
                rid: boost_saturation_rgb(
                    sub_sample_gradient(
                        frame, mask, 1, orientation=orientation, vibrancy=vibrancy, hdr=hdr
                    ),
                    boost,
                )
                for rid, (mask, n_region, orientation) in region_plan.items()
            }

            async def _wled_pipeline(
                plan=region_plan, current_frame=frame, vib=vibrancy, bst=boost,
                hdr_on=hdr,
            ):
                # Build the WLED-sized gradients in a worker thread so the
                # event loop stays free for the Hue DTLS pack/send. The
                # per-LED cv2.mean loop is ~0.6 ms per region at n=300 --
                # well worth the to_thread hop.
                def _compute() -> dict[str, np.ndarray]:
                    result: dict[str, np.ndarray] = {}
                    for rid, (mask, n_region, orientation) in plan.items():
                        g = sub_sample_gradient(
                            current_frame, mask, n_region,
                            orientation=orientation, vibrancy=vib, hdr=hdr_on,
                        )
                        result[rid] = boost_saturation_rgb(g, bst)
                    return result
                wled_gradients = await asyncio.to_thread(_compute)
                await self._wled.render(wled_gradients)

            # Quick-task 260516-iqp + wled-activation-latency fix: fan out
            # to both sinks concurrently. Hue gets its cheap n=1 gradients
            # immediately; WLED first builds n=N gradients off the loop
            # via to_thread, then sends. return_exceptions=True so a
            # WLED-side exception (D-06 says it should not normally escape)
            # cannot mask a Hue-side bridge error.
            results = await asyncio.gather(
                self._hue.render(hue_gradients),
                _wled_pipeline(),
                return_exceptions=True,
            )
            hue_exc, wled_exc = results
            if isinstance(wled_exc, BaseException):
                logger.warning(
                    "WLED render raised unexpectedly (should be isolated): %s",
                    wled_exc,
                )
            if isinstance(hue_exc, BaseException):
                # Per D-06: Hue errors trigger Hue reconnect.
                ok = await self._hue.handle_bridge_error(hue_exc)
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
