"""Unit tests for WledStreamer (Plan 17-04).

Task 1 covers lifecycle (start/stop), set_enabled gate, health_snapshot payload
shape, lock discipline, and the udp_port constructor kwarg (chosen over
monkey-patching module-level UDP_PORT for hermetic loopback integration tests).

Task 2 covers render() per-frame fan-out: DRGB/DNRGB packet emission, disabled
gate (zero packets), multi-channel slicing, asyncio.gather concurrency,
30-failure cooldown trigger, 30-second auto-clear, blackout-on-stop, and
ISO-8601 last_success_at timestamps. Render-tests use udp_listener on port
41324 with WledStreamer(udp_port=41324) — no module patching.
"""
import asyncio
import threading
import time

import numpy as np
import pytest

from services.wled_streamer import UDP_PORT, WledStreamer
from tests.fixtures.wled_loopback import udp_listener


def _row(id_="d1", ip="127.0.0.1", led_count=10, enabled=True, channels=None):
    if channels is None:
        channels = [{"id": "c1", "region_id": "r1", "start_led": 0, "end_led": led_count - 1}]
    return {
        "id": id_,
        "ip": ip,
        "led_count": led_count,
        "enabled": enabled,
        "channels": channels,
    }


def test_default_udp_port_is_21324():
    s = WledStreamer()
    assert s._udp_port == UDP_PORT == 21324


def test_udp_port_override_constructor_kwarg():
    s = WledStreamer(udp_port=41324)
    assert s._udp_port == 41324


@pytest.mark.asyncio
async def test_start_creates_socket_per_device():
    streamer = WledStreamer()
    await streamer.start([_row()])
    snap = streamer.health_snapshot()
    assert "d1" in snap
    assert snap["d1"]["in_cooldown"] is False
    assert snap["d1"]["last_error"] is None
    await streamer.stop()


@pytest.mark.asyncio
async def test_start_empty_is_noop():
    streamer = WledStreamer()
    await streamer.start([])
    assert streamer.health_snapshot() == {}
    await streamer.stop()


@pytest.mark.asyncio
async def test_start_twice_raises():
    streamer = WledStreamer()
    await streamer.start([_row()])
    with pytest.raises(RuntimeError):
        await streamer.start([_row()])
    await streamer.stop()


@pytest.mark.asyncio
async def test_stop_without_start_is_safe():
    streamer = WledStreamer()
    await streamer.stop()  # must not raise


@pytest.mark.asyncio
async def test_set_enabled_toggle():
    streamer = WledStreamer()
    await streamer.start([_row()])
    streamer.set_enabled("d1", False)
    with streamer._lock:
        assert streamer._devices["d1"]["enabled"] is False
    streamer.set_enabled("d1", True)
    with streamer._lock:
        assert streamer._devices["d1"]["enabled"] is True
    streamer.set_enabled("unknown", True)  # no-op, must not raise
    await streamer.stop()


@pytest.mark.asyncio
async def test_health_snapshot_shape():
    streamer = WledStreamer()
    await streamer.start([_row()])
    snap = streamer.health_snapshot()
    assert set(snap.keys()) == {"d1"}
    assert set(snap["d1"].keys()) == {"last_error", "last_success_at", "in_cooldown"}
    await streamer.stop()


@pytest.mark.asyncio
async def test_lock_discipline_under_concurrent_toggle_and_snapshot():
    streamer = WledStreamer()
    await streamer.start([_row(id_=f"d{i}") for i in range(5)])
    stop_flag = threading.Event()

    def toggle_loop():
        while not stop_flag.is_set():
            streamer.set_enabled("d0", True)
            streamer.set_enabled("d0", False)

    t = threading.Thread(target=toggle_loop, daemon=True)
    t.start()
    try:
        for _ in range(1000):
            snap = streamer.health_snapshot()
            assert "d0" in snap
    finally:
        stop_flag.set()
        t.join(timeout=1.0)
    await streamer.stop()


# ---------------------------------------------------------------------------
# Task 2: render() per-frame fan-out
# ---------------------------------------------------------------------------

LOOPBACK_PORT = 41324


def _gradient(n, rgb):
    """Build an (n, 3) ndarray of the given RGB triplet."""
    return np.tile(np.array(rgb, dtype=np.uint8), (n, 1))


@pytest.mark.asyncio
async def test_render_sends_drgb_for_small_strip():
    with udp_listener(port=LOOPBACK_PORT) as q:
        streamer = WledStreamer(udp_port=LOOPBACK_PORT)
        await streamer.start([_row(led_count=10, channels=[
            {"id": "c1", "region_id": "r1", "start_led": 0, "end_led": 9},
        ])])
        try:
            await streamer.render({"r1": _gradient(10, [255, 0, 0])})
            await asyncio.sleep(0.05)
            pkt = q.get(timeout=1.0)
            assert pkt.data[0] == 0x02, f"expected DRGB protocol, got {pkt.data[0]:#x}"
            assert pkt.data[1] == 0x02, f"expected timeout byte 0x02, got {pkt.data[1]:#x}"
            assert len(pkt.data) == 2 + 10 * 3
            for i in range(10):
                assert pkt.data[2 + i * 3 : 2 + (i + 1) * 3] == bytes([255, 0, 0])
        finally:
            await streamer.stop()


@pytest.mark.asyncio
async def test_render_skips_disabled_device():
    with udp_listener(port=LOOPBACK_PORT) as q:
        streamer = WledStreamer(udp_port=LOOPBACK_PORT)
        await streamer.start([_row(enabled=False)])
        try:
            await streamer.render({"r1": _gradient(10, [255, 0, 0])})
            await asyncio.sleep(0.1)
            assert q.empty(), "disabled device should send zero packets"
        finally:
            await streamer.stop()


@pytest.mark.asyncio
async def test_render_dnrgb_for_large_strip():
    with udp_listener(port=LOOPBACK_PORT) as q:
        streamer = WledStreamer(udp_port=LOOPBACK_PORT)
        await streamer.start([_row(led_count=500, channels=[
            {"id": "c1", "region_id": "r1", "start_led": 0, "end_led": 499},
        ])])
        try:
            await streamer.render({"r1": _gradient(500, [0, 255, 0])})
            await asyncio.sleep(0.1)
            packets = []
            while not q.empty():
                packets.append(q.get_nowait())
            assert len(packets) == 2, f"expected 2 DNRGB packets, got {len(packets)}"
            assert packets[0].data[0] == 0x04
            assert packets[0].data[1] == 0x02
            assert packets[0].data[2:4] == bytes([0x00, 0x00])
            assert packets[1].data[2:4] == bytes([0x01, 0xE9])  # start = 489
        finally:
            await streamer.stop()


@pytest.mark.asyncio
async def test_render_two_devices_concurrent():
    """Both devices receive packets in the same render() call (asyncio.gather)."""
    with udp_listener(port=LOOPBACK_PORT) as q:
        streamer = WledStreamer(udp_port=LOOPBACK_PORT)
        await streamer.start([
            _row(id_="dA", led_count=10, channels=[
                {"id": "cA", "region_id": "r1", "start_led": 0, "end_led": 9},
            ]),
            _row(id_="dB", led_count=10, channels=[
                {"id": "cB", "region_id": "r1", "start_led": 0, "end_led": 9},
            ]),
        ])
        try:
            await streamer.render({"r1": _gradient(10, [128, 128, 128])})
            await asyncio.sleep(0.1)
            packets = []
            while not q.empty():
                packets.append(q.get_nowait())
            # Both devices send to the same loopback port; expect 2 datagrams.
            assert len(packets) == 2, f"expected 2 packets (one per device), got {len(packets)}"
        finally:
            await streamer.stop()


class _FailingSocket:
    """Stand-in for socket.socket that raises OSError on every sendto.

    Used to exercise the cooldown path without binding a real socket. Real
    socket.socket objects refuse attribute assignment to sendto, so we swap
    the device's stored 'socket' value with this lightweight stub.
    """

    def __init__(self) -> None:
        self.send_count: int = 0

    def sendto(self, *args, **kwargs) -> None:  # noqa: D401 — match socket API
        self.send_count += 1
        raise OSError("injected")

    def close(self) -> None:  # called by stop() blackout-and-close path
        pass


@pytest.mark.asyncio
async def test_cooldown_after_30_failures():
    streamer = WledStreamer(udp_port=LOOPBACK_PORT)
    await streamer.start([_row()])
    try:
        # Swap the socket with a stub that always raises OSError on sendto.
        with streamer._lock:
            streamer._devices["d1"]["socket"].close()
            streamer._devices["d1"]["socket"] = _FailingSocket()

        for _ in range(30):
            await streamer.render({"r1": _gradient(10, [1, 2, 3])})
        snap = streamer.health_snapshot()
        assert snap["d1"]["in_cooldown"] is True, (
            "device should be in cooldown after 30 failures"
        )
        assert snap["d1"]["last_error"] is not None
        assert "OSError" in snap["d1"]["last_error"]
    finally:
        await streamer.stop()


@pytest.mark.asyncio
async def test_cooldown_skips_render_no_further_failure_increments():
    """A device in cooldown is SKIPPED — no extra failures, no extra sends."""
    streamer = WledStreamer(udp_port=LOOPBACK_PORT)
    await streamer.start([_row()])
    try:
        with streamer._lock:
            streamer._devices["d1"]["socket"].close()
            failing = _FailingSocket()
            streamer._devices["d1"]["socket"] = failing

        for _ in range(30):
            await streamer.render({"r1": _gradient(10, [1, 2, 3])})
        sends_after_cooldown = failing.send_count
        # Render again while in cooldown — should be skipped entirely
        for _ in range(5):
            await streamer.render({"r1": _gradient(10, [1, 2, 3])})
        assert failing.send_count == sends_after_cooldown, (
            "render() must not call sendto on a cooldown device"
        )
        with streamer._lock:
            assert streamer._devices["d1"]["consecutive_failures"] == 30, (
                "consecutive_failures must not increment further during cooldown"
            )
    finally:
        await streamer.stop()


@pytest.mark.asyncio
async def test_cooldown_auto_clears_after_30_seconds(monkeypatch):
    streamer = WledStreamer(udp_port=LOOPBACK_PORT)
    await streamer.start([_row()])
    try:
        base = time.monotonic()
        with streamer._lock:
            streamer._devices["d1"]["consecutive_failures"] = 30
            streamer._devices["d1"]["in_cooldown_until"] = base + 30.0
        # Advance monotonic() past cooldown window
        monkeypatch.setattr(
            "services.wled_streamer.time.monotonic", lambda: base + 31.0
        )
        snap = streamer.health_snapshot()
        assert snap["d1"]["in_cooldown"] is False
    finally:
        await streamer.stop()


@pytest.mark.asyncio
async def test_multi_channel_slicing():
    """Two channels on same device receive correct gradient slices."""
    with udp_listener(port=LOOPBACK_PORT) as q:
        streamer = WledStreamer(udp_port=LOOPBACK_PORT)
        await streamer.start([_row(led_count=10, channels=[
            {"id": "c1", "region_id": "rA", "start_led": 0, "end_led": 4},
            {"id": "c2", "region_id": "rB", "start_led": 5, "end_led": 9},
        ])])
        try:
            await streamer.render({
                "rA": _gradient(5, [255, 0, 0]),
                "rB": _gradient(5, [0, 0, 255]),
            })
            await asyncio.sleep(0.1)
            pkt = q.get(timeout=1.0)
            body = pkt.data[2:]
            assert body[:15] == bytes([255, 0, 0] * 5)
            assert body[15:] == bytes([0, 0, 255] * 5)
        finally:
            await streamer.stop()


@pytest.mark.asyncio
async def test_stop_sends_blackout_packet():
    with udp_listener(port=LOOPBACK_PORT) as q:
        streamer = WledStreamer(udp_port=LOOPBACK_PORT)
        await streamer.start([_row(led_count=10)])
        await streamer.render({"r1": _gradient(10, [255, 255, 255])})
        await asyncio.sleep(0.1)
        # Drain queue
        while not q.empty():
            q.get_nowait()
        await streamer.stop()
        # Blackout should arrive
        pkt = q.get(timeout=1.0)
        body = pkt.data[2:]
        assert body == bytes([0] * 30), f"expected zeroed body, got {body[:10]}..."


@pytest.mark.asyncio
async def test_last_success_at_iso_format():
    with udp_listener(port=LOOPBACK_PORT) as q:
        streamer = WledStreamer(udp_port=LOOPBACK_PORT)
        await streamer.start([_row(led_count=10)])
        try:
            await streamer.render({"r1": _gradient(10, [1, 2, 3])})
            await asyncio.sleep(0.1)
            while not q.empty():
                q.get_nowait()
            snap = streamer.health_snapshot()
            assert snap["d1"]["last_error"] is None
            ts = snap["d1"]["last_success_at"]
            assert isinstance(ts, str) and "T" in ts and (
                ts.endswith("+00:00") or ts.endswith("Z")
            )
        finally:
            await streamer.stop()


@pytest.mark.asyncio
async def test_render_no_assigned_channel_sends_nothing():
    """Device whose channels reference an absent region sends zero packets."""
    with udp_listener(port=LOOPBACK_PORT) as q:
        streamer = WledStreamer(udp_port=LOOPBACK_PORT)
        await streamer.start([_row(led_count=10, channels=[
            {"id": "c1", "region_id": "r1", "start_led": 0, "end_led": 9},
        ])])
        try:
            # Provide a different region's gradient — channel maps to "r1" only
            await streamer.render({"r2": _gradient(10, [255, 0, 0])})
            await asyncio.sleep(0.1)
            assert q.empty(), "no assigned region in payload should mean no packets sent"
        finally:
            await streamer.stop()


@pytest.mark.asyncio
async def test_unassigned_channel_region_id_none_sends_nothing():
    with udp_listener(port=LOOPBACK_PORT) as q:
        streamer = WledStreamer(udp_port=LOOPBACK_PORT)
        await streamer.start([_row(led_count=10, channels=[
            {"id": "c1", "region_id": None, "start_led": 0, "end_led": 9},
        ])])
        try:
            await streamer.render({"r1": _gradient(10, [255, 0, 0])})
            await asyncio.sleep(0.1)
            assert q.empty(), "unassigned channel (region_id=None) should not send"
        finally:
            await streamer.stop()
