"""Spin sensing, smooth scroll and wheel ducking."""
import time

from orbit.core.engine import Engine, State
from orbit.core.events import InputEvent, Kind
from orbit.core.motion import SpinTracker
from orbit.core.tools import SmoothScrollTool
from tests.test_engine import FakeOut, ev, make


def test_slow_clicks_stay_exact():
    s = SpinTracker()
    t = 100.0
    for _ in range(5):
        s.update(1, t)
        t += 0.8
    assert s.gain(8) == 1.0


def test_flick_is_fast_from_second_report():
    """Real log: a quick flick arrives as 2-3 reports ~0.32-0.4 s apart."""
    s = SpinTracker()
    s.update(1, 100.0)                 # first of a flick looks slow (after a pause)
    assert s.gain(8) == 1.0
    s.update(1, 100.35)
    assert s.gain(8) == 8.0 and s.catch_up
    s.update(1, 100.70)
    assert s.gain(8) == 8.0 and not s.catch_up
    assert s.momentum > 0.6


def test_folded_double_report_counts_as_fast():
    s = SpinTracker()
    s.update(1, 100.0)
    s.update(2, 101.0)          # slow gap, but the firmware folded two detents
    assert s.intensity > 0


def test_reverse_resets_streak():
    s = SpinTracker()
    t = 100.0
    for _ in range(5):
        s.update(1, t)
        t += 0.3
    s.update(-1, t)
    assert s.streak <= 1 and s.gain(8) < 3


class _E:
    def __init__(self):
        self.out = FakeOut()


def _scrolled(tool, deltas, gap):
    e = _E()
    tool.enter(e)
    for d in deltas:
        tool.rotate(e, d)
        time.sleep(gap)
    time.sleep(1.2)
    tool.leave(e)
    return sum(n for k, n in e.out.log if k == "scroll")


def test_fast_spin_scrolls_further_than_slow():
    slow = _scrolled(SmoothScrollTool("s", {}), [1] * 4, 0.75)
    fast = _scrolled(SmoothScrollTool("s", {}), [1] * 4, 0.33)
    assert 3.5 < slow < 4.8            # careful clicks ~ 1 notch each
    assert fast > slow * 1.4           # faster turning goes further...
    assert fast < slow * 3.2           # ...but stays the same page, not a jump


def test_speed_builds_gradually_and_ignores_one_quick_click():
    """Mac test gaps (s): normal turning varies 0.3-0.6 from click to click. The
    distance per click must change smoothly, not swing 2x <-> 8x."""
    tool = SmoothScrollTool("s", {})
    tool.pace._dir = tool._dir = 1
    gains = []
    for gap in (0.54, 0.43, 0.63, 0.30, 0.55, 0.45):
        tool.pace._t = time.monotonic() - gap
        tool.rotate(_E(), 1)
        gains.append(1 + (tool.max_gain - 1) * tool.pace.speed ** 2)
    tool.leave(_E())
    span = tool.max_gain - 1            # limits scale with the configured top speed
    steps = [abs(b - a) for a, b in zip(gains, gains[1:])]
    assert max(steps) < 0.23 * span, gains          # no jump between neighbouring clicks
    assert max(gains) < 1 + 0.6 * span, gains       # normal turning never reaches top speed


def test_reverse_brakes_momentum():
    tool, e = SmoothScrollTool("s", {}), _E()
    tool.enter(e)
    for _ in range(4):
        tool.rotate(e, 1)
        time.sleep(0.33)
    mark = len(e.out.log)
    tool.rotate(e, -1)                 # turn back mid-glide
    time.sleep(1.0)
    tool.leave(e)
    after = [n for k, n in e.out.log[mark:] if k == "scroll"]
    assert all(n < 0 for n in after)   # no forward glide survives the reversal
    assert -1.3 < sum(after) < -0.7    # and the correction is one precise click


class _BrightOut(FakeOut):
    def __init__(self):
        super().__init__()
        self.level = 40.0
        self.writes = []

    def brightness_get(self):
        return self.level

    def brightness_set(self, v):
        time.sleep(0.1)                # DDC/CI is slow
        self.writes.append(v)


def test_brightness_steps_clamps_and_coalesces():
    from orbit.core.tools import BrightnessTool
    t, e = BrightnessTool("b", {"step": 5}), _E()
    e.out = _BrightOut()
    t.enter(e)
    time.sleep(0.05)
    h = t.rotate(e, 1)
    assert h.detail == "45%" and abs(h.progress - 0.45) < 1e-9
    for _ in range(30):                # a burst far past 100
        t.rotate(e, 1)
    time.sleep(0.5)
    assert e.out.writes[-1] == 100     # clamped, newest value wins
    assert len(e.out.writes) < 10      # slow writes coalesced, no backlog


def test_wheel_ducks_and_restores():
    e, out, ui, rot = make()
    e.handle(ev(Kind.DOUBLE))
    assert rot.duck[-1] == 0.5 and rot.passthrough is False
    e.handle(ev(Kind.CLICK))           # back to volume
    assert rot.duck[-1] is None and rot.passthrough is True
    e.handle(ev(Kind.DOUBLE))
    e.handle(ev(Kind.DOUBLE))            # cancel also restores
    assert rot.duck[-1] is None


def test_scrub_steps_frames_when_careful_and_jumps_when_fast():
    from orbit.core.tools import ScrubTool
    t, e = ScrubTool("scrub", {}), _E()
    now = [100.0]

    def turn(d, gap):
        now[0] += gap
        t.pace._t = now[0] - gap
        import orbit.core.motion as m
        real = m.time.monotonic
        m.time.monotonic = lambda: now[0]
        try:
            t.rotate(e, d)
        finally:
            m.time.monotonic = real

    for _ in range(3):
        turn(1, 0.8)                            # careful: one frame each
    for _ in range(6):
        turn(1, 0.3)                            # fast: becomes jumps once the pace builds
    turn(-1, 0.3)                               # turn back: always one frame
    keys = [c for k, c in e.out.log if k == "keys"]
    assert keys[:3] == ["right"] * 3
    assert "shift+right" in keys[3:9] and keys[3] == "right"      # no jump on the first quick click
    assert keys[-1] == "left"
