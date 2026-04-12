"""StreamingService: async class that owns the capture-to-DTLS streaming loop.

Connects LatestFrameCapture, color_math, StatusBroadcaster, and
hue-entertainment-pykit into a managed 50 Hz loop that extracts colors
from screen regions and sends them to Hue lights via DTLS.

Exports:
    StreamingService -- Main async streaming orchestrator
"""
import asyncio
import json
import logging
import time

from hue_entertainment_pykit import create_bridge, Entertainment, Streaming

from services.capture_service import CAPTURE_DEVICE
from services.color_math import extract_region_color, rgb_to_xy, build_polygon_mask
from services.hue_client import (
    activate_entertainment_config,
    deactivate_entertainment_config,
    resolve_light_to_channel_map,
)

logger = logging.getLogger(__name__)


class StreamingService:
    """Manages the full capture -> color extract -> DTLS stream loop at 50 Hz.

    Lifecycle::

        service = StreamingService(db, capture, broadcaster)
        await service.start(config_id)   # idle -> starting -> streaming
        await service.stop()             # streaming -> stopping -> idle

    The frame loop runs as an asyncio.Task started by start(). It can be
    stopped by calling stop() which clears the run event and awaits the task.

    Bridge disconnect triggers exponential backoff reconnect; during reconnect
    the capture pipeline continues independently (not paused/released).

    Capture card disconnect also triggers exponential backoff reconnect via
    _capture_reconnect_loop. Streaming resumes automatically on reconnect.
    If run_event is cleared during reconnect, streaming transitions to error.
    """

    DEFAULT_HZ = 60

    def __init__(self, db, capture_registry, broadcaster) -> None:
        self._db = db
        self._capture_registry = capture_registry
        self._capture = None        # Set by start() via registry.acquire()
        self._device_path = None    # Track for release in stop()
        self._broadcaster = broadcaster
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

        Transitions: idle/error -> starting -> streaming (inside run loop)

        Args:
            config_id: UUID of the Hue entertainment configuration to stream to.
            target_hz: Target update rate in Hz (1-100, default 50).
        """
        if self._state not in ("idle", "error"):
            return
        self._target_hz = max(1, min(100, target_hz))
        self._period = 1.0 / self._target_hz
        self._config_id = config_id
        self._state = "starting"
        await self._broadcaster.push_state(self._state)

        # Resolve device path from DB camera assignment (falls back to CAPTURE_DEVICE)
        device_path = await self._resolve_device_path(config_id)
        self._device_path = device_path

        # Acquire capture backend from registry
        try:
            self._capture = await asyncio.to_thread(self._capture_registry.acquire, device_path)
        except RuntimeError as exc:
            self._state = "error"
            await self._broadcaster.push_state("error", error=str(exc))
            return

        self._run_event.set()
        self._task = asyncio.create_task(self._run_loop(config_id))

    async def stop(self) -> None:
        """Stop the streaming loop cleanly.

        No-op if already idle. Clears the run event and awaits the task.
        The task's cleanup routine handles the locked stop sequence:
        stop_stream -> deactivate -> capture.release.
        """
        if self._state == "idle":
            return
        self._state = "stopping"
        await self._broadcaster.push_state(self._state)
        self._run_event.clear()
        if self._task:
            await self._task
        self._state = "idle"
        await self._broadcaster.push_state(self._state)

    # ------------------------------------------------------------------
    # Internal: device resolution
    # ------------------------------------------------------------------

    async def _resolve_device_path(self, config_id: str) -> str:
        """Resolve the device path for the given entertainment config.

        Looks up camera_assignments for the config_id, then finds the
        last_device_path in known_cameras. Falls back to CAPTURE_DEVICE
        if no assignment exists or the camera is unknown.

        Args:
            config_id: Entertainment configuration UUID.

        Returns:
            Device path string (e.g. '/dev/video0').
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
    # Internal: run loop
    # ------------------------------------------------------------------

    async def _run_loop(self, config_id: str) -> None:
        """Main streaming orchestration: setup, frame loop, teardown.

        1. Load bridge credentials from DB
        2. Load channel map (light_assignments JOIN regions -> {channel_id: mask})
        3. Build Bridge, Entertainment, Streaming objects
        4. Activate entertainment config via REST
        5. Start DTLS stream (asyncio.to_thread)
        6. Set color space to xyb
        7. Start broadcaster heartbeat
        8. Run frame loop (exits when run_event is cleared or error occurs)
        9. Teardown: stop_stream -> deactivate -> capture.release (locked sequence)
        """
        streaming = None
        bridge_ip: str = ""
        username: str = ""

        try:
            # 1. Load bridge credentials
            async with await self._db.execute(
                "SELECT * FROM bridge_config WHERE id = 1"
            ) as cursor:
                bridge_row = await cursor.fetchone()

            bridge_ip = bridge_row["ip_address"]
            username = bridge_row["username"]
            client_key = bridge_row["client_key"]
            rid = bridge_row["rid"]
            bridge_id = bridge_row["bridge_id"]
            hue_app_id = bridge_row["hue_app_id"]
            swversion = bridge_row["swversion"]
            name = bridge_row["name"]

            # 2. Load channel map once (masks are constant for a given config)
            channel_map = await self._load_channel_map(config_id, bridge_ip, username)

            # 3. Build pykit objects
            bridge = create_bridge(
                identification=bridge_id,
                rid=rid,
                ip_address=bridge_ip,
                username=username,
                hue_app_id=hue_app_id,
                clientkey=client_key,
                swversion=swversion,
                name=name,
            )
            entertainment = Entertainment(bridge)
            configs = entertainment.get_entertainment_configs()
            config = configs.get(config_id) or list(configs.values())[0]
            repo = entertainment.get_ent_conf_repo()
            streaming = Streaming(bridge, config, repo)

            # 4. Activate entertainment config via REST
            await activate_entertainment_config(bridge_ip, username, config_id)

            # 5. Start DTLS stream
            await asyncio.to_thread(streaming.start_stream)

            # 6. Set color space to xyb
            await asyncio.to_thread(streaming.set_color_space, "xyb")

            # Transition to streaming state
            self._state = "streaming"
            await self._broadcaster.push_state(self._state)

            # 7. Start broadcaster heartbeat
            await self._broadcaster.start_heartbeat()

            # 8. Run the frame loop
            await self._frame_loop(streaming, channel_map, bridge_ip, username)

        except RuntimeError as exc:
            # Capture card disconnect — stop entirely
            logger.error("Capture error in run loop: %s", exc)
            self._run_event.clear()
            self._state = "error"
            await self._broadcaster.push_state("error", error=str(exc))

        except Exception as exc:
            logger.error("Unexpected error in run loop: %s", exc)
            self._run_event.clear()
            self._state = "error"
            await self._broadcaster.push_state("error", error=str(exc))

        finally:
            # 9. Locked stop sequence: stop_stream -> deactivate -> capture.release
            await self._broadcaster.stop_heartbeat()

            if streaming is not None:
                try:
                    await asyncio.to_thread(streaming.stop_stream)
                except Exception:
                    logger.warning("stop_stream failed (best-effort)")

            if bridge_ip and username and self._config_id:
                await deactivate_entertainment_config(bridge_ip, username, self._config_id)

            if self._device_path:
                try:
                    await asyncio.to_thread(self._capture_registry.release, self._device_path)
                except Exception:
                    logger.warning("Registry release failed (best-effort)")
                self._device_path = None
                self._capture = None

            if self._state not in ("error",):
                self._state = "idle"

    # ------------------------------------------------------------------
    # Internal: channel map
    # ------------------------------------------------------------------

    async def _load_channel_map(
        self, config_id: str, bridge_ip: str, username: str
    ) -> dict:
        """Load channel map: {channel_id: polygon_mask}.

        Uses the light_assignments table for precise per-channel mapping when
        available (auto-mapped regions). Falls back to resolving
        regions.light_id → all channel_ids for manually assigned regions.

        Args:
            config_id: Entertainment configuration UUID.
            bridge_ip: Bridge IP for channel resolution.
            username: Bridge application key.

        Returns:
            dict mapping channel_id (int) to uint8 mask ndarray (480x640).
        """
        # Load explicit channel assignments from light_assignments table
        assign_query = """
            SELECT la.region_id, la.channel_id, r.polygon
            FROM light_assignments la
            JOIN regions r ON r.id = la.region_id
            WHERE la.entertainment_config_id = ?
        """
        async with await self._db.execute(assign_query, (config_id,)) as cursor:
            assignment_rows = await cursor.fetchall()

        channel_map = {}
        assigned_region_ids = set()

        for row in assignment_rows:
            polygon_points = json.loads(row["polygon"])
            mask = build_polygon_mask(polygon_points)
            channel_map[row["channel_id"]] = mask
            assigned_region_ids.add(row["region_id"])

        # Fallback: regions with light_id but no light_assignments entry
        light_to_channels = await resolve_light_to_channel_map(
            bridge_ip, username, config_id
        )

        query = "SELECT id, polygon, light_id FROM regions WHERE light_id IS NOT NULL"
        async with await self._db.execute(query) as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            if row["id"] in assigned_region_ids:
                continue
            light_id = row["light_id"]
            channel_ids = light_to_channels.get(light_id, [])
            if not channel_ids:
                logger.warning(
                    "Region %s has light_id=%s but no matching channels in config %s",
                    row["id"], light_id, config_id,
                )
                continue

            polygon_points = json.loads(row["polygon"])
            mask = build_polygon_mask(polygon_points)
            for channel_id in channel_ids:
                if channel_id not in channel_map:
                    channel_map[channel_id] = mask

        logger.info(
            "Loaded channel map: %d channels (%d from assignments, %d fallback)",
            len(channel_map), len(assignment_rows), len(channel_map) - len(assignment_rows),
        )
        return channel_map

    # ------------------------------------------------------------------
    # Internal: frame loop
    # ------------------------------------------------------------------

    async def _frame_loop(self, streaming, channel_map: dict, bridge_ip: str, username: str) -> None:
        """50 Hz frame loop: extract colors from screen regions and send to Hue lights.

        For each frame:
        - Grab frame from capture
        - For each channel_id, mask in channel_map:
            - extract_region_color -> (r, g, b)
            - rgb_to_xy -> (x, y)
            - compute brightness, clamp to 0.01 minimum
            - smooth toward target using exponential moving average
            - asyncio.to_thread(streaming.set_input, (x, y, bri, channel_id))
        - update_metrics (silent, NOT broadcast -- 1 Hz heartbeat handles delivery)
        - Sleep to maintain ~50 Hz

        Bridge socket errors trigger _reconnect_loop (unlimited retries with
        exponential backoff). Capture RuntimeError stops the loop entirely.
        """
        seq = 0
        packets_sent = 0
        prev_t0 = time.monotonic()

        while self._run_event.is_set():
            t0 = time.monotonic()

            try:
                frame = await self._capture.get_frame()
            except RuntimeError as exc:
                logger.warning("Capture device error: %s, starting reconnect", exc)
                success = await self._capture_reconnect_loop()
                if success:
                    continue
                else:
                    self._state = "error"
                    await self._broadcaster.push_state("error", error=str(exc))
                    return

            t_capture = time.monotonic()
            # How old is this frame? (time since reader thread stored it)
            frame_age = t_capture - self._capture._last_frame_time if self._capture._last_frame_time > 0 else 0

            # Compute colors for all channels and send immediately (no smoothing)
            inputs = []
            for channel_id, mask in channel_map.items():
                r, g, b = extract_region_color(frame, mask)
                x, y = rgb_to_xy(r, g, b)
                bri = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255.0
                bri = max(bri, 0.01)  # dark scene protection
                inputs.append((x, y, bri, channel_id))

            t_color = time.monotonic()

            # Send all channels to bridge synchronously — set_input is a
            # tiny DTLS packet send, thread pool overhead costs more than
            # the brief GIL hold.
            try:
                for inp in inputs:
                    streaming.set_input(inp)
                packets_sent += len(inputs)
            except Exception as exc:
                logger.warning("Bridge socket error: %s, starting reconnect", exc)
                success = await self._reconnect_loop(
                    self._config_id or "", bridge_ip, username
                )
                if not success:
                    return

            t_send = time.monotonic()

            seq += 1
            elapsed = time.monotonic() - t0
            latency_ms = elapsed * 1000.0

            # Log timing breakdown every 60 frames (~1s)
            if seq % 60 == 0:
                print(
                    f"PERF seq={seq} frame_age={frame_age*1000:.1f}ms capture={( t_capture-t0)*1000:.1f}ms color={(t_color-t_capture)*1000:.1f}ms send={(t_send-t_color)*1000:.1f}ms total={latency_ms:.1f}ms",
                    flush=True,
                )

            # FPS = actual loop rate (includes sleep), not just processing speed
            cycle_time = t0 - prev_t0
            prev_t0 = t0

            # Silent metrics update — StatusBroadcaster 1 Hz heartbeat handles delivery
            self._broadcaster.update_metrics({
                "fps": round(1.0 / max(cycle_time, 1e-6), 1) if seq > 1 else self._target_hz,
                "latency_ms": round(latency_ms, 1),
                "packets_sent": packets_sent,
                "seq": seq,
            })

            # Sleep to maintain target Hz
            sleep_time = self._period - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Internal: reconnect
    # ------------------------------------------------------------------

    async def _capture_reconnect_loop(self) -> bool:
        """Reconnect the capture device with exponential backoff.

        Called when get_frame() raises RuntimeError (device disconnected).
        Retries indefinitely while run_event is set.
        Delays: 1s, 2s, 4s, 8s, 16s, 30s (capped).

        capture.open() is called via asyncio.to_thread because cv2.VideoCapture
        is a blocking operation (Pitfall 3 from research).

        Returns:
            True if reconnection succeeded, False if run_event was cleared.
        """
        self._state = "reconnecting"
        await self._broadcaster.push_state(self._state)

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
                await self._broadcaster.push_state(self._state)
                return True
            except Exception as exc:
                logger.warning(
                    "Capture reconnect failed: %s, retrying in %ds", exc, delay
                )
                # Ensure clean state before next attempt
                try:
                    self._capture.release()
                except Exception:
                    pass
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

        return False

    async def _reconnect_loop(
        self, config_id: str, bridge_ip: str, username: str
    ) -> bool:
        """Reconnect to the Hue bridge with exponential backoff.

        Retries indefinitely while run_event is set.
        Delays: 1s, 2s, 4s, 8s, 16s, 30s (capped).

        IMPORTANT: Does NOT touch the capture pipeline. Capture continues
        independently during bridge reconnect (per locked decision).

        Args:
            config_id: Entertainment configuration UUID.
            bridge_ip: Bridge IP address.
            username: Bridge application key.

        Returns:
            True if reconnection succeeded, False if run_event was cleared.
        """
        if not self._run_event.is_set():
            return False

        delay = 1
        max_delay = 30

        while self._run_event.is_set():
            try:
                await activate_entertainment_config(bridge_ip, username, config_id)
                logger.info("Bridge reconnection succeeded")
                return True
            except Exception as exc:
                logger.warning(
                    "Bridge reconnect failed: %s, retrying in %ds", exc, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

        return False
