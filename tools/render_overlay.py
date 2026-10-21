"""Render the wheel and HUD offscreen to PNGs (no visible window, works headless / in CI).

    python tools/render_overlay.py out_prefix
Writes <prefix>_wheel.png and <prefix>_hud.png. Exit code 1 if either drew nothing.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32":                      # the offscreen platform ships no fonts
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.expandvars(r"%WINDIR%\Fonts"))
elif sys.platform == "darwin":
    os.environ.setdefault("QT_QPA_FONTDIR", "/System/Library/Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import shiboken6
from PySide6.QtCore import QTimer, qInstallMessageHandler
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QApplication

from orbit.core import config, tools
from orbit.ui.qtui import QtUI

out = sys.argv[1] if len(sys.argv) > 1 else "overlay"
warnings = []
qInstallMessageHandler(lambda mode, ctx, msg: warnings.append(msg))

app = QApplication(sys.argv[:1])
cfg, _ = config.load()
cfg["wheel"]["dismiss_after_ms"] = 60000
cfg["ui"]["appearance"] = os.environ.get("ORBIT_APPEARANCE", cfg["ui"]["appearance"])
ui = QtUI(cfg)
wheel_win, hud_win = (shiboken6.wrapInstance(shiboken6.getCppPointer(w)[0], QQuickWindow) for w in ui.windows)
items = [tools.build(i, cfg["tools"][i]).to_item() for i in cfg["wheel"]["items"]]
ok = {"wheel": False, "hud": False}


def painted(img, step=5):
    n = 0
    for x in range(0, img.width(), step):
        for y in range(0, img.height(), step):
            if img.pixelColor(x, y).alpha() > 120:     # glass is ~60% opaque
                n += 1
    return n


def shot_wheel():
    img = wheel_win.grabWindow()
    img.save(out + "_wheel.png")
    ok["wheel"] = painted(img) > 1500
    ui.wheel_cancel()
    QTimer.singleShot(500, lambda: ui.hud(tools.Hud("brightness", "Brightness", "45%", 0.45, 1)))
    QTimer.singleShot(1300, shot_hud)


def shot_hud():
    img = hud_win.grabWindow()
    img.save(out + "_hud.png")
    ok["hud"] = painted(img, 3) > 150
    app.quit()


QTimer.singleShot(100, lambda: ui.wheel_open(items, 0))
QTimer.singleShot(700, lambda: ui.wheel_move(2, 1))
QTimer.singleShot(1500, shot_wheel)
app.exec()
for w in warnings:
    if "ffmpeg" not in w and "offscreen" not in w.lower():
        print("QT:", w)
print("rendered:", ok)
sys.exit(0 if all(ok.values()) else 1)
