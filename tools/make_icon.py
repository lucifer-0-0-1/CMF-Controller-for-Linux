"""Render Orbit's icons from one drawing (no design tool needed).

    python tools/make_icon.py

Writes, into orbit/ui/icons/:
  orbit.png        1024 x 1024 app icon (macOS .app via packaging/mac/build_app.sh,
                   window icons, Windows tray)
  orbit_tray.png   44 x 44 black-on-transparent menu-bar template (macOS tints it)

The mark is the wheel itself: a dark disc whose selected item is a light source,
lighting the disc around it and catching the rim.
"""
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath,  # noqa: E402
                           QPen, QRadialGradient)

OUT = Path(__file__).resolve().parents[1] / "orbit" / "ui" / "icons"
ACCENT = QColor("#7C9CFF")
LIT_DEG = 40                     # where the selected item sits (clockwise from 12 o'clock)
ITEMS = 8


def a(c: QColor, alpha: float) -> QColor:
    return QColor(c.red(), c.green(), c.blue(), max(0, min(255, int(255 * alpha))))


def polar(c: QPointF, r: float, deg: float) -> QPointF:
    t = math.radians(deg)
    return QPointF(c.x() + r * math.sin(t), c.y() - r * math.cos(t))


def app_icon(size: int = 1024) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 1024

    # macOS icon grid: 824 px tile, ~185 px corners, soft drop shadow
    tile = QRectF(100 * s, 100 * s, 824 * s, 824 * s)
    for i in range(14):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 7))
        p.drawRoundedRect(tile.adjusted(-i * s, (12 - i) * s, i * s, (14 + i) * s), 185 * s, 185 * s)
    g = QLinearGradient(tile.topLeft(), tile.bottomLeft())
    g.setColorAt(0, QColor("#1F2330"))
    g.setColorAt(1, QColor("#0B0C11"))
    p.setBrush(g)
    p.drawRoundedRect(tile, 185 * s, 185 * s)

    c = QPointF(512 * s, 512 * s)
    R = 300 * s
    lit = polar(c, 205 * s, LIT_DEG)

    # light spilling past the rim, nearest the lit item
    spill = QRadialGradient(lit, 300 * s)
    for pos, al in ((0, 0.55), (0.25, 0.28), (0.55, 0.08), (1, 0)):
        spill.setColorAt(pos, a(ACCENT, al))
    ring = QPainterPath()
    ring.addEllipse(c, R + 70 * s, R + 70 * s)
    ring.addEllipse(c, R, R)
    p.save()
    clip = QPainterPath()
    clip.addRoundedRect(tile, 185 * s, 185 * s)
    p.setClipPath(clip)
    p.fillPath(ring, spill)
    p.restore()

    # the disc
    p.setBrush(QColor("#0B0C11"))
    p.setPen(QPen(QColor(255, 255, 255, 22), 3 * s))
    p.drawEllipse(c, R, R)
    # light across the disc
    light = QRadialGradient(lit, 420 * s)
    for pos, al in ((0, 0.70), (0.08, 0.50), (0.20, 0.26), (0.40, 0.09), (0.65, 0.02), (1, 0)):
        light.setColorAt(pos, a(ACCENT, al))
    p.setPen(Qt.NoPen)
    p.setBrush(light)
    p.drawEllipse(c, R - 2 * s, R - 2 * s)
    # the rim catching it
    for span, al in ((90, 0.18), (50, 0.45), (22, 0.95)):
        p.setPen(QPen(a(ACCENT, al), 7 * s, Qt.SolidLine, Qt.RoundCap if span < 30 else Qt.FlatCap))
        p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), int((90 - LIT_DEG - span / 2) * 16), int(span * 16))
    # the other items: quiet dots around the ring
    for i in range(ITEMS):
        deg = LIT_DEG + i * 360 / ITEMS
        if i == 0:
            continue
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 60))
        p.drawEllipse(polar(c, 205 * s, deg), 15 * s, 15 * s)
    # the lit item: a bright core with a soft bloom
    bloom = QRadialGradient(lit, 90 * s)
    bloom.setColorAt(0, QColor(255, 255, 255, 230))
    bloom.setColorAt(0.25, a(ACCENT, 0.85))
    bloom.setColorAt(1, a(ACCENT, 0))
    p.setBrush(bloom)
    p.drawEllipse(lit, 90 * s, 90 * s)
    p.setBrush(QColor("#FFFFFF"))
    p.drawEllipse(lit, 30 * s, 30 * s)
    p.end()
    return img


def tray_template(size: int = 44) -> QImage:
    """Menu-bar template: macOS recolours it for light/dark menu bars."""
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 44
    c = QPointF(22 * s, 22 * s)
    p.setPen(QPen(QColor(0, 0, 0, 255), 3.2 * s))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(c, 15 * s, 15 * s)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 255))
    p.drawEllipse(polar(c, 9.5 * s, LIT_DEG), 4.6 * s, 4.6 * s)
    p.end()
    return img


if __name__ == "__main__":
    app = QGuiApplication(sys.argv[:1])
    app_icon().save(str(OUT / "orbit.png"))
    tray_template().save(str(OUT / "orbit_tray.png"))
    print("wrote", OUT / "orbit.png", "and", OUT / "orbit_tray.png")
