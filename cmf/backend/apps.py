"""Fast Linux XDG desktop applications scanner, icon resolver, and launcher."""
from __future__ import annotations

import configparser
import glob
import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass

log = logging.getLogger("cmf.apps")

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
            "glyph": self.name[:2].upper() if self.name else "AP",
            "sticky": False,
            "exec_cmd": self.exec_cmd,
            "desktop_file": self.desktop_file,
        }


def find_icon_path(icon_name: str) -> str | None:
    if not icon_name:
        return None
    if os.path.isabs(icon_name) and os.path.isfile(icon_name):
        return icon_name
    if icon_name in _ICON_CACHE:
        return _ICON_CACHE[icon_name]

    for base_dir in ICON_SEARCH_DIRS:
        if not os.path.isdir(base_dir):
            continue
        for ext in ["", ".svg", ".png", ".xpm"]:
            target = os.path.join(base_dir, icon_name + ext)
            if os.path.isfile(target):
                _ICON_CACHE[icon_name] = target
                return target

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


def clean_exec(raw: str) -> str:
    return re.sub(r"%[a-zA-Z]", "", raw).strip()


def parse_desktop_file(filepath: str) -> AppInfo | None:
    """Parse a single .desktop file into an AppInfo or None if invalid/hidden."""
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read(filepath, encoding="utf-8")
        sec = "Desktop Entry"
        if not cp.has_section(sec):
            return None
        if cp.get(sec, "Type", fallback="").strip() != "Application":
            return None
        if cp.getboolean(sec, "NoDisplay", fallback=False) or cp.getboolean(sec, "Hidden", fallback=False):
            return None

        name = cp.get(sec, "Name", fallback="").strip()
        if not name:
            return None

        exec_raw = cp.get(sec, "Exec", fallback="").strip()
        if not exec_raw:
            return None

        icon = cp.get(sec, "Icon", fallback="").strip()
        cats = [c.strip() for c in cp.get(sec, "Categories", fallback="").split(";") if c.strip()]
        app_id = os.path.splitext(os.path.basename(filepath))[0]
        icon_path = find_icon_path(icon)

        return AppInfo(
            id=app_id,
            name=name,
            icon=icon or "app",
            exec_cmd=clean_exec(exec_raw),
            desktop_file=filepath,
            categories=cats,
            icon_path=icon_path,
        )
    except Exception:
        return None


def scan_applications(force: bool = False) -> list[AppInfo]:
    global _APP_CACHE
    if _APP_CACHE is not None and not force:
        return _APP_CACHE

    seen_names = set()
    seen_ids = set()
    apps: list[AppInfo] = []

    for d in SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        for f in glob.glob(os.path.join(d, "*.desktop")):
            app_id = os.path.splitext(os.path.basename(f))[0]
            if app_id in seen_ids:
                continue

            app = parse_desktop_file(f)
            if app and app.name not in seen_names:
                apps.append(app)
                seen_ids.add(app_id)
                seen_names.add(app.name)

    apps.sort(key=lambda a: a.name.lower())
    _APP_CACHE = apps
    return apps


def launch(target: AppInfo | str) -> bool:
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
                    return True
                except FileNotFoundError:
                    pass
            cmd = target.exec_cmd
        else:
            cmd = str(target)

        args = shlex.split(cmd)
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception as ex:
        log.error("failed to launch %s: %s", target, ex)
        return False
