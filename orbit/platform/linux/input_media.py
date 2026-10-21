"""Linux: dial presses via evdev AVRCP kernel input device and MPRIS D-Bus.

The CMF Buds Pro 2 dial sends button events:
  Single press  -> Play/Pause
  Double press  -> Next track
  Triple press  -> Previous track
  Hold          -> Voice assistant / long hold

On Linux, BlueZ registers an evdev kernel device (e.g. "/dev/input/eventX: CMF Buds Pro 2 (AVRCP)")
emitting standard multimedia keys: KEY_PLAYCD/KEY_PAUSECD, KEY_NEXTSONG, KEY_PREVIOUSSONG.
We monitor this device directly for lowest latency, and register a companion MPRIS2 player
on D-Bus so desktop environment media handlers also route commands here.
"""
from __future__ import annotations

import logging
import select
import threading
import time

import evdev
from evdev import ecodes as e

from orbit.core.events import Capability, InputEvent, Kind
from orbit.platform.base import Emit, InputSource

log = logging.getLogger("orbit.media")
trace = logging.getLogger("orbit.trace")

# Deduplication window between evdev and MPRIS triggers
DEDUP_WINDOW_S = 0.18


class EventDeduplicator:
    def __init__(self, emit: Emit):
        self._emit = emit
        self._last_event: dict[str, float] = {}
        self._lock = threading.Lock()

    def emit(self, kind: Kind, source: str):
        now = time.monotonic()
        key = kind.value
        with self._lock:
            last = self._last_event.get(key, 0.0)
            if now - last < DEDUP_WINDOW_S:
                trace.debug("ignoring duplicate event %s from %s", key, source)
                return
            self._last_event[key] = now
        trace.debug("event %s from %s", key, source)
        self._emit(InputEvent(kind, 0, source, now))


class LinuxEvdevButtonSource(InputSource):
    name = "evdev-buttons"
    capabilities = frozenset({Capability.CLICKS, Capability.HOLD})

    def __init__(self, match_name: str = "CMF Buds Pro 2", dedup: EventDeduplicator | None = None):
        self.match_name = match_name.lower()
        self._dedup = dedup
        self._emit: Emit | None = None
        self._stop = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._dev: evdev.InputDevice | None = None

    def start(self, emit: Emit):
        self._emit = emit
        self._stop.clear()
        self._worker_thread = threading.Thread(
            target=self._run,
            name="evdev-button-worker",
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self):
        self._stop.set()
        if self._dev:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    def _find_device(self) -> evdev.InputDevice | None:
        try:
            for path in evdev.list_devices():
                try:
                    dev = evdev.InputDevice(path)
                    name = dev.name.lower()
                    if (
                        (self.match_name in name or "cmf" in name or "buds" in name)
                        and "avrcp" in name
                    ) or (self.match_name in name and "avrcp" in name):
                        return dev
                    dev.close()
                except Exception:
                    continue
        except Exception as ex:
            log.debug("error listing evdev devices: %s", ex)
        return None

    def _run(self):
        while not self._stop.is_set():
            dev = self._find_device()
            if not dev:
                time.sleep(1.5)
                continue

            self._dev = dev
            log.info("bound button listener to %s (%s)", dev.name, dev.path)

            press_down_time: dict[int, float] = {}

            try:
                while not self._stop.is_set():
                    r, _, _ = select.select([dev.fd], [], [], 0.5)
                    if not r:
                        continue

                    for ev in dev.read():
                        if ev.type != e.EV_KEY:
                            continue

                        # ev.value: 1 = down, 0 = up, 2 = hold/repeat
                        code = ev.code
                        val = ev.value
                        now = time.monotonic()

                        if val == 1:
                            press_down_time[code] = now
                        elif val == 2:
                            # Autorepeat -> long hold!
                            if now - press_down_time.get(code, now) >= 0.4:
                                self._dispatch(Kind.HOLD)
                                press_down_time[code] = now + 10.0  # avoid rapid re-trigger
                        elif val == 0:
                            down_t = press_down_time.pop(code, now)
                            held_duration = now - down_t
                            if held_duration >= 0.65:
                                self._dispatch(Kind.HOLD)
                                continue

                            if code in (e.KEY_PLAYCD, e.KEY_PAUSECD, getattr(e, "KEY_PLAYPAUSE", 164)):
                                self._dispatch(Kind.CLICK)
                            elif code in (e.KEY_NEXTSONG, getattr(e, "KEY_FASTFORWARD", 208)):
                                self._dispatch(Kind.DOUBLE)
                            elif code in (e.KEY_PREVIOUSSONG, getattr(e, "KEY_REWIND", 168)):
                                self._dispatch(Kind.TRIPLE)
                            elif code in (getattr(e, "KEY_VOICECOMMAND", 582), getattr(e, "KEY_ASSISTANT", 583)):
                                self._dispatch(Kind.HOLD)

            except (OSError, IOError) as ex:
                log.info("evdev device disconnected (%s), rescanning...", ex)
                try:
                    dev.close()
                except Exception:
                    pass
                self._dev = None
                time.sleep(1.0)

    def _dispatch(self, kind: Kind):
        if self._dedup:
            self._dedup.emit(kind, self.name)
        elif self._emit:
            self._emit(InputEvent(kind, 0, self.name))


class MPRISInputSource(InputSource):
    """Fake MPRIS2 player on D-Bus to capture desktop media key events."""
    name = "mpris-buttons"
    capabilities = frozenset({Capability.CLICKS})

    def __init__(self, dedup: EventDeduplicator | None = None):
        self._dedup = dedup
        self._emit: Emit | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._server = None

    @property
    def available(self) -> bool:
        try:
            import dbus
            return True
        except ImportError:
            return False

    def start(self, emit: Emit):
        self._emit = emit
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_dbus,
            name="mpris-dbus-service",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if hasattr(self, "_loop") and self._loop:
            try:
                self._loop.quit()
            except Exception:
                pass

    def _dispatch(self, kind: Kind):
        if self._dedup:
            self._dedup.emit(kind, self.name)
        elif self._emit:
            self._emit(InputEvent(kind, 0, self.name))

    def _run_dbus(self):
        try:
            import dbus
            import dbus.service
            import dbus.mainloop.glib
            from gi.repository import GLib

            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SessionBus()
            bus_name = "org.mpris.MediaPlayer2.orbit"

            source = self

            class _Player(dbus.service.Object):
                def __init__(self):
                    super().__init__(dbus.service.BusName(bus_name, bus), "/org/mpris/MediaPlayer2")

                @dbus.service.method("org.mpris.MediaPlayer2.Player")
                def PlayPause(self):
                    source._dispatch(Kind.CLICK)

                @dbus.service.method("org.mpris.MediaPlayer2.Player")
                def Next(self):
                    source._dispatch(Kind.DOUBLE)

                @dbus.service.method("org.mpris.MediaPlayer2.Player")
                def Previous(self):
                    source._dispatch(Kind.TRIPLE)

                @dbus.service.method("org.mpris.MediaPlayer2")
                def Raise(self): pass

                @dbus.service.method("org.mpris.MediaPlayer2")
                def Quit(self): pass

                @dbus.service.method("org.freedesktop.DBus.Properties",
                                     in_signature="ss", out_signature="v")
                def Get(self, iface, prop):
                    return self.GetAll(iface).get(prop, "")

                @dbus.service.method("org.freedesktop.DBus.Properties",
                                     in_signature="s", out_signature="a{sv}")
                def GetAll(self, iface):
                    if iface == "org.mpris.MediaPlayer2":
                        return {
                            "Identity": dbus.String("Orbit"),
                            "CanRaise": dbus.Boolean(False),
                            "CanQuit": dbus.Boolean(False),
                            "HasTrackList": dbus.Boolean(False),
                            "SupportedUriSchemes": dbus.Array([], "s"),
                            "SupportedMimeTypes": dbus.Array([], "s"),
                        }
                    if iface == "org.mpris.MediaPlayer2.Player":
                        return {
                            "PlaybackStatus": dbus.String("Playing"),
                            "CanPlay": dbus.Boolean(True),
                            "CanPause": dbus.Boolean(True),
                            "CanGoNext": dbus.Boolean(True),
                            "CanGoPrevious": dbus.Boolean(True),
                            "CanSeek": dbus.Boolean(False),
                            "CanControl": dbus.Boolean(True),
                            "Rate": dbus.Double(1.0),
                            "MinimumRate": dbus.Double(1.0),
                            "MaximumRate": dbus.Double(1.0),
                            "Metadata": dbus.Dictionary({}, "sv"),
                            "Volume": dbus.Double(1.0),
                            "Position": dbus.Int64(0),
                        }
                    return {}

            self._player = _Player()
            self._loop = GLib.MainLoop()
            log.info("registered MPRIS2 service as %s", bus_name)
            self._loop.run()
        except Exception as ex:
            log.debug("MPRIS service error: %s", ex)
