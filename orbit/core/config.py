"""Config: TOML file, validated, with defaults filled in."""
from __future__ import annotations

import copy
import os
import sys
import tomllib
from pathlib import Path

DEFAULTS: dict = {
    "device": {"audio_endpoint_match": "CMF Buds Pro 2"},
    "gestures": {
        "click": "media:play_pause",
        "triple": "last_tool",
        "open_wheel": ["double", "hold"],
        "open_wheel_fallback": "triple",
    },
    "wheel": {"items": [], "dismiss_after_ms": 6000, "duck_volume": 0.5, "accel": 1},
    "ui": {"hud_ms": 1400, "scale": 1.0, "accent": "#7C9CFF", "hide_os_volume_flyout": True,
           "appearance": "dark"},
    "tools": {},
    "claude": {"shortcut": "ctrl+alt+v"},
}

APPEARANCES = ("system", "dark", "light")
PROJECT_CONFIG = Path(__file__).resolve().parents[2] / "config.toml"


def user_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "Orbit" / "config.toml"


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


USER_STUB = """# Orbit: your changes.
# Orbit reads its built-in config.toml first, then this file on top of it, so put only
# the keys you want to change here. New defaults from updates still reach you.
# Most things (wheel items, gestures, appearance, shortcuts) are easier in Settings.
#
# Examples:
# [tools.scroll]
# max_gain = 5            # scroll further when turning fast
#
# [wheel]
# dismiss_after_ms = 4000
"""


def base_config() -> Path:
    """The built-in config: next to the code, or inside a packaged app."""
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "config.toml"
    if getattr(sys, "frozen", False) and bundled.exists():
        return bundled
    if PROJECT_CONFIG.exists():
        return PROJECT_CONFIG
    if bundled.exists():
        return bundled
    raise FileNotFoundError("no built-in config.toml found")


def user_overrides(create: bool = False) -> Path | None:
    """The user's own file, merged over the built-in config. With `create`, a commented
    stub is written on first use (a full copy would freeze every default at that day)."""
    p = user_config_path()
    if not p.exists() and create:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(USER_STUB, encoding="utf-8")
    return p if p.exists() else None


def find(explicit: str | None) -> Path:
    """The file to open for editing ("Open config"): --config, else the user overrides."""
    if explicit:
        return Path(explicit)
    return user_overrides(create=True) or base_config()


PLATFORM_KEYS = {"win32": "windows", "darwin": "mac", "linux": "linux"}


def current_platform() -> str:
    return PLATFORM_KEYS.get(sys.platform, sys.platform)


def apply_platform(cfg: dict, platform: str | None = None) -> dict:
    """Merge [platforms.<name>] over the shared config, e.g. Cmd instead of Ctrl on mac.
    A tool or gesture set there replaces individual keys, not the whole table."""
    platform = platform or current_platform()
    overrides = cfg.pop("platforms", {})
    return _merge(cfg, overrides.get(platform, {}))


def _read(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def load(explicit: str | None = None, platform: str | None = None,
         user_settings: dict | None = None) -> tuple[dict, Path]:
    """Built-in config.toml and its [platforms.<os>], then the user's overrides and theirs
    on top (or a full --config file), then the Settings window's choices (`user_settings`).
    Returns the config and the path to open for editing."""
    if explicit:
        path = Path(explicit)
        cfg = apply_platform(_merge(DEFAULTS, _read(path)), platform)
    else:
        # built-in (with its per-OS tweaks), then the user's file (with theirs) on top:
        # a user setting always beats a built-in one, per-OS or not
        cfg = apply_platform(_merge(DEFAULTS, _read(base_config())), platform)
        user = user_overrides(create=getattr(sys, "frozen", False))
        if user:
            cfg = apply_platform(_merge(cfg, _read(user)), platform)
        path = user or base_config()
    if user_settings:
        from orbit.core import settings
        cfg = settings.apply(cfg, user_settings)
    validate(cfg)
    return cfg, path


def validate(cfg: dict) -> None:
    from orbit.core import actions, tools

    if not cfg["tools"]:
        raise ValueError("config: [tools] is empty")
    for tid, tc in cfg["tools"].items():
        tools.build(tid, tc)  # raises on bad type / bad action strings
    missing = [i for i in cfg["wheel"]["items"] if i not in cfg["tools"]]
    if missing:
        raise ValueError(f"config: wheel.items references unknown tools: {missing}")
    if not cfg["wheel"]["items"]:
        cfg["wheel"]["items"] = list(cfg["tools"])
    if len(cfg["wheel"]["items"]) > 12:
        raise ValueError("config: more than 12 wheel items is unusable on a dial; keep it to 8 or fewer")
    if cfg["ui"].get("appearance") not in APPEARANCES:
        raise ValueError(f"config: ui.appearance must be one of {list(APPEARANCES)}")
    dt = cfg.get("default_tool")
    if dt and dt not in cfg["tools"]:
        raise ValueError(f"config: default_tool '{dt}' is not a tool")
    names = {"click", "double", "triple", "hold"}
    g_cfg = cfg["gestures"]
    opens = g_cfg.get("open_wheel", [])
    opens = [opens] if isinstance(opens, str) else opens
    bad = [o for o in [*opens, g_cfg.get("open_wheel_fallback", "triple")] if o not in names]
    if bad:
        raise ValueError(f"config: gestures.open_wheel must use {sorted(names)}, got {bad}")
    for g, a in g_cfg.items():
        if g not in ("open_wheel", "open_wheel_fallback"):
            actions.parse(a)
