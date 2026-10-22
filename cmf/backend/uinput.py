"""Linux uinput input injector for high-resolution Wayland scrolling and key combinations."""
from __future__ import annotations

import logging
import time

from evdev import UInput
from evdev import ecodes as e

log = logging.getLogger("cmf.uinput")

_KEY_MAP = {
    "ctrl": e.KEY_LEFTCTRL,
    "control": e.KEY_LEFTCTRL,
    "shift": e.KEY_LEFTSHIFT,
    "alt": e.KEY_LEFTALT,
    "meta": e.KEY_LEFTMETA,
    "super": e.KEY_LEFTMETA,
    "win": e.KEY_LEFTMETA,
    "enter": e.KEY_ENTER,
    "return": e.KEY_ENTER,
    "esc": e.KEY_ESC,
    "escape": e.KEY_ESC,
    "space": e.KEY_SPACE,
    "tab": e.KEY_TAB,
    "backspace": e.KEY_BACKSPACE,
    "delete": e.KEY_DELETE,
    "up": e.KEY_UP,
    "down": e.KEY_DOWN,
    "left": e.KEY_LEFT,
    "right": e.KEY_RIGHT,
    "pageup": e.KEY_PAGEUP,
    "pagedown": e.KEY_PAGEDOWN,
    "home": e.KEY_HOME,
    "end": e.KEY_END,
    "plus": e.KEY_EQUAL,
    "minus": e.KEY_MINUS,
    "equals": e.KEY_EQUAL,
}
for c in "abcdefghijklmnopqrstuvwxyz":
    _KEY_MAP[c] = getattr(e, f"KEY_{c.upper()}")
for d in "0123456789":
    _KEY_MAP[d] = getattr(e, f"KEY_{d}")
for f in range(1, 13):
    _KEY_MAP[f"f{f}"] = getattr(e, f"KEY_F{f}")


class UInputDevice:
    def __init__(self):
        self._ui: UInput | None = None
        self._init_device()

    def _init_device(self):
        try:
            rel_events = [e.REL_WHEEL, e.REL_HWHEEL]
            if hasattr(e, "REL_WHEEL_HI_RES"):
                rel_events.append(e.REL_WHEEL_HI_RES)
            if hasattr(e, "REL_HWHEEL_HI_RES"):
                rel_events.append(e.REL_HWHEEL_HI_RES)

            caps = {
                e.EV_KEY: list(set(_KEY_MAP.values())),
                e.EV_REL: rel_events,
            }
            self._ui = UInput(caps, name="CMF Virtual Input", version=0x3)
            log.info("virtual input device created: %s", self._ui.name)
        except Exception as ex:
            log.warning("cannot open /dev/uinput (%s) — input simulation disabled", ex)
            self._ui = None

    def scroll(self, notches: float, horizontal: bool = False):
        if not self._ui:
            return
        # Linux evdev: REL_WHEEL negative = down, positive = up
        units = int(round(-notches * 120.0)) if not horizontal else int(round(notches * 120.0))
        if units == 0:
            return

        discrete = -1 if notches > 0 else 1 if notches < 0 else 0

        if horizontal:
            if hasattr(e, "REL_HWHEEL_HI_RES"):
                self._ui.write(e.EV_REL, e.REL_HWHEEL_HI_RES, units)
            self._ui.write(e.EV_REL, e.REL_HWHEEL, -discrete)
        else:
            if hasattr(e, "REL_WHEEL_HI_RES"):
                self._ui.write(e.EV_REL, e.REL_WHEEL_HI_RES, units)
            self._ui.write(e.EV_REL, e.REL_WHEEL, discrete)
        self._ui.syn()

    def keys(self, combo: str):
        if not self._ui:
            return
        parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
        codes = [_KEY_MAP.get(p) for p in parts]
        codes = [c for c in codes if c is not None]
        if not codes:
            return

        for c in codes:
            self._ui.write(e.EV_KEY, c, 1)
        self._ui.syn()
        time.sleep(0.01)
        for c in reversed(codes):
            self._ui.write(e.EV_KEY, c, 0)
        self._ui.syn()

    def close(self):
        if self._ui:
            try:
                self._ui.close()
            except Exception:
                pass
            self._ui = None
