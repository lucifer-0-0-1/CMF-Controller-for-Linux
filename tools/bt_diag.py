"""Admin diagnostic: which ETW session setup receives BTHPORT HCI packets (and the dial hold).

Runs three sessions side by side for 25 s:
  A  BTHPORT, level 5, all keywords, paged buffers   (what Orbit did)
  B  same, non-paged buffers                          (EVENT_TRACE_USE_NONPAGED_MEMORY)
  C  BTHPORT, level 4, keywords 0, non-paged          (exactly what WPR's profile does)
Writes tools/bt_diag.txt.
"""
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orbit.platform.windows import etw

OUT = Path(__file__).with_name("bt_diag.txt")
BTHPORT = uuid.UUID("8a1f9517-3a8c-4a9e-a018-4f17a200f277")
ALL = 0xFFFFFFFFFFFFFFFF
lines = []
events, hits = Counter(), Counter()


def p(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def handler(tag):
    def on(data, prov):
        events[tag] += 1
        if b"AT+" in data:
            hits[tag] += 1
            i = data.find(b"AT+")
            p(time.strftime("%H:%M:%S"), tag, data[i:i + 20].split(b"\r")[0])
    return on


setups = {
    "A": dict(providers=[(BTHPORT, 5, ALL)], nonpaged=False),
    "B": dict(providers=[(BTHPORT, 5, ALL)], nonpaged=True),
    "C": dict(providers=[(BTHPORT, 4, 0)], nonpaged=True),
}
sessions = []
for tag, sp in setups.items():
    s = etw.EtwSession(f"OrbitDiag{tag}", sp["providers"], handler(tag), nonpaged=sp["nonpaged"])
    try:
        s.start()
        sessions.append(s)
    except OSError as e:
        p(tag, "failed:", e)
p("LISTENING 25s - hold the dial 2x now, turn once")
time.sleep(25)
for s in sessions:
    s.stop()
p("events:", dict(events))
p("AT hits:", dict(hits))
OUT.write_text("\n".join(lines), encoding="utf-8")
time.sleep(2)
