"""Dev/demo input: inject dial events over localhost UDP.

    python -m orbit.inject rotate 1
    python -m orbit.inject click | double | triple | hold | press | release

Enabled with --dev. Lets you test the UI with no buds, and script demo takes.
"""
from __future__ import annotations

import logging
import socket
import threading

from orbit.core.events import Capability, InputEvent, Kind
from orbit.platform.base import InputSource

log = logging.getLogger("orbit.dev")
PORT = 47800


class UdpDevSource(InputSource):
    name = "dev-udp"
    capabilities = frozenset({Capability.ROTATE, Capability.CLICKS, Capability.HOLD})

    def __init__(self, port: int = PORT):
        self.port = port
        self._sock = None

    def start(self, emit):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", self.port))

        def loop():
            while True:
                try:
                    data, _ = self._sock.recvfrom(256)
                except OSError:
                    return
                parts = data.decode(errors="ignore").split()
                if not parts:
                    continue
                try:
                    kind = Kind(parts[0])
                    delta = int(parts[1]) if len(parts) > 1 else 0
                except ValueError:
                    log.warning("bad dev event %r", data)
                    continue
                emit(InputEvent(kind, delta, self.name))

        threading.Thread(target=loop, name="dev-udp", daemon=True).start()
        log.info("dev input on udp://127.0.0.1:%d", self.port)

    def stop(self):
        if self._sock:
            self._sock.close()


def send(kind: str, delta: int = 0, port: int = PORT):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.sendto(f"{kind} {delta}".encode(), ("127.0.0.1", port))
    s.close()
