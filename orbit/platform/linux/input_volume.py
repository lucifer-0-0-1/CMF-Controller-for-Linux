"""Linux: dial rotation via PipeWire/PulseAudio sink volume events.

Thin backend for orbit.core.volume_dial.VolumeDial. The CMF dial has no channel
of its own; each click nudges the buds' volume one step (1/16th of 100%) and the
sound server reports the new level. We monitor sink volume changes via `pactl
subscribe` and report each level to VolumeDial.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time

from orbit.core.events import Capability
from orbit.core.volume_dial import VolumeDial
from orbit.platform.base import Emit, RotationSource

log = logging.getLogger("orbit.volume")
trace = logging.getLogger("orbit.trace")

OURS_S = 0.5
OURS_EPS = 0.005


def _run_pactl(args: list[str], timeout: float = 1.0) -> str:
    try:
        r = subprocess.run(
            ["pactl"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.stdout if r.returncode == 0 else ""
    except Exception as ex:
        log.debug("pactl %s failed: %s", args, ex)
        return ""


def find_sink(match_str: str = "CMF Buds Pro 2") -> str:
    """Find sink identifier matching device name, falling back to @DEFAULT_SINK@."""
    out = _run_pactl(["list", "sinks", "short"])
    if not out:
        return "@DEFAULT_SINK@"

    match_lower = match_str.lower()
    for line in out.strip().splitlines():
        parts = line.split()
        if len(parts) >= 2:
            sink_name = parts[1]
            if (
                match_lower in sink_name.lower()
                or "cmf" in sink_name.lower()
                or "bluez" in sink_name.lower()
            ):
                return sink_name
    return "@DEFAULT_SINK@"


class LinuxVolumeRotationSource(RotationSource):
    name = "pipewire-volume"
    capabilities = frozenset({Capability.ROTATE})

    def __init__(self, match: str = "CMF Buds Pro 2"):
        self.match = match
        self.dial: VolumeDial | None = None
        self._sink: str = "@DEFAULT_SINK@"
        self._our: tuple[float, float] | None = None  # (level, time)
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._listener_thread: threading.Thread | None = None

    # ---- RotationSource
    def start(self, emit: Emit):
        self._sink = find_sink(self.match)
        self.dial = VolumeDial(self, emit, self.name)
        self.dial.start()

        self._stop.clear()
        self._listener_thread = threading.Thread(
            target=self._listen_loop,
            name="pactl-subscribe",
            daemon=True,
        )
        self._listener_thread.start()
        log.info("rotation bound to sink '%s' (level %.0f%%)", self._sink, (self.get_level() or 0) * 100)

    def stop(self):
        self._stop.set()
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
        if self.dial:
            self.dial.stop()

    def set_passthrough(self, on: bool):
        if self.dial:
            self.dial.set_passthrough(on)

    def set_duck(self, factor: float | None):
        if self.dial:
            self.dial.set_duck(factor)

    def level(self) -> float | None:
        return self.dial.level() if self.dial else None

    def last_activity(self) -> float:
        return self.dial.last_activity() if self.dial else 0.0

    def describe(self) -> str:
        return f"{self.name} on {self._sink}"

    # ---- LevelBackend
    def get_level(self) -> float | None:
        out = _run_pactl(["get-sink-volume", self._sink])
        if not out and self._sink != "@DEFAULT_SINK@":
            self._sink = "@DEFAULT_SINK@"
            out = _run_pactl(["get-sink-volume", self._sink])
        if not out:
            return None
        m = re.search(r"(\d+)%", out)
        if m:
            return int(m.group(1)) / 100.0
        return None

    def set_level(self, level: float):
        level = max(0.0, min(1.0, level))
        self._our = (level, time.monotonic())
        pct = f"{round(level * 100)}%"
        _run_pactl(["set-sink-volume", self._sink, pct])

    # ---- Event loop
    def _listen_loop(self):
        while not self._stop.is_set():
            try:
                self._proc = subprocess.Popen(
                    ["pactl", "subscribe"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                )
                for line in self._proc.stdout:
                    if self._stop.is_set():
                        break
                    # We are interested in sink changes or server changes
                    if "Event 'change' on sink" in line or "Event 'new' on sink" in line:
                        # Brief debounce to allow the sound server to settle
                        time.sleep(0.03)
                        lvl = self.get_level()
                        if lvl is None or not self.dial:
                            continue
                        now = time.monotonic()
                        ours = bool(
                            self._our
                            and abs(lvl - self._our[0]) < OURS_EPS
                            and now - self._our[1] < OURS_S
                        )
                        trace.debug("linux vol=%5.1f %s", lvl * 100, "ours" if ours else "")
                        self.dial.on_level(lvl, ours, now=now)
            except Exception as ex:
                if not self._stop.is_set():
                    log.debug("pactl subscribe loop error: %s (restarting)", ex)
                    time.sleep(1.0)
            finally:
                if self._proc:
                    try:
                        self._proc.terminate()
                        self._proc.wait(timeout=0.5)
                    except Exception:
                        pass
                    self._proc = None
