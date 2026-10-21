"""Unit tests for the Linux platform backend and extra CMF / Nothing tools."""
import unittest
import time
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


if __name__ == "__main__":
    unittest.main()
