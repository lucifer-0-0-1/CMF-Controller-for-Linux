"""Recorded key shortcuts <-> Orbit key combos ("ctrl+alt+v").

The Settings window records a chord with Qt (QKeySequence, PortableText), which
names keys its own way and, on macOS, calls Cmd "Ctrl" and Control "Meta". These
helpers turn that into the combo strings the platform outputs understand, and back
into something readable for the button. Pure string work: testable without Qt.
"""
from __future__ import annotations

import sys

_QT_KEYS = {
    "del": "delete", "ins": "insert", "pgup": "pageup", "pgdown": "pagedown", "esc": "esc",
    "return": "enter", "enter": "enter", "backspace": "backspace", "space": "space", "tab": "tab",
    "home": "home", "end": "end", "left": "left", "right": "right", "up": "up", "down": "down",
    "print": "printscreen", "capslock": "capslock", "menu": "menu",
    ",": "comma", ".": "period", "/": "slash", ";": "semicolon", "'": "quote", "`": "backquote",
    "[": "lbracket", "]": "rbracket", "\\": "backslash", "-": "minus", "=": "equals", "+": "plus",
}
_MODS = ("ctrl", "cmd", "win", "alt", "shift")   # the usual reading order
_SHOW = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win", "cmd": "Cmd",
         "pageup": "Page Up", "pagedown": "Page Down", "printscreen": "Print Screen",
         "esc": "Esc", "enter": "Enter", "space": "Space", "tab": "Tab", "delete": "Delete",
         "backspace": "Backspace", "comma": ",", "period": ".", "slash": "/", "semicolon": ";",
         "quote": "'", "backquote": "`", "lbracket": "[", "rbracket": "]", "backslash": "\\",
         "minus": "-", "equals": "=", "plus": "+"}
_MAC_SHOW = {"cmd": "⌘", "alt": "⌥", "shift": "⇧", "ctrl": "⌃"}


def from_qt(portable: str, platform: str | None = None) -> str:
    """'Ctrl+Alt+V' (QKeySequence PortableText, first chord) -> 'ctrl+alt+v'. '' if empty."""
    platform = platform or sys.platform
    chord = portable.split(",")[0].strip()
    if not chord:
        return ""
    parts = chord.split("+")
    if chord.endswith("++"):                          # "Ctrl++": the key itself is plus
        parts = parts[:-2] + ["+"]
    out = []
    for p in parts:
        k = p.strip().lower()
        if not k:
            continue
        if k == "meta":
            k = "ctrl" if platform == "darwin" else "win"
        elif k == "ctrl" and platform == "darwin":
            k = "cmd"
        else:
            k = _QT_KEYS.get(k, k)
        out.append(k)
    mods = [m for m in _MODS if m in out]
    keys = [k for k in out if k not in _MODS]
    return "+".join(mods + keys)


def to_qt(combo: str, platform: str | None = None) -> str:
    """Inverse of from_qt, for showing a stored combo in the recorder."""
    platform = platform or sys.platform
    rev = {v: k for k, v in _QT_KEYS.items()}
    out = []
    for k in (c.strip().lower() for c in combo.split("+") if c.strip()):
        if k == "cmd":
            out.append("Ctrl" if platform == "darwin" else "Meta")
        elif k == "ctrl":
            out.append("Meta" if platform == "darwin" else "Ctrl")
        elif k == "win":
            out.append("Meta")
        elif k in ("alt", "shift"):
            out.append(k.title())
        else:
            q = rev.get(k, k)
            out.append(q.upper() if len(q) == 1 else q.title())
    return "+".join(out)


def pretty(combo: str, platform: str | None = None) -> str:
    """'ctrl+alt+v' -> 'Ctrl + Alt + V' (Windows) or '⌃⌥V' (macOS)."""
    platform = platform or sys.platform
    keys = [c.strip().lower() for c in combo.split("+") if c.strip()]
    if platform == "darwin":
        return "".join(_MAC_SHOW.get(k) or _SHOW.get(k) or k.upper() for k in keys)
    return " + ".join(_SHOW.get(k) or (k.upper() if len(k) <= 3 else k.title()) for k in keys)
