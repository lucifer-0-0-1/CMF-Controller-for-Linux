"""Engine behaviour, no hardware or Qt. Run: python -m pytest -q"""
import time

import pytest

from orbit.core import config as config_mod
from orbit.core.engine import Engine, State
from orbit.core.events import Capability, InputEvent, Kind
from orbit.platform.base import InputSource, Output, RotationSource


class FakeOut(Output):
    def __init__(self):
        self.log = []

    def keys(self, combo): self.log.append(("keys", combo))
    def key_down(self, key): self.log.append(("down", key))
    def key_up(self, key): self.log.append(("up", key))
    def scroll(self, notches, horizontal=False): self.log.append(("scroll", notches))
    def media(self, command): self.log.append(("media", command))
    def launch(self, target): self.log.append(("launch", target))
    def center_window(self, title): self.log.append(("center", title))


class FakeUI:
    def __init__(self):
        self.log = []

    def wheel_open(self, items, index): self.log.append(("open", index))
    def wheel_move(self, index, direction): self.log.append(("move", index, direction))
    def wheel_commit(self, index): self.log.append(("commit", index))
    def wheel_cancel(self): self.log.append(("cancel",))
    def hud(self, h): self.log.append(("hud", h.title))


class FakeRot(RotationSource):
    capabilities = frozenset({Capability.ROTATE})

    def __init__(self):
        self.passthrough = None
        self.duck = []

    def start(self, emit): ...
    def stop(self): ...
    def set_passthrough(self, on): self.passthrough = on
    def set_duck(self, f): self.duck.append(f)
    def level(self): return 0.5


class FakeSrc(InputSource):
    def __init__(self, caps):
        self.capabilities = frozenset(caps)

    def start(self, emit): ...
    def stop(self): ...


# Tests count wheel positions, so they pin their own order instead of following
# whatever the user put in config.toml.
TEST_WHEEL = ["volume", "switcher", "scroll", "zoom", "undo", "desktops", "tabs", "voice"]


def make(caps=(Capability.CLICKS, Capability.HOLD)):
    cfg, _ = config_mod.load(platform="windows")    # same expectations on every CI runner
    cfg["wheel"]["items"] = list(TEST_WHEEL)
    rot = FakeRot()
    out, ui = FakeOut(), FakeUI()
    e = Engine(cfg, out, ui, [rot, FakeSrc(caps)])
    return e, out, ui, rot


def ev(kind, delta=0):
    return InputEvent(kind, delta, "test")


def test_starts_on_volume_with_passthrough():
    e, out, ui, rot = make()
    assert e.tool.id == "volume"
    assert rot.passthrough is True


def test_double_opens_wheel_rotate_click_selects():
    e, out, ui, rot = make()
    e.handle(ev(Kind.DOUBLE))
    assert e.state == State.WHEEL and rot.passthrough is False
    e.handle(ev(Kind.ROTATE, 2))
    e.handle(ev(Kind.CLICK))
    assert e.tool.id == "scroll" and e.state == State.TOOL
    assert rot.passthrough is False          # scroll consumes rotation
    e.handle(ev(Kind.ROTATE, 1))
    time.sleep(0.4)                          # smooth scroll delivers over a few frames
    assert 0.8 < sum(n for k, n in out.log if k == "scroll") <= 1.2


def test_wheel_wraps_backwards():
    e, *_ = make()
    e.handle(ev(Kind.DOUBLE))
    e.handle(ev(Kind.ROTATE, -1))
    assert e.wheel_ids[e.index] == "voice"


def test_hold_closes_open_wheel():
    e, out, ui, rot = make()
    e.handle(ev(Kind.DOUBLE))
    e.handle(ev(Kind.ROTATE, 3))
    e.handle(ev(Kind.HOLD))
    assert e.state == State.TOOL and e.tool.id == "volume" and rot.passthrough is True


def test_one_shot_runs_and_keeps_tool():
    e, out, *_ = make()
    e.handle(ev(Kind.DOUBLE))
    e.handle(ev(Kind.ROTATE, -1))   # voice
    e.handle(ev(Kind.CLICK))
    assert ("keys", "win+h") in out.log and e.tool.id == "volume"


def test_timeout_selects_sticky_but_never_fires_action():
    e, out, *_ = make()
    e.handle(ev(Kind.DOUBLE))
    e.handle(ev(Kind.ROTATE, 1))     # switcher
    e._wheel_last = time.monotonic() - 99
    e.tick()
    assert e.tool.id == "switcher"
    e.handle(ev(Kind.DOUBLE))
    e.handle(ev(Kind.ROTATE, -2))    # voice (one-shot)
    e._wheel_last = time.monotonic() - 99
    e.tick()
    assert e.tool.id == "switcher" and ("keys", "win+h") not in out.log


def test_double_opens_and_closes_wheel_from_any_tool():
    e, out, *_ = make()
    for tool in ("volume", "zoom", "scroll"):
        e.set_tool(tool)
        e.handle(ev(Kind.DOUBLE))
        assert e.state == State.WHEEL
        e.handle(ev(Kind.DOUBLE))
        assert e.state == State.TOOL and e.tool.id == tool
    assert not [x for x in out.log if x[0] == "media"]   # double never leaks to the player


def test_triple_flips_last_tool():
    e, *_ = make()
    e.set_tool("zoom")
    e.handle(ev(Kind.TRIPLE))
    assert e.tool.id == "volume"


def test_volume_tool_media_gestures():
    e, out, *_ = make()
    e.handle(ev(Kind.CLICK))
    e.handle(ev(Kind.TRIPLE))
    assert [x for x in out.log if x[0] == "media"] == [("media", "play_pause"), ("media", "next")]


def test_switcher_holds_alt_and_commits_on_click():
    e, out, *_ = make()
    e.set_tool("switcher")
    e.handle(ev(Kind.ROTATE, 1))
    e.handle(ev(Kind.ROTATE, 1))
    e.handle(ev(Kind.ROTATE, -1))
    assert out.log == [("down", "alt"), ("keys", "tab"), ("keys", "tab"), ("keys", "shift+tab")]
    e.handle(ev(Kind.CLICK))
    assert out.log[-1] == ("up", "alt")


def test_switcher_releases_alt_when_wheel_opens():
    e, out, *_ = make()
    e.set_tool("switcher")
    e.handle(ev(Kind.ROTATE, 1))
    e.handle(ev(Kind.DOUBLE))
    assert ("up", "alt") in out.log


def test_hold_opens_claude_centres_it_and_starts_voice_typing():
    e, out, *_ = make()
    e.handle(ev(Kind.HOLD))
    time.sleep(0.5)                       # list with wait/center runs on a background thread
    assert e.state == State.TOOL
    assert out.log == [("keys", "ctrl+alt+v"), ("center", "Claude"), ("keys", "win+h")]


def test_no_hold_source_still_opens_with_double():
    e, *_ = make(caps=(Capability.CLICKS,))
    assert e.open_with == {"double"}
    e.handle(ev(Kind.DOUBLE))
    assert e.state == State.WHEEL


def test_hold_only_config_falls_back_to_triple():
    cfg, _ = config_mod.load(platform="windows")
    cfg["gestures"]["open_wheel"] = ["hold"]
    e = Engine(cfg, FakeOut(), FakeUI(), [FakeRot(), FakeSrc((Capability.CLICKS,))])
    assert e.open_with == {"triple"}


def test_press_release_quick_select():
    e, *_ = make(caps=(Capability.CLICKS, Capability.PRESS_RELEASE))
    e.handle(ev(Kind.PRESS))
    e.handle(ev(Kind.ROTATE, 3))
    assert e.state == State.WHEEL
    e.handle(ev(Kind.RELEASE))
    assert e.state == State.TOOL and e.tool.id == "zoom"


def test_bad_config_rejected():
    cfg, _ = config_mod.load(platform="windows")
    cfg["tools"]["x"] = {"type": "keys", "rotate_cw": "teleport:mars"}
    with pytest.raises(ValueError):
        config_mod.validate(cfg)



def test_wheel_moves_further_on_fast_reports_but_stays_exact_slow_and_on_turn_back(monkeypatch):
    """Calibration: the buds drop clicks between reports when spun fast, so reports at
    their max rate (~0.35 s apart) move 2 items; slow clicks and turn-backs move 1."""
    import orbit.core.motion as motion
    e, *_ = make()
    e.wheel_accel = 2                      # opt-in (wheel.accel)
    e.handle(ev(Kind.DOUBLE))
    moved = []
    for d, t in [(1, 100.0), (1, 101.5), (1, 101.85), (1, 102.2), (-1, 102.55), (-1, 104.0)]:
        monkeypatch.setattr(motion.time, "monotonic", lambda t=t: t)
        before = e.index
        e.handle(ev(Kind.ROTATE, d))
        moved.append((e.index - before + 4) % len(e.wheel_ids) - 4)
    assert moved == [1, 1, 2, 2, -1, -1]


def test_wheel_is_one_item_per_click_by_default(monkeypatch):
    """Two controlled clicks ~0.45 s apart must not skip an item."""
    import orbit.core.motion as motion
    e, *_ = make()
    e.handle(ev(Kind.DOUBLE))
    start = e.index
    for t in (100.0, 100.45, 100.8):
        monkeypatch.setattr(motion.time, "monotonic", lambda t=t: t)
        e.handle(ev(Kind.ROTATE, 1))
    assert e.index == (start + 3) % len(e.wheel_ids)


def test_slides_one_slide_per_click_even_fast_and_press_blacks_out():
    e, out, ui, rot = make()
    e.set_tool("slides")
    for _ in range(4):                       # a fast spin: still exactly one slide each
        e.handle(ev(Kind.ROTATE, 1))
    e.handle(ev(Kind.ROTATE, -1))
    keys = [c for k, c in out.log if k == "keys"]
    assert keys == ["right"] * 4 + ["left"]
    e.handle(ev(Kind.CLICK))
    assert out.log[-1] == ("keys", "b")


def test_timeline_pans_the_view_sideways_and_press_plays():
    """Resolve feedback: the dial should slide the timeline view, not move the playhead."""
    e, out, ui, rot = make()
    e.set_tool("scrub")
    assert e.tool.horizontal
    hud = e.tool.rotate(e, 1)
    assert hud.detail.startswith("later")
    time.sleep(0.4)                          # smooth scroll delivers over a few frames
    assert sum(n for k, n in out.log if k == "scroll") > 0.8
    assert not any(k == "keys" for k, _ in out.log)      # no arrow keys: the playhead stays
    e.handle(ev(Kind.CLICK))
    assert out.log[-1] == ("keys", "space")


def test_off_steps_aside_presses_go_to_music_and_dial_is_volume():
    e, out, ui, rot = make()
    e.set_tool("scroll")
    e.handle(ev(Kind.DOUBLE))                       # wheel open...
    e.set_paused(True)                              # ...turning Orbit off closes it
    assert e.state == State.TOOL and rot.passthrough is True
    e.handle(ev(Kind.ROTATE, 1))
    assert not [k for k, _ in out.log if k == "scroll"]
    for k in (Kind.CLICK, Kind.DOUBLE, Kind.TRIPLE):
        e.handle(ev(k))
    assert [c for k, c in out.log if k == "media"][-3:] == ["play_pause", "next", "previous"]
    assert e.state == State.TOOL                    # double never opened the wheel
    e.set_paused(False)
    assert rot.passthrough is False                 # scroll consumes rotation again
    e.handle(ev(Kind.DOUBLE))
    assert e.state == State.WHEEL
