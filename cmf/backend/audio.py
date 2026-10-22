"""PipeWire audio volume and MPRIS media controller for Linux."""
from __future__ import annotations

import logging
import re
import subprocess
import threading

log = logging.getLogger("cmf.audio")


class AudioController:
    """Controls PipeWire default sink volume, mic mute, and MPRIS media playback."""

    def get_volume(self) -> float:
        try:
            r = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=0.8)
            if r.returncode == 0:
                m = re.search(r"Volume:\s+([0-9.]+)", r.stdout)
                if m:
                    return float(m.group(1))
        except Exception:
            pass
        # Fallback to pactl
        try:
            r = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], capture_output=True, text=True, timeout=0.8)
            m = re.search(r"(\d+)%", r.stdout)
            if m:
                return int(m.group(1)) / 100.0
        except Exception:
            pass
        return 0.5

    def set_volume(self, level: float):
        level = max(0.0, min(1.5, level))
        pct = f"{round(level * 100)}%"
        try:
            subprocess.Popen(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", pct], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            try:
                subprocess.Popen(["pactl", "set-sink-volume", "@DEFAULT_SINK@", pct], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def adjust_volume(self, delta_pct: float) -> float:
        cur = self.get_volume()
        new_vol = max(0.0, min(1.0, cur + delta_pct))
        self.set_volume(new_vol)
        return new_vol

    def toggle_mic_mute(self) -> bool:
        try:
            subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"], timeout=0.8)
            r = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"], capture_output=True, text=True, timeout=0.8)
            return "[MUTED]" in r.stdout
        except Exception:
            try:
                subprocess.run(["pactl", "set-source-mute", "@DEFAULT_SOURCE@", "toggle"], timeout=0.8)
            except Exception:
                pass
        return False

    def media(self, command: str):
        threading.Thread(target=self._mpris_fwd, args=(command,), name="mpris-fwd", daemon=True).start()

    def _mpris_fwd(self, command: str):
        verb_map = {
            "play_pause": "PlayPause",
            "play": "Play",
            "pause": "Pause",
            "next": "Next",
            "previous": "Previous",
            "stop": "Stop",
        }
        method = verb_map.get(command.lower())
        if not method:
            return

        try:
            import dbus
            bus = dbus.SessionBus()
            players = [s for s in bus.list_names() if s.startswith("org.mpris.MediaPlayer2.")]
            for p in players:
                try:
                    obj = bus.get_object(p, "/org/mpris/MediaPlayer2")
                    iface = dbus.Interface(obj, "org.mpris.MediaPlayer2.Player")
                    getattr(iface, method)()
                    log.debug("forwarded %s to %s", method, p)
                    return
                except Exception:
                    continue
        except Exception as ex:
            log.debug("MPRIS forwarding failed: %s", ex)
