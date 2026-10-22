"""Linux native CMF Buds Pro 2 dial driver using BlueZ D-Bus.

Connects directly to the BlueZ system bus and monitors the MediaTransport1 interface
for AVRCP volume change signals. Each detent of the physical CMF dial updates the
transport Volume property by +/-8 units.

Maintains a continuous virtual rotary encoder centered at 64 so the physical knob
operates as an unconstrained, endless 360-degree dial with infinite rotation in
both directions, completely eliminating hardware AVRCP 0..127 boundary freeze.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from cmf.core.events import Event, Kind

log = logging.getLogger("cmf.dial")

STEP_SIZE = 8          # CMF Buds Pro 2 sends 8 units per detent (0..127 grid)
EDGE_LOW = 40          # Emergency recenter if spinning fast below 40
EDGE_HIGH = 88         # Emergency recenter if spinning fast above 88
CENTER_VOL = 64        # Sweet spot center providing +/- 64 detent headroom
IDLE_RECENTER_DELAY = 0.12  # Debounced idle recenter (120ms after last rotation)


class BlueZDialSource:
    name = "bluez-dial"

    def __init__(self, emit: Callable[[Event], None], match_address: str = "2C:BE:EE:EF:EF:61"):
        self.emit = emit
        self.match_addr = match_address.replace(":", "_").lower()
        self._last_vol: int | None = None
        self._transport_path: str | None = None
        self._transport_props = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._bus = None

        # Robust recentering tracking
        self._pending_recenter_target: int | None = None
        self._pending_recenter_time: float = 0.0
        self._last_rotation_time: float = 0.0
        self._lock = threading.RLock()

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="bluez-dial-listener", daemon=True)
        self._thread.start()
        log.info("started native BlueZ D-Bus dial listener with endless rotary encoder engine")

    def stop(self):
        self._stop.set()

    def set_passthrough(self, on: bool):
        # Kept for interface compatibility; virtual encoder always maintains headroom
        pass

    def recenter(self):
        """Immediately reset the Bluetooth transport volume back to CENTER_VOL (64)."""
        with self._lock:
            if not self._transport_props or not self._transport_path:
                return
            try:
                import dbus
                # If already at center and no recenter is pending, nothing to do
                if self._last_vol == CENTER_VOL and self._pending_recenter_target is None:
                    return

                self._pending_recenter_target = CENTER_VOL
                self._pending_recenter_time = time.monotonic()
                self._transport_props.Set(
                    "org.bluez.MediaTransport1",
                    "Volume",
                    dbus.UInt16(CENTER_VOL),
                )
                log.debug("scheduled instant recenter to %d (was %s)", CENTER_VOL, self._last_vol)
            except Exception as ex:
                self._pending_recenter_target = None
                log.debug("failed to recenter transport volume: %s", ex)

    def _bind_transport(self, path: str):
        if not self._bus:
            return
        try:
            import dbus
            self._transport_path = path
            t_obj = self._bus.get_object("org.bluez", path)
            self._transport_props = dbus.Interface(t_obj, "org.freedesktop.DBus.Properties")
            try:
                vol = int(self._transport_props.Get("org.bluez.MediaTransport1", "Volume"))
                self._last_vol = vol
                log.info("bound to transport %s (initial vol %d)", path, vol)
                # If initial volume is off-center, gently center it for full headroom
                if vol != CENTER_VOL:
                    self.recenter()
            except Exception:
                self._last_vol = CENTER_VOL
        except Exception as ex:
            log.debug("error binding transport %s: %s", path, ex)

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

    def _on_interfaces_added(self, path, interfaces):
        if "org.bluez.MediaTransport1" in interfaces:
            dev_path = str(interfaces["org.bluez.MediaTransport1"].get("Device", "")).lower()
            if "cmf" in dev_path or self.match_addr in dev_path:
                log.info("CMF Buds audio transport added: %s", path)
                self._bind_transport(str(path))

    def _on_interfaces_removed(self, path, interfaces):
        if str(path) == self._transport_path or "org.bluez.MediaTransport1" in interfaces:
            log.info("CMF Buds audio transport removed: %s", path)
            with self._lock:
                self._transport_path = None
                self._transport_props = None
                self._last_vol = None
                self._pending_recenter_target = None

    def _on_properties_changed(self, interface, changed, invalidated, path=None):
        if interface != "org.bluez.MediaTransport1":
            return
        if "Volume" not in changed:
            return

        vol = int(changed["Volume"])
        now = time.monotonic()

        with self._lock:
            # If we received signal from a path different from current, update binding
            if path and path != self._transport_path:
                self._bind_transport(path)

            # Check if this volume change is the confirmation of our recenter
            if self._pending_recenter_target is not None:
                if vol == self._pending_recenter_target:
                    self._pending_recenter_target = None
                    self._last_vol = vol
                    log.debug("recenter echo confirmed (vol=%d)", vol)
                    return
                elif now - self._pending_recenter_time > 1.0:
                    # Recenter timed out; clear it so we don't block user detents
                    self._pending_recenter_target = None

            prev = self._last_vol
            self._last_vol = vol

            if prev is None:
                log.info("initial CMF Buds dial level: %d / 127", vol)
                if vol != CENTER_VOL:
                    self.recenter()
                return

            diff = vol - prev
            if diff == 0:
                return

            # Determine number of detents (usually +/-1 step of 8)
            steps = int(round(abs(diff) / STEP_SIZE))
            if steps == 0:
                steps = 1
            delta = steps if diff > 0 else -steps

            self._last_rotation_time = now
            log.debug("dial rotation: %+d (vol %d -> %d)", delta, prev, vol)
            self.emit(Event(Kind.ROTATE, delta, self.name))

            # Emergency recenter if continuous fast rotation approaches boundaries
            if vol <= EDGE_LOW or vol >= EDGE_HIGH:
                self.recenter()

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

            # Listen for transport plug / unplug (connect / reconnect)
            bus.add_signal_receiver(
                self._on_interfaces_added,
                bus_name="org.bluez",
                signal_name="InterfacesAdded",
                dbus_interface="org.freedesktop.DBus.ObjectManager",
            )
            bus.add_signal_receiver(
                self._on_interfaces_removed,
                bus_name="org.bluez",
                signal_name="InterfacesRemoved",
                dbus_interface="org.freedesktop.DBus.ObjectManager",
            )

            # Discover current transport
            t_path = self._find_transport(manager)
            if t_path:
                self._bind_transport(t_path)

            loop = GLib.MainLoop()
            while not self._stop.is_set():
                ctx = loop.get_context()
                ctx.iteration(False)

                # Debounced idle recenter: when spinning pauses, restore center for full headroom
                now = time.monotonic()
                if (
                    self._last_rotation_time > 0
                    and (now - self._last_rotation_time >= IDLE_RECENTER_DELAY)
                    and self._last_vol is not None
                    and self._last_vol != CENTER_VOL
                ):
                    self._last_rotation_time = 0.0
                    self.recenter()

                time.sleep(0.01)

        except Exception as ex:
            log.warning("BlueZ D-Bus dial loop exited: %s", ex)
