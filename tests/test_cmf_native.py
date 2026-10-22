"""Comprehensive native test suite for CMF Buds Pro 2 Linux Controller (cmf package)."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from cmf.core.events import Event, Kind
from cmf.core.tools import (
    ANCTool,
    AppsTool,
    BrightnessTool,
    Hud,
    MicMuteTool,
    PhoneTool,
    ScrollTool,
    SwitcherTool,
    Tool,
    UndoTool,
    VolumeTool,
    WorkspacesTool,
)
from cmf.core.engine import ControllerEngine, State
from cmf.backend.dial import BlueZDialSource, STEP_SIZE, EDGE_LOW, EDGE_HIGH, CENTER_VOL
from cmf.backend.nothing import build_anc_packet, CMFBudsManager
from cmf.backend.apps import AppInfo, parse_desktop_file, scan_applications, launch
from cmf.ui.assets import get_icon_path, tinted_url


class TestCMFEvents(unittest.TestCase):
    def test_kind_enum(self):
        self.assertEqual(Kind.ROTATE.value, "rotate")
        self.assertEqual(Kind.CLICK.value, "click")
        self.assertEqual(Kind.DOUBLE.value, "double")
        self.assertEqual(Kind.TRIPLE.value, "triple")
        self.assertEqual(Kind.HOLD.value, "hold")

    def test_event_dataclass(self):
        ev = Event(kind=Kind.ROTATE, delta=1, source="dial")
        self.assertEqual(ev.kind, Kind.ROTATE)
        self.assertEqual(ev.delta, 1)
        self.assertEqual(ev.source, "dial")
        self.assertGreater(ev.timestamp, 0.0)


class TestCMFBlueZDial(unittest.TestCase):
    def setUp(self):
        self.events: list[Event] = []
        self.dial = BlueZDialSource(emit=self.events.append)
        self.dial._transport_props = MagicMock()
        self.dial._transport_path = "/org/bluez/hci0/dev_2C_BE_EE_EF_EF_61/fd0"
        self.dial._passthrough = False

    def _send_vol(self, vol: int):
        self.dial._on_properties_changed("org.bluez.MediaTransport1", {"Volume": vol}, {})

    def test_step_calculation_clockwise(self):
        self.dial._last_vol = 64
        # Volume increases by 8 (one detent CW)
        self._send_vol(72)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].kind, Kind.ROTATE)
        self.assertEqual(self.events[0].delta, 1)
        self.assertEqual(self.dial._last_vol, 72)

    def test_step_calculation_counter_clockwise(self):
        self.dial._last_vol = 64
        # Volume decreases by 8 (one detent CCW)
        self._send_vol(56)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].kind, Kind.ROTATE)
        self.assertEqual(self.events[0].delta, -1)
        self.assertEqual(self.dial._last_vol, 56)

    def test_fast_spin_multi_step(self):
        self.dial._last_vol = 64
        # Fast spin: +24 (3 detents)
        self._send_vol(88)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0].delta, 3)

    def test_recenter_at_boundary(self):
        self.dial._last_vol = 108
        # Crosses EDGE_HIGH (112) -> should schedule recenter to CENTER_VOL (64)
        self._send_vol(116)
        self.assertEqual(len(self.events), 1)
        self.dial._transport_props.Set.assert_called_with("org.bluez.MediaTransport1", "Volume", dbus_uint16(CENTER_VOL))

    def test_ignore_recenter_echo(self):
        self.dial._ignore_our_set = True
        self.dial._last_vol = 112
        self._send_vol(64)
        # Recenter echo must NOT emit an event to the engine
        self.assertEqual(len(self.events), 0)
        self.assertFalse(self.dial._ignore_our_set)
        self.assertEqual(self.dial._last_vol, 64)


def dbus_uint16(val):
    from unittest.mock import ANY
    return ANY


class TestCMFNothingBackend(unittest.TestCase):
    def test_anc_packet_structure(self):
        # Mode 1 = ANC: header (2) + cmd (1) + len (1) + payload (1) + checksum (1) = 6 bytes
        pkt = build_anc_packet(1)
        self.assertEqual(len(pkt), 6)
        self.assertEqual(pkt[0], 0x55)
        self.assertEqual(pkt[1], 0xAA)
        self.assertEqual(pkt[2], 0x02)  # Command
        self.assertEqual(pkt[3], 0x01)  # Length
        self.assertEqual(pkt[4], 0x01)  # Payload
        self.assertEqual(pkt[5], sum(pkt[2:5]) & 0xFF)  # Checksum

    def test_anc_mode_cycling(self):
        mgr = CMFBudsManager()
        self.assertEqual(mgr.anc_mode, 1)  # Default: ANC ON
        with patch.object(mgr, "_rfcomm_send_anc"):
            mode2 = mgr.cycle_anc()
            self.assertEqual(mode2, "Transparency")
            self.assertEqual(mgr.anc_mode, 2)

            mode3 = mgr.cycle_anc()
            self.assertEqual(mode3, "Off")
            self.assertEqual(mgr.anc_mode, 0)

            mode1 = mgr.cycle_anc()
            self.assertEqual(mode1, "ANC")
            self.assertEqual(mgr.anc_mode, 1)


class TestCMFAppScanner(unittest.TestCase):
    def test_desktop_file_parsing(self):
        desktop_content = """[Desktop Entry]
Name=Firefox Web Browser
Exec=firefox %u
Icon=firefox
Terminal=false
Type=Application
Categories=Network;WebBrowser;
"""
        with tempfile.NamedTemporaryFile("w", suffix=".desktop", delete=False) as f:
            f.write(desktop_content)
            temp_path = f.name

        try:
            app = parse_desktop_file(temp_path)
            self.assertIsNotNone(app)
            self.assertEqual(app.name, "Firefox Web Browser")
            self.assertEqual(app.exec_cmd, "firefox")
            self.assertEqual(app.icon, "firefox")
        finally:
            os.unlink(temp_path)

    def test_nodisplay_ignored(self):
        desktop_content = """[Desktop Entry]
Name=Hidden App
Exec=hidden
NoDisplay=true
Type=Application
"""
        with tempfile.NamedTemporaryFile("w", suffix=".desktop", delete=False) as f:
            f.write(desktop_content)
            temp_path = f.name

        try:
            app = parse_desktop_file(temp_path)
            self.assertIsNone(app)
        finally:
            os.unlink(temp_path)


class MockUI:
    def __init__(self):
        self.opened: list[tuple[list[dict], int]] = []
        self.moved: list[tuple[int, int]] = []
        self.committed: list[int] = []
        self.cancelled: int = 0
        self.huds: list[Hud] = []

    def wheel_open(self, items, index):
        self.opened.append((items, index))

    def wheel_move(self, index, direction):
        self.moved.append((index, direction))

    def wheel_commit(self, index):
        self.committed.append(index)

    def wheel_cancel(self):
        self.cancelled += 1

    def hud(self, h):
        self.huds.append(h)


class TestCMFEngine(unittest.TestCase):
    def setUp(self):
        self.ui = MockUI()
        self.audio = MagicMock()
        self.audio.adjust_volume.return_value = 0.50
        self.audio.toggle_mic_mute.return_value = True
        self.uinput = MagicMock()
        self.kde = MagicMock()
        self.kde.get_brightness.return_value = 60
        self.nothing_buds = MagicMock()
        self.nothing_buds.cycle_anc.return_value = "Transparency"
        self.nothing_buds.ANC_MODES = {0: "Off", 1: "Noise Cancellation", 2: "Transparency"}
        self.nothing_buds.anc_mode = 2
        self.nothing_phone = MagicMock()
        self.nothing_phone.ring_phone.return_value = True
        self.dial_source = MagicMock()

        self.engine = ControllerEngine(
            ui=self.ui,
            audio=self.audio,
            uinput=self.uinput,
            kde=self.kde,
            nothing_buds=self.nothing_buds,
            nothing_phone=self.nothing_phone,
            dial_source=self.dial_source,
        )

    def test_initial_state(self):
        self.assertEqual(self.engine.state, State.TOOL)
        self.assertEqual(self.engine.active_tool.id, "volume")
        # Ensure 'slides' and 'scrub' are absent
        self.assertNotIn("slides", self.engine.wheel_ids)
        self.assertNotIn("scrub", self.engine.wheel_ids)
        # Ensure 'apps' is present right after 'volume'
        self.assertEqual(self.engine.wheel_ids[0], "volume")
        self.assertEqual(self.engine.wheel_ids[1], "apps")

    def test_tool_rotate_in_volume(self):
        self.engine.handle(Event(Kind.ROTATE, delta=1, source="dial"))
        self.audio.adjust_volume.assert_called_with(0.05)
        self.assertEqual(len(self.ui.huds), 1)
        self.assertEqual(self.ui.huds[-1].detail, "50%")

    def test_open_wheel_on_hold_or_double(self):
        self.engine.handle(Event(Kind.HOLD, source="buttons"))
        self.assertEqual(self.engine.state, State.WHEEL)
        self.assertEqual(len(self.ui.opened), 1)
        # Dial passthrough must be disabled in wheel!
        self.dial_source.set_passthrough.assert_called_with(False)

    def test_wheel_navigation_and_selection(self):
        self.engine.open_wheel()
        # Rotate wheel CW
        self.engine.handle(Event(Kind.ROTATE, delta=1, source="dial"))
        self.assertEqual(self.engine.index, 1)  # apps tool
        self.assertEqual(len(self.ui.moved), 1)

        # Rotate wheel further CW to brightness
        self.engine.handle(Event(Kind.ROTATE, delta=1, source="dial"))
        self.assertEqual(self.engine.index, 2)  # brightness tool

        # Click to select brightness
        self.engine.handle(Event(Kind.CLICK, source="buttons"))
        self.assertEqual(self.engine.state, State.TOOL)
        self.assertEqual(self.engine.active_tool.id, "brightness")
        # When active tool is brightness, passthrough must remain False!
        self.dial_source.set_passthrough.assert_called_with(False)

        # Now rotating dial changes brightness, NOT audio volume!
        self.engine.handle(Event(Kind.ROTATE, delta=1, source="dial"))
        self.kde.set_brightness.assert_called_with(65)
        self.audio.adjust_volume.assert_not_called()

    def test_apps_subwheel(self):
        dummy_apps = [
            AppInfo("firefox", "Firefox", "firefox", "firefox", "/usr/share/applications/firefox.desktop", ["Network"]),
            AppInfo("vlc", "VLC", "vlc", "vlc", "/usr/share/applications/vlc.desktop", ["AudioVideo"]),
        ]
        with patch("cmf.backend.apps.scan_applications", return_value=dummy_apps):
            self.engine.open_apps_wheel()

        self.assertEqual(self.engine.state, State.APPS_WHEEL)
        items, idx = self.ui.opened[-1]
        self.assertEqual(items[0]["id"], "back")
        self.assertEqual(items[1]["id"], "app:firefox")
        self.assertEqual(items[2]["id"], "app:vlc")

        # Rotating in apps wheel moves between apps
        self.engine.handle(Event(Kind.ROTATE, delta=1, source="dial"))
        self.assertEqual(self.engine.index, 2)  # vlc

        # Clicking on vlc launches it and returns to previous tool
        with patch("cmf.backend.apps.launch") as mock_launch:
            self.engine.handle(Event(Kind.CLICK, source="buttons"))
            mock_launch.assert_called_with(dummy_apps[1])

        self.assertEqual(self.engine.state, State.TOOL)
        self.assertEqual(self.ui.huds[-1].detail, "Launched")

    def test_apps_wheel_back_button(self):
        dummy_apps = [AppInfo("firefox", "Firefox", "firefox", "firefox", "/usr/share/applications/firefox.desktop", ["Network"])]
        with patch("cmf.backend.apps.scan_applications", return_value=dummy_apps):
            self.engine.open_apps_wheel()

        # Index 0 is "back"
        self.engine.index = 0
        self.engine.handle(Event(Kind.CLICK, source="buttons"))
        # Clicking Back should return to main WHEEL
        self.assertEqual(self.engine.state, State.WHEEL)

    def test_wheel_auto_dismiss_timeout(self):
        self.engine.open_wheel()
        self.engine.dismiss_after_s = 0.05
        time.sleep(0.06)
        self.engine.tick()
        # Should have auto-committed sticky tool
        self.assertEqual(self.engine.state, State.TOOL)
        self.assertEqual(len(self.ui.committed), 1)


class TestCMFAssets(unittest.TestCase):
    def test_lucide_icon_resolution(self):
        p_vol = get_icon_path("volume")
        self.assertIsNotNone(p_vol)
        self.assertTrue(os.path.exists(p_vol))
        self.assertTrue(str(p_vol).endswith(".svg"))

        p_bright = get_icon_path("brightness")
        self.assertIsNotNone(p_bright)
        self.assertTrue(os.path.exists(p_bright))

    def test_qml_url_generation(self):
        url = tinted_url("volume", "#ffffff")
        self.assertTrue(url.startswith("file://") or url.startswith("image://"))


if __name__ == "__main__":
    unittest.main()
