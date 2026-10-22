"""Wayland Qt Quick overlay controller for CMF Controller."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from cmf.core.tools import Hud
from cmf.ui import assets

log = logging.getLogger("cmf.overlay")
QML_PATH = Path(__file__).parent / "qml" / "Overlay.qml"


class Bridge(QObject):
    wheelOpened = Signal("QVariantList", int)
    wheelMoved = Signal(int, int)
    wheelCommitted = Signal(int)
    wheelCancelled = Signal()
    hudShown = Signal(str, str, str, str, float, int)
    placed = Signal(int, int, int, int)

    @Property(float, constant=True)
    def uiScale(self):
        return 1.0

    @Slot(str, str, result=str)
    def tint(self, icon, color):
        return assets.tinted_url(icon, color)


class WaylandOverlayUI:
    def __init__(self):
        self.bridge = Bridge()
        self.qml = QQmlApplicationEngine()
        self.qml.rootContext().setContextProperty("cmfBridge", self.bridge)
        self.qml.load(QUrl.fromLocalFile(str(QML_PATH)))
        if not self.qml.rootObjects():
            raise RuntimeError("Failed to load Wayland Overlay.qml")
        by_name = {w.objectName(): w for w in QGuiApplication.topLevelWindows()}
        self.wheel_win = by_name.get("cmfWheel")
        self.hud_win = by_name.get("cmfHud")

    def _place(self):
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = scr.geometry()
        self.bridge.placed.emit(g.x(), g.y(), g.width(), g.height())

    def wheel_open(self, items: list[dict], index: int):
        self._place()
        payload = [dict(i, glyph=i.get("label", "TL")[:2].upper()) for i in items]
        self.bridge.wheelOpened.emit(payload, index)

    def wheel_move(self, index: int, direction: int):
        self.bridge.wheelMoved.emit(index, direction)

    def wheel_commit(self, index: int):
        self.bridge.wheelCommitted.emit(index)

    def wheel_cancel(self):
        self.bridge.wheelCancelled.emit()

    def hud(self, h: Hud):
        self._place()
        self.bridge.hudShown.emit(
            h.icon,
            h.title[:2].upper(),
            h.title,
            h.detail,
            -1.0 if h.progress is None else float(h.progress),
            h.direction,
        )
