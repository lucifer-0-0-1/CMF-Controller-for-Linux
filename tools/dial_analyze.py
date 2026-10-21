"""Analyze a dial_record.py capture.

    python tools/dial_analyze.py [tools/calib/<file>.jsonl]   (newest if omitted)

Per phase: physical clicks reported by the buds (AVRCP CHANGED, in steps of their
own grid), what Windows reported, timing between reports, latency from the buds'
packet to Windows' callback, and what happened around our own recenters.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

GRID = 16


def k_of(u: int) -> float:
    return u * GRID / 127


def main():
    files = sorted((Path(__file__).parent / "calib").glob("dial-*.jsonl"))
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else files[-1]
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    print(path.name, len(recs), "records")

    # grid check across all buds values
    vals = Counter(r["v"] for r in recs if r["src"] == "bt" and r.get("kind") == "changed")
    print("buds values seen:", dict(sorted(vals.items())))
    for n in (14, 15, 16, 17, 20, 25, 32):
        on = sum(c for v, c in vals.items() if any(round(k * 127 / n) == v for k in range(n + 1)))
        print(f"  grid {n:2d}: {on}/{sum(vals.values())} values on grid")

    # ETW hands packet times as FILETIME (not our QPC clock): align on the fastest delivery
    # (we force a flush every 50 ms, so the error is under that).
    bts = [r for r in recs if r["src"] == "bt"]
    off = min(r["t"] - r["tc"] for r in bts) if bts else 0.0
    for r in bts:
        r["tc"] += off

    by_phase = defaultdict(list)
    for r in recs:
        if r.get("phase"):
            by_phase[r["phase"]].append(r)
    notes = {r["phase"]: r.get("note") for r in recs if r["src"] == "mark" and r.get("what") == "end"}

    for phase, rs in by_phase.items():
        print("\n" + "=" * 72)
        print(f"{phase}   note: {notes.get(phase)!r}")
        t0 = rs[0]["t"]
        last_bt = None
        bt_steps, win_steps, gaps, lat = [], [], [], []
        last_bt_t = None
        last_win_u = None
        pending = []        # buds CHANGED waiting to be matched to a win report
        for r in rs:
            t = r["t"] - t0
            if r["src"] == "bt" and r["kind"] in ("changed", "setabs", "setabs-ok", "setabs-rej"):
                tc = r["tc"] - t0
                extra = ""
                if r["kind"] == "changed":
                    if last_bt is not None:
                        dk = k_of(r["v"]) - k_of(last_bt)
                        extra = f"  dk={dk:+.2f}"
                        bt_steps.append(round(dk, 2))
                    if last_bt_t is not None:
                        gaps.append(r["tc"] - last_bt_t)
                    last_bt_t = r["tc"]
                    last_bt = r["v"]
                    pending.append(r["tc"])
                elif r["kind"] == "setabs-ok":
                    last_bt = r["v"]
                print(f"  {tc:7.3f}  bt  {r['kind']:<10} {r['v']:3d}  k={k_of(r['v']):5.2f}{extra}")
            elif r["src"] == "win":
                extra = ""
                if last_win_u is not None and not r["ours"]:
                    win_steps.append(round(k_of(r["u"]) - k_of(last_win_u), 2))
                if not r["ours"] and pending:
                    # nearest buds packet before this report
                    cands = [p for p in pending if p <= r["t"] + 0.01]
                    if cands:
                        lat.append(r["t"] - cands[-1])
                        pending = [p for p in pending if p > cands[-1]]
                last_win_u = r["u"]
                print(f"  {t:7.3f}  win {'ours' if r['ours'] else '    '}       {r['u']:3d}  k={k_of(r['u']):5.2f}")
            elif r["src"] == "set":
                print(f"  {t:7.3f}  SET {r['why']:<10} {r['u']:3d}  k={k_of(r['u']):5.2f}")
        print(f"  buds step sizes: {Counter(bt_steps)}")
        print(f"  win  step sizes: {Counter(win_steps)}")
        if gaps:
            print(f"  gap between buds reports: min {min(gaps):.3f}  median {statistics.median(gaps):.3f}  "
                  f"max {max(gaps):.3f}")
        if lat:
            print(f"  buds packet -> windows callback: median {statistics.median(lat) * 1000:.0f} ms  "
                  f"max {max(lat) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
