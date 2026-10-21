"""Minimal CoreAudio HAL access through ctypes (PyObjC's CoreAudio binding is too thin).

Finds the buds' output device, reads/sets its main volume, and listens for
changes. The system volume slider is kAudioHardwareServiceDeviceProperty_VirtualMainVolume
('vmvc', AudioToolbox), which works whether the device exposes a main volume
control or only per-channel ones. Listener callbacks arrive on a HAL thread.
"""
from __future__ import annotations

import ctypes
import logging
import struct
from ctypes import CFUNCTYPE, POINTER, byref, c_char_p, c_float, c_int32, c_uint32, c_void_p, sizeof

log = logging.getLogger("orbit.coreaudio")

_CA = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
_AT = ctypes.CDLL("/System/Library/Frameworks/AudioToolbox.framework/AudioToolbox")
_CF = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")


def fourcc(s: str) -> int:
    return struct.unpack(">I", s.encode("ascii"))[0]


class Addr(ctypes.Structure):
    _fields_ = [("selector", c_uint32), ("scope", c_uint32), ("element", c_uint32)]


SYSTEM = 1                          # kAudioObjectSystemObject
GLOBAL, OUTPUT = fourcc("glob"), fourcc("outp")
MAIN = 0                            # kAudioObjectPropertyElementMain
DEVICES, NAME, UID = fourcc("dev#"), fourcc("lnam"), fourcc("uid ")
TRANSPORT, STREAMS = fourcc("tran"), fourcc("stm#")
VMVC, VOLM = fourcc("vmvc"), fourcc("volm")
DEFAULT_OUT = fourcc("dOut")
BLUETOOTH, BLUETOOTH_LE = fourcc("blue"), fourcc("blea")

Listener = CFUNCTYPE(c_int32, c_uint32, c_uint32, POINTER(Addr), c_void_p)

for f in ("AudioObjectGetPropertyDataSize", "AudioObjectGetPropertyData", "AudioObjectSetPropertyData",
          "AudioObjectAddPropertyListener", "AudioObjectRemovePropertyListener"):
    getattr(_CA, f).restype = c_int32
_CA.AudioObjectHasProperty.restype = ctypes.c_bool
for f in ("AudioHardwareServiceGetPropertyData", "AudioHardwareServiceSetPropertyData",
          "AudioHardwareServiceAddPropertyListener", "AudioHardwareServiceRemovePropertyListener"):
    getattr(_AT, f).restype = c_int32
_AT.AudioHardwareServiceHasProperty.restype = ctypes.c_bool
_CF.CFStringGetCString.argtypes = [c_void_p, c_char_p, ctypes.c_long, c_uint32]
_CF.CFStringGetCString.restype = ctypes.c_bool
_CF.CFRelease.argtypes = [c_void_p]


def _check(rc: int, what: str):
    if rc != 0:
        raise OSError(rc, f"CoreAudio {what} failed ({rc})")


def devices() -> list[int]:
    a = Addr(DEVICES, GLOBAL, MAIN)
    size = c_uint32()
    _check(_CA.AudioObjectGetPropertyDataSize(SYSTEM, byref(a), 0, None, byref(size)), "device list size")
    ids = (c_uint32 * (size.value // 4))()
    _check(_CA.AudioObjectGetPropertyData(SYSTEM, byref(a), 0, None, byref(size), ids), "device list")
    return list(ids)


def _cfstring(dev: int, selector: int) -> str:
    a = Addr(selector, GLOBAL, MAIN)
    ref = c_void_p()
    size = c_uint32(sizeof(c_void_p))
    if _CA.AudioObjectGetPropertyData(dev, byref(a), 0, None, byref(size), byref(ref)) != 0 or not ref.value:
        return ""
    buf = ctypes.create_string_buffer(512)
    ok = _CF.CFStringGetCString(ref, buf, 512, 0x08000100)   # kCFStringEncodingUTF8
    _CF.CFRelease(ref)
    return buf.value.decode("utf-8", "replace") if ok else ""


def name(dev: int) -> str:
    return _cfstring(dev, NAME)


def uid(dev: int) -> str:
    return _cfstring(dev, UID)


def transport(dev: int) -> int:
    a = Addr(TRANSPORT, GLOBAL, MAIN)
    v = c_uint32()
    size = c_uint32(4)
    _CA.AudioObjectGetPropertyData(dev, byref(a), 0, None, byref(size), byref(v))
    return v.value


def has_output(dev: int) -> bool:
    a = Addr(STREAMS, OUTPUT, MAIN)
    size = c_uint32()
    return _CA.AudioObjectGetPropertyDataSize(dev, byref(a), 0, None, byref(size)) == 0 and size.value > 0


def find_output(match: str) -> int | None:
    """Output device whose name contains `match`; Bluetooth devices win ties."""
    match = match.lower()
    hits = [d for d in devices() if has_output(d) and match in name(d).lower()]
    hits.sort(key=lambda d: transport(d) not in (BLUETOOTH, BLUETOOTH_LE))
    return hits[0] if hits else None


def get_volume(dev: int) -> float | None:
    a = Addr(VMVC, OUTPUT, MAIN)
    v = c_float()
    size = c_uint32(4)
    if _AT.AudioHardwareServiceGetPropertyData(dev, byref(a), 0, None, byref(size), byref(v)) != 0:
        return None
    return float(v.value)


def set_volume(dev: int, level: float):
    a = Addr(VMVC, OUTPUT, MAIN)
    v = c_float(max(0.0, min(1.0, level)))
    _check(_AT.AudioHardwareServiceSetPropertyData(dev, byref(a), 0, None, 4, byref(v)), "set volume")


# Every registered ctypes callback lives here until it is removed: if one were
# garbage-collected while CoreAudio still holds its pointer, the next notification
# would jump into freed memory and crash the process.
_alive: dict[int, object] = {}


def _proc(cb):
    def call(obj, n, addrs, ctx):
        try:
            cb()
        except Exception:
            log.exception("CoreAudio listener failed")
        return 0
    return Listener(call)


def add_volume_listener(dev: int, cb) -> object:
    """cb() is called (HAL thread) whenever the device's main volume changes.
    Returns a handle for remove_volume_listener."""
    proc = _proc(cb)
    a = Addr(VMVC, OUTPUT, MAIN)
    _check(_AT.AudioHardwareServiceAddPropertyListener(dev, byref(a), proc, None), "add volume listener")
    handle = (dev, proc)
    _alive[id(proc)] = handle
    return handle


def remove_volume_listener(handle):
    dev, proc = handle
    a = Addr(VMVC, OUTPUT, MAIN)
    _AT.AudioHardwareServiceRemovePropertyListener(dev, byref(a), proc, None)
    _alive.pop(id(proc), None)


def add_devices_listener(cb) -> object:
    """cb() on any device-list change (connect/disconnect). Returns a handle."""
    proc = _proc(cb)
    a = Addr(DEVICES, GLOBAL, MAIN)
    _check(_CA.AudioObjectAddPropertyListener(SYSTEM, byref(a), proc, None), "add devices listener")
    _alive[id(proc)] = proc
    return proc


def remove_devices_listener(proc):
    a = Addr(DEVICES, GLOBAL, MAIN)
    _CA.AudioObjectRemovePropertyListener(SYSTEM, byref(a), proc, None)
    _alive.pop(id(proc), None)
