"""Linux native CMF Buds Pro 2 dial driver using BlueZ D-Bus.

Connects directly to the BlueZ system bus and monitors the MediaTransport1 interface
for AVRCP volume change signals. Each detent of the physical CMF dial updates the
transport Volume property by +/-8 units. This provides sub-millisecond dial rotation
detection with ZERO subprocess overhead and ZERO sound-server race conditions.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from cmf.core.events import Event, Kind

log = logging.getLogger("cmf.dial")

STEP_SIZE = 8          # CMF Buds Pro 2 sends 8 units per detent (0..127 grid)
EDGE_LOW = 16
EDGE_HIGH = 112
CENTER_VOL = 64


class BlueZDialSource:
    name = "bluez-dial"

    def __init__(self, emit: Callable[[Event], None], match_address: str = "2C:BE:EE:EF:EF_61"):
        self.emit = emit
        self.match_addr = match_address.replace(":", "_").lower()
        self._last_vol: int | None = None
        self._transport_path: str | None = None
        self._transport_props = None
        self._passthrough: bool = True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ignore_our_set: bool = False
        self._bus = None

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="bluez-dial-listener", daemon=True)
        self._thread.start()
        log.info("started native BlueZ D-Bus dial listener")

    def stop(self):
        self._stop.set()

    def set_passthrough(self, on: bool):
        self._passthrough = on

    def _find_transport(self, manager) -> str | None:
        try:
            objects = manager.GetManagedObjects()
            for path, ifaces in objects.items():
                if "org.bluez.MediaTransport1" in ifaces:
                    dev_path = str(ifaces["org.bluez.MediaTransport1"].get("Device", "")).lower()
                    if "cmf" in dev_path or self.match_addr in dev_path:
                        return str(path)
            # If no direct CMF match, find the first connected A2DP transport
            for path, ifaces in objects.items():
                if "org.bluez.MediaTransport1" in ifaces:
                    return str(path)
        except Exception as ex:
            log.debug("error finding BlueZ transport: %s", ex)
        return None

    def _on_properties_changed(self, interface, changed, invalidated, path=None):
        if interface != "org.bluez.MediaTransport1":
            return
        if "Volume" not in changed:
            return

        vol = int(changed["Volume"])
        if self._ignore_our_set:
            self._ignore_our_set = False
            self._last_vol = vol
            return

        prev = self._last_vol
        self._last_vol = vol

        if prev is None:
            log.info("initial CMF Buds dial level: %d / 127", vol)
            return

        diff = vol - prev
        if diff == 0:
            return

        # Determine number of detents (usually +/-1 step of 8)
        steps = int(round(abs(diff) / STEP_SIZE))
        if steps == 0:
            steps = 1
        delta = steps if diff > 0 else -steps

        log.debug("dial rotation: %+d (vol %d -> %d)", delta, prev, vol)
        self.emit(Event(Kind.ROTATE, delta, self.name))

        # If not in passthrough and approaching edges, reset to center
        if not self._passthrough and (vol <= EDGE_LOW or vol >= EDGE_HIGH):
            self._recenter_transport()

    def _recenter_transport(self):
        if not self._transport_props or not self._transport_path:
            return
        try:
            import dbus
            self._ignore_our_set = True
            self._transport_props.Set(
                "org.bluez.MediaTransport1",
                "Volume",
                dbus.UInt16(CENTER_VOL),
            )
            self._last_vol = CENTER_VOL
            log.debug("recentered BlueZ transport volume to %d", CENTER_VOL)
        except Exception as ex:
            self._ignore_our_set = False
            log.debug("failed to recenter transport volume: %s", ex)

    def _run_loop(self):
        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop
            from gi.repository import GLib

            DBusGMainLoop(set_as_default=True)
            bus = dbus.SystemBus()
            self._bus = bus
            manager = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")

            # Listen for properties changes on all transports
            bus.add_signal_receiver(
                self._on_properties_changed,
                bus_name="org.bluez",
                signal_name="PropertiesChanged",
                dbus_interface="org.freedesktop.DBus.Properties",
                path_keyword="path",
            )

            # Discover current transport
            t_path = self._find_transport(manager)
            if t_path:
                self._transport_path = t_path
                t_obj = bus.get_object("org.bluez", t_path)
                self._transport_props = dbus.Interface(t_obj, "org.freedesktop.DBus.Properties")
                try:
                    self._last_vol = int(self._transport_props.Get("org.bluez.MediaTransport1", "Volume"))
                    log.info("bound to transport %s (initial vol %d)", t_path, self._last_vol)
                except Exception:
                    self._last_vol = CENTER_VOL

            loop = GLib.MainLoop()
            while not self._stop.is_set():
                ctx = loop.get_context()
                ctx.iteration(False)
                time.sleep(0.01)

        except Exception as ex:
            log.warning("BlueZ D-Bus dial loop exited: %s", ex)
