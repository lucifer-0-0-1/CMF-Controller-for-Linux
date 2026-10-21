"""Settings window choices layered over config.toml (orbit.core.settings)."""
from orbit.core import config as config_mod
from orbit.core import settings as st
from orbit.core.engine import Engine
from orbit.core.events import Capability

from tests.test_engine import FakeOut, FakeRot, FakeSrc, FakeUI


def base():
    cfg, _ = config_mod.load(platform="windows")
    return cfg


def test_no_settings_changes_nothing():
    cfg = base()
    assert st.apply(cfg, {}) == cfg


def test_disabled_items_leave_the_wheel_and_order_is_kept():
    cfg = base()
    order = ["scroll", "volume", "tabs", "brightness"] + [t for t in cfg["tools"]
                                                         if t not in ("scroll", "volume", "tabs", "brightness")]
    out = st.apply(cfg, {"wheel": {"order": order, "enabled": ["volume", "scroll", "tabs"]}})
    assert out["wheel"]["items"] == ["scroll", "volume", "tabs"]


def test_unknown_tools_in_settings_are_ignored():
    cfg = base()
    out = st.apply(cfg, {"wheel": {"order": ["gone", "volume"], "enabled": ["gone", "volume"]},
                         "default_tool": "gone"})
    assert out["wheel"]["items"] == ["volume"]
    assert out.get("default_tool") == cfg.get("default_tool")


def test_gesture_can_take_or_give_up_open_wheel():
    cfg = base()
    assert st.gesture_action(cfg, "double") == st.OPEN_WHEEL
    out = st.apply(cfg, {"gestures": {"double": "media:next", "triple": st.OPEN_WHEEL}})
    assert st.gesture_action(out, "double") == "media:next"
    assert st.gesture_action(out, "triple") == st.OPEN_WHEEL
    assert "triple" not in out["gestures"]


def test_settings_survive_validation_and_drive_the_engine():
    cfg, _ = config_mod.load(platform="windows", user_settings={
        "wheel": {"order": ["volume", "scroll"], "enabled": ["volume", "scroll"]},
        "default_tool": "scroll",
        "gestures": {"click": "none", "double": "media:next", "triple": st.OPEN_WHEEL},
    })
    e = Engine(cfg, FakeOut(), FakeUI(), [FakeRot(), FakeSrc((Capability.CLICKS, Capability.HOLD))])
    assert e.wheel_ids == ["volume", "scroll"]
    assert e.tool.id == "scroll"
    assert e.open_with == {"triple"}


def test_engine_keeps_a_way_into_the_wheel_when_no_gesture_opens_it():
    cfg = st.apply(base(), {"gestures": {"double": "none"}})
    config_mod.validate(cfg)
    e = Engine(cfg, FakeOut(), FakeUI(), [FakeRot(), FakeSrc((Capability.CLICKS,))])
    assert e.open_with == {"triple"}


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    s = {"wheel": {"order": ["volume"], "enabled": ["volume"]}, "gestures": {"hold": ["keys:a", "wait:10"]}}
    st.save(s, p)
    assert st.load(p) == s
    assert st.load(tmp_path / "missing.json") == {}
