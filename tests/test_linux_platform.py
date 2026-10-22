"""Unit tests for the Linux platform backend and extra CMF / Nothing tools."""
import unittest
import time
import evdev
from unittest.mock import MagicMock, patch

from orbit.platform import get_platform
from orbit.platform.linux import LinuxPlatform
from orbit.platform.linux.input_media import EventDeduplicator
from orbit.platform.linux.nothing_integration import build_anc_packet, CMFBudsManager
from orbit.platform.linux.autostart import is_enabled, set_enabled
from orbit.core.events import Kind, InputEvent
from orbit.core import actions
from orbit.core import tools


class TestLinuxPlatform(unittest.TestCase):
    def test_platform_dispatch(self):
        plat = get_platform()
        self.assertIsInstance(plat, LinuxPlatform)
        self.assertEqual(plat.name, "linux")

    def test_sources_creation(self):
        plat = LinuxPlatform()
        sources = plat.create_sources({"device": {"audio_endpoint_match": "CMF Buds Pro 2"}})
        self.assertEqual(len(sources), 2)
        self.assertEqual(sources[0].name, "pipewire-volume")
        self.assertEqual(sources[1].name, "linux-buttons")

    def test_output_creation(self):
        plat = LinuxPlatform()
        out = plat.create_output({})
        self.assertIsNotNone(out)

    def test_event_deduplicator(self):
        emitted = []
        dedup = EventDeduplicator(emitted.append)
        dedup.emit(Kind.CLICK, "evdev")
        # Immediate duplicate should be suppressed
        dedup.emit(Kind.CLICK, "mpris")
        self.assertEqual(len(emitted), 1)

        # Different kind should NOT be suppressed
        dedup.emit(Kind.DOUBLE, "mpris")
        self.assertEqual(len(emitted), 2)

    def test_cmf_anc_packet(self):
        # Header: 55 AA, cmd 02, len 01, payload 01 (ANC ON), checksum
        pkt = build_anc_packet(1)
        self.assertEqual(pkt[:2], bytes([0x55, 0xAA]))
        self.assertEqual(pkt[2], 0x02)  # cmd
        self.assertEqual(pkt[3], 0x01)  # len
        self.assertEqual(pkt[4], 0x01)  # payload: 1
        expected_cs = (0x02 + 0x01 + 0x01) & 0xFF
        self.assertEqual(pkt[5], expected_cs)

    def test_cmd_action(self):
        act = actions.parse("cmd:echo 1")
        self.assertEqual(act.spec, "cmd:echo 1")
        with patch("subprocess.Popen") as mock_popen:
            act(MagicMock())
            mock_popen.assert_called_once_with("echo 1", shell=True)

    def test_custom_tools_registered(self):
        self.assertIn("mic_mute", tools.TOOL_TYPES)
        self.assertIn("anc", tools.TOOL_TYPES)
        self.assertIn("phone", tools.TOOL_TYPES)

        t_mic = tools.build("mic_mute", {"type": "mic_mute", "label": "Mic Mute"})
        self.assertEqual(t_mic.label, "Mic Mute")

        t_anc = tools.build("anc", {"type": "anc", "label": "ANC Mode"})
        self.assertEqual(t_anc.label, "ANC Mode")

        t_phone = tools.build("phone", {"type": "phone", "label": "Nothing Phone"})
        self.assertEqual(t_phone.label, "Nothing Phone")

    def test_linux_duck_volume_disabled(self):
        from orbit.core import config as cfg_mod
        cfg, _ = cfg_mod.load(platform="linux")
        # On Linux, duck_volume is 1.0 (disabled) so volume does not drop when opening wheel
        self.assertEqual(cfg["wheel"]["duck_volume"], 1.0)

    def test_high_res_scroll_accumulation(self):
        from orbit.platform.linux.output import LinuxOutput
        out = LinuxOutput()
        if out._ui is None:
            self.skipTest("uinput not accessible")

        written_events = []
        out._ui.write = lambda ev_type, code, val: written_events.append((ev_type, code, val))
        out._ui.syn = lambda: None

        # Scroll 0.5 notches down (positive in Orbit -> negative in evdev)
        out.scroll(0.5)
        # 0.5 * 120 = 60 units
        self.assertIn((evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL_HI_RES, -60), written_events)
        # Discrete wheel should not have fired yet (needs 120 units)
        self.assertNotIn((evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL, -1), written_events)

        # Another 0.5 notches (total 1.0 notch = 120 units)
        written_events.clear()
        out.scroll(0.5)
        self.assertIn((evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL_HI_RES, -60), written_events)
        self.assertIn((evdev.ecodes.EV_REL, evdev.ecodes.REL_WHEEL, -1), written_events)

    def test_apps_tool_and_wheel(self):
        from orbit.core import tools
        from orbit.core.engine import Engine, State
        from orbit.core.events import InputEvent, Kind
        from orbit.platform.linux.apps import AppInfo
        from tests.test_engine import FakeOut, FakeUI, FakeRot, FakeSrc

        t_apps = tools.build("apps", {"type": "apps", "label": "Applications", "icon": "app"})
        self.assertEqual(t_apps.label, "Applications")
        self.assertEqual(t_apps.icon, "app")
        self.assertFalse(t_apps.sticky)

        # Test engine apps wheel
        cfg = {
            "wheel": {"items": ["volume", "apps"], "dismiss_after_ms": 5000, "duck_volume": 1.0, "accel": 1},
            "tools": {
                "volume": {"type": "volume"},
                "apps": {"type": "apps"},
            },
            "gestures": {"open_wheel": ["double"]},
            "ui": {"accent": "#D71921"},
            "device": {},
        }
        out, ui, rot = FakeOut(), FakeUI(), FakeRot()
        e = Engine(cfg, out, ui, [rot, FakeSrc([])])

        # Inject fake apps
        fake_app = AppInfo(
            id="firefox",
            name="Firefox",
            icon="firefox",
            exec_cmd="firefox",
            desktop_file="/usr/share/applications/firefox.desktop",
            categories=["Network"],
        )

        # Mock scan_applications in engine
        import orbit.platform.linux.apps as apps_mod
        orig_scan = apps_mod.scan_applications
        apps_mod.scan_applications = lambda: [fake_app]
        try:
            # Trigger apps wheel
            e.open_apps_wheel()
            self.assertEqual(e.state, State.APPS_WHEEL)
            self.assertEqual(len(e._apps_items), 2)  # [Back, Firefox]
            self.assertEqual(e._apps_items[0]["id"], "back")
            self.assertEqual(e._apps_items[1]["id"], "app:firefox")

            # Click on Back returns to main wheel
            e.index = 0
            e.handle(InputEvent(Kind.CLICK, 0, "test"))
            self.assertEqual(e.state, State.WHEEL)

            # Open apps wheel again, rotate to app, and click to launch
            e.open_apps_wheel()
            self.assertEqual(e.state, State.APPS_WHEEL)
            e.index = 1
            launched = []
            orig_launch = apps_mod.launch
            apps_mod.launch = lambda app: launched.append(app.name)
            try:
                e.handle(InputEvent(Kind.CLICK, 0, "test"))
                self.assertEqual(e.state, State.TOOL)
                self.assertEqual(launched, ["Firefox"])
            finally:
                apps_mod.launch = orig_launch
        finally:
            apps_mod.scan_applications = orig_scan


if __name__ == "__main__":
    unittest.main()
