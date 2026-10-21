"""Linux backend for Orbit.

Sources:
  LinuxVolumeRotationSource  rotation  (AVRCP volume changes on PipeWire / PulseAudio sink)
  LinuxEvdevButtonSource     clicks    (evdev kernel device for CMF Buds Pro 2 AVRCP)
  MPRISInputSource           clicks    (D-Bus MPRIS2 player fallback for desktop media handlers)

Output:
  LinuxOutput                keys/scroll via evdev UInput, KDE PowerManagement brightness,
                             MPRIS media forwarding, KWin window management.
"""
from __future__ import annotations

import logging
from orbit.platform.base import Platform
from orbit.platform.linux.input_volume import LinuxVolumeRotationSource
from orbit.platform.linux.input_media import EventDeduplicator, LinuxEvdevButtonSource, MPRISInputSource
from orbit.platform.linux.output import LinuxOutput

log = logging.getLogger("orbit.platform.linux")


class LinuxPlatform(Platform):
    name = "linux"

    def __init__(self):
        self._output: LinuxOutput | None = None
        self._volume: LinuxVolumeRotationSource | None = None

    def create_sources(self, cfg: dict):
        match_name = cfg.get("device", {}).get("audio_endpoint_match", "CMF Buds Pro 2")
        self._volume = LinuxVolumeRotationSource(match_name)

        # Create shared event deduplicator for button sources
        sources = [self._volume]

        # Use an internal forwarder that will be bound when start(emit) is called
        class _BridgeEmit:
            def __init__(self):
                self.target = None
            def __call__(self, ev):
                if self.target:
                    self.target(ev)

        bridge = _BridgeEmit()
        dedup = EventDeduplicator(bridge)

        # Evdev direct button listener
        evdev_src = LinuxEvdevButtonSource(match_name, dedup=dedup)
        # MPRIS D-Bus listener
        mpris_src = MPRISInputSource(dedup=dedup)

        class _CompositeButtonSource:
            name = "linux-buttons"
            capabilities = evdev_src.capabilities

            def start(self, emit):
                bridge.target = emit
                evdev_src.start(emit)
                if mpris_src.available:
                    mpris_src.start(emit)

            def stop(self):
                evdev_src.stop()
                mpris_src.stop()

            def describe(self):
                return "evdev + MPRIS media buttons"

            def observe(self, ev):
                pass

        sources.append(_CompositeButtonSource())
        return sources

    def create_output(self, cfg: dict) -> LinuxOutput:
        self._output = LinuxOutput()
        return self._output

    def create_services(self, cfg: dict) -> list:
        return []

    def is_elevated(self) -> bool:
        return True

    def relaunch_elevated(self, argv: list[str]) -> bool:
        return False
