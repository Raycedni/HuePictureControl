"""UDP loopback listener fixture for WLED packet-byte assertions.

Binds a SOCK_DGRAM socket to 127.0.0.1:<port> in a background thread and
collects every received datagram into a thread-safe queue. Tests assert
exact byte contents, packet counts, and ordering.
"""
import queue
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass
class Packet:
    data: bytes
    addr: tuple[str, int]


@contextmanager
def udp_listener(port: int = 21324, host: str = "127.0.0.1") -> Iterator[queue.Queue]:
    """Bind a UDP socket and collect incoming packets until exit.

    Usage::

        with udp_listener(21324) as q:
            # ... send packets to 127.0.0.1:21324 ...
            pkt = q.get(timeout=1.0)   # blocks up to 1s for first packet
            assert pkt.data[0] == 0x02  # DRGB protocol byte
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.settimeout(0.1)
    q: queue.Queue = queue.Queue()
    stop = threading.Event()

    def _reader() -> None:
        while not stop.is_set():
            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            q.put(Packet(data=data, addr=addr))

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    try:
        yield q
    finally:
        stop.set()
        try:
            sock.close()
        except OSError:
            pass
        thread.join(timeout=1.0)
