"""Unit tests for WledStreamer (Plan 17-04).

Task 1 covers lifecycle (start/stop), set_enabled gate, health_snapshot payload
shape, lock discipline, and the udp_port constructor kwarg (chosen over
monkey-patching module-level UDP_PORT for hermetic loopback integration tests).
"""
import asyncio
import threading

import pytest

from services.wled_streamer import UDP_PORT, WledStreamer


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
