"""WLED UDP realtime streaming primitives.

Module-level constants and packet builders for the DRGB (<=490 LEDs) and
DNRGB (>490 LEDs, 489-LED chunks) protocols documented at
https://kno.wled.ge/interfaces/udp-realtime/.

The WledStreamer class itself lives in this module (added in Plan 04) and
consumes these helpers on every frame.

Exports:
    DRGB_PROTOCOL, DNRGB_PROTOCOL    -- Header byte 0 values
    UDP_PORT                          -- WLED realtime port (21324)
    TIMEOUT_SECONDS                   -- Header byte 1 value (2s per D-14)
    DRGB_MAX_LEDS                     -- 490 (DRGB strip-wide cap)
    DNRGB_MAX_LEDS_PER_PACKET         -- 489 (DNRGB chunk cap; 4-byte header eats 1 LED)
    build_drgb_packet                 -- Build a single DRGB packet
    build_dnrgb_packets               -- Build a list of DNRGB chunk packets
    build_packets_for_device          -- Auto-select DRGB or DNRGB based on led_count
"""
import logging

logger = logging.getLogger(__name__)

# WLED protocol constants (verified against kno.wled.ge/interfaces/udp-realtime/)
DRGB_PROTOCOL: int = 0x02
DNRGB_PROTOCOL: int = 0x04
UDP_PORT: int = 21324
TIMEOUT_SECONDS: int = 2            # D-14: strip reverts after 2s of silence
DRGB_MAX_LEDS: int = 490            # 2-byte header + 490*3 body = 1472 bytes
DNRGB_MAX_LEDS_PER_PACKET: int = 489  # 4-byte header + 489*3 body = 1471 bytes


def build_drgb_packet(colors: list[tuple[int, int, int]]) -> bytes:
    """Build a DRGB packet for a full strip (<=490 LEDs).

    Layout: ``[0x02, 0x02, R0, G0, B0, R1, G1, B1, ...]``

    Header byte 0 is the DRGB protocol marker; byte 1 is the timeout (D-14).
    Body is sequential RGB triplets, one per LED, in RGB order (not BGR).

    Raises:
        ValueError: if ``len(colors) > 490``.
    """
    if len(colors) > DRGB_MAX_LEDS:
        raise ValueError(
            f"DRGB supports at most {DRGB_MAX_LEDS} LEDs, got {len(colors)}"
        )
    header = bytes([DRGB_PROTOCOL, TIMEOUT_SECONDS])
    body = bytes(c for rgb in colors for c in rgb)
    return header + body


def build_dnrgb_packets(colors: list[tuple[int, int, int]]) -> list[bytes]:
    """Chunk a long strip into DNRGB packets (up to 489 LEDs each).

    Layout per packet: ``[0x04, 0x02, start_hi, start_lo, R0, G0, B0, ...]``
    where ``start_hi``/``start_lo`` is a big-endian uint16 LED index offset.

    Returns an empty list for empty input. Otherwise one or more packets,
    each ready for a single sendto() call.
    """
    packets: list[bytes] = []
    for chunk_start in range(0, len(colors), DNRGB_MAX_LEDS_PER_PACKET):
        chunk = colors[chunk_start : chunk_start + DNRGB_MAX_LEDS_PER_PACKET]
        header = bytes([
            DNRGB_PROTOCOL,
            TIMEOUT_SECONDS,
            (chunk_start >> 8) & 0xFF,
            chunk_start & 0xFF,
        ])
        body = bytes(c for rgb in chunk for c in rgb)
        packets.append(header + body)
    return packets


def build_packets_for_device(
    led_count: int, colors: list[tuple[int, int, int]]
) -> list[bytes]:
    """Auto-select DRGB (led_count <= 490) or DNRGB (>490) and return packet list.

    Always returns a list (single-element for DRGB, multi-element for DNRGB)
    so the per-frame send loop has a uniform shape regardless of strip size.

    Raises:
        ValueError: if ``len(colors) != led_count`` (caller bug).
    """
    if len(colors) != led_count:
        raise ValueError(
            f"colors length {len(colors)} != led_count {led_count}"
        )
    if led_count <= DRGB_MAX_LEDS:
        return [build_drgb_packet(colors)]
    return build_dnrgb_packets(colors)
