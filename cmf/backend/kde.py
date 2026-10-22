"""KDE Plasma D-Bus integrations for brightness, window management, and virtual desktops."""
from __future__ import annotations

import logging

log = logging.getLogger("cmf.kde")


class KDEController:
    """Interfaces with KDE Plasma D-Bus services."""

    def __init__(self):
        self._bus = None

    def _get_bus(self):
        if self._bus is None:
            try:
                import dbus
                self._bus = dbus.SessionBus()
            except Exception:
                pass
        return self._bus

    def get_brightness(self) -> int | None:
        bus = self._get_bus()
        if not bus:
            return None
        try:
            import dbus
            obj = bus.get_object("org.kde.Solid.PowerManagement", "/org/kde/Solid/PowerManagement/Actions/BrightnessControl")
            iface = dbus.Interface(obj, "org.kde.Solid.PowerManagement.Actions.BrightnessControl")
            cur = int(iface.brightness())
            mx = int(iface.brightnessMax())
            return int(round((cur / max(1, mx)) * 100))
        except Exception as ex:
            log.debug("error getting KDE brightness: %s", ex)
            return None

    def set_brightness(self, pct: int):
        bus = self._get_bus()
        if not bus:
            return
        pct = max(0, min(100, pct))
        try:
            import dbus
            obj = bus.get_object("org.kde.Solid.PowerManagement", "/org/kde/Solid/PowerManagement/Actions/BrightnessControl")
            iface = dbus.Interface(obj, "org.kde.Solid.PowerManagement.Actions.BrightnessControl")
            mx = int(iface.brightnessMax())
            target = int(round((pct / 100.0) * mx))
            iface.setBrightness(target)
        except Exception as ex:
            log.debug("error setting KDE brightness: %s", ex)

    def switch_desktop(self, direction: int):
        """Direction: +1 (right/next), -1 (left/prev)."""
        bus = self._get_bus()
        if not bus:
            return
        try:
            import dbus
            obj = bus.get_object("org.kde.KWin", "/VirtualDesktopManager")
            iface = dbus.Interface(obj, "org.kde.KWin.VirtualDesktopManager")
            if direction > 0:
                iface.next()
            else:
                iface.previous()
        except Exception as ex:
            log.debug("error switching virtual desktop: %s", ex)
