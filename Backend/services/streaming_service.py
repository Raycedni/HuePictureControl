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

from services.color_math import extract_region_color, rgb_to_xy, build_polygon_mask
from services.hue_client import activate_entertainment_config, deactivate_entertainment_config

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

    Capture card disconnect stops streaming entirely and pushes an error state
    to the broadcaster.
    """

    TARGET_HZ = 50
    PERIOD = 1.0 / TARGET_HZ

    def __init__(self, db, capture, broadcaster) -> None:
        self._db = db
        self._capture = capture
        self._broadcaster = broadcaster
        self._run_event: asyncio.Event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._state: str = "idle"
        self._config_id: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Current streaming state: idle | starting | streaming | stopping | error."""
        return self._state

    async def start(self, config_id: str) -> None:
        """Start the streaming loop for the given entertainment config ID.

        No-op if already streaming (state not idle or error).

        Transitions: idle/error -> starting -> streaming (inside run loop)

        Args:
            config_id: UUID of the Hue entertainment configuration to stream to.
        """
        if self._state not in ("idle", "error"):
            return
        self._config_id = config_id
        self._state = "starting"
        await self._broadcaster.push_state(self._state)
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
            channel_map = await self._load_channel_map(config_id)

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

            self._capture.release()

            if self._state not in ("error",):
                self._state = "idle"

    # ------------------------------------------------------------------
    # Internal: channel map
    # ------------------------------------------------------------------

    async def _load_channel_map(self, config_id: str) -> dict:
        """Load channel map from SQLite: {channel_id: polygon_mask}.

        Executes:
            SELECT la.channel_id, r.polygon
            FROM light_assignments la
            JOIN regions r ON la.region_id = r.id
            WHERE la.entertainment_config_id = ?

        Returns:
            dict mapping channel_id (int) to uint8 mask ndarray (480x640).
        """
        query = """
            SELECT la.channel_id, r.polygon
            FROM light_assignments la
            JOIN regions r ON la.region_id = r.id
            WHERE la.entertainment_config_id = ?
        """
        async with await self._db.execute(query, (config_id,)) as cursor:
            rows = await cursor.fetchall()

        channel_map = {}
        for row in rows:
            channel_id = row["channel_id"]
            polygon_points = json.loads(row["polygon"])
            mask = build_polygon_mask(polygon_points)
            channel_map[channel_id] = mask

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
            - asyncio.to_thread(streaming.set_input, (x, y, bri, channel_id))
        - update_metrics (silent, NOT broadcast -- 1 Hz heartbeat handles delivery)
        - Sleep to maintain ~50 Hz

        Bridge socket errors trigger _reconnect_loop (unlimited retries with
        exponential backoff). Capture RuntimeError stops the loop entirely.
        """
        seq = 0
        packets_sent = 0

        while self._run_event.is_set():
            t0 = time.monotonic()

            try:
                frame = await self._capture.get_frame()
            except RuntimeError as exc:
                logger.error("Capture device error: %s", exc)
                self._run_event.clear()
                self._state = "error"
                await self._broadcaster.push_state("error", error=str(exc))
                return

            # Process each channel in the map
            for channel_id, mask in channel_map.items():
                r, g, b = extract_region_color(frame, mask)
                x, y = rgb_to_xy(r, g, b)

                # Perceived luminance (BT.601 coefficients), normalized to [0, 1]
                bri = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255.0
                bri = max(bri, 0.01)  # dark scene protection

                try:
                    await asyncio.to_thread(streaming.set_input, (x, y, bri, channel_id))
                    packets_sent += 1
                except Exception as exc:
                    logger.warning("Bridge socket error: %s, starting reconnect", exc)
                    success = await self._reconnect_loop(
                        self._config_id or "", bridge_ip, username
                    )
                    if not success:
                        return

            seq += 1
            elapsed = time.monotonic() - t0
            latency_ms = elapsed * 1000.0

            # Silent metrics update — StatusBroadcaster 1 Hz heartbeat handles delivery
            self._broadcaster.update_metrics({
                "fps": round(1.0 / max(elapsed, 1e-6), 1),
                "latency_ms": round(latency_ms, 1),
                "packets_sent": packets_sent,
                "seq": seq,
            })

            # Sleep to maintain target Hz
            sleep_time = self.PERIOD - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Internal: reconnect
    # ------------------------------------------------------------------

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
