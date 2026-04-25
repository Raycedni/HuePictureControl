"""Byte-exact unit tests for WLED UDP packet builders (Plan 17-03 Task 1)."""
import pytest

from services.wled_streamer import (
    DRGB_MAX_LEDS,
    DNRGB_MAX_LEDS_PER_PACKET,
    DNRGB_PROTOCOL,
    DRGB_PROTOCOL,
    TIMEOUT_SECONDS,
    UDP_PORT,
    build_dnrgb_packets,
    build_drgb_packet,
    build_packets_for_device,
)


def test_constants():
    assert DRGB_PROTOCOL == 0x02
    assert DNRGB_PROTOCOL == 0x04
    assert UDP_PORT == 21324
    assert TIMEOUT_SECONDS == 2
    assert DRGB_MAX_LEDS == 490
    assert DNRGB_MAX_LEDS_PER_PACKET == 489


def test_drgb_single_led_black():
    pkt = build_drgb_packet([(0, 0, 0)])
    assert pkt == bytes([0x02, 0x02, 0, 0, 0])


def test_drgb_single_led_red_rgb_order():
    pkt = build_drgb_packet([(255, 0, 0)])
    assert pkt == bytes([0x02, 0x02, 0xFF, 0x00, 0x00])


def test_drgb_max_490_leds_size_1472():
    pkt = build_drgb_packet([(0, 0, 0)] * 490)
    assert len(pkt) == 1472


def test_drgb_100_leds_size_302():
    pkt = build_drgb_packet([(0, 0, 0)] * 100)
    assert len(pkt) == 302


def test_drgb_sequential_triplets():
    pkt = build_drgb_packet([(1, 2, 3), (4, 5, 6)])
    assert pkt == bytes([0x02, 0x02, 1, 2, 3, 4, 5, 6])


def test_drgb_too_many_leds_raises():
    with pytest.raises(ValueError):
        build_drgb_packet([(0, 0, 0)] * 491)


def test_dnrgb_980_leds_exactly_3_packets():
    packets = build_dnrgb_packets([(0, 0, 0)] * 980)
    assert len(packets) == 3
    # 489 + 489 + 2 LEDs -> 4 + 489*3 = 1471, 1471, 4 + 2*3 = 10
    assert [len(p) for p in packets] == [1471, 1471, 10]


def test_dnrgb_protocol_and_timeout_bytes():
    packets = build_dnrgb_packets([(1, 2, 3)] * 500)
    for pkt in packets:
        assert pkt[0] == 0x04, "DNRGB protocol byte"
        assert pkt[1] == 0x02, "2-second timeout byte (D-14)"


def test_dnrgb_start_index_big_endian():
    packets = build_dnrgb_packets([(0, 0, 0)] * 980)
    assert packets[0][2:4] == bytes([0x00, 0x00])  # start = 0
    assert packets[1][2:4] == bytes([0x01, 0xE9])  # start = 489 = 0x01E9
    assert packets[2][2:4] == bytes([0x03, 0xD2])  # start = 978 = 0x03D2


def test_dnrgb_exactly_489_one_packet():
    packets = build_dnrgb_packets([(0, 0, 0)] * 489)
    assert len(packets) == 1
    assert len(packets[0]) == 4 + 489 * 3


def test_dnrgb_empty_returns_empty_list():
    assert build_dnrgb_packets([]) == []


def test_build_packets_for_device_picks_drgb_at_490():
    packets = build_packets_for_device(490, [(0, 0, 0)] * 490)
    assert len(packets) == 1
    assert packets[0][0] == 0x02


def test_build_packets_for_device_picks_dnrgb_at_491():
    packets = build_packets_for_device(491, [(0, 0, 0)] * 491)
    assert all(p[0] == 0x04 for p in packets)
    assert len(packets) == 2  # ceil(491/489) = 2


def test_build_packets_for_device_colors_length_mismatch_raises():
    with pytest.raises(ValueError):
        build_packets_for_device(100, [(0, 0, 0)] * 99)
