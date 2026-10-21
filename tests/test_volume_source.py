"""Replays of real dial traces through the shared VolumeDial (platform independent)."""
import pytest

from orbit.core import volume_dial as vd


class FakeBackend:
    def __init__(self, level):
        self.lvl = level
        self.sets = []

    def get_level(self):
        return self.lvl

    def set_level(self, level):
        self.sets.append(level)


def make(level, passthrough=False):
    got = []
    d = vd.VolumeDial(FakeBackend(level), lambda ev: got.append(ev.delta))
    d._level = level
    d._passthrough = passthrough
    return d, got


def dial(d, pct):
    d.on_level(pct / 100, ours=False)


def our_set(d, pct):
    d._set(pct / 100, "test")                 # records the lag window like a real recenter
    d.on_level(pct / 100, ours=True)


def test_15_step_buds_from_off_grid_home_count_single_clicks():
    d, got = make(0.5625)                     # recentered on the old 1/16 grid
    for v in (66.7, 73.3, 80.0):
        dial(d, v)
    assert got == [1, 1, 1]                   # was [+2, +1, +1]


def test_reverse_click_from_off_grid_level_is_not_lost():
    d, got = make(0.5625)
    dial(d, 53.3)                             # -0.47 of a 1/16 step: used to round to 0
    assert got == [-1]


def test_click_landing_on_buds_old_level_after_recenter_counts():
    """Calibration capture: buds at 71/127, we recenter one step down to 64, the
    user clicks up again -> 71. That is a click, not the buds re-sending 71."""
    d, got = make(71 / 127)
    our_set(d, 64 / 127 * 100)
    dial(d, 64 / 127 * 100)                   # Windows echoes our set ~1 ms later
    dial(d, 71 / 127 * 100)
    assert got == [1]


def test_click_in_flight_during_recenter_is_one_step_not_plus2_minus2():
    """orbit.log 15:46:20: buds at 95/127, recenter to 64, Windows echo, then the
    user's click down (87, measured from 95) and a Windows re-apply of ours.
    The old logic emitted +2 then -2 and lost the click."""
    d, got = make(95 / 127)
    our_set(d, 64 / 127 * 100)
    dial(d, 64 / 127 * 100)                   # echo
    dial(d, 87 / 127 * 100)                   # click from their old level
    dial(d, 64 / 127 * 100)                   # Windows puts ours back
    assert got == [-1]


def test_recenters_land_on_the_16_step_grid():
    d, got = make(0.5, passthrough=True)
    for u in (71, 79, 87, 95):
        dial(d, u / 127 * 100)
    assert got == [1, 1, 1, 1] and d.grid == 16
    assert round(d._snap_home(0.53) * 127) == 64      # step 8 of 16 = what the buds send


def test_click_before_buds_take_recenter_counts_once():
    """Real trace 15:23:44: buds at 80, we recenter to 56.2, buds report 86.7 -> was +5."""
    d, got = make(0.80)
    our_set(d, 56.25)
    dial(d, 86.7)
    assert got == [1]


def test_echo_of_our_level_confirms_it():
    d, got = make(0.80)
    our_set(d, 56.25)
    dial(d, 56.3)                             # buds took it
    dial(d, 62.9)                             # next real click
    assert got == [1]


def test_glitch_capped():
    d, got = make(0.20)
    dial(d, 90.0)
    assert got == [vd.MAX_CLICKS]


def test_keyboard_nudge_ignored():
    d, got = make(0.50)
    dial(d, 52.0)
    assert got == []


def test_step_is_learned_and_home_snaps_to_buds_grid():
    d, got = make(0.40)
    for v in (46.67, 53.33, 60.0, 66.67):
        dial(d, v)
    assert abs(d.step - 1 / 15) < 0.002
    assert d._snap_home(0.55) == pytest.approx(8 / 15)


def test_duck_and_restore():
    d, got = make(0.60, passthrough=True)
    d.set_duck(0.5)
    assert d._apply == pytest.approx(5 / 16)  # half, on the grid
    d.set_duck(None)
    assert d._apply == pytest.approx(0.60) and d.level() == pytest.approx(0.60)


def test_click_at_100_percent_counts_toward_the_end_but_repeats_do_not():
    """macOS (Oct 2026 Mac capture): a click at 100% fires a burst of 5 callbacks at
    the unchanged level. Each burst is one click up; repeats within ~5 ms are not."""
    d, got = make(15 / 16, passthrough=True)
    t = 100.0
    d.on_level(1.0, ours=False, now=t)                 # 93.75 -> 100: +1
    for i in range(4):
        d.on_level(1.0, ours=False, now=t + 0.001 * (i + 1))   # its 4 duplicates
    t += 0.7
    for i in range(5):                                 # a click at the top: one burst
        d.on_level(1.0, ours=False, now=t + 0.001 * i)
    t += 0.7
    d.on_level(15 / 16, ours=False, now=t)             # back down
    assert got == [1, 1, -1]


def test_same_level_away_from_the_ends_is_never_a_click():
    d, got = make(0.5, passthrough=True)
    d.on_level(0.5, ours=False, now=10.0)
    d.on_level(0.5, ours=False, now=11.0)
    assert got == []
