"""Nothing OS Desktop Control Center for Linux."""
from __future__ import annotations

import logging
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from cmf.backend.apps import launch, scan_applications
from cmf.ui import assets

log = logging.getLogger("cmf.gui")

ACCENT = "#D71921"
CANVAS = "#0C0D11"
PANEL = "#12141B"
CARD = "#191B24"
BORDER = "#252836"
INK = "#F4F6FB"
INK_DIM = "#8C92A4"


def _font(px: int, weight=QFont.Normal) -> QFont:
    f = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _icon(name: str, color: str = INK) -> QIcon:
    url = assets.tinted_url(name, color)
    return QIcon(QUrl(url).toLocalFile()) if url else QIcon()


class ControlCenterWindow(QWidget):
    def __init__(self, engine=None):
        super().__init__()
        self.engine = engine
        self.setWindowTitle("Nothing Control Center")
        self.resize(920, 640)
        self.setMinimumSize(800, 500)
        self.setStyleSheet(self._qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(18)

        # Header
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("NOTHING / CMF CONTROLLER")
        title.setFont(_font(16, QFont.Bold))
        title.setStyleSheet(f"color: {ACCENT}; letter-spacing: 2px;")
        sub = QLabel("Garuda Linux · Wayland")
        sub.setFont(_font(12))
        sub.setStyleSheet(f"color: {INK_DIM};")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        top_bar.addLayout(title_box)
        top_bar.addStretch(1)

        btn_wheel = QPushButton("  Open Wheel")
        btn_wheel.setIcon(_icon("orbit_tray", INK))
        btn_wheel.setCursor(Qt.PointingHandCursor)
        btn_wheel.clicked.connect(self._open_wheel)
        top_bar.addWidget(btn_wheel)

        btn_app_wheel = QPushButton("  Apps Wheel")
        btn_app_wheel.setIcon(_icon("app", INK))
        btn_app_wheel.setCursor(Qt.PointingHandCursor)
        btn_app_wheel.clicked.connect(self._open_apps_wheel)
        top_bar.addWidget(btn_app_wheel)

        root.addLayout(top_bar)

        # Body: Left Devices & Controls, Right Apps Launcher
        body = QHBoxLayout()
        body.setSpacing(18)

        # Left Column: Devices & Sound
        left_col = QVBoxLayout()
        left_col.setSpacing(14)

        # Card 1: CMF Buds Pro 2
        buds_card = QFrame()
        buds_card.setObjectName("card")
        bl = QVBoxLayout(buds_card)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(10)

        bh = QHBoxLayout()
        b_icon = QLabel()
        b_icon.setPixmap(_icon("volume", ACCENT).pixmap(20, 20))
        bh.addWidget(b_icon)
        b_name = QLabel("CMF Buds Pro 2")
        b_name.setFont(_font(14, QFont.DemiBold))
        bh.addWidget(b_name)
        bh.addStretch(1)
        self.b_bat_lbl = QLabel("Active")
        self.b_bat_lbl.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 11px;")
        bh.addWidget(self.b_bat_lbl)
        bl.addLayout(bh)

        anc_hdr = QLabel("Active Noise Cancellation")
        anc_hdr.setStyleSheet(f"color: {INK_DIM}; font-size: 11px;")
        bl.addWidget(anc_hdr)

        anc_box = QHBoxLayout()
        anc_box.setSpacing(8)
        self.anc_btns = {}
        for m_id, m_name in [(1, "ANC"), (2, "Transparency"), (0, "Off")]:
            btn = QPushButton(m_name)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, m=m_id: self._set_anc(m))
            self.anc_btns[m_id] = btn
            anc_box.addWidget(btn)
        bl.addLayout(anc_box)
        left_col.addWidget(buds_card)

        # Card 2: Nothing Phone 4b
        phone_card = QFrame()
        phone_card.setObjectName("card")
        pl = QVBoxLayout(phone_card)
        pl.setContentsMargins(16, 14, 16, 14)
        pl.setSpacing(10)

        ph = QHBoxLayout()
        p_icon = QLabel()
        p_icon.setPixmap(_icon("bolt", ACCENT).pixmap(20, 20))
        ph.addWidget(p_icon)
        p_name = QLabel("Nothing Phone (4b)")
        p_name.setFont(_font(14, QFont.DemiBold))
        ph.addWidget(p_name)
        ph.addStretch(1)
        self.p_bat_lbl = QLabel("KDE Connect")
        self.p_bat_lbl.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 11px;")
        ph.addWidget(self.p_bat_lbl)
        pl.addLayout(ph)

        phone_btn_box = QHBoxLayout()
        phone_btn_box.setSpacing(8)
        btn_ring = QPushButton("Find My Phone")
        btn_ring.setCursor(Qt.PointingHandCursor)
        btn_ring.clicked.connect(self._ring_phone)
        phone_btn_box.addWidget(btn_ring)

        btn_ping = QPushButton("Ping Phone")
        btn_ping.setCursor(Qt.PointingHandCursor)
        btn_ping.clicked.connect(self._ping_phone)
        phone_btn_box.addWidget(btn_ping)
        pl.addLayout(phone_btn_box)
        left_col.addWidget(phone_card)

        # Sliders: Volume & Brightness
        sliders_card = QFrame()
        sliders_card.setObjectName("card")
        sl = QVBoxLayout(sliders_card)
        sl.setContentsMargins(16, 14, 16, 14)
        sl.setSpacing(10)

        vol_hdr = QHBoxLayout()
        vol_lbl = QLabel("Master Volume")
        vol_lbl.setFont(_font(12, QFont.DemiBold))
        vol_hdr.addWidget(vol_lbl)
        vol_hdr.addStretch(1)
        self.vol_val_lbl = QLabel("50%")
        self.vol_val_lbl.setStyleSheet(f"color: {INK_DIM};")
        vol_hdr.addWidget(self.vol_val_lbl)
        sl.addLayout(vol_hdr)

        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(50)
        self.vol_slider.valueChanged.connect(self._on_vol_change)
        sl.addWidget(self.vol_slider)

        bright_hdr = QHBoxLayout()
        bright_lbl = QLabel("Screen Brightness")
        bright_lbl.setFont(_font(12, QFont.DemiBold))
        bright_hdr.addWidget(bright_lbl)
        bright_hdr.addStretch(1)
        self.bright_val_lbl = QLabel("70%")
        self.bright_val_lbl.setStyleSheet(f"color: {INK_DIM};")
        bright_hdr.addWidget(self.bright_val_lbl)
        sl.addLayout(bright_hdr)

        self.bright_slider = QSlider(Qt.Horizontal)
        self.bright_slider.setRange(0, 100)
        self.bright_slider.setValue(70)
        self.bright_slider.valueChanged.connect(self._on_bright_change)
        sl.addWidget(self.bright_slider)

        left_col.addWidget(sliders_card)
        left_col.addStretch(1)
        body.addLayout(left_col, 1)

        # Right Column: Applications Launcher
        right_card = QFrame()
        right_card.setObjectName("card")
        rl = QVBoxLayout(right_card)
        rl.setContentsMargins(18, 16, 18, 16)
        rl.setSpacing(12)

        apps_hdr = QHBoxLayout()
        apps_lbl = QLabel("APPLICATIONS")
        apps_lbl.setFont(_font(12, QFont.Bold))
        apps_lbl.setStyleSheet(f"color: {ACCENT}; letter-spacing: 1px;")
        apps_hdr.addWidget(apps_lbl)
        apps_hdr.addStretch(1)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search apps...")
        self.search_box.setFixedWidth(180)
        self.search_box.textChanged.connect(self._filter_apps)
        apps_hdr.addWidget(self.search_box)
        rl.addLayout(apps_hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.apps_list_w = QWidget()
        self.apps_list_l = QVBoxLayout(self.apps_list_w)
        self.apps_list_l.setContentsMargins(0, 0, 0, 0)
        self.apps_list_l.setSpacing(6)
        scroll.setWidget(self.apps_list_w)
        rl.addWidget(scroll)

        body.addWidget(right_card, 1)
        root.addLayout(body)

        self._populate_apps()
        self._sync_status()

    def _open_wheel(self):
        if self.engine:
            self.engine.open_wheel()

    def _open_apps_wheel(self):
        if self.engine:
            self.engine.open_apps_wheel()

    def _set_anc(self, mode: int):
        if self.engine:
            self.engine.nothing_buds.set_anc(mode)
            for m, b in self.anc_btns.items():
                if m == mode:
                    b.setStyleSheet(f"background: {ACCENT}; color: #000; font-weight: bold;")
                else:
                    b.setStyleSheet("")

    def _ring_phone(self):
        if self.engine:
            self.engine.nothing_phone.ring_phone()

    def _ping_phone(self):
        if self.engine:
            self.engine.nothing_phone.ping_phone()

    def _on_vol_change(self, val: int):
        self.vol_val_lbl.setText(f"{val}%")
        if self.engine:
            self.engine.audio.set_volume(val / 100.0)

    def _on_bright_change(self, val: int):
        self.bright_val_lbl.setText(f"{val}%")
        if self.engine:
            self.engine.kde.set_brightness(val)

    def _sync_status(self):
        if self.engine:
            cur_vol = int(round(self.engine.audio.get_volume() * 100))
            self.vol_slider.setValue(cur_vol)
            self.vol_val_lbl.setText(f"{cur_vol}%")
            b = self.engine.kde.get_brightness()
            if b is not None:
                self.bright_slider.setValue(b)
                self.bright_val_lbl.setText(f"{b}%")
            bat = self.engine.nothing_buds.get_battery()
            if bat is not None:
                self.b_bat_lbl.setText(f"{bat}%")
            p_bat = self.engine.nothing_phone.get_phone_battery()
            if p_bat is not None:
                self.p_bat_lbl.setText(f"{p_bat}%")

    def _populate_apps(self, query: str = ""):
        while self.apps_list_l.count():
            item = self.apps_list_l.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        apps = scan_applications()
        q = query.strip().lower()
        matched = [a for a in apps if not q or q in a.name.lower() or any(q in c.lower() for c in a.categories)]

        for app in matched[:20]:
            row = QFrame()
            row.setObjectName("app_row")
            rh = QHBoxLayout(row)
            rh.setContentsMargins(10, 6, 10, 6)
            rh.setSpacing(10)

            ic = QLabel()
            ic.setPixmap(_icon(app.icon, INK).pixmap(22, 22))
            rh.addWidget(ic)

            name = QLabel(app.name)
            name.setFont(_font(12, QFont.DemiBold))
            rh.addWidget(name)

            if app.categories:
                cat = QLabel(app.categories[0])
                cat.setStyleSheet(f"color: {INK_DIM}; font-size: 11px;")
                rh.addWidget(cat)

            rh.addStretch(1)

            btn = QPushButton("Launch")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(f"background: #252836; padding: 4px 12px; font-size: 11px;")
            btn.clicked.connect(lambda _, a=app: launch(a))
            rh.addWidget(btn)

            self.apps_list_l.addWidget(row)

    def _filter_apps(self, text: str):
        self._populate_apps(text)

    def _qss(self) -> str:
        return f"""
        QWidget {{ background: {CANVAS}; color: {INK}; }}
        QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
        QFrame#app_row {{ background: #151720; border-radius: 8px; border: 1px solid #1E212D; }}
        QFrame#app_row:hover {{ border-color: {BORDER}; }}
        QLineEdit {{ background: #1E202B; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; color: {INK}; font-size: 12px; }}
        QLineEdit:focus {{ border-color: {ACCENT}; }}
        QPushButton {{ background: #202330; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 14px; font-size: 12px; color: {INK}; font-weight: 500; }}
        QPushButton:hover {{ border-color: #383D50; background: #262A3A; }}
        QPushButton:focus {{ border-color: {ACCENT}; }}
        QSlider::groove:horizontal {{ height: 4px; background: #252836; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background: #FFFFFF; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
        QScrollBar:vertical {{ background: transparent; width: 8px; }}
        QScrollBar::handle:vertical {{ background: #252836; border-radius: 4px; }}
        """
