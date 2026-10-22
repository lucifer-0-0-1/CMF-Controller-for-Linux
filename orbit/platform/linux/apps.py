"""Linux desktop application scanner and launcher.

Discovers desktop applications from XDG system and user directories,
extracts app metadata (name, icon, categories, exec command),
and launches applications cleanly in their own process session.
"""
from __future__ import annotations

import configparser
import glob
import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("orbit.apps")

SEARCH_DIRS = [
    os.path.expanduser("~/.local/share/applications"),
    "/usr/local/share/applications",
    "/usr/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
]

ICON_SEARCH_DIRS = [
    os.path.expanduser("~/.local/share/icons"),
    "/usr/share/icons/hicolor/scalable/apps",
    "/usr/share/icons/hicolor/48x48/apps",
    "/usr/share/icons/hicolor/128x128/apps",
    "/usr/share/icons/hicolor/256x256/apps",
    "/usr/share/pixmaps",
]

_APP_CACHE: list[AppInfo] | None = None
_ICON_CACHE: dict[str, str | None] = {}


@dataclass
class AppInfo:
    id: str
    name: str
    icon: str
    exec_cmd: str
    desktop_file: str
    categories: list[str]
    icon_path: str | None = None

    def to_item(self) -> dict:
        return {
            "id": f"app:{self.id}",
            "label": self.name,
            "icon": self.icon if self.icon else "app",
            "glyph": self.name[:2].upper() if self.name else "APP",
            "sticky": False,
            "exec_cmd": self.exec_cmd,
            "desktop_file": self.desktop_file,
        }


def find_icon_path(icon_name: str) -> str | None:
    """Find absolute path to an icon file on disk."""
    if not icon_name:
        return None
    if os.path.isabs(icon_name) and os.path.isfile(icon_name):
        return icon_name
    if icon_name in _ICON_CACHE:
        return _ICON_CACHE[icon_name]

    # Check common icon extensions
    extensions = [".svg", ".png", ".xpm"]
    for base_dir in ICON_SEARCH_DIRS:
        if not os.path.isdir(base_dir):
            continue
        for ext in [""] + extensions:
            target = os.path.join(base_dir, icon_name + ext)
            if os.path.isfile(target):
                _ICON_CACHE[icon_name] = target
                return target

    # Try Qt theme lookup if Qt is active
    try:
        from PySide6.QtGui import QIcon
        qicon = QIcon.fromTheme(icon_name)
        if not qicon.isNull():
            _ICON_CACHE[icon_name] = icon_name
            return icon_name
    except Exception:
        pass

    _ICON_CACHE[icon_name] = None
    return None


def clean_exec(raw_exec: str) -> str:
    """Strip desktop entry field codes (%f, %F, %u, %U, etc.)."""
    cleaned = re.sub(r"%[a-zA-Z]", "", raw_exec).strip()
    return cleaned


def scan_applications(force_refresh: bool = False) -> list[AppInfo]:
    """Scan and return all installed user-launchable desktop applications."""
    global _APP_CACHE
    if _APP_CACHE is not None and not force_refresh:
        return _APP_CACHE

    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    apps: list[AppInfo] = []

    for directory in SEARCH_DIRS:
        if not os.path.isdir(directory):
            continue
        for file_path in glob.glob(os.path.join(directory, "*.desktop")):
            app_id = os.path.splitext(os.path.basename(file_path))[0]
            if app_id in seen_ids:
                continue

            cp = configparser.ConfigParser(interpolation=None)
            try:
                cp.read(file_path, encoding="utf-8")
                sec = "Desktop Entry"
                if not cp.has_section(sec):
                    continue
                if cp.get(sec, "Type", fallback="").strip() != "Application":
                    continue
                if cp.getboolean(sec, "NoDisplay", fallback=False):
                    continue
                if cp.getboolean(sec, "Hidden", fallback=False):
                    continue

                name = cp.get(sec, "Name", fallback="").strip()
                if not name or name in seen_names:
                    continue

                exec_raw = cp.get(sec, "Exec", fallback="").strip()
                if not exec_raw:
                    continue

                exec_cmd = clean_exec(exec_raw)
                icon = cp.get(sec, "Icon", fallback="").strip()
                cats = [c.strip() for c in cp.get(sec, "Categories", fallback="").split(";") if c.strip()]
                icon_path = find_icon_path(icon)

                app = AppInfo(
                    id=app_id,
                    name=name,
                    icon=icon or "app",
                    exec_cmd=exec_cmd,
                    desktop_file=file_path,
                    categories=cats,
                    icon_path=icon_path,
                )
                apps.append(app)
                seen_ids.add(app_id)
                seen_names.add(name)
            except Exception as ex:
                log.debug("error reading %s: %s", file_path, ex)

    # Sort alphabetically by app name
    apps.sort(key=lambda a: a.name.lower())
    _APP_CACHE = apps
    log.info("scanned %d installed desktop applications", len(apps))
    return apps


def launch(target: AppInfo | str) -> bool:
    """Launch an application given an AppInfo or executable/desktop file."""
    try:
        if isinstance(target, AppInfo):
            if os.path.isfile(target.desktop_file):
                try:
                    subprocess.Popen(
                        ["gio", "launch", target.desktop_file],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    log.info("launched app '%s' via gio", target.name)
                    return True
                except FileNotFoundError:
                    pass
            cmd = target.exec_cmd
        else:
            cmd = str(target)

        args = shlex.split(cmd)
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        log.info("launched app command: %s", args[0])
        return True
    except Exception as ex:
        log.error("failed to launch '%s': %s", target, ex)
        return False
