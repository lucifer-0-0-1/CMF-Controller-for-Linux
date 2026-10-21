"""Qt Quick overlay: implements the engine's UI protocol.

Two small frameless, transparent, click-through, never-focused windows (wheel,
HUD), placed on the screen under the cursor. QML does all drawing and animation.
Platform tweaks: Windows gets no-activate/tool-window styles and the software
renderer, macOS gets HUD-panel behaviour.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Qt Quick's default threaded render loop advances animations on the swapchain's
# vsync. For a transparent click-through overlay the OS may never present it, so
# animations froze at their start values (opacity 0): the wheel never appeared.
# The basic loop drives animations from a timer. Must be set before Qt starts.
os.environ.setdefault("QSG_RENDER_LOOP", "basic")
# On Windows, click-through needs a layered window, and Direct3D/OpenGL presents
# to layered windows only reliably for the first frame: later frames (every
# animation) never reached the screen. Qt Quick's software renderer updates layered
# windows the way Windows expects. The windows are small, so the CPU cost is low.
if sys.platform == "win32":
    os.environ.setdefault("QT_QUICK_BACKEND", "software")

from PySide6.QtCore import Property, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from orbit.core.tools import Hud
from orbit.ui import assets

log = logging.getLogger("orbit.ui")
QML = Path(__file__).with_name("qml") / "Overlay.qml"


class Bridge(QObject):
    wheelOpened = Signal("QVariantList", int)
    wheelMoved = Signal(int, int)
    wheelCommitted = Signal(int)
    wheelCancelled = Signal()
    # icon name, glyph fallback, title, detail, progress (-1 = none), direction
    hudShown = Signal(str, str, str, str, float, int)
    placed = Signal(int, int, int, int)
    darkChanged = Signal()

    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg
        self._appearance = cfg["ui"].get("appearance", "dark")
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):                 # Qt 6.5+: follow the OS live
            hints.colorSchemeChanged.connect(lambda *_: self.darkChanged.emit())

    def _get_dark(self) -> bool:
        if self._appearance == "system":
            hints = QGuiApplication.styleHints()
            return not hasattr(hints, "colorScheme") or hints.colorScheme() != Qt.ColorScheme.Light
        return self._appearance == "dark"

    def set_appearance(self, a: str):
        if a != self._appearance:
            self._appearance = a
            self.darkChanged.emit()

    dark = Property(bool, _get_dark, notify=darkChanged)


    @Property(str, constant=True)
    def accent(self):
        return self._cfg["ui"]["accent"]

    @Property(float, constant=True)
    def uiScale(self):
        return float(self._cfg["ui"]["scale"])

    @Property(int, constant=True)
    def hudMs(self):
        return int(self._cfg["ui"]["hud_ms"])

    @Slot(str, str, result=str)
    def tint(self, icon, color):
        return assets.tinted_url(icon, color)


class QtUI:
    """Engine-facing adapter."""

    def __init__(self, cfg: dict):
        self.bridge = Bridge(cfg)
        self.qml = QQmlApplicationEngine()
        self.qml.rootContext().setContextProperty("orbit", self.bridge)
        self.qml.load(QUrl.fromLocalFile(str(QML)))
        if not self.qml.rootObjects():
            raise RuntimeError("Overlay.qml failed to load")
        by_name = {w.objectName(): w for w in QGuiApplication.topLevelWindows()}
        self.windows = [by_name["orbitWheel"], by_name["orbitHud"]]
        self.window = self.windows[0]
        native = QGuiApplication.platformName() in ("windows", "cocoa")   # not offscreen/minimal
        for w in self.windows:
            if not native:
                continue
            if sys.platform == "win32":
                self._win_noactivate(w)
            elif sys.platform == "darwin":
                from orbit.platform.mac.overlay import macify
                w.visibleChanged.connect(lambda v, w=w: v and macify(w))
                macify(w)

    @staticmethod
    def _win_noactivate(window):
        import ctypes
        hwnd = int(window.winId())
        GWL_EXSTYLE = -20
        u = ctypes.windll.user32
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        style = u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        # NOACTIVATE | TOOLWINDOW | TRANSPARENT | LAYERED | TOPMOST
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | 0x08000000 | 0x80 | 0x20 | 0x80000 | 0x8)

    def _place(self):
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = scr.geometry()
        self.bridge.placed.emit(g.x(), g.y(), g.width(), g.height())

    # ---- UI protocol
    def wheel_open(self, items, index):
        self._place()
        payload = [dict(i, glyph=assets.glyph(i["icon"], i["label"])) for i in items]
        self.bridge.wheelOpened.emit(payload, index)

    def wheel_move(self, index, direction):
        self.bridge.wheelMoved.emit(index, direction)

    def wheel_commit(self, index):
        self.bridge.wheelCommitted.emit(index)

    def wheel_cancel(self):
        self.bridge.wheelCancelled.emit()

    def hud(self, h: Hud):
        self._place()
        self.bridge.hudShown.emit(h.icon, assets.glyph(h.icon, h.title), h.title, h.detail,
                                  -1.0 if h.progress is None else float(h.progress), h.direction)
