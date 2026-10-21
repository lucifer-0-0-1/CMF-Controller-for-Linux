"""macOS key names -> virtual key codes (kVK_*, HIToolbox/Events.h) and modifier flags.

Pure data + parsing, no PyObjC, so it is testable anywhere.
Letters use ANSI physical positions (like kVK_ANSI_*).
"""
from __future__ import annotations

KEYCODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07,
    "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10,
    "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17,
    "equals": 0x18, "plus": 0x18, "9": 0x19, "7": 0x1A, "minus": 0x1B, "8": 0x1C, "0": 0x1D,
    "rbracket": 0x1E, "o": 0x1F, "u": 0x20, "lbracket": 0x21, "i": 0x22, "p": 0x23,
    "enter": 0x24, "return": 0x24, "l": 0x25, "j": 0x26, "quote": 0x27, "k": 0x28,
    "semicolon": 0x29, "backslash": 0x2A, "comma": 0x2B, "slash": 0x2C, "n": 0x2D, "m": 0x2E,
    "period": 0x2F, "tab": 0x30, "space": 0x31, "backquote": 0x32, "backspace": 0x33,
    "esc": 0x35, "escape": 0x35,
    "cmd": 0x37, "shift": 0x38, "capslock": 0x39, "alt": 0x3A, "ctrl": 0x3B,
    "fn": 0x3F, "volumeup": 0x48, "volumedown": 0x49, "mute": 0x4A,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61, "f7": 0x62,
    "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F, "f13": 0x69, "f14": 0x6B,
    "f15": 0x71, "f16": 0x6A, "f17": 0x40,
    "home": 0x73, "pageup": 0x74, "delete": 0x75, "del": 0x75, "end": 0x77, "pagedown": 0x79,
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
}
# Windows-flavoured names people will type in shared configs
ALIASES = {"win": "cmd", "command": "cmd", "option": "alt", "opt": "alt", "control": "ctrl"}

FLAGS = {"cmd": 0x100000, "shift": 0x020000, "alt": 0x080000, "ctrl": 0x040000, "fn": 0x800000}


def norm(name: str) -> str:
    n = name.strip().lower()
    return ALIASES.get(n, n)


def keycode(name: str) -> int:
    n = norm(name)
    if n not in KEYCODES:
        raise ValueError(f"unknown key '{name}' on macOS")
    return KEYCODES[n]


def parse(combo: str) -> tuple[list[int], int, int]:
    """'cmd+shift+z' -> (modifier keycodes, flag mask, main keycode)."""
    parts = [norm(p) for p in combo.split("+") if p.strip()] or ["plus"]
    *mods, main = parts
    for m in mods:
        if m not in FLAGS:
            raise ValueError(f"'{m}' is not a modifier (combo '{combo}')")
    flags = 0
    for m in mods:
        flags |= FLAGS[m]
    return [keycode(m) for m in mods], flags, keycode(main)
