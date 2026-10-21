"""Icons for the wheel and HUD.

Bundled Lucide SVGs (ISC, see icons/LICENSE-lucide.txt) render identically on
Windows and macOS; strokes are white and tinted in QML. A config `icon` may also
be a single character (shown as text) or an absolute path to an SVG.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from PySide6.QtCore import QUrl

ICON_DIR = Path(__file__).with_name("icons")
TINT_DIR = Path(tempfile.gettempdir()) / "orbit-icons"


def _svg_path(icon: str) -> Path | None:
    p = Path(icon)
    if p.suffix.lower() == ".svg" and p.is_absolute() and p.exists():
        return p
    f = ICON_DIR / f"{icon}.svg"
    return f if f.exists() else None


def has_icon(icon: str) -> bool:
    return _svg_path(icon) is not None


def tinted_url(icon: str, color: str) -> str:
    """file:// URL of `icon` recoloured to `color` ('#rrggbb'), '' if no SVG.
    Tinting is done on the SVG text (white strokes -> color) and cached, so QML needs
    no shader effect: graphics-effect failures can never make icons disappear."""
    src = _svg_path(icon)
    if src is None:
        return ""
    color = color.lower()
    stroke = f'stroke="{color}"'
    if len(color) == 9:                       # QML's #aarrggbb -> SVG colour + opacity
        stroke = f'stroke="#{color[3:]}" stroke-opacity="{int(color[1:3], 16) / 255:.3f}"'
    key = hashlib.sha1(f"{src}|{src.stat().st_mtime}|{color}".encode()).hexdigest()[:16]
    out = TINT_DIR / f"{src.stem}-{key}.svg"
    if not out.exists():
        TINT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(src.read_text(encoding="utf-8").replace('stroke="#ffffff"', stroke), encoding="utf-8")
    return QUrl.fromLocalFile(str(out)).toString()


def glyph(icon: str, label: str) -> str:
    """Text fallback when there's no SVG: a given single character, else the label's initial."""
    if len(icon) == 1:
        return icon
    return (label or "?")[:1].upper()
