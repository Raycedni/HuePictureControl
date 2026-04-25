"""Self-test for the udp_listener fixture."""
import socket

from tests.fixtures.wled_loopback import udp_listener


def test_udp_listener_receives_exact_bytes():
    """Verify the listener captures bytes verbatim, including header + payload."""
    with udp_listener(port=41324) as q:
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload = bytes([0x02, 0x02, 0xFF, 0x00, 0x00])  # DRGB header + 1 red LED
        client.sendto(payload, ("127.0.0.1", 41324))
        client.close()
        pkt = q.get(timeout=1.0)
        assert pkt.data == payload
        assert pkt.addr[0] == "127.0.0.1"
