"""Linux native CMF Buds Pro 2 button driver using evdev with exclusive grab.

Monitors the Bluetooth AVRCP input event device registered by BlueZ.
Uses EVIOCGRAB to prevent background media players from misfiring when the dial
button is used to navigate and select tools in the wheel.
"""
from __future__ import annotations

import logging
import select
import threading
import time
from typing import Callable

import evdev
from evdev import ecodes as e

from cmf.core.events import Event, Kind

log = logging.getLogger("cmf.buttons")

HOLD_THRESHOLD_S = 0.55


class EvdevButtonSource:
    name = "evdev-buttons"

    def __init__(self, emit: Callable[[Event], None], match_name: str = "CMF Buds Pro 2"):
        self.emit = emit
        self.match_name = match_name.lower()
        self._dev: evdev.InputDevice | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._grabbed = False

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="cmf-buttons-listener", daemon=True)
        self._thread.start()
        log.info("started native evdev button listener")

    def stop(self):
        self._stop.set()
        if self._dev:
            try:
                if self._grabbed:
                    self._dev.ungrab()
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    def _find_device(self) -> evdev.InputDevice | None:
        try:
            for path in evdev.list_devices():
                dev = evdev.InputDevice(path)
                if self.match_name in dev.name.lower() or ("buds" in dev.name.lower() and "avrcp" in dev.name.lower()):
                    return dev
                dev.close()
        except Exception as ex:
            log.debug("error listing evdev devices: %s", ex)
        return None

    def _run_loop(self):
        while not self._stop.is_set():
            dev = self._find_device()
            if not dev:
                time.sleep(1.5)
                continue

            self._dev = dev
            self._grabbed = False
            try:
                # Try exclusive grab
                dev.grab()
                self._grabbed = True
                log.info("bound and grabbed input device: %s (%s)", dev.name, dev.path)
            except Exception as ex:
                log.info("bound input device (ungrabbed: %s): %s (%s)", ex, dev.name, dev.path)

            press_down: dict[int, float] = {}

            try:
                while not self._stop.is_set():
                    r, _, _ = select.select([dev.fd], [], [], 0.5)
                    if not r:
                        continue

                    for ev in dev.read():
                        if ev.type != e.EV_KEY:
                            continue

                        code, val = ev.code, ev.value
                        now = time.monotonic()

                        if val == 1:  # Key down
                            press_down[code] = now
                        elif val == 2:  # Autorepeat -> Long hold
                            if now - press_down.get(code, now) >= 0.4:
                                self.emit(Event(Kind.HOLD, 0, self.name))
                                press_down[code] = now + 10.0
                        elif val == 0:  # Key up
                            down_t = press_down.pop(code, now)
                            duration = now - down_t
                            if duration >= HOLD_THRESHOLD_S:
                                self.emit(Event(Kind.HOLD, 0, self.name))
                                continue

                            if code in (e.KEY_PLAYCD, e.KEY_PAUSECD, getattr(e, "KEY_PLAYPAUSE", 164)):
                                self.emit(Event(Kind.CLICK, 0, self.name))
                            elif code in (e.KEY_NEXTSONG, getattr(e, "KEY_FASTFORWARD", 208)):
                                self.emit(Event(Kind.DOUBLE, 0, self.name))
                            elif code in (e.KEY_PREVIOUSSONG, getattr(e, "KEY_REWIND", 168)):
                                self.emit(Event(Kind.TRIPLE, 0, self.name))
                            elif code in (getattr(e, "KEY_VOICECOMMAND", 582), getattr(e, "KEY_ASSISTANT", 583)):
                                self.emit(Event(Kind.HOLD, 0, self.name))

            except (OSError, IOError) as ex:
                log.info("CMF button device disconnected (%s), rescanning...", ex)
                try:
                    dev.close()
                except Exception:
                    pass
                self._dev = None
                time.sleep(1.0)
