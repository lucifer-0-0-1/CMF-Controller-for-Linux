# CMF Buds Pro 2 dial: calibration (Windows, Oct 2026)

Captured with `tools/dial_record.py`: Windows' endpoint-volume callbacks and the buds'
own AVRCP packets (raw Bluetooth trace) on one clock, while turning in guided patterns.
`tools/dial_analyze.py` prints the timeline; `tools/dial_replay.py` replays a capture
through `VolumeDial` and checks every click against the buds' own reports.

## What the buds send

| | |
|---|---|
| Grid | 16 steps. Raw AVRCP volume = round(k * 127 / 16): 0, 8, 16 ... 64, 71, 79, 87, 95, 103 ... |
| Windows level | exactly raw / 127 |
| Per report | always exactly one step (no folded doubles in 70+ reports) |
| Rate | at most one report every ~0.27-0.45 s while turning; the clicks in between are **dropped**, not queued |
| Loss | spin ~10 clicks -> 3 reports; flick 4 -> 1-3; "2 up, 2 down" fast -> +1, -1 |
| Windows side | re-registers for the next notification within 3 ms, buds answer within ~40 ms: the limit is the buds' firmware |
| Our set | the buds always accept SetAbsoluteVolume (25/25). A value between grid points is rounded; the next click is +-1 from that |
| Echo | every SetMasterVolume of ours is followed ~1 ms later by a not-ours callback with the same level |
| Slow vs fast | deliberate single clicks arrive >= 0.5 s apart; reports < ~0.45 s apart mean "turning faster than the buds report" |

## What Orbit does with it

* Counts clicks on the detected grid (smallest N all recent reports sit on; 16 here).
  The old learned step size drifted toward 1/15 and put recenters between grid points.
* Recenters only to grid points.
* Never counts the echo of its own set as a click.
* A report arriving while a set is fresh is measured from whichever of (our level, the
  buds' old level) makes it one step. This fixes the "+2 then -2" jitter when a click
  crossed a recenter (orbit.log 15:46:20).
* Landing back on the buds' old level right after a recenter is a click (the old
  "stale re-send" rule swallowed it; the buds never re-sent a stale level).
* Wheel: one item per click. `wheel.accel = 2` makes reports at the buds' max rate
  move 2, but two deliberate clicks ~0.45 s apart look the same as a spin with
  dropped clicks, so it skipped items in real use; off by default. Tools (scroll,
  keys, brightness) still scale fast reports via `orbit.core.motion`.

Dropped clicks cannot be recovered on the PC: the information never leaves the buds.
