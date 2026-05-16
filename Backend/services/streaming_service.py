"""HueStreamer: DTLS sink that streams per-frame RGB to the Hue bridge via pykit.

Refactored from the former ``StreamingService`` (Phase 17 Plan 05). Capture
lifecycle, broadcaster orchestration, and the 60 Hz frame loop moved to
``StreamingCoordinator`` (services/streaming_coordinator.py). This class owns
only the Hue-specific concerns: bridge creation, Entertainment API
activation/deactivation, DTLS stream start/stop, batched per-frame DTLS send,
and Hue-only reconnect.

The coordinator produces ``region_gradients: dict[region_id, (N, 3) uint8]``
once per frame and calls ``HueStreamer.render(region_gradients)``. Hue
averages the per-region gradient back to a single RGB per channel
(``gradient.mean(axis=0)``), preserving the pre-refactor single-color
behavior — N=1 for Hue-only regions is the trivial case (Plan 05).

Quick-task 260516-iqp: render() now assembles ONE DTLS message containing
all channel records concatenated and sends it directly via the pykit
DTLS socket — bypassing pykit's per-channel ``set_input`` queue/thread that
was producing N× DTLS packets per frame plus N× ``logger.info`` calls per
frame. Hue Entertainment v2 channel records are 7 bytes each
([ch_id u8][x u16_be][y u16_be][b u16_be]) and are legal to concatenate
in a single message (the pykit `_send_color_to_light` builds the same
header — we just emit multiple records in one body).

Exports:
    HueStreamer -- DTLS sink; one instance per coordinator.
"""
import asyncio
import json
import logging
import struct

import numpy as np

from hue_entertainment_pykit import create_bridge, Entertainment, Streaming

from services.color_math import (
    build_polygon_mask,
    rgb_to_xy,
    rgb_to_xy_batch,
)
from services.hue_client import (
    activate_entertainment_config,
    deactivate_entertainment_config,
    resolve_light_to_channel_map,
)

logger = logging.getLogger(__name__)


class HueStreamer:
    """Hue DTLS sink: bridge + Entertainment API + per-channel set_input.

    Lifecycle is owned by ``StreamingCoordinator``::

        sink = HueStreamer(db)
        await sink.start(config_id)            # bridge + DTLS + channel map
        # per frame:
        await sink.render(region_gradients)
        # on bridge socket error:
        ok = await sink.handle_bridge_error(exc)
        await sink.stop()                      # stop_stream + deactivate

    No capture, no broadcaster, no run loop — coordinator owns those.
    """

    # Hue Entertainment v2 message header — mirrors pykit
    # StreamingService._build_message but emitted ONCE per frame with all
    # channel records concatenated instead of one message per channel.
    _HEADER_PROTOCOL = b"HueStream"
    _HEADER_VERSION = b"\x02\x00"
    _HEADER_SEQ = b"\x07"
    _HEADER_RESERVED = b"\x00\x00"
    _HEADER_COLOR_SPACE_XYB = b"\x01"
    _HEADER_RESERVED2 = b"\x00"

    def __init__(self, db) -> None:
        self._db = db
        self._streaming = None
        self._dtls_socket = None
        self._entertainment_id_bytes: bytes = b""
        self._bridge_ip: str = ""
        self._username: str = ""
        self._config_id: str | None = None
        self._channel_map: dict = {}            # channel_id -> RegionMask
        self._channel_to_region: dict = {}      # channel_id -> region_id

    # ------------------------------------------------------------------
    # Public API (called by StreamingCoordinator)
    # ------------------------------------------------------------------

    async def start(self, config_id: str) -> None:
        """Hue bridge + DTLS + channel map setup. No capture, no frame loop.

        Lifted verbatim from the former ``StreamingService`` run-loop
        bridge-setup block (streaming_service.py lines 206-248 pre-refactor).
        Order preserved so existing integration behavior is unchanged:
        bridge_config SELECT -> create_bridge -> Entertainment -> configs.get
        -> repo -> Streaming() -> activate_entertainment_config -> start_stream
        -> set_color_space("xyb").
        """
        self._config_id = config_id

        # 1. Load bridge credentials
        async with await self._db.execute(
            "SELECT * FROM bridge_config WHERE id = 1"
        ) as cursor:
            bridge_row = await cursor.fetchone()

        self._bridge_ip = bridge_row["ip_address"]
        self._username = bridge_row["username"]
        client_key = bridge_row["client_key"]
        rid = bridge_row["rid"]
        bridge_id = bridge_row["bridge_id"]
        hue_app_id = bridge_row["hue_app_id"]
        swversion = bridge_row["swversion"]
        name = bridge_row["name"]

        # 2. Load channel map once (masks are constant for a given config).
        #    This runs independently of the coordinator's _build_region_plan —
        #    self._load_channel_map builds {channel_id: RegionMask} for Hue
        #    set_input; the coordinator's region_plan builds
        #    {region_id: (mask, N_region)} for sub_sample_gradient. Both
        #    queries run at stream start and meet at the per-frame render call.
        #    See <query_responsibilities> in 17-05-PLAN.md.
        channel_map = await self._load_channel_map(
            config_id, self._bridge_ip, self._username
        )
        self._channel_map = channel_map
        # Build the parallel channel_id -> region_id map needed by render().
        self._channel_to_region = await self._load_channel_to_region(
            config_id, self._bridge_ip, self._username
        )

        # 3. Build pykit objects
        bridge = create_bridge(
            identification=bridge_id,
            rid=rid,
            ip_address=self._bridge_ip,
            username=self._username,
            hue_app_id=hue_app_id,
            clientkey=client_key,
            swversion=swversion,
            name=name,
        )
        entertainment = Entertainment(bridge)
        configs = entertainment.get_entertainment_configs()
        config = configs.get(config_id) or list(configs.values())[0]
        repo = entertainment.get_ent_conf_repo()
        self._streaming = Streaming(bridge, config, repo)

        # 4. Activate entertainment config via REST
        await activate_entertainment_config(
            self._bridge_ip, self._username, config_id
        )

        # 5. Start DTLS stream
        await asyncio.to_thread(self._streaming.start_stream)

        # 6. Set color space to xyb
        await asyncio.to_thread(self._streaming.set_color_space, "xyb")

        # 7. Grab the live DTLS socket + entertainment_id for the batched
        #    render() path. We send full multi-channel frames directly via
        #    this socket instead of pykit's per-channel set_input queue.
        #    pykit's _keep_connection_alive thread continues to read
        #    self._streaming._last_message — render() updates that field
        #    after each batched send so keep-alive retransmits the latest
        #    frame, not the empty init message.
        try:
            self._dtls_socket = (
                self._streaming._dtls_service.get_socket()
            )
            self._entertainment_id_bytes = (
                self._streaming._entertainment_id
            )
        except AttributeError:
            # Fallback path for environments where pykit internals are mocked
            # in tests — render() will fall back to per-channel set_input.
            self._dtls_socket = None
            self._entertainment_id_bytes = b""

    async def render(self, region_gradients: dict) -> None:
        """Per frame: build ONE batched DTLS message with all channels and send.

        ``region_gradients``: ``{region_id: np.ndarray of shape (N, 3) uint8}``.

        Quick-task 260516-iqp: the pre-2026-05 code called pykit
        ``set_input`` per channel; pykit's background thread then popped
        each queue entry and built a fresh DTLS message containing a
        single channel record. That produced N× DTLS round trips per
        frame (6× at our typical 6-channel config) plus N×
        ``logger.info`` calls per frame. Now we build one Hue
        Entertainment v2 frame containing every channel record and send
        it directly via the pykit DTLS socket. ``_last_message`` is
        updated so pykit's keep-alive thread retransmits the latest
        frame during idle gaps (>9.5s without a render).

        The Hue sink averages the N-point gradient back to a single RGB per
        channel per D-05 — preserved bit-for-bit so Hue-only regions stay
        unchanged.
        """
        if self._streaming is None:
            return

        # 1. Collect (channel_id, xy, bri) for every channel that has a
        #    matching region gradient. Skip channels with no gradient (same
        #    as the pre-batch behavior).
        #
        #    Microbench note: scalar rgb_to_xy for 6 channels takes ~16us
        #    total — faster than rgb_to_xy_batch's ~56us per-call overhead
        #    at small N (numpy broadcasting + per-row gamut projection
        #    dominate). For typical Hue configs (≤16 channels) we stay
        #    scalar. rgb_to_xy_batch remains exported for callers that
        #    want bulk conversion (e.g. potential future WLED gamma path).
        records = bytearray()
        fallback_inputs: list = []
        any_channel = False
        for channel_id, region_id in self._channel_to_region.items():
            gradient = region_gradients.get(region_id)
            if gradient is None or len(gradient) == 0:
                continue
            mean_rgb = gradient.mean(axis=0)
            r = int(mean_rgb[0])
            g = int(mean_rgb[1])
            b = int(mean_rgb[2])
            x, y = rgb_to_xy(r, g, b)
            bri = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 255.0
            if bri < 0.01:
                bri = 0.01  # dark-scene floor
            any_channel = True

            if self._dtls_socket is None or not self._entertainment_id_bytes:
                # Test-friendly fallback: pykit internals are mocked away.
                fallback_inputs.append(
                    (float(x), float(y), float(bri), channel_id)
                )
                continue

            x_u16 = int(max(0.0, min(1.0, x)) * 65535)
            y_u16 = int(max(0.0, min(1.0, y)) * 65535)
            b_u16 = int(max(0.0, min(1.0, bri)) * 65535)
            records += struct.pack(">BHHH", int(channel_id), x_u16, y_u16, b_u16)

        if not any_channel:
            return

        # 2. Fallback path: real bridge sessions always have a captured
        #    DTLS socket; tests that mock self._streaming without wiring
        #    up the socket keep working via per-channel set_input.
        if fallback_inputs:
            for inp in fallback_inputs:
                self._streaming.set_input(inp)
            return

        # 3. Batched send.
        message = self._build_dtls_message(bytes(records))

        # 4. Send once. asyncio.to_thread keeps the event loop responsive
        #    if the DTLS write briefly blocks.
        sock = self._dtls_socket
        await asyncio.to_thread(sock.send, message)

        # 5. Keep pykit's keep-alive thread retransmitting the latest
        #    frame instead of the empty init message.
        try:
            self._streaming._last_message = message
        except AttributeError:
            pass

    def _build_dtls_message(self, channel_records: bytes) -> bytes:
        """Assemble a Hue Entertainment v2 message body for one frame.

        Mirrors pykit ``StreamingService._build_message`` exactly: the
        16-byte header layout (HueStream + v2 + seq + reserved +
        color_space + reserved2 + entertainment_id) is identical so we
        share the bridge's parser without modification. Only difference
        from pykit: ``channel_records`` may concatenate multiple records,
        not just one.
        """
        return (
            self._HEADER_PROTOCOL
            + self._HEADER_VERSION
            + self._HEADER_SEQ
            + self._HEADER_RESERVED
            + self._HEADER_COLOR_SPACE_XYB
            + self._HEADER_RESERVED2
            + self._entertainment_id_bytes
            + channel_records
        )

    async def stop(self) -> None:
        """Stop DTLS and deactivate; no capture release (coordinator owns that)."""
        if self._streaming is not None:
            try:
                await asyncio.to_thread(self._streaming.stop_stream)
            except Exception:
                logger.warning("stop_stream failed (best-effort)")
            self._streaming = None
        if self._bridge_ip and self._username and self._config_id:
            try:
                await deactivate_entertainment_config(
                    self._bridge_ip, self._username, self._config_id
                )
            except Exception:
                logger.warning(
                    "deactivate_entertainment_config failed (best-effort)"
                )

    async def handle_bridge_error(self, exc: BaseException) -> bool:
        """Invoke the Hue-only reconnect loop. Returns True on success.

        Called by ``StreamingCoordinator._frame_loop`` when ``render`` raises
        a bridge socket error. Capture pipeline is NOT touched (per Phase 16
        locked decision).
        """
        logger.warning("Bridge socket error: %s, starting reconnect", exc)
        return await self._reconnect_loop(
            self._config_id or "", self._bridge_ip, self._username
        )

    # ------------------------------------------------------------------
    # Internal: channel map (Hue-only DB queries)
    # ------------------------------------------------------------------

    async def _load_channel_map(
        self, config_id: str, bridge_ip: str, username: str
    ) -> dict:
        """Load channel map: {channel_id: RegionMask}.

        Uses the light_assignments table for precise per-channel mapping when
        available (auto-mapped regions). Falls back to resolving
        regions.light_id → all channel_ids for manually assigned regions.
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

        channel_map: dict = {}
        assigned_region_ids: set = set()

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
            len(channel_map),
            len(assignment_rows),
            len(channel_map) - len(assignment_rows),
        )
        return channel_map

    async def _load_channel_to_region(
        self, config_id: str, bridge_ip: str, username: str
    ) -> dict:
        """Load {channel_id: region_id} mapping for render().

        Mirrors ``_load_channel_map``'s SELECT but projects ``region_id``
        alongside ``channel_id``. For the fallback branch (regions with
        ``light_id`` but no explicit ``light_assignments`` row), the same
        region.id is reused for every channel produced by
        ``resolve_light_to_channel_map``.
        """
        assign_query = """
            SELECT la.region_id, la.channel_id
            FROM light_assignments la
            JOIN regions r ON r.id = la.region_id
            WHERE la.entertainment_config_id = ?
        """
        async with await self._db.execute(assign_query, (config_id,)) as cursor:
            assignment_rows = await cursor.fetchall()

        channel_to_region: dict = {}
        assigned_region_ids: set = set()

        for row in assignment_rows:
            channel_to_region[row["channel_id"]] = row["region_id"]
            assigned_region_ids.add(row["region_id"])

        # Fallback: regions with light_id but no light_assignments entry
        light_to_channels = await resolve_light_to_channel_map(
            bridge_ip, username, config_id
        )

        query = "SELECT id, light_id FROM regions WHERE light_id IS NOT NULL"
        async with await self._db.execute(query) as cursor:
            rows = await cursor.fetchall()

        for row in rows:
            region_id = row["id"]
            if region_id in assigned_region_ids:
                continue
            light_id = row["light_id"]
            channel_ids = light_to_channels.get(light_id, [])
            if not channel_ids:
                continue
            for channel_id in channel_ids:
                if channel_id not in channel_to_region:
                    channel_to_region[channel_id] = region_id

        return channel_to_region

    # ------------------------------------------------------------------
    # Internal: bridge reconnect (Hue-only — capture is the coordinator's)
    # ------------------------------------------------------------------

    async def _reconnect_loop(
        self, config_id: str, bridge_ip: str, username: str
    ) -> bool:
        """Reconnect to the Hue bridge with exponential backoff.

        Retries indefinitely while caller is still streaming.
        Delays: 1s, 2s, 4s, 8s, 16s, 30s (capped).

        IMPORTANT: Does NOT touch the capture pipeline. Capture continues
        independently during bridge reconnect (per locked decision).

        The pre-refactor StreamingService gated this loop on its run-event;
        that event lives on the coordinator post-refactor. HueStreamer can't
        see when the coordinator wants to shut down, so the loop instead
        retries until ``activate_entertainment_config`` succeeds. The
        coordinator cancels the parent task on stop(), which cancels the
        awaited ``asyncio.sleep`` and bubbles a CancelledError out of this
        loop — the standard cooperative-cancel pattern for sink-side
        reconnects.
        """
        delay = 1
        max_delay = 30

        while True:
            try:
                await activate_entertainment_config(
                    bridge_ip, username, config_id
                )
                logger.info("Bridge reconnection succeeded")
                return True
            except Exception as exc:
                logger.warning(
                    "Bridge reconnect failed: %s, retrying in %ds", exc, delay
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)
