"""Replay a dial_record.py capture through VolumeDial and compare with the buds' own packets.

    python tools/dial_replay.py [tools/calib/<file>.jsonl]

Ground truth per phase = grid steps between consecutive buds levels, where our
recenter (and its ~1 ms Windows echo) resets the buds' level. The recorder only
recenters after 1.6 s of quiet, so in a capture this is unambiguous. (The AVRCP
packets agree wherever ETW didn't drop one.) The replay feeds what Windows
reported, exactly as Orbit sees it, through the real VolumeDial.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orbit.core import volume_dial as vd  # noqa: E402

GRID = 16


class Backend:
    def get_level(self):
        return None

    def set_level(self, level):
        pass


def truth(recs):
    out = defaultdict(list)
    buds = target = None
    for r in recs:
        if r["src"] == "set":
            target = r["u"]
        elif r["src"] == "win" and not r["ours"]:
            if r["u"] == target:
                buds, target = target, None                 # echo of our recenter
                continue
            target = None
            if buds is not None and r["u"] != buds:
                step = round((r["u"] - buds) * GRID / 127)
                if step:
                    out[r["phase"]].append(step)
            buds = r["u"]
    return out


def replay(recs):
    got = defaultdict(list)
    cur = {"phase": None}
    d = vd.VolumeDial(Backend(), lambda ev: got[cur["phase"]].append(ev.delta))
    d._passthrough = False
    for r in recs:
        if r["src"] == "set":
            d._last_set = (r["t"], d._level, r["u"] / 127)
        elif r["src"] == "win":
            cur["phase"] = r["phase"]
            d.on_level(r["level"], r["ours"], now=r["t"])
    return got


def main():
    files = sorted((ROOT / "tools" / "calib").glob("dial-*.jsonl"))
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else files[-1]
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    t, g = truth(recs), replay(recs)
    bad = 0
    for phase in dict.fromkeys(r["phase"] for r in recs if r.get("phase")):
        ok = t[phase] == g[phase]
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {phase:<11} buds {t[phase]}\n{'':16}orbit {g[phase]}")
    print("all phases match" if not bad else f"{bad} phase(s) differ")
    return bad


if __name__ == "__main__":
    sys.exit(main())
