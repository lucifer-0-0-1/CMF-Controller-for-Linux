"""Start Orbit at sign-in, already elevated (press-and-hold needs admin).

A Run-key entry would raise a UAC prompt at every sign-in; a scheduled task with
"run with highest privileges" starts elevated silently. Creating it needs admin,
which Orbit has when it offers this. Packaged builds only: a source checkout has
no single executable to point the task at.
"""
from __future__ import annotations

import logging
import subprocess
import sys

log = logging.getLogger("orbit.autostart")
TASK = "Orbit"
NO_WINDOW = 0x08000000


def available() -> bool:
    return bool(getattr(sys, "frozen", False))


def enabled() -> bool:
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK], capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def set_enabled(on: bool) -> bool:
    if on:
        cmd = ["schtasks", "/Create", "/F", "/TN", TASK, "/SC", "ONLOGON", "/RL", "HIGHEST",
               "/DELAY", "0000:10", "/TR", f'"{sys.executable}"']
    else:
        cmd = ["schtasks", "/Delete", "/F", "/TN", TASK]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        log.warning("autostart %s failed: %s", "on" if on else "off", (r.stderr or r.stdout).strip())
        return False
    log.info("start with Windows: %s", "on" if on else "off")
    return True
