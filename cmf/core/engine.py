"""State-driven controller engine managing Tool mode, Main Wheel, and Applications Wheel."""
from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Protocol

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

log = logging.getLogger("cmf.engine")


class State(Enum):
    TOOL = "tool"
    WHEEL = "wheel"
    APPS_WHEEL = "apps_wheel"


class UI(Protocol):
    def wheel_open(self, items: list[dict], index: int) -> None: ...
    def wheel_move(self, index: int, direction: int) -> None: ...
    def wheel_commit(self, index: int) -> None: ...
    def wheel_cancel(self) -> None: ...
    def hud(self, h: Hud) -> None: ...


class ControllerEngine:
    def __init__(self, ui: UI, audio, uinput, kde, nothing_buds, nothing_phone, dial_source):
        self.ui = ui
        self.audio = audio
        self.uinput = uinput
        self.kde = kde
        self.nothing_buds = nothing_buds
        self.nothing_phone = nothing_phone
        self.dial_source = dial_source

        # Register tools
        self.tools: dict[str, Tool] = {
            "volume": VolumeTool(),
            "apps": AppsTool(),
            "brightness": BrightnessTool(),
            "switcher": SwitcherTool(),
            "scroll": ScrollTool(),
            "desktops": WorkspacesTool(),
            "anc": ANCTool(),
            "phone": PhoneTool(),
            "mic_mute": MicMuteTool(),
            "undo": UndoTool(),
        }

        # Main wheel order (slides and scrub removed, apps right after volume)
        self.wheel_ids = ["volume", "apps", "brightness", "switcher", "scroll", "desktops", "anc", "phone", "undo"]
        self.active_tool: Tool = self.tools["volume"]
        self.state: State = State.TOOL
        self.index: int = 0
        self._wheel_last: float = 0.0
        self.dismiss_after_s: float = 5.0

        # Sub-wheel state
        self._app_page: int = 0
        self._apps_items: list[dict] = []

    def set_tool(self, tid: str):
        if tid in self.tools:
            self.active_tool = self.tools[tid]
            self._sync_passthrough()
            h = Hud(self.active_tool.icon, self.active_tool.label)
            self.ui.hud(h)

    def open_wheel(self):
        self.state = State.WHEEL
        self.index = self.wheel_ids.index(self.active_tool.id) if self.active_tool.id in self.wheel_ids else 0
        self._wheel_last = time.monotonic()
        self._sync_passthrough()
        items = [self.tools[tid].to_item() for tid in self.wheel_ids]
        self.ui.wheel_open(items, self.index)
        log.info("opened main wheel at index %d (%s)", self.index, self.wheel_ids[self.index])

    def open_apps_wheel(self, page: int = 0):
        try:
            from cmf.backend.apps import scan_applications
            apps = scan_applications()
        except Exception:
            apps = []

        if not apps:
            self.ui.hud(Hud("app", "Applications", "No apps found"))
            return

        PAGE_SIZE = 8
        total_pages = max(1, (len(apps) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = page % total_pages
        self._app_page = page

        start_idx = page * PAGE_SIZE
        page_apps = apps[start_idx : start_idx + PAGE_SIZE]

        items = [{
            "id": "back",
            "label": "Back",
            "icon": "arrow_left",
            "glyph": "‹",
            "sticky": False,
        }]
        for a in page_apps:
            items.append({
                "id": f"app:{a.id}",
                "label": a.name,
                "icon": a.icon,
                "glyph": a.name[:2].upper(),
                "sticky": False,
                "app_obj": a,
            })
        if total_pages > 1:
            items.append({
                "id": "next_page",
                "label": f"Page {(page + 1) % total_pages + 1}/{total_pages} »",
                "icon": "redo",
                "glyph": "»",
                "sticky": False,
            })

        self.state = State.APPS_WHEEL
        self._apps_items = items
        self.index = 1 if len(items) > 1 else 0
        self._wheel_last = time.monotonic()
        self._sync_passthrough()
        self.ui.wheel_open(items, self.index)
        log.info("opened applications wheel page %d/%d", page + 1, total_pages)

    def handle(self, ev: Event):
        if self.state == State.WHEEL:
            self._handle_wheel(ev)
        elif self.state == State.APPS_WHEEL:
            self._handle_apps_wheel(ev)
        else:
            self._handle_tool(ev)

    def _handle_tool(self, ev: Event):
        if ev.kind == Kind.ROTATE:
            h = self.active_tool.rotate(self, ev.delta)
            if h:
                self.ui.hud(h)
        elif ev.kind in (Kind.DOUBLE, Kind.HOLD):
            self.open_wheel()
        elif ev.kind == Kind.CLICK:
            h = self.active_tool.click(self)
            if h:
                self.ui.hud(h)
        elif ev.kind == Kind.TRIPLE:
            self.nothing_buds.cycle_anc()
            self.ui.hud(Hud("volume", "ANC Mode", self.nothing_buds.ANC_MODES[self.nothing_buds.anc_mode]))

    def _handle_wheel(self, ev: Event):
        self._wheel_last = time.monotonic()
        if ev.kind == Kind.ROTATE:
            n = len(self.wheel_ids)
            self.index = (self.index + ev.delta) % n
            self.ui.wheel_move(self.index, 1 if ev.delta > 0 else -1)
        elif ev.kind == Kind.CLICK:
            self._commit_wheel()
        elif ev.kind in (Kind.DOUBLE, Kind.TRIPLE, Kind.HOLD):
            self._cancel_wheel()

    def _commit_wheel(self):
        tid = self.wheel_ids[self.index]
        tool = self.tools[tid]
        self.ui.wheel_commit(self.index)
        self.state = State.TOOL

        if tool.sticky:
            self.active_tool = tool
            self._sync_passthrough()
            self.ui.hud(Hud(tool.icon, tool.label))
        else:
            self._sync_passthrough()
            h = tool.click(self)
            if h:
                self.ui.hud(h)

    def _cancel_wheel(self):
        self.state = State.TOOL
        self.ui.wheel_cancel()
        self._sync_passthrough()

    def _handle_apps_wheel(self, ev: Event):
        self._wheel_last = time.monotonic()
        if ev.kind == Kind.ROTATE:
            n = len(self._apps_items)
            self.index = (self.index + ev.delta) % n
            self.ui.wheel_move(self.index, 1 if ev.delta > 0 else -1)
        elif ev.kind == Kind.CLICK:
            self._commit_apps_wheel()
        elif ev.kind in (Kind.DOUBLE, Kind.TRIPLE, Kind.HOLD):
            self.open_wheel()

    def _commit_apps_wheel(self):
        if not self._apps_items or self.index >= len(self._apps_items):
            self.open_wheel()
            return
        item = self._apps_items[self.index]
        if item["id"] == "back":
            self.open_wheel()
            return
        if item["id"] == "next_page":
            self.open_apps_wheel(page=self._app_page + 1)
            return
        if "app_obj" in item:
            from cmf.backend.apps import launch
            app = item["app_obj"]
            launch(app)
            self.ui.wheel_commit(self.index)
            self.state = State.TOOL
            self._sync_passthrough()
            self.ui.hud(Hud(app.icon, app.name, "Launched"))

    def _sync_passthrough(self):
        in_wheel = self.state in (State.WHEEL, State.APPS_WHEEL)
        passthrough = not in_wheel and self.active_tool.id == "volume"
        if self.dial_source:
            self.dial_source.set_passthrough(passthrough)

    def tick(self):
        if self.state in (State.WHEEL, State.APPS_WHEEL):
            if time.monotonic() - self._wheel_last > self.dismiss_after_s:
                if self.state == State.WHEEL and self.tools[self.wheel_ids[self.index]].sticky:
                    self._commit_wheel()
                else:
                    self._cancel_wheel()
