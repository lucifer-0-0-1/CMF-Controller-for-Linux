"""Asset and icon resolver for CMF Linux Controller."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QUrl

ICON_DIR = Path(__file__).resolve().parent / "icons"
TINT_DIR = Path(tempfile.gettempdir()) / "cmf-icons"


def _find_icon(icon: str) -> Path | None:
    p = Path(icon)
    if p.is_absolute() and p.exists():
        return p
    f = ICON_DIR / f"{icon}.svg"
    if f.exists():
        return f
    # Check Linux system icons
    try:
        from cmf.backend.apps import find_icon_path
        sys_path = find_icon_path(icon)
        if sys_path and os.path.isfile(sys_path):
            return Path(sys_path)
    except Exception:
        pass
    return None


find_icon = _find_icon
get_icon_path = _find_icon


def tinted_url(icon: str, color: str) -> str:
    src = _find_icon(icon)
    if src is None:
        return ""
    if src.suffix.lower() == ".png":
        return QUrl.fromLocalFile(str(src)).toString()
    if src.suffix.lower() == ".svg" and src.parent != ICON_DIR:
        return QUrl.fromLocalFile(str(src)).toString()

    color = color.lower()
    stroke = f'stroke="{color}"'
    if len(color) == 9:
        stroke = f'stroke="#{color[3:]}" stroke-opacity="{int(color[1:3], 16) / 255:.3f}"'
    key = hashlib.sha1(f"{src}|{src.stat().st_mtime}|{color}".encode()).hexdigest()[:16]
    out = TINT_DIR / f"{src.stem}-{key}.svg"
    if not out.exists():
        TINT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(src.read_text(encoding="utf-8").replace('stroke="#ffffff"', stroke), encoding="utf-8")
    return QUrl.fromLocalFile(str(out)).toString()
