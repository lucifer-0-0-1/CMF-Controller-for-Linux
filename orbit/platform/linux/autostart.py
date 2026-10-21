"""Linux autostart implementation following the XDG Autostart specification."""
from __future__ import annotations

import sys
from pathlib import Path

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
DESKTOP_FILE = AUTOSTART_DIR / "orbit.desktop"

DESKTOP_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Orbit
GenericName=CMF Buds Pro 2 Dial Controller
Comment=Turn your CMF Buds Pro 2 dial into a Linux tool wheel
Exec={executable} -m orbit
Icon=orbit
Terminal=false
Categories=Utility;HardwareSettings;
StartupNotify=false
X-GNOME-Autostart-enabled=true
"""


def is_enabled() -> bool:
    return DESKTOP_FILE.exists()


def set_enabled(on: bool) -> None:
    if on:
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        DESKTOP_FILE.write_text(
            DESKTOP_TEMPLATE.format(executable=sys.executable),
            encoding="utf-8",
        )
    else:
        try:
            DESKTOP_FILE.unlink(missing_ok=True)
        except Exception:
            pass
