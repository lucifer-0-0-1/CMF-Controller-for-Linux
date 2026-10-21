"""Dial events sniffed from raw Bluetooth packets (ETW, admin only).

Windows logs every HCI packet to the Microsoft-Windows-BTH-BTHPORT provider.
We scan each one with a list of decoders. Today:

    AT+BVRA=1   hands-free "start voice recognition"  -> HOLD

To add press/release later (e.g. once the vendor RFCOMM/GATT channel is mapped,
or AVRCP PASS THROUGH press/release bits), write another Decoder and add it to
DECODERS, and add Capability.PRESS_RELEASE to `capabilities`. Nothing else in
the app has to change.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable

from orbit.core.events import Capability, InputEvent, Kind
from orbit.platform.base import Emit, InputSource
from orbit.platform.windows import etw

log = logging.getLogger("orbit.bt")
trace = logging.getLogger("orbit.trace")

ALL = 0xFFFFFFFFFFFFFFFF
PROVIDER_NAMES = {
    uuid.UUID("8a1f9517-3a8c-4a9e-a018-4f17a200f277"): "BTHPORT",
    uuid.UUID("33693e1d-246a-471b-83be-3e75f47a832d"): "BTHUSB",
    uuid.UUID("db25b328-a6f6-444f-9d97-a50e20217d16"): "BTHMINI",
    uuid.UUID("d88ace07-cac0-11d8-a4c6-000d560bcba5"): "WPP.BthPort",
    uuid.UUID("f1b0ec6a-87cb-4eaa-bfba-82770400a80b"): "WPP.RFCOMM",
    uuid.UUID("f0cb5d88-0c28-475a-8ae9-d3331ed861de"): "WPP.BTHMINI",
}
STALE_SESSIONS = ["CMFDialHold", "OrbitDiag", "OrbitDiagA", "OrbitDiagB", "OrbitDiagC"]
ALL_PROVIDERS = [(g, 5, ALL) for g in PROVIDER_NAMES]   # diagnostics only: ~3.5k events/s
# Raw HCI packets (incl. the hold's AT+BVRA) come from the BTHPORT manifest provider.
PROVIDERS = [(uuid.UUID("8a1f9517-3a8c-4a9e-a018-4f17a200f277"), 5, 0)]


@dataclass
class Decoder:
    name: str
    match: Callable[[bytes], bool]
    kind: Kind
    debounce_s: float = 0.8   # one packet can be logged more than once


DECODERS = [
    # The buds toggle their own idea of "voice recognition active": a hold sends BVRA=1,
    # but after anything opens the headset mic (call audio, AT+BCS) the next holds send
    # BVRA=0. Both mean "the user held the dial".
    Decoder("hfp-voice-recognition", lambda d: b"AT+BVRA=1" in d or b"AT+BVRA=0" in d, Kind.HOLD),
]


class BluetoothPacketSource(InputSource):
    name = "bt-etw"
    capabilities = frozenset({Capability.HOLD})

    def __init__(self, decoders: list[Decoder] | None = None):
        self.decoders = decoders or DECODERS
        self._emit: Emit | None = None
        self._last: dict[str, float] = {}
        self._session: etw.EtwSession | None = None
        self._count = 0
        self._count_t = time.monotonic()
        self._last_packet = 0.0
        self._last_restart = 0.0
        self._checking = False
        self._last_trace: dict[str, float] = {}

    _failed = False

    @property
    def available(self):
        return etw.is_admin() and not self._failed

    def start(self, emit):
        self._emit = emit
        if not self.available:
            log.warning("not admin — press-and-hold detection off")
            return
        # A leftover session from a crash or an older tool can stop BTHPORT feeding us at all.
        for stale in STALE_SESSIONS:
            etw.stop_session(stale)
        self._open()

    def _open(self):
        self._session = etw.EtwSession("OrbitDialBT", PROVIDERS, self._on_payload)
        try:
            self._session.start()
        except OSError:
            self._failed = True
            raise
        self._last_packet = time.monotonic()
        log.info("bluetooth packet sniffer active (%d decoders)", len(self.decoders))

    def stop(self):
        if self._session:
            self._session.stop()

    def observe(self, ev):
        """Self-check: a dial turn/press is itself Bluetooth traffic. If one arrives from
        another source and we saw no packet around it, our session has gone deaf."""
        if ev.source == self.name or self._session is None or self._checking:
            return
        self._checking = True
        threading.Timer(1.5, self._check, args=(ev.t,)).start()

    def _check(self, t):
        self._checking = False
        if self._last_packet < t - 1.0 and time.monotonic() - self._last_restart > 30:
            self._last_restart = time.monotonic()
            log.warning("bluetooth sniffer saw no packets around a dial event — restarting it")
            try:
                self._session.stop()
                self._open()
            except OSError:
                log.exception("sniffer restart failed; hold unavailable")

    def _trace_avrcp(self, data: bytes, now: float):
        """Timeline debugging: what the buds actually said over AVRCP, before Windows."""
        if not trace.isEnabledFor(logging.DEBUG):
            return
        msgs = []
        i = data.find(b"\x00\x19\x58\x31\x00\x00\x02\x0d")          # RegisterNotification rsp, VOLUME_CHANGED
        if i >= 3 and len(data) > i + 8:
            ctype = {0x0D: "CHANGED", 0x0F: "INTERIM"}.get(data[i - 3], hex(data[i - 3]))
            v = data[i + 8] & 0x7F
            msgs.append(f"buds vol {ctype:<7} {v:3d}/127 step={v * 16 / 127:5.2f}")
        i = data.find(b"\x00\x19\x58\x50\x00\x00\x01")              # SetAbsoluteVolume
        if i >= 3 and len(data) > i + 7:
            ctype = {0x00: "CMD", 0x09: "ACCEPTED", 0x08: "REJECTED"}.get(data[i - 3], hex(data[i - 3]))
            v = data[i + 7] & 0x7F
            msgs.append(f"pc   setabs  {ctype:<8} {v:3d}/127 step={v * 16 / 127:5.2f}")
        i = data.find(b"\x48\x7c")                                   # PASS THROUGH (buttons)
        if i >= 1 and len(data) > i + 2 and data[i - 1] in (0x00, 0x09):
            op = data[i + 2]
            name = {0x44: "PLAY", 0x46: "PAUSE", 0x4B: "NEXT", 0x4C: "PREV", 0x41: "VOL_UP",
                    0x42: "VOL_DOWN", 0x45: "STOP", 0x48: "REWIND", 0x49: "FFWD"}.get(op & 0x7F, f"op{op & 0x7F:#04x}")
            msgs.append(f"buds button {name} {'release' if op & 0x80 else 'press'}"
                        f"{' (ack)' if data[i - 1] == 0x09 else ''}")
        for m in msgs:
            if self._last_trace.get(m, 0) < now - 0.03:              # ETW may log a packet twice
                trace.debug("bt   %s", m)
            self._last_trace[m] = now

    def _on_payload(self, data: bytes, provider=None):
        now = time.monotonic()
        self._last_packet = now
        self._trace_avrcp(data, now)
        self._count += 1
        if now - self._count_t > 10:
            log.debug("bt packets seen: %d in %.0fs", self._count, now - self._count_t)
            self._count, self._count_t = 0, now
        if b"AT+" in data:   # every hands-free command, so new ones show up in the log
            i = data.find(b"AT+")
            log.debug("hf command: %r", data[i:i + 24].split(b"\r")[0])
        for d in self.decoders:
            if d.match(data):
                if now - self._last.get(d.name, 0) < d.debounce_s:
                    continue
                self._last[d.name] = now
                log.debug("decoded %s", d.name)
                if self._emit:
                    self._emit(InputEvent(d.kind, 0, self.name))
