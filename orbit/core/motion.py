"""Turn-speed sensing tuned to the CMF dial.

The buds rate-limit dial reports to ~1 per 0.32 s, so a quick flick arrives as
just 2-3 reports at that floor, and the first report of any flick looks slow
(it follows a pause). So:

  - a report at (or near) the floor = full speed, immediately, no ramp
  - when the 2nd report of a burst reveals a flick, `catch_up` tells the tool
    to make up the boost the 1st report missed
  - the first report after a direction change stays precise (corrections)
  - `momentum` grows only with sustained same-direction spinning
"""
from __future__ import annotations

import math
import time

FAST_GAP = 0.40    # at or under: the buds are reporting at their max rate = flat-out
SLOW_GAP = 0.70    # at or over: a deliberate single click
STREAK_FULL = 3    # fast reports in a row for full momentum


class Pace:
    """Smoothed turning speed, 0 (careful clicks) .. 1 (faster than the buds report).

    The buds report at most one step every ~0.3 s and drop the clicks in between, so
    normal turning lands anywhere in 0.3-0.8 s and neighbouring gaps differ by chance.
    Speed eases toward the per-gap rate (EMA) instead of jumping with it. A turn-back
    resets it: corrections are exact."""
    FAST_GAP = 0.35
    SLOW_GAP = 0.90
    SMOOTH = 0.35

    def __init__(self):
        self._t = 0.0
        self._dir = 0
        self.speed = 0.0

    def update(self, delta: int, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        gap, self._t = now - self._t, now
        d = 1 if delta > 0 else -1
        raw = min(1.0, max(0.0, (self.SLOW_GAP - gap) / (self.SLOW_GAP - self.FAST_GAP)))
        if d != self._dir:
            self.speed = 0.0
        else:
            self.speed += self.SMOOTH * (raw - self.speed)
        self._dir = d
        return self.speed


class SpinTracker:
    def __init__(self):
        self._t = 0.0
        self._dir = 0
        self.streak = 0
        self.intensity = 0.0   # 0 = careful click, 1 = flat-out
        self.catch_up = False  # this report shows the previous one was part of a flick

    def update(self, delta: int, now: float | None = None) -> float:
        now = time.monotonic() if now is None else now
        gap, self._t = now - self._t, now
        d = 1 if delta > 0 else -1
        reversed_ = d != self._dir
        self._dir = d

        speed = min(1.0, max(0.0, (SLOW_GAP - gap) / (SLOW_GAP - FAST_GAP)))
        if abs(delta) >= 2:          # firmware folded a fast spin into one report
            speed = 1.0
        if reversed_:
            speed = 0.0              # a turn-back is a correction: keep it exact

        self.catch_up = speed > 0 and self.streak == 0 and not reversed_
        self.streak = self.streak + 1 if speed > 0 else 0
        self.intensity = speed
        return speed

    def gain(self, max_gain: float) -> float:
        """1 for careful clicks, up to max_gain for a report at the buds' max rate."""
        return 1.0 + (max_gain - 1.0) * math.pow(self.intensity, 1.2)

    @property
    def momentum(self) -> float:
        """0..1, how much glide a sustained spin has earned."""
        return self.intensity * min(1.0, self.streak / STREAK_FULL)
