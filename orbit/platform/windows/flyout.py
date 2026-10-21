"""Hide the Windows volume flyout when the dial caused it.

Windows 11 shows its volume pill (an Explorer `XamlExplorerHostIslandWindow`)
on every endpoint volume change, including the AVRCP changes the dial makes and
the recenters Orbit makes. Orbit already shows its own HUD, so the pill is noise.

An out-of-context WinEvent hook sees the pill's EVENT_OBJECT_SHOW within a few
ms and hides it. Only pills that appear right around dial activity are hidden,
so keyboard volume keys keep the normal flyout. Explorer re-shows the same
window next time, so nothing stays broken if Orbit exits.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import threading
import time
from typing import Callable

log = logging.getLogger("orbit.flyout")
u = ctypes.WinDLL("user32")

EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0
FLYOUT_CLASS = "XamlExplorerHostIslandWindow"
MAX_W, MAX_H = 700, 200      # the pill; full-size islands (Start, widgets) are never touched
NEAR_S = 0.7                 # pill counts as dial-caused if dial activity is this close in time
RECHECK_S = 0.08             # pill can beat our volume callback by a few ms; look again once

_Proc = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)


class FlyoutSuppressor:
    def __init__(self, last_activity: Callable[[], float]):
        self.last_activity = last_activity
        self.enabled = True
        self._proc = _Proc(self._on_event)  # keep alive
        self._thread_id = 0
        self.hidden = 0

    def start(self):
        threading.Thread(target=self._pump, name="flyout-hook", daemon=True).start()

    def stop(self):
        if self._thread_id:
            u.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT

    def _pump(self):
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        hook = u.SetWinEventHook(EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW, 0, self._proc, 0, 0, WINEVENT_OUTOFCONTEXT)
        if not hook:
            log.warning("could not hook window events; Windows volume flyout will show")
            return
        log.info("windows volume flyout suppression active")
        msg = wt.MSG()
        while u.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            u.DispatchMessageW(ctypes.byref(msg))
        u.UnhookWinEvent(hook)

    def _is_pill(self, hwnd) -> bool:
        cls = ctypes.create_unicode_buffer(64)
        u.GetClassNameW(hwnd, cls, 64)
        if cls.value != FLYOUT_CLASS:
            return False
        r = wt.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(r))
        return 0 < r.right - r.left <= MAX_W and 0 < r.bottom - r.top <= MAX_H

    def _dial_near(self) -> bool:
        return time.monotonic() - self.last_activity() < NEAR_S

    def _on_event(self, hook, event, hwnd, id_object, id_child, thread, t):
        if not self.enabled or id_object != 0 or not hwnd or not self._is_pill(hwnd):
            return
        if self._dial_near():
            self._hide(hwnd)
        else:
            threading.Timer(RECHECK_S, self._recheck, args=(hwnd,)).start()

    def _recheck(self, hwnd):
        if self._dial_near() and u.IsWindowVisible(hwnd):
            self._hide(hwnd)

    def _hide(self, hwnd):
        u.ShowWindow(hwnd, 0)  # SW_HIDE
        self.hidden += 1
