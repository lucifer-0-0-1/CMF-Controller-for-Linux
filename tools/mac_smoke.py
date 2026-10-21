"""macOS smoke test: exercises the real macOS APIs the backend uses, without buds.

    python tools/mac_smoke.py
Exit code 0 when every step either works or is clearly unavailable on this
machine (e.g. no audio output on a CI runner); 1 on an unexpected error.
"""
import faulthandler
import sys
import time
import traceback
from pathlib import Path

faulthandler.enable()          # a native crash prints the Python stack instead of just "139"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

failures = []


def step(name, fn):
    try:
        r = fn()
        print(f"ok   {name}: {r}")
    except Exception as e:
        failures.append(name)
        print(f"FAIL {name}: {e!r}")
        traceback.print_exc()


def coreaudio():
    from orbit.platform.mac import coreaudio as ca
    devs = ca.devices()
    outs = [(d, ca.name(d), ca.transport(d)) for d in devs if ca.has_output(d)]
    for d, n, t in outs:
        print(f"       out dev {d}: {n!r} transport={t:#x} volume={ca.get_volume(d)}")
    if outs:
        d = outs[0][0]
        h = ca.add_volume_listener(d, lambda: None)
        ca.remove_volume_listener(h)
    ca.remove_devices_listener(ca.add_devices_listener(lambda: None))
    return f"{len(devs)} devices, {len(outs)} outputs"


def rotation_source():
    from orbit.platform.mac.input_volume import MacVolumeRotationSource
    got = []
    s = MacVolumeRotationSource("definitely-not-a-device")
    s.start(got.append)
    time.sleep(0.2)
    s.set_passthrough(False)
    s.stop()
    return s.describe()


def output():
    from orbit.platform.mac.output import MacOutput
    o = MacOutput()
    o.keys("shift")            # harmless: posts nothing visible without Accessibility
    o.scroll(0.0)
    o.scroll(0.2)              # posts a real 8 px scroll (dropped without Accessibility)
    import Quartz as Q
    from orbit.platform.mac.output import scroll_event
    e = scroll_event(-24)
    got = {name: Q.CGEventGetIntegerValueField(e, getattr(Q, f"kCGScrollWheelEvent{name}"))
           for name in ("PointDeltaAxis1", "DeltaAxis1", "IsContinuous")}
    print("       scroll event fields:", got, "type", Q.CGEventGetType(e))
    assert Q.CGEventGetType(e) == Q.kCGEventScrollWheel, f"type {Q.CGEventGetType(e)}"
    assert got["PointDeltaAxis1"] == -24, got
    assert got["DeltaAxis1"] in (-2, -3), got
    assert got["IsContinuous"] == 1, got
    cur = Q.CGEventGetLocation(Q.CGEventCreate(None))
    loc = Q.CGEventGetLocation(e)
    assert abs(loc.x - cur.x) < 1 and abs(loc.y - cur.y) < 1, f"event at {loc}, cursor at {cur}"
    h = scroll_event(30, horizontal=True)
    h2 = Q.CGEventGetIntegerValueField(h, Q.kCGScrollWheelEventPointDeltaAxis2)
    assert h2 == 30, f"horizontal point delta {h2}"
    return f"brightness={o.brightness_get()} scroll event ok at {loc.x:.0f},{loc.y:.0f}"


def media_and_overlay():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from orbit.platform.mac.input_media import MacMediaButtonSource
    from orbit.platform.mac.overlay import ensure_accessibility, make_agent_app
    app = QApplication.instance() or QApplication(sys.argv[:1])
    make_agent_app()
    trusted = ensure_accessibility(prompt=False)
    src = MacMediaButtonSource()
    src.start(lambda ev: None)
    QTimer.singleShot(800, app.quit)
    app.exec()
    src.reassert()
    src.stop()
    return f"accessibility trusted={trusted}"


def platform_config():
    from orbit.core import config
    cfg, _ = config.load()
    return f"switcher modifier={cfg['tools']['switcher'].get('modifier')} zoom={cfg['tools']['zoom']['rotate_cw']}"


if sys.platform != "darwin":
    sys.exit("run this on macOS")
step("platform config", platform_config)
step("coreaudio", coreaudio)
step("rotation source", rotation_source)
step("quartz output", output)
step("now-playing + agent app", media_and_overlay)
print("FAILED:" if failures else "all steps passed", failures or "")
sys.exit(1 if failures else 0)
