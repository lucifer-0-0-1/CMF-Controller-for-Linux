"""Native Linux tools driving system actions."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Hud:
    icon: str
    title: str
    detail: str = ""
    progress: float | None = None
    direction: int = 0


class Tool:
    id: str = ""
    label: str = ""
    icon: str = ""
    glyph: str = ""
    sticky: bool = True

    def __init__(self, tid: str, label: str, icon: str, sticky: bool = True):
        self.id = tid
        self.label = label
        self.icon = icon
        self.sticky = sticky

    def rotate(self, context, delta: int) -> Hud | None:
        return None

    def click(self, context) -> Hud | None:
        return None

    def to_item(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "icon": self.icon,
            "glyph": self.label[:2].upper() if self.label else "TL",
            "sticky": self.sticky,
        }


class VolumeTool(Tool):
    def __init__(self):
        super().__init__("volume", "Volume", "volume", sticky=True)

    def rotate(self, context, delta: int) -> Hud | None:
        vol = context.audio.adjust_volume(0.05 * delta)
        pct = int(round(vol * 100))
        return Hud(self.icon, self.label, f"{pct}%", progress=vol, direction=1 if delta > 0 else -1)

    def click(self, context) -> Hud | None:
        context.audio.media("play_pause")
        return Hud(self.icon, "Play / Pause")


class AppsTool(Tool):
    def __init__(self):
        super().__init__("apps", "Applications", "app", sticky=False)

    def click(self, context) -> Hud | None:
        context.open_apps_wheel()
        return Hud(self.icon, "Applications", "Select App")


class BrightnessTool(Tool):
    def __init__(self):
        super().__init__("brightness", "Brightness", "brightness", sticky=True)

    def rotate(self, context, delta: int) -> Hud | None:
        cur = context.kde.get_brightness() or 50
        nxt = max(0, min(100, cur + 5 * delta))
        context.kde.set_brightness(nxt)
        return Hud(self.icon, self.label, f"{nxt}%", progress=nxt / 100.0, direction=1 if delta > 0 else -1)


class ScrollTool(Tool):
    def __init__(self):
        super().__init__("scroll", "Scroll", "scroll", sticky=True)

    def rotate(self, context, delta: int) -> Hud | None:
        context.uinput.scroll(float(delta))
        return Hud(self.icon, self.label, "Down" if delta > 0 else "Up", direction=1 if delta > 0 else -1)


class SwitcherTool(Tool):
    def __init__(self):
        super().__init__("switcher", "Windows", "windows", sticky=True)

    def rotate(self, context, delta: int) -> Hud | None:
        if delta > 0:
            context.uinput.keys("alt+tab")
        else:
            context.uinput.keys("alt+shift+tab")
        return Hud(self.icon, self.label, "Next" if delta > 0 else "Prev", direction=1 if delta > 0 else -1)


class WorkspacesTool(Tool):
    def __init__(self):
        super().__init__("desktops", "Workspaces", "desktops", sticky=True)

    def rotate(self, context, delta: int) -> Hud | None:
        context.kde.switch_desktop(1 if delta > 0 else -1)
        return Hud(self.icon, self.label, "Next" if delta > 0 else "Prev", direction=1 if delta > 0 else -1)

    def click(self, context) -> Hud | None:
        context.uinput.keys("meta+w")  # KDE Plasma Overview
        return Hud(self.icon, "Overview")


class ANCTool(Tool):
    def __init__(self):
        super().__init__("anc", "ANC Mode", "volume", sticky=False)

    def click(self, context) -> Hud | None:
        mode = context.nothing_buds.cycle_anc()
        return Hud(self.icon, "ANC Mode", mode)


class PhoneTool(Tool):
    def __init__(self):
        super().__init__("phone", "Nothing Phone", "bolt", sticky=False)

    def click(self, context) -> Hud | None:
        ok = context.nothing_phone.ring_phone()
        return Hud(self.icon, "Find My Phone", "Ringing..." if ok else "No Device Found")


class MicMuteTool(Tool):
    def __init__(self):
        super().__init__("mic_mute", "Mic Mute", "mute", sticky=False)

    def click(self, context) -> Hud | None:
        muted = context.audio.toggle_mic_mute()
        return Hud(self.icon, "Microphone", "Muted" if muted else "Active")


class UndoTool(Tool):
    def __init__(self):
        super().__init__("undo", "Undo / Redo", "undo", sticky=True)

    def rotate(self, context, delta: int) -> Hud | None:
        if delta < 0:
            context.uinput.keys("ctrl+z")
            return Hud("undo", "Undo", direction=-1)
        else:
            context.uinput.keys("ctrl+y")
            return Hud("redo", "Redo", direction=1)
