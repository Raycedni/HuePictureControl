"""WLED UDP realtime streaming primitives.

Module-level constants and packet builders for the DRGB (<=490 LEDs) and
DNRGB (>490 LEDs, 489-LED chunks) protocols documented at
https://kno.wled.ge/interfaces/udp-realtime/.

The WledStreamer class consumes these helpers on every frame and owns
per-device socket lifecycle, the enabled gate (D-12), consecutive-failure
cooldown (D-15), blackout-before-close (D-13), and the health snapshot
payload (D-16).

Exports:
    DRGB_PROTOCOL, DNRGB_PROTOCOL    -- Header byte 0 values
    UDP_PORT                          -- WLED realtime port (21324)
    TIMEOUT_SECONDS                   -- Header byte 1 value (2s per D-14)
    DRGB_MAX_LEDS                     -- 490 (DRGB strip-wide cap)
    DNRGB_MAX_LEDS_PER_PACKET         -- 489 (DNRGB chunk cap; 4-byte header eats 1 LED)
    WLED_FAILURE_COOLDOWN_THRESHOLD   -- Consecutive failures before cooldown (30)
    WLED_COOLDOWN_DURATION_SECONDS    -- Cooldown hold time (30.0s)
    WLED_ERROR_LOG_RATE_LIMIT_SECONDS -- Per-device error log throttle (5.0s)
    build_drgb_packet                 -- Build a single DRGB packet
    build_dnrgb_packets               -- Build a list of DNRGB chunk packets
    build_packets_for_device          -- Auto-select DRGB or DNRGB based on led_count
    WledStreamer                      -- Per-frame UDP sink with lifecycle + cooldown
"""
import asyncio
import logging
import socket
import threading
import time
from datetime import datetime, timezone

import numpy as np

logger = logging.getLogger(__name__)

# WLED protocol constants (verified against kno.wled.ge/interfaces/udp-realtime/)
DRGB_PROTOCOL: int = 0x02
DNRGB_PROTOCOL: int = 0x04
UDP_PORT: int = 21324
TIMEOUT_SECONDS: int = 2            # D-14: strip reverts after 2s of silence
DRGB_MAX_LEDS: int = 490            # 2-byte header + 490*3 body = 1472 bytes
DNRGB_MAX_LEDS_PER_PACKET: int = 489  # 4-byte header + 489*3 body = 1471 bytes


def _colors_to_uint8_array(colors) -> np.ndarray:
    """Coerce input colors to a contiguous (N, 3) uint8 array.

    Accepts the legacy list-of-tuples shape used by existing tests AND a
    pre-built numpy (N, 3) uint8 array produced by the per-frame
    vectorized fill in ``WledStreamer._render_one_device``.

    Quick-task 260516-iqp: the ndarray path skips Python-level
    iteration entirely and lets ``np.ndarray.tobytes()`` emit the
    packet body in C.
    """
    if isinstance(colors, np.ndarray):
        if colors.ndim != 2 or colors.shape[1] != 3:
            raise ValueError(
                f"ndarray colors must be (N, 3); got {colors.shape}"
            )
        return np.ascontiguousarray(colors, dtype=np.uint8)
    # Legacy list-of-tuples path — convert in one np.asarray call.
    return np.asarray(colors, dtype=np.uint8).reshape(-1, 3)


def build_drgb_packet(colors) -> bytes:
    """Build a DRGB packet for a full strip (<=490 LEDs).

    Layout: ``[0x02, 0x02, R0, G0, B0, R1, G1, B1, ...]``

    Header byte 0 is the DRGB protocol marker; byte 1 is the timeout (D-14).
    Body is sequential RGB triplets, one per LED, in RGB order (not BGR).

    Accepts either a list-of-tuples (legacy) or an (N, 3) uint8 ndarray.

    Raises:
        ValueError: if ``len(colors) > 490``.
    """
    arr = _colors_to_uint8_array(colors)
    if arr.shape[0] > DRGB_MAX_LEDS:
        raise ValueError(
            f"DRGB supports at most {DRGB_MAX_LEDS} LEDs, got {arr.shape[0]}"
        )
    header = bytes([DRGB_PROTOCOL, TIMEOUT_SECONDS])
    # arr.tobytes() emits R0 G0 B0 R1 G1 B1 ... in C — replaces the old
    # Python generator + bytes() build that ran one yield per channel.
    return header + arr.tobytes()


def build_dnrgb_packets(colors) -> list[bytes]:
    """Chunk a long strip into DNRGB packets (up to 489 LEDs each).

    Layout per packet: ``[0x04, 0x02, start_hi, start_lo, R0, G0, B0, ...]``
    where ``start_hi``/``start_lo`` is a big-endian uint16 LED index offset.

    Accepts either a list-of-tuples (legacy) or an (N, 3) uint8 ndarray.
    Returns an empty list for empty input. Otherwise one or more packets,
    each ready for a single sendto() call.
    """
    arr = _colors_to_uint8_array(colors)
    n = arr.shape[0]
    packets: list[bytes] = []
    for chunk_start in range(0, n, DNRGB_MAX_LEDS_PER_PACKET):
        chunk = arr[chunk_start : chunk_start + DNRGB_MAX_LEDS_PER_PACKET]
        header = bytes([
            DNRGB_PROTOCOL,
            TIMEOUT_SECONDS,
            (chunk_start >> 8) & 0xFF,
            chunk_start & 0xFF,
        ])
        packets.append(header + chunk.tobytes())
    return packets


def build_packets_for_device(led_count: int, colors) -> list[bytes]:
    """Auto-select DRGB (led_count <= 490) or DNRGB (>490) and return packet list.

    Always returns a list (single-element for DRGB, multi-element for DNRGB)
    so the per-frame send loop has a uniform shape regardless of strip size.

    Accepts either a list-of-tuples or an (N, 3) uint8 ndarray for colors.

    Raises:
        ValueError: if ``len(colors) != led_count`` (caller bug).
    """
    if isinstance(colors, np.ndarray):
        actual_n = colors.shape[0]
    else:
        actual_n = len(colors)
    if actual_n != led_count:
        raise ValueError(
            f"colors length {actual_n} != led_count {led_count}"
        )
    if led_count <= DRGB_MAX_LEDS:
        return [build_drgb_packet(colors)]
    return build_dnrgb_packets(colors)


# ---------------------------------------------------------------------------
# WledStreamer — Per-frame UDP sink with lifecycle, cooldown, and health
# ---------------------------------------------------------------------------

# Tuning constants (Open Question 1 in 17-RESEARCH.md RESOLVED per CONTEXT D-15).
# 30 frames at 60 Hz ~= 0.5s of failures before flagging a bad device. Cooldown
# of 30s caps a misbehaving device's traffic at ~30 packets per minute. Error
# log rate-limited to once per 5s per device to avoid log spam during outages.
WLED_FAILURE_COOLDOWN_THRESHOLD: int = 30
WLED_COOLDOWN_DURATION_SECONDS: float = 30.0
WLED_ERROR_LOG_RATE_LIMIT_SECONDS: float = 5.0


class WledStreamer:
    """UDP sink that streams per-frame RGB data to WLED ESP32 devices.

    Sibling of HueStreamer (D-03) — driven by StreamingCoordinator.render() with
    a dict[region_id, np.ndarray] of sub-sampled gradients per frame.

    Lifecycle::

        streamer = WledStreamer()                       # default port 21324
        # or, for integration tests against a loopback listener:
        streamer = WledStreamer(udp_port=41324)
        await streamer.start([{id, ip, led_count, enabled, channels}])
        await streamer.render({region_id: gradient_ndarray})   # per frame
        await streamer.stop()                                  # blackout + close

    Thread safety:
        ``_devices`` is read by the coordinator task (asyncio loop) and written
        by FastAPI handlers (set_enabled from a thread). All mutations hold
        ``self._lock``; iterations snapshot under the lock and release before
        IO so a slow sendto cannot block a toggle from the HTTP layer.

    Per-device cooldown:
        After ``WLED_FAILURE_COOLDOWN_THRESHOLD`` consecutive send failures,
        a device enters cooldown for ``WLED_COOLDOWN_DURATION_SECONDS``.
        ``render()`` skips cooldown devices; the cooldown auto-clears at the
        next render() that occurs past ``in_cooldown_until``.
    """

    def __init__(self, udp_port: int = UDP_PORT) -> None:
        """Create a new streamer.

        Args:
            udp_port: Destination UDP port for WLED realtime packets.
                Defaults to the module-level ``UDP_PORT`` constant (21324).
                Plan 06 integration tests pass ``udp_port=41324`` to redirect
                packets to a loopback ``udp_listener`` without monkey-patching
                module state (chosen over ``patch.object(module, "UDP_PORT")``
                to keep tests hermetic — see Plan 06 preamble).
        """
        self._devices: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._started: bool = False
        self._udp_port: int = udp_port

    async def start(self, device_rows: list[dict]) -> None:
        """Create one SOCK_DGRAM socket per device. Idempotent only when stopped.

        Raises:
            RuntimeError: if start() is called twice without stop() between.
        """
        if self._started:
            raise RuntimeError(
                "WledStreamer.start called while already running; call stop() first"
            )
        with self._lock:
            for row in device_rows:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setblocking(False)
                self._devices[row["id"]] = {
                    "ip": row["ip"],
                    "led_count": int(row["led_count"]),
                    "enabled": bool(row["enabled"]),
                    "channels": row.get("channels", []),
                    "socket": sock,
                    "last_error": None,
                    "last_success_at": None,
                    "consecutive_failures": 0,
                    "in_cooldown_until": 0.0,
                    "last_error_log_at": 0.0,
                }
            self._started = True

    async def stop(self) -> None:
        """D-13 stop sequence: blackout packet then close each socket."""
        with self._lock:
            device_ids = list(self._devices.keys())
        for dev_id in device_ids:
            await self._blackout_and_close(dev_id)
        with self._lock:
            self._devices.clear()
            self._started = False

    async def _blackout_and_close(self, device_id: str) -> None:
        """Send a single zeroed DRGB/DNRGB packet then close the socket (best-effort)."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return
            sock = dev["socket"]
            ip = dev["ip"]
            led_count = dev["led_count"]
            enabled = dev["enabled"]
            in_cooldown = time.monotonic() < dev["in_cooldown_until"]

        if enabled and not in_cooldown and led_count > 0:
            packets = build_packets_for_device(led_count, [(0, 0, 0)] * led_count)
            port = self._udp_port

            def _send_all() -> None:
                for pkt in packets:
                    try:
                        sock.sendto(pkt, (ip, port))
                    except (OSError, BlockingIOError):
                        # best-effort blackout — swallow per D-13 / Pitfall 7
                        pass

            try:
                await asyncio.to_thread(_send_all)
            except Exception:
                # Never let a blackout failure prevent socket close
                pass

        try:
            sock.close()
        except OSError:
            pass

    def set_enabled(self, device_id: str, enabled: bool) -> None:
        """Toggle the per-device UDP-send gate (D-12). Safe from any thread.

        No-op if ``device_id`` is unknown — set_enabled mirrors a DB row that
        may have been removed from the streamer's view between calls.
        """
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return
            dev["enabled"] = bool(enabled)

    def health_snapshot(self) -> dict:
        """Return D-16 payload: ``{device_id: {last_error, last_success_at, in_cooldown}}``."""
        now = time.monotonic()
        with self._lock:
            return {
                dev_id: {
                    "last_error": dev["last_error"],
                    "last_success_at": dev["last_success_at"],
                    "in_cooldown": now < dev["in_cooldown_until"],
                }
                for dev_id, dev in self._devices.items()
            }

    async def render(self, region_gradients: dict) -> None:
        """Per-frame fan-out to all enabled, non-cooldown devices.

        Concurrent per-device via ``asyncio.gather`` per 17-RESEARCH.md Open
        Question 4 (RESOLVED): one slow device must never block another (D-06
        per-device isolation). Each device's send runs in its own
        ``asyncio.to_thread`` batch — one to_thread call per device per frame
        (NOT per packet, per anti-pattern note).

        Args:
            region_gradients: ``{region_id: np.ndarray of shape (N_region, 3),
                dtype uint8}``. Each device's channels reference a region_id;
                the channel's ``[start_led, end_led]`` slice is filled from the
                gradient via linear sub-sampling (D-10).
        """
        now = time.monotonic()
        with self._lock:
            # Snapshot targets under the lock; release before IO.
            plan: list[tuple[str, dict]] = []
            for dev_id, dev in self._devices.items():
                if not dev["enabled"]:
                    continue
                if now < dev["in_cooldown_until"]:
                    continue
                plan.append((dev_id, {
                    "ip": dev["ip"],
                    "led_count": dev["led_count"],
                    "channels": list(dev["channels"]),
                    "socket": dev["socket"],
                }))

        if not plan:
            return

        # Fire sends concurrently per device (bounded by len(plan)).
        await asyncio.gather(*(
            self._render_one_device(dev_id, snap, region_gradients)
            for dev_id, snap in plan
        ), return_exceptions=False)

    async def _render_one_device(
        self, device_id: str, snap: dict, region_gradients: dict
    ) -> None:
        """Build and send packets for one device in a single to_thread batch.

        Quick-task 260516-iqp: the per-LED Python loop that built a
        list-of-tuples is replaced with one numpy fill per channel:
        ``colors[start:end+1] = slice_arr`` after computing the LED range
        intersected with [0, led_count). ``build_packets_for_device``
        accepts the (led_count, 3) uint8 buffer directly and uses
        ``tobytes()`` to emit packet bodies in C.
        """
        led_count = snap["led_count"]
        if led_count <= 0:
            return

        # quick-task 260516-kra: per-frame read of the global brightness
        # cutoff. 0.0 = disabled (default). `_app_state` may be absent in
        # unit tests that exercise WledStreamer directly without going
        # through the coordinator wiring; we read defensively via getattr.
        threshold = 0.0
        app_state = getattr(self, "_app_state", None)
        if app_state is not None:
            try:
                threshold = float(
                    getattr(app_state, "brightness_cutoff_threshold", 0.0)
                )
            except (TypeError, ValueError):
                threshold = 0.0

        colors = np.zeros((led_count, 3), dtype=np.uint8)
        populated = False
        for ch in snap["channels"]:
            region_id = ch.get("region_id")
            if region_id is None:
                continue
            gradient = region_gradients.get(region_id)
            if gradient is None:
                continue
            start = int(ch["start_led"])
            end = int(ch["end_led"])
            range_len = end - start + 1
            if range_len <= 0:
                continue
            src_n = len(gradient)
            if src_n == 0:
                continue
            if src_n == range_len:
                slice_arr = gradient
            elif src_n == 1:
                # Single-color region — broadcast the same color across the range
                slice_arr = np.broadcast_to(
                    np.asarray(gradient[0], dtype=np.uint8), (range_len, 3)
                )
            else:
                # Resample the gradient along its first axis to match range_len (D-10).
                idx = np.linspace(0, src_n - 1, range_len).astype(np.int32)
                slice_arr = gradient[idx]

            # quick-task 260516-kra: per-channel brightness gating. Decision
            # is per-region (compute mean Rec.709 luma of the SOURCE
            # gradient, not the resampled slice — keeps the cost O(N_region)
            # not O(led_count) for short regions painted to long ranges).
            # When threshold == 0.0 we skip the luma compute entirely so
            # users who never enable the feature pay zero per-frame cost.
            if threshold > 0.0:
                mean_rgb = gradient.mean(axis=0)
                luma = (
                    float(mean_rgb[0]) * 0.2126
                    + float(mean_rgb[1]) * 0.7152
                    + float(mean_rgb[2]) * 0.0722
                ) / 255.0
                if luma < threshold:
                    # Zero this channel's LED range. np.zeros((range_len, 3),
                    # uint8) replaces slice_arr — the subsequent intersect-
                    # and-clip math then writes zeros into `colors`.
                    slice_arr = np.zeros((range_len, 3), dtype=np.uint8)

            # Intersect [start, end] with [0, led_count) in one slice op.
            clip_lo = max(start, 0)
            clip_hi = min(start + range_len, led_count)
            if clip_hi <= clip_lo:
                continue
            src_lo = clip_lo - start
            src_hi = src_lo + (clip_hi - clip_lo)
            colors[clip_lo:clip_hi] = np.asarray(
                slice_arr[src_lo:src_hi], dtype=np.uint8
            )
            populated = True

        if not populated:
            return  # no channels in this device matched the frame's regions

        packets = build_packets_for_device(led_count, colors)
        sock = snap["socket"]
        ip = snap["ip"]
        port = self._udp_port  # respects constructor override for tests

        def _send_all() -> None:
            for pkt in packets:
                sock.sendto(pkt, (ip, port))

        try:
            await asyncio.to_thread(_send_all)
            self._mark_success(device_id)
        except (OSError, BlockingIOError) as exc:
            self._mark_failure(device_id, exc)

    def _mark_success(self, device_id: str) -> None:
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return
            dev["last_error"] = None
            dev["last_success_at"] = datetime.now(timezone.utc).isoformat()
            dev["consecutive_failures"] = 0

    def _mark_failure(self, device_id: str, exc: BaseException) -> None:
        now_mono = time.monotonic()
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return
            dev["consecutive_failures"] += 1
            dev["last_error"] = f"{type(exc).__name__}: {exc}"
            # Rate-limited log to avoid spam during sustained outages.
            if now_mono - dev["last_error_log_at"] >= WLED_ERROR_LOG_RATE_LIMIT_SECONDS:
                logger.warning(
                    "WLED send failure for device %s (%s): %s",
                    device_id, dev["ip"], dev["last_error"],
                )
                dev["last_error_log_at"] = now_mono
            if dev["consecutive_failures"] >= WLED_FAILURE_COOLDOWN_THRESHOLD:
                dev["in_cooldown_until"] = now_mono + WLED_COOLDOWN_DURATION_SECONDS
                logger.info(
                    "WLED device %s entered cooldown for %.0fs",
                    device_id, WLED_COOLDOWN_DURATION_SECONDS,
                )
