"""Calibration recorder: what the dial really sends, click by click (Windows, admin).

Records side by side, on one clock (QueryPerformanceCounter):
  win   every endpoint volume change Windows reports (what Orbit sees today)
  bt    the buds' own AVRCP messages from the raw Bluetooth trace, stamped with
        the packet's capture time (not the time ETW handed it to us)
  set   our own SetMasterVolume calls (recenters)
  mark  phase start/end + your notes

Walks you through turning patterns (slow, steady, flicks, back-and-forth) so the
analysis knows how many clicks you actually made. Stops Orbit while it runs and
restarts it at the end.

    python tools/dial_record.py            (asks for admin)
    python tools/dial_analyze.py tools/calib/<file>.jsonl
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import uuid
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orbit.platform.windows import etw  # noqa: E402

OUT_DIR = ROOT / "tools" / "calib"
MATCH = "cmf buds pro 2"
RECENTER_IDLE_S = 1.6
CTX = uuid.UUID("7a0c2a1e-6d3b-4c9a-9a47-0b1e7a1d1a22")

PHASES = [
    ("slow-up", "SLOW UP: 8 single clicks in the volume-UP direction, about one per second."),
    ("slow-down", "SLOW DOWN: 8 single clicks in the volume-DOWN direction, about one per second."),
    ("steady", "STEADY: turn UP smoothly ~3 clicks a second for 6 clicks, pause 2 s, then 6 DOWN the same way."),
    ("flick-up", "FLICK UP: flick exactly 4 clicks UP as fast as you can. Wait 2 s. Do this 4 times."),
    ("flick-down", "FLICK DOWN: flick exactly 4 clicks DOWN as fast as you can. Wait 2 s. Do this 4 times."),
    ("spin", "FAST SPIN: spin UP as fast as you comfortably can for about 10 clicks, stop, wait 2 s, then 10 DOWN."),
    ("alt-slow", "BACK-AND-FORTH SLOW: 1 up, 1 down, 1 up, 1 down... 10 clicks total, about one per second."),
    ("alt-fast", "BACK-AND-FORTH FAST: 2 up, 2 down quickly, repeated for about 6 seconds."),
    ("reverse", "QUICK REVERSE: 3 clicks UP fast and immediately 3 DOWN fast, wait 2 s. Do this 3 times."),
    ("offgrid", "SLOW AGAIN (recenter now lands between steps): 4 single clicks UP then 4 DOWN, one per second."),
]


# ------------------------------------------------------------------ recording
class Recorder:
    def __init__(self, path: Path):
        self.f = path.open("w", encoding="utf-8")
        self.lock = threading.Lock()
        self.phase = None
        self.last_move = time.perf_counter()
        self.offgrid = False
        self.qpf = ctypes.c_int64()
        ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(self.qpf))

    def put(self, **rec):
        rec.setdefault("t", time.perf_counter())
        rec["phase"] = self.phase
        with self.lock:
            self.f.write(json.dumps(rec) + "\n")
            self.f.flush()

    def close(self):
        self.f.close()


class BtSession(etw.EtwSession):
    """EtwSession that also hands over the packet's capture timestamp."""

    def _record(self, rec):
        n = ctypes.c_ushort.from_address(rec + etw._OFF_LEN).value
        ptr = ctypes.c_void_p.from_address(rec + etw._OFF_DATA).value
        if n and ptr:
            ts = ctypes.c_int64.from_address(rec + 16).value     # EVENT_HEADER.TimeStamp (QPC)
            self.on_payload(ctypes.string_at(ptr, n), ts)


def decode_avrcp(data: bytes):
    out = []
    i = data.find(b"\x00\x19\x58\x31\x00\x00\x02\x0d")          # RegisterNotification rsp, VOLUME_CHANGED
    if i >= 3 and len(data) > i + 8:
        out.append(({0x0D: "changed", 0x0F: "interim"}.get(data[i - 3], hex(data[i - 3])), data[i + 8] & 0x7F))
    i = data.find(b"\x00\x19\x58\x31\x00\x00\x05\x0d")          # RegisterNotification cmd (PC re-arms)
    if i >= 3:
        out.append(("register", None))
    i = data.find(b"\x00\x19\x58\x50\x00\x00\x01")              # SetAbsoluteVolume
    if i >= 3 and len(data) > i + 7:
        out.append(({0x00: "setabs", 0x09: "setabs-ok", 0x08: "setabs-rej"}.get(data[i - 3], hex(data[i - 3])),
                    data[i + 7] & 0x7F))
    return out


def main():
    if not etw.is_admin():
        params = subprocess.list2cmdline([str(Path(__file__).resolve())] + sys.argv[1:])
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, str(ROOT), 1)
        print("opened an admin window for the recorder" if rc > 32 else "admin was refused")
        return

    import comtypes
    from pycaw.callbacks import AudioEndpointVolumeCallback
    from pycaw.pycaw import AudioUtilities
    warnings.filterwarnings("ignore")

    # Orbit would fight us over the volume; stop it and bring it back at the end.
    orbit_pid = None
    lockf = Path(os.environ["LOCALAPPDATA"]) / "Orbit" / "orbit.lock"
    if lockf.exists():
        try:
            orbit_pid = int(lockf.read_text().split()[0])
            subprocess.run(["taskkill", "/PID", str(orbit_pid), "/T", "/F"], capture_output=True)
            print(f"stopped Orbit (pid {orbit_pid})")
            time.sleep(0.8)
        except Exception as e:
            print("could not stop Orbit:", e)
    etw.stop_session("OrbitDialBT")

    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / time.strftime("dial-%Y%m%d-%H%M%S.jsonl")
    rec = Recorder(path)

    try:
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
    except OSError:
        pass                                            # comtypes already set up this thread
    dev = None
    waited = False
    while not dev:
        coll = AudioUtilities.GetDeviceEnumerator().EnumAudioEndpoints(0, 1)
        for i in range(coll.GetCount()):
            d = AudioUtilities.CreateDevice(coll.Item(i))
            if MATCH in (d.FriendlyName or "").lower():
                dev = d
        if not dev:
            if not waited:
                print("Waiting for CMF Buds Pro 2 to connect as this PC's audio output "
                      "(open the case / reconnect in Bluetooth settings)...", flush=True)
                waited = True
            time.sleep(1.0)
    if waited:
        print("Buds connected.")
        time.sleep(1.5)
    ev = dev.EndpointVolume
    ours_guid = comtypes.GUID("{" + str(CTX) + "}")
    state = {"pending_set": None}

    class Cb(AudioEndpointVolumeCallback):
        def on_notify(self, new_volume, new_mute, event_context, channels, channel_volumes):
            ours = event_context.contents == ours_guid
            rec.put(src="win", level=round(new_volume, 5), u=round(new_volume * 127), ours=ours)
            if not ours:
                rec.last_move = time.perf_counter()
                if rec.phase:
                    print(f"   win {new_volume * 127:6.1f}/127", flush=True)

    cb = Cb()
    ev.RegisterControlChangeNotify(cb)

    def on_bt(data: bytes, ts: int):
        for kind, v in decode_avrcp(data):
            rec.put(src="bt", kind=kind, v=v, tc=ts / rec.qpf.value)

    sess = BtSession("OrbitCalib", [(uuid.UUID("8a1f9517-3a8c-4a9e-a018-4f17a200f277"), 5, 0)], on_bt)
    sess.start()

    def set_u(u: int, why: str):
        rec.put(src="set", u=u, why=why)
        ev.SetMasterVolumeLevelScalar(u / 127, ctypes.byref(ours_guid))

    def recenter_loop():
        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        while True:
            time.sleep(0.1)
            if time.perf_counter() - rec.last_move < RECENTER_IDLE_S:
                continue
            target = 60 if rec.offgrid else 64          # 64 = step 8 of 16; 60 sits between 56 and 64
            cur = round(ev.GetMasterVolumeLevelScalar() * 127)
            if cur != target:
                set_u(target, "recenter")
            rec.last_move = time.perf_counter()

    threading.Thread(target=recenter_loop, daemon=True).start()

    print(f"\nRecording to {path}\n")
    print("Keep music paused (volume will jump around). For each step: press Enter, do the")
    print("turning, press Enter again. If you made a different number of clicks than asked,")
    print("type the real count (or any note) before the second Enter.\n")
    rec.put(src="mark", what="start", grid_hint=16)
    try:
        for name, text in PHASES:
            print("-" * 70)
            print(text)
            input("  [Enter] to start ")
            rec.offgrid = name == "offgrid"
            rec.last_move = 0.0                         # recenter right away before this phase
            time.sleep(0.4)
            rec.phase = name
            rec.put(src="mark", what="begin")
            print("  GO")
            note = input("  ...turning. [Enter] when done (or type a note first): ").strip()
            rec.put(src="mark", what="end", note=note)
            rec.phase = None
            time.sleep(0.3)
        print("-" * 70)
        print(f"Done. Saved {path.name}")
    finally:
        sess.stop()
        try:
            ev.UnregisterControlChangeNotify(cb)
        except Exception:
            pass
        rec.close()
        if orbit_pid:
            subprocess.Popen([sys.executable, "-m", "orbit"], cwd=str(ROOT), creationflags=0x00000008)
            print("Orbit restarted.")
    input("[Enter] to close this window")


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        import traceback
        traceback.print_exc()
        input("Recorder failed (see above). [Enter] to close")
