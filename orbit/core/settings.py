"""User settings from the Settings window, layered over config.toml.

config.toml stays the hand-edited source (with its comments); the window writes a
small settings.json next to the user config and this module applies it on load:

    {
      "wheel": {"order": ["volume", "scroll", ...],     # every tool, in wheel order
                "enabled": ["volume", "scroll"]},       # the ones switched on
      "default_tool": "volume",
      "appearance": "system",                           # system | dark | light
      "claude_shortcut": "ctrl+alt+v",                  # Claude's Quick Entry shortcut
      "scroll": {"max_gain": 3.5, "notches_per_detent": 1.0},   # this computer's scroll feel
      "shortcuts": [{"id": "sc1a2b", "label": "Snip", "keys": "win+shift+s"}],
                                                        # wheel items that press a key combo
      "gestures": {"click": "media:play_pause", "double": "open_wheel",
                   "triple": "last_tool", "hold": ["keys:ctrl+alt+v", "..."]}
    }

A gesture set to "open_wheel" joins gestures.open_wheel; any other action removes
it from there. Missing keys keep what config.toml says.
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

from orbit.core import config as config_mod

log = logging.getLogger("orbit.settings")

GESTURES = ("click", "double", "triple", "hold")
OPEN_WHEEL = "open_wheel"


def path() -> Path:
    return config_mod.user_config_path().with_name("settings.json")


def load(p: Path | None = None) -> dict:
    p = p or path()
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.exception("settings.json unreadable, ignoring it")
        return {}


def save(s: dict, p: Path | None = None) -> Path:
    p = p or path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def shortcut_tool_id(sid: str) -> str:
    return f"shortcut_{sid}"


def shortcut_tool(sc: dict) -> dict:
    """A one-shot wheel item that presses a key combo when picked."""
    return {"type": "action", "label": sc.get("label") or "Shortcut", "icon": "keyboard",
            "run": f"keys:{sc['keys']}"}


def gesture_action(cfg: dict, g: str):
    """What a gesture does in a (merged) config: 'open_wheel', an action string/list, or 'none'."""
    opens = cfg["gestures"].get("open_wheel", [])
    opens = [opens] if isinstance(opens, str) else opens
    if g in opens:
        return OPEN_WHEEL
    return cfg["gestures"].get(g, "none")


def wheel_order(cfg: dict) -> tuple[list[str], list[str]]:
    """(every tool in wheel order, the enabled ones) for a config."""
    enabled = list(cfg["wheel"]["items"]) or list(cfg["tools"])
    order = enabled + [t for t in cfg["tools"] if t not in enabled]
    return order, enabled


def apply(cfg: dict, s: dict) -> dict:
    """cfg with settings `s` layered on. Unknown tool ids are dropped, never fatal."""
    cfg = copy.deepcopy(cfg)
    sc_feel = s.get("scroll") or {}
    if "scroll" in cfg["tools"]:
        for k in ("max_gain", "notches_per_detent"):
            if isinstance(sc_feel.get(k), (int, float)) and sc_feel[k] > 0:
                cfg["tools"]["scroll"][k] = float(sc_feel[k])
    if s.get("claude_shortcut"):
        cfg.setdefault("claude", {})["shortcut"] = s["claude_shortcut"]
    added = []
    for sc in s.get("shortcuts") or []:
        if sc.get("id") and sc.get("keys"):
            tid = shortcut_tool_id(sc["id"])
            cfg["tools"][tid] = shortcut_tool(sc)
            added.append(tid)
    w = s.get("wheel") or {}
    if added and "enabled" not in w:            # no saved order yet: new shortcuts join the wheel
        cfg["wheel"]["items"] = [t for t in cfg["wheel"]["items"] if t in cfg["tools"]] + added
    if "enabled" in w:
        order = [t for t in w.get("order", []) if t in cfg["tools"]]
        order += [t for t in cfg["tools"] if t not in order]
        enabled = set(w["enabled"])
        items = [t for t in order if t in enabled]
        if items:
            cfg["wheel"]["items"] = items[:12]
    if s.get("appearance") in config_mod.APPEARANCES:
        cfg["ui"]["appearance"] = s["appearance"]
    dt = s.get("default_tool")
    if dt in cfg["tools"]:
        cfg["default_tool"] = dt
    g = cfg["gestures"]
    opens = g.get("open_wheel", [])
    opens = [opens] if isinstance(opens, str) else list(opens)
    for name, act in (s.get("gestures") or {}).items():
        if name not in GESTURES:
            continue
        if act == OPEN_WHEEL:
            if name not in opens:
                opens.append(name)
            g.pop(name, None)
        else:
            if name in opens:
                opens.remove(name)
            g[name] = act
    g["open_wheel"] = opens
    return cfg
