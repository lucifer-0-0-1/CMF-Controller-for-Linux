"""CMF Linux Controller daemon: system tray, socket IPC, and device coordinator."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from cmf.backend.audio import AudioController
from cmf.backend.buttons import EvdevButtonSource
from cmf.backend.dial import BlueZDialSource
from cmf.backend.kde import KDEController
from cmf.backend.nothing import CMFBudsManager, NothingPhoneManager
from cmf.backend.uinput import UInputDevice
from cmf.core.engine import ControllerEngine
from cmf.ui.control_center import ControlCenterWindow
from cmf.ui.overlay import WaylandOverlayUI

log = logging.getLogger("cmf")
SOCKET_NAME = "cmf_controller_ipc"


def setup_logging(debug: bool = False):
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname).1s cmf: %(message)s",
        datefmt="%H:%M:%S",
    )


def ping_running(cmd: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(cmd.encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(300)
    sock.disconnectFromServer()
    return True


def make_tray_icon() -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#D71921"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 28, 28)
    p.setBrush(QColor("#0E0F14"))
    p.drawEllipse(7, 7, 18, 18)
    p.setBrush(QColor("#FFFFFF"))
    p.drawEllipse(13, 13, 6, 6)
    p.end()
    return QIcon(pm)


def run():
    parser = argparse.ArgumentParser(description="CMF Buds Pro 2 Native Linux Controller")
    parser.add_argument("--wheel", action="store_true", help="Open the on-screen wheel")
    parser.add_argument("--apps", action="store_true", help="Open the applications sub-wheel")
    parser.add_argument("--gui", "--control", dest="gui", action="store_true", help="Open the Nothing Control Center")
    parser.add_argument("--anc", action="store_true", help="Cycle ANC mode on CMF Buds")
    parser.add_argument("--ring", action="store_true", help="Ring Nothing Phone (4b)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(args.debug)

    # Route command to running instance if active
    if args.wheel and ping_running("wheel"):
        return 0
    if args.apps and ping_running("apps"):
        return 0
    if args.gui and ping_running("gui"):
        return 0
    if args.anc and ping_running("anc"):
        return 0
    if args.ring and ping_running("ring"):
        return 0
    if not any([args.wheel, args.apps, args.gui, args.anc, args.ring]) and ping_running("gui"):
        log.info("controller already running; opened Control Center")
        return 0

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("CMF Controller")

    # Native subsystems
    audio = AudioController()
    uinput = UInputDevice()
    kde = KDEController()
    nothing_buds = CMFBudsManager()
    nothing_phone = NothingPhoneManager()

    # Engine & UI
    overlay_ui = WaylandOverlayUI()

    engine_holder = []

    def dispatch_event(ev):
        if engine_holder:
            engine_holder[0].handle(ev)

    dial_source = BlueZDialSource(emit=dispatch_event)
    button_source = EvdevButtonSource(emit=dispatch_event)

    engine = ControllerEngine(
        ui=overlay_ui,
        audio=audio,
        uinput=uinput,
        kde=kde,
        nothing_buds=nothing_buds,
        nothing_phone=nothing_phone,
        dial_source=dial_source,
    )
    engine_holder.append(engine)

    # Start native hardware listeners
    dial_source.start()
    button_source.start()

    # GUI Window
    control_win = None

    def open_control_center():
        nonlocal control_win
        if control_win is None:
            control_win = ControlCenterWindow(engine=engine)
        control_win.show()
        control_win.raise_()
        control_win.activateWindow()

    # System Tray
    tray = QSystemTrayIcon(make_tray_icon(), app)
    tray.setToolTip("CMF Controller (Nothing OS)")
    menu = QMenu()

    a_ctrl = QAction("Nothing Control Center…")
    a_ctrl.triggered.connect(open_control_center)
    menu.addAction(a_ctrl)

    a_wheel = QAction("Show Wheel")
    a_wheel.triggered.connect(engine.open_wheel)
    menu.addAction(a_wheel)

    a_apps = QAction("Show Applications Wheel")
    a_apps.triggered.connect(engine.open_apps_wheel)
    menu.addAction(a_apps)

    menu.addSeparator()

    a_anc = QAction("Toggle ANC Mode")
    a_anc.triggered.connect(lambda: nothing_buds.cycle_anc())
    menu.addAction(a_anc)

    a_phone = QAction("Ring Nothing Phone")
    a_phone.triggered.connect(lambda: nothing_phone.ring_phone())
    menu.addAction(a_phone)

    menu.addSeparator()

    a_quit = QAction("Quit")
    a_quit.triggered.connect(app.quit)
    menu.addAction(a_quit)

    tray.setContextMenu(menu)
    tray.activated.connect(lambda r: open_control_center() if r == QSystemTrayIcon.Trigger else None)
    tray.show()

    # Local IPC Server
    server = QLocalServer()
    QLocalServer.removeServer(SOCKET_NAME)

    def on_ipc_connection():
        conn = server.nextPendingConnection()
        if not conn:
            return

        def read_ipc():
            cmd = bytes(conn.readAll()).strip().decode("utf-8", errors="ignore")
            if cmd == "wheel":
                engine.open_wheel()
            elif cmd == "apps":
                engine.open_apps_wheel()
            elif cmd == "gui":
                open_control_center()
            elif cmd == "anc":
                nothing_buds.cycle_anc()
            elif cmd == "ring":
                nothing_phone.ring_phone()

        conn.readyRead.connect(read_ipc)
        conn.disconnected.connect(conn.deleteLater)

    server.newConnection.connect(on_ipc_connection)
    if not server.listen(SOCKET_NAME):
        log.warning("cannot listen on IPC socket: %s", server.errorString())

    # Handle initial CLI actions
    if args.wheel:
        QTimer.singleShot(250, engine.open_wheel)
    elif args.apps:
        QTimer.singleShot(250, engine.open_apps_wheel)
    elif args.gui:
        QTimer.singleShot(250, open_control_center)

    # Periodic engine tick timer (for auto-dismissing wheel after timeout)
    tick_timer = QTimer()
    tick_timer.timeout.connect(engine.tick)
    tick_timer.start(100)

    def cleanup():
        log.info("shutting down CMF Controller...")
        dial_source.stop()
        button_source.stop()
        try:
            server.close()
        except Exception:
            pass

    app.aboutToQuit.connect(cleanup)

    log.info("CMF Controller is running natively on Wayland!")
    return app.exec()
