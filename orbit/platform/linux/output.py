"""Linux output: evdev/uinput virtual keyboard and wheel, KDE D-Bus, and MPRIS forwarding.

Implements the Output protocol for Linux:
  - keys, key_down, key_up via evdev UInput
  - scroll, hscroll via evdev REL_WHEEL and REL_HWHEEL
  - media via MPRIS2 player calls (forwarded to active player such as Spotify, Firefox, VLC)
  - brightness via KDE Solid PowerManagement D-Bus, sysfs backlight, or ddcutil
  - active_window_title via KDE KWin D-Bus
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time

import evdev
from evdev import UInput, ecodes as e

from orbit.platform.base import Output

log = logging.getLogger("orbit.output")

# Map orbit key names -> evdev keycodes
_KEY_MAP: dict[str, int] = {
    "ctrl": e.KEY_LEFTCTRL,
    "shift": e.KEY_LEFTSHIFT,
    "alt": e.KEY_LEFTALT,
    "win": e.KEY_LEFTMETA,
    "meta": e.KEY_LEFTMETA,
    "super": e.KEY_LEFTMETA,
    "cmd": e.KEY_LEFTMETA,
    "tab": e.KEY_TAB,
    "enter": e.KEY_ENTER,
    "return": e.KEY_ENTER,
    "esc": e.KEY_ESC,
    "escape": e.KEY_ESC,
    "space": e.KEY_SPACE,
    "backspace": e.KEY_BACKSPACE,
    "delete": e.KEY_DELETE,
    "del": e.KEY_DELETE,
    "insert": e.KEY_INSERT,
    "ins": e.KEY_INSERT,
    "left": e.KEY_LEFT,
    "right": e.KEY_RIGHT,
    "up": e.KEY_UP,
    "down": e.KEY_DOWN,
    "home": e.KEY_HOME,
    "end": e.KEY_END,
    "pageup": e.KEY_PAGEUP,
    "pgup": e.KEY_PAGEUP,
    "pagedown": e.KEY_PAGEDOWN,
    "pgdown": e.KEY_PAGEDOWN,
    "printscreen": e.KEY_SYSRQ,
    "capslock": e.KEY_CAPSLOCK,
    "minus": e.KEY_MINUS,
    "equals": e.KEY_EQUAL,
    "plus": e.KEY_EQUAL,
    "comma": e.KEY_COMMA,
    "period": e.KEY_DOT,
    "slash": e.KEY_SLASH,
    "backslash": e.KEY_BACKSLASH,
    "semicolon": e.KEY_SEMICOLON,
    "quote": e.KEY_APOSTROPHE,
    "backquote": e.KEY_GRAVE,
    "lbracket": e.KEY_LEFTBRACE,
    "rbracket": e.KEY_RIGHTBRACE,
}

# Add a-z and 0-9
for _c in "abcdefghijklmnopqrstuvwxyz":
    _KEY_MAP[_c] = getattr(e, f"KEY_{_c.upper()}")
for _d in "0123456789":
    _KEY_MAP[_d] = getattr(e, f"KEY_{_d}")
for _i in range(1, 25):
    _KEY_MAP[f"f{_i}"] = getattr(e, f"KEY_F{_i}")


def _resolve_code(name: str) -> int | None:
    return _KEY_MAP.get(name.strip().lower())


class LinuxOutput(Output):
    def __init__(self):
        self._ui: UInput | None = None
        self._scroll_accum = 0.0
        self._hscroll_accum = 0.0
        self._init_uinput()

    def _init_uinput(self):
        try:
            rel_events = [e.REL_WHEEL, e.REL_HWHEEL]
            if hasattr(e, "REL_WHEEL_HI_RES"):
                rel_events.append(e.REL_WHEEL_HI_RES)
            if hasattr(e, "REL_HWHEEL_HI_RES"):
                rel_events.append(e.REL_HWHEEL_HI_RES)

            capabilities = {
                e.EV_KEY: list(set(_KEY_MAP.values())),
                e.EV_REL: rel_events,
            }
            self._ui = UInput(
                capabilities,
                name="Orbit Virtual Input",
                version=0x3,
            )
            log.info("virtual input device ready: %s", self._ui.name)
        except Exception as ex:
            log.warning("cannot open uinput (%s) — key and scroll injection disabled", ex)
            self._ui = None

    # ---- Keys
    def keys(self, combo: str) -> None:
        if not self._ui:
            return
        parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
        codes = [_resolve_code(p) for p in parts]
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

    def key_down(self, key: str) -> None:
        if not self._ui:
            return
        c = _resolve_code(key)
        if c is not None:
            self._ui.write(e.EV_KEY, c, 1)
            self._ui.syn()

    def key_up(self, key: str) -> None:
        if not self._ui:
            return
        c = _resolve_code(key)
        if c is not None:
            self._ui.write(e.EV_KEY, c, 0)
            self._ui.syn()

    # ---- Scroll
    def scroll(self, notches: float, horizontal: bool = False) -> None:
        if not self._ui:
            return
        # Orbit: +notches = down / right
        # Linux evdev: REL_WHEEL negative = down, positive = up
        if horizontal:
            units = notches * 120.0
            self._hscroll_accum += units
            int_units = int(round(units))
            discrete = int(self._hscroll_accum / 120.0)
            if discrete != 0:
                self._hscroll_accum -= discrete * 120.0
                self._ui.write(e.EV_REL, e.REL_HWHEEL, discrete)
            if int_units != 0 and hasattr(e, "REL_HWHEEL_HI_RES"):
                self._ui.write(e.EV_REL, e.REL_HWHEEL_HI_RES, int_units)
            self._ui.syn()
        else:
            units = -notches * 120.0  # negative = down
            self._scroll_accum += units
            int_units = int(round(units))
            discrete = int(self._scroll_accum / 120.0)
            if discrete != 0:
                self._scroll_accum -= discrete * 120.0
                self._ui.write(e.EV_REL, e.REL_WHEEL, discrete)
            if int_units != 0 and hasattr(e, "REL_WHEEL_HI_RES"):
                self._ui.write(e.EV_REL, e.REL_WHEEL_HI_RES, int_units)
            self._ui.syn()

    # ---- Media (MPRIS2 forwarding to real player)
    def media(self, command: str) -> None:
        threading.Thread(
            target=self._media_fwd,
            args=(command,),
            name="mpris-forward",
            daemon=True,
        ).start()

    def _media_fwd(self, command: str) -> None:
        verb_map = {
            "play_pause": "PlayPause",
            "play": "Play",
            "pause": "Pause",
            "next": "Next",
            "previous": "Previous",
            "stop": "Stop",
        }
        method = verb_map.get(command.lower())
        if not method:
            log.warning("unknown media command '%s'", command)
            return

        try:
            import dbus
            bus = dbus.SessionBus()
            # List all MPRIS players excluding orbit itself
            players = [
                name for name in bus.list_names()
                if str(name).startswith("org.mpris.MediaPlayer2.")
                and "orbit" not in str(name).lower()
            ]
            if players:
                target = players[0]
                proxy = bus.get_object(target, "/org/mpris/MediaPlayer2")
                player_iface = dbus.Interface(proxy, "org.mpris.MediaPlayer2.Player")
                getattr(player_iface, method)()
                log.info("forwarded media:%s to %s", command, target)
                return
        except Exception as ex:
            log.debug("dbus mpris forward error: %s", ex)

        # Fallback to playerctl if installed
        try:
            subprocess.run(["playerctl", command.replace("_", "-")], timeout=1, capture_output=True)
        except Exception:
            pass

    # ---- Launch
    def launch(self, target: str) -> None:
        try:
            if target.startswith("http://") or target.startswith("https://") or "/" in target:
                subprocess.Popen(["xdg-open", target])
            else:
                subprocess.Popen([target])
        except Exception as ex:
            log.error("launch '%s' failed: %s", target, ex)

    # ---- Active window title
    def active_window_title(self) -> str:
        # 1. Try KDE KWin via D-Bus
        try:
            r = subprocess.run(
                ["qdbus", "org.kde.KWin", "/KWin", "activeClient"],
                capture_output=True,
                text=True,
                timeout=0.5,
            )
            client_path = r.stdout.strip()
            if client_path:
                r2 = subprocess.run(
                    ["qdbus", "org.kde.KWin", client_path, "caption"],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                )
                title = r2.stdout.strip()
                if title:
                    return title
        except Exception:
            pass

        # 2. Try xdotool fallback if available
        try:
            r = subprocess.run(
                ["xdotool", "getactivewindow", "getwindowname"],
                capture_output=True,
                text=True,
                timeout=0.5,
            )
            title = r.stdout.strip()
            if title:
                return title
        except Exception:
            pass
        return ""

    # ---- Brightness
    def brightness_get(self) -> float | None:
        # Try KDE Solid PowerManagement D-Bus
        try:
            import dbus
            bus = dbus.SessionBus()
            proxy = bus.get_object(
                "org.kde.Solid.PowerManagement",
                "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
            )
            iface = dbus.Interface(proxy, "org.kde.Solid.PowerManagement.Actions.BrightnessControl")
            return float(iface.brightness())
        except Exception:
            pass

        # Try ddcutil for external monitors
        try:
            r = subprocess.run(
                ["ddcutil", "getvcp", "10", "--brief"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            m = re.search(r"current value =\s*(\d+)", r.stdout)
            if m:
                return float(m.group(1))
        except Exception:
            pass
        return None

    def brightness_set(self, value: float) -> None:
        val = max(0, min(100, int(round(value))))
        # Try KDE D-Bus
        try:
            import dbus
            bus = dbus.SessionBus()
            proxy = bus.get_object(
                "org.kde.Solid.PowerManagement",
                "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
            )
            iface = dbus.Interface(proxy, "org.kde.Solid.PowerManagement.Actions.BrightnessControl")
            iface.setBrightness(val)
            return
        except Exception:
            pass

        # Try ddcutil
        try:
            subprocess.run(["ddcutil", "setvcp", "10", str(val)], timeout=3, capture_output=True)
        except Exception:
            pass

    def press_app_button(self, app_title: str, name_pattern: str) -> None:
        log.info("press_app_button(%s, %s) not supported on Wayland directly", app_title, name_pattern)

    def center_window(self, title: str) -> None:
        log.info("center_window(%s) called", title)
