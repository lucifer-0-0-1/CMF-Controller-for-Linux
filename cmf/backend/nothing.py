"""Nothing & CMF ecosystem integration: CMF Buds Pro 2 ANC/battery & Nothing Phone 4b."""
from __future__ import annotations

import logging
import socket
import threading

log = logging.getLogger("cmf.nothing")

CMF_HEADER = bytes([0x55, 0xAA])
CMD_SET_ANC = 0x02
CMD_GET_BATTERY = 0x01


def _calc_checksum(pkt: bytes) -> int:
    return sum(pkt[2:]) & 0xFF


def build_anc_packet(mode: int) -> bytes:
    # 0 = Off, 1 = ANC, 2 = Transparency, 3 = Adaptive
    payload = bytes([mode & 0xFF])
    pkt = CMF_HEADER + bytes([CMD_SET_ANC, len(payload)]) + payload
    return pkt + bytes([_calc_checksum(pkt)])


class CMFBudsManager:
    ANC_MODES = ["Off", "ANC", "Transparency", "Adaptive"]

    def __init__(self, mac_address: str = "2C:BE:EE:EF:EF:61"):
        self.mac = mac_address
        self.anc_mode = 1  # default to ANC
        self.battery_level: int | None = None

    def get_battery(self) -> int | None:
        try:
            import dbus
            bus = dbus.SystemBus()
            manager = dbus.Interface(bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager")
            objects = manager.GetManagedObjects()
            for path, ifaces in objects.items():
                if "org.bluez.Battery1" in ifaces:
                    dev_props = ifaces.get("org.bluez.Device1", {})
                    name = str(dev_props.get("Name", "")).lower()
                    if "cmf" in name or "buds" in name:
                        pct = int(ifaces["org.bluez.Battery1"].get("Percentage", 0))
                        self.battery_level = pct
                        return pct
        except Exception as ex:
            log.debug("error querying battery via BlueZ: %s", ex)
        return self.battery_level

    def cycle_anc(self) -> str:
        # Cycle: 1 (ANC) -> 2 (Transparency) -> 0 (Off) -> 1
        if self.anc_mode == 1:
            self.anc_mode = 2
        elif self.anc_mode == 2:
            self.anc_mode = 0
        else:
            self.anc_mode = 1

        mode_name = self.ANC_MODES[self.anc_mode]
        self.set_anc(self.anc_mode)
        return mode_name

    def set_anc(self, mode: int):
        self.anc_mode = mode
        threading.Thread(target=self._rfcomm_send_anc, args=(mode,), name="cmf-anc-send", daemon=True).start()

    def _rfcomm_send_anc(self, mode: int):
        if not self.mac:
            return
        try:
            pkt = build_anc_packet(mode)
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.settimeout(2.0)
            s.connect((self.mac, 1))
            s.send(pkt)
            s.close()
            log.info("sent ANC mode %d to %s", mode, self.mac)
        except Exception as ex:
            log.debug("RFCOMM ANC send failed: %s", ex)


class NothingPhoneManager:
    def __init__(self):
        self._device_id: str | None = None
        self._device_name: str = "Nothing Phone"

    def _find_device(self) -> str | None:
        if self._device_id:
            return self._device_id
        try:
            import dbus
            bus = dbus.SessionBus()
            daemon = dbus.Interface(bus.get_object("org.kde.kdeconnect", "/modules/kdeconnect"), "org.kde.kdeconnect.daemon")
            devices = daemon.devices(True, True)  # reachable=True, paired=True
            for dev_id in devices:
                dev_proxy = bus.get_object("org.kde.kdeconnect", f"/modules/kdeconnect/devices/{dev_id}")
                name = str(dev_proxy.Get("org.kde.kdeconnect.device", "name", dbus_interface="org.freedesktop.DBus.Properties"))
                if "nothing" in name.lower() or "phone" in name.lower() or "4b" in name.lower():
                    self._device_id = str(dev_id)
                    self._device_name = name
                    return self._device_id
            if devices:
                self._device_id = str(devices[0])
                return self._device_id
        except Exception as ex:
            log.debug("error finding KDE Connect device: %s", ex)
        return None

    def get_phone_battery(self) -> int | None:
        dev_id = self._find_device()
        if not dev_id:
            return None
        try:
            import dbus
            bus = dbus.SessionBus()
            proxy = bus.get_object("org.kde.kdeconnect", f"/modules/kdeconnect/devices/{dev_id}")
            prop = proxy.Get("org.kde.kdeconnect.device.battery", "charge", dbus_interface="org.freedesktop.DBus.Properties")
            return int(prop)
        except Exception:
            return None

    def ring_phone(self) -> bool:
        dev_id = self._find_device()
        if not dev_id:
            return False
        try:
            import dbus
            bus = dbus.SessionBus()
            proxy = bus.get_object("org.kde.kdeconnect", f"/modules/kdeconnect/devices/{dev_id}/findmyphone")
            iface = dbus.Interface(proxy, "org.kde.kdeconnect.device.findmyphone")
            iface.ring()
            return True
        except Exception as ex:
            log.debug("error ringing phone: %s", ex)
            return False

    def ping_phone(self) -> bool:
        dev_id = self._find_device()
        if not dev_id:
            return False
        try:
            import dbus
            bus = dbus.SessionBus()
            proxy = bus.get_object("org.kde.kdeconnect", f"/modules/kdeconnect/devices/{dev_id}/ping")
            iface = dbus.Interface(proxy, "org.kde.kdeconnect.device.ping")
            iface.sendPing()
            return True
        except Exception:
            return False
