#!/usr/bin/env python3
"""Guided hands-on test of Orbit on macOS with the CMF Buds Pro 2.

Walks the tester through each check, slices ~/.orbit/orbit.log per step,
takes screenshots, and writes everything to mac_test_report/<timestamp>/.
Stdlib only:  python3 tools/mac_guided_test.py
"""
import datetime
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "dist" / "Orbit.app"
LOG = Path.home() / ".orbit" / "orbit.log"
OUT = ROOT / "mac_test_report" / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

B, G, Y, R, D, X = "\033[1m", "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
report = []


def say(msg=""):
    print(msg, flush=True)


def header(n, title):
    say(f"\n{B}━━━ {n}. {title} ━━━{X}")
    report.append(f"\n## {n}. {title}\n")


def step(text):
    say(f"  {Y}▶{X} {text}")


def wait(prompt="Press Enter when ready"):
    input(f"  {D}{prompt} ⏎{X} ")


def ask(question, choices="y/n"):
    ans = input(f"  {B}?{X} {question} [{choices}] ").strip()
    report.append(f"- **{question}** → {ans or '(no answer)'}")
    return ans


def note(question):
    ans = input(f"  {B}?{X} {question} (Enter to skip) ").strip()
    if ans:
        report.append(f"- **{question}** → {ans}")
    return ans


def clock(line):
    h, m, s = line.split()[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def log_pos():
    return LOG.stat().st_size if LOG.exists() else 0


def log_since(pos):
    if not LOG.exists():
        return []
    with open(LOG, "rb") as f:
        f.seek(pos)
        return f.read().decode("utf-8", "replace").splitlines()


def keep_log(label, lines, pattern=None):
    picked = [l for l in lines if not pattern or re.search(pattern, l)]
    report.append(f"\n<details><summary>log: {label} ({len(picked)} lines)</summary>\n\n```\n"
                  + "\n".join(picked) + "\n```\n</details>")
    errs = [l for l in lines if re.search(r" E |Traceback|Error|Exception", l)]
    if errs:
        say(f"  {R}! {len(errs)} error line(s) in the log during this step{X}")
        report.append("\n**Errors during this step:**\n```\n" + "\n".join(errs) + "\n```")
    return picked


def screenshot(name, delay):
    path = OUT / f"{name}.png"
    for s in range(delay, 0, -1):
        print(f"\r  📸 screenshot in {s}… ", end="", flush=True)
        time.sleep(1)
    r = subprocess.run(["screencapture", "-x", str(path)], capture_output=True, text=True)
    ok = r.returncode == 0 and path.exists() and path.stat().st_size > 0
    if not ok:
        # no Screen Recording permission for this terminal: let the tester take it
        say(f"\r  {Y}📸 Take it yourself now: ⌘⇧4, then Space, then click the window/wheel "
            f"(for the menu bar: ⌘⇧4 and drag a box around the icon).{X}")
        wait("Press Enter once the screenshot is saved")
        loc = subprocess.run(["defaults", "read", "com.apple.screencapture", "location"],
                             capture_output=True, text=True).stdout.strip() or "~/Desktop"
        shots = sorted(Path(os.path.expanduser(loc)).glob("Screenshot*.png"), key=lambda p: p.stat().st_mtime)
        if shots and time.time() - shots[-1].stat().st_mtime < 120:
            path.write_bytes(shots[-1].read_bytes())
            ok = True
    say(f"\r  {G}📸 saved {path.name}{X}      " if ok else f"\r  {R}screenshot not found{X}")
    report.append(f"- screenshot: `{path.name}`" if ok else f"- screenshot {name}: missing")


def orbit_pids():
    r = subprocess.run(["pgrep", "-f", "Orbit.app/Contents/MacOS/Orbit"], capture_output=True, text=True)
    return [p for p in r.stdout.split()]


def restart_orbit():
    subprocess.run(["pkill", "-f", "Orbit.app/Contents/MacOS/Orbit"])
    for _ in range(20):
        if not orbit_pids():
            break
        time.sleep(0.25)
    pos = log_pos()
    subprocess.run(["open", "-n", str(APP), "--args", "--debug"])
    for _ in range(40):
        lines = log_since(pos)
        if any("Orbit running" in l for l in lines):
            return lines
        time.sleep(0.25)
    return log_since(pos)


def preflight():
    header(0, "Setup")
    if not APP.exists():
        sys.exit(f"{R}{APP} not found — build it first: bash packaging/mac/build_app.sh{X}")
    OUT.mkdir(parents=True, exist_ok=True)
    while True:
        step("Restarting Orbit (debug mode)…")
        lines = restart_orbit()
        bound = next((l for l in lines if "rotation bound to" in l), None)
        ax_missing = any("Accessibility permission missing" in l for l in lines)
        say(f"  {'✅' if bound else '❌'} dial source: {bound.split('orbit.volume: ')[-1] if bound else 'buds not found'}")
        say(f"  {'❌' if ax_missing else '✅'} Accessibility: {'MISSING' if ax_missing else 'granted'}")
        if bound and not ax_missing:
            report.append(f"- Orbit started, {bound.split('orbit.volume: ')[-1]}, Accessibility granted")
            return
        if not bound:
            step("Connect the CMF Buds Pro 2 and set them as the Mac's sound output.")
        if ax_missing:
            step("System Settings › Privacy & Security › Accessibility:")
            say(f"      remove any old 'Orbit' entry (−), then + › ⌘⇧G › {APP} › switch ON")
            subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
        wait("Press Enter to retry")


def test_clicks():
    header(1, "Click counting (most important)")
    say("  Each round resets the volume to 50%, then captures from the moment the instruction appears.")
    say("  Count the clicks you feel. Keep your hands off the dial between rounds. macOS's volume HUD is expected.")
    rounds = [("slow_up", "Turn the dial SLOWLY up, 8 clicks (about 1 per second)", 8),
              ("slow_down", "Turn the dial SLOWLY down, 8 clicks", 8),
              ("fast_up", "Spin the dial FAST up, about 10 clicks", 10)]
    for key, text, expected in rounds:
        say(f"\n  {B}Round: {key}{X}")
        # start mid-scale so 8 clicks can't hit 0% / 100% and get swallowed
        subprocess.run(["osascript", "-e", "set volume output volume 50"])
        time.sleep(1.5)
        pos = log_pos()
        step(f"{text} — start now.")
        wait("Press Enter when you've finished turning")
        time.sleep(0.5)
        lines = log_since(pos)
        stamped = [(clock(l), float(m.group(1))) for l in lines if (m := re.search(r"mac\s+vol=\s*([\d.]+)", l))]
        vols = [v for _, v in stamped]
        # CoreAudio fires several callbacks per change; a burst = reports within 100 ms of each other
        bursts = sum(1 for i, (t, _) in enumerate(stamped) if i == 0 or t - stamped[i - 1][0] > 0.1)
        deltas = [int(m.group(1)) for l in lines if (m := re.search(r"delta=([+-]\d+)", l))]
        distinct = [v for i, v in enumerate(vols) if i == 0 or v != vols[i - 1]]
        steps_ = sorted({round(abs(b - a), 4) for a, b in zip(distinct, distinct[1:])})
        felt = input(f"  {B}?{X} How many clicks did you actually feel? [{expected}] ").strip() or str(expected)
        summary = (f"felt={felt} · counted delta sum={sum(deltas):+d} over {len(deltas)} deltas · "
                   f"{bursts} report bursts ({len(vols)} callbacks), {len(distinct)} distinct levels · "
                   f"level steps seen={steps_}")
        say(f"  {G}→ {summary}{X}")
        report.append(f"\n**{key}** — {summary}\n\nlevels: {distinct}")
        keep_log(key, lines, r"mac\s+vol=|delta=|orbit\.engine:")


def test_scroll():
    header(2, "Scroll")
    step("Open a long Safari page (or a Finder list) and put the mouse pointer over it.")
    wait()
    pos = log_pos()
    step("Double-press the bud → the wheel opens. Turn to 'Scroll' and press once to pick it.")
    step("Now turn the dial up and down a few clicks over the page.")
    wait("Press Enter when done")
    keep_log("scroll", log_since(pos), r"orbit\.|scroll|Traceback")
    ask("Which app did you test in?", "Safari/Finder/other")
    ask("Did the page scroll?")
    ask("Was it smooth (not jumpy)?")
    ask("Dial UP moved the page content which way?", "up/down/none")
    ask("Is that the direction you'd expect?")
    note("Anything odd?")
    step("Switch back to the Volume tool (double-press › Volume › press) before continuing.")
    wait()


def test_look():
    header(3, "Wheel look (Dark / Light)")
    for mode in ("Dark", "Light"):
        step(f"Menu-bar Orbit icon › Settings… › Look › Appearance = {mode}, Save, close the window.")
        wait()
        step("When the countdown starts, DOUBLE-PRESS the bud and turn ONE click so an item is selected.")
        wait("Press Enter to start the countdown")
        screenshot(f"wheel_{mode.lower()}", 5)
        ask(f"{mode}: does the selected item light up the disc around it, with no bar?")
        step("Dismiss the wheel (press, or wait for it to close).")
        wait()


def test_settings():
    header(4, "Settings window")
    step("Menu-bar Orbit icon › Settings…  — leave it open and visible.")
    wait("Press Enter to start the countdown")
    screenshot("settings_window", 3)
    step("In Settings: turn one wheel item OFF, move another item up/down, change 'Double press', then Save.")
    wait()
    pos = log_pos()
    step("Double-press the bud (or do your new double-press action) to check the wheel.")
    wait("Press Enter when done")
    keep_log("settings", log_since(pos), r"orbit\.|Traceback")
    ask("Did the wheel/double-press change WITHOUT restarting Orbit?")
    screenshot("wheel_after_settings", 0) if ask("Take a screenshot of the wheel now? (open it first)") == "y" else None
    step("Put Settings back how you like them (re-enable the item, restore Double press = wheel), Save.")
    wait()


def test_shortcuts():
    header(7, "Custom shortcut item + Claude Quick Entry field")
    step("Settings… › Shortcuts › add an item: name 'Screenshot', click the key field and press ⌘⇧4. Save.")
    wait()
    ask("Did the key field show Cmd+Shift+4 (not Ctrl+Shift+4)?")
    step("Open Finder (or any app) so it's frontmost.")
    wait()
    pos = log_pos()
    step("Double-press › turn to 'Screenshot' › press. The screenshot crosshair should appear (Esc to cancel).")
    wait("Press Enter when done")
    keep_log("shortcut", log_since(pos), r"orbit\.|Traceback")
    ask("Did the ⌘⇧4 crosshair appear?")
    step("Settings… › Claude › click the Quick Entry field and press ⌥Space (or your shortcut).")
    wait()
    ask("Did it record exactly what you pressed (Cmd shown as Cmd, Option as Option)?")
    note("What did the field show?")
    step("Remove the test 'Screenshot' item if you don't want it, Save.")
    wait()


def test_icons():
    header(8, "Icons + Settings preview")
    step("Look at Orbit's icon in the menu bar.")
    ask("Is it a plain black/white icon like the other menu-bar icons (not coloured)?")
    screenshot("menubar_icon", 0)
    subprocess.run(["touch", str(APP)])
    subprocess.run(["open", "-R", str(APP)])
    step("A Finder window opened with Orbit.app selected.")
    ask("Does Finder show the Orbit mark (not a generic app/Python icon)?")
    screenshot("finder_icon", 0)
    step("Menu-bar Orbit icon › Settings… — look at the wheel preview on the left.")
    wait()
    ask("Are the icons small (~20 pt), evenly spaced round the ring, and the centre text readable (not covered)?")
    screenshot("settings_preview", 0)


def test_slides():
    header(9, "Slides tool")
    for app in ("Keynote", "PowerPoint / Google Slides in Safari"):
        if ask(f"Test {app} now?") != "y":
            continue
        step(f"Open a deck with 8+ slides in {app} and START THE SLIDESHOW (Keynote: ⌥⌘P; Google Slides: ⌘⏎).")
        wait()
        pos = log_pos()
        step("Double-press › turn to 'Slides' (last on the wheel) › press.")
        step("Turn 5 clicks FORWARD (any speed), then 2 clicks BACK.")
        wait("Press Enter when done")
        ask(f"{app}: did it move exactly 5 slides forward, then exactly 2 back?")
        step("Single-press → screen should go black. Single-press again → slide comes back.")
        wait("Press Enter when done")
        keep_log(f"slides_{app.split()[0].lower()}", log_since(pos), r"orbit\.engine:|orbit\.out|keys|Traceback")
        ask(f"{app}: did press toggle black screen on and off?")
        note(f"{app}: anything odd?")
    step("Leave the slideshow (Esc) and switch Orbit back to Volume (double-press › Volume › press).")
    wait()


def test_timeline():
    header(10, "Timeline tool (DaVinci Resolve / Final Cut)")
    step("Open DaVinci Resolve (or Final Cut) with a clip on the timeline; click the timeline once so it has focus.")
    wait()
    pos = log_pos()
    step("Double-press › turn to 'Timeline' › press.")
    step("Turn 3 SLOW careful clicks forward, then ONE quick click, then a FAST spin.")
    wait("Press Enter when done")
    ask("Did each slow click move exactly 1 frame?")
    ask("Was the single quick click still just 1 frame (not a jump)?")
    ask("Did the fast spin jump (Resolve ~1 s, FCP ~10 frames per click)?")
    step("Single-press → play. Single-press again → pause.")
    wait("Press Enter when done")
    keep_log("timeline", log_since(pos), r"orbit\.engine:|keys|Traceback")
    ask("Did press toggle play/pause?")
    note("Timeline: anything odd?")


def test_camera():
    header(11, "Camera tool (Photo Booth)")
    step("Settings… › turn the 'Camera' wheel item ON, Save.")
    step("Open Photo Booth.")
    wait()
    pos = log_pos()
    step("Double-press › turn to 'Camera' › press. Then single-press once more.")
    wait("Press Enter when done")
    keep_log("camera", log_since(pos), r"orbit\.engine:|keys|Traceback")
    ask("Did a press take a photo (countdown + flash)?")
    note("Camera: anything odd?")


def test_scroll_sliders():
    header(12, "Settings › Scroll sliders")
    step("Switch Orbit to Scroll (double-press › Scroll › press) and scroll a Safari page — note the feel.")
    wait()
    step("Settings… › Scroll: move 'fast-turn speed' a lot higher and 'distance per click' higher, Save.")
    step("Scroll the same page again (no restart).")
    wait("Press Enter when done")
    ask("Did the feel change right away, without restarting Orbit?")
    step("Put the sliders back where you like them (default fast-turn = 4.5×), Save.")
    wait()
    note("Sliders: anything odd?")


def test_open_app():
    header(13, "Open an app from a press gesture")
    step("Settings… › Dial › Triple press = 'Open an app…' › Spotify (quit Spotify first). Save.")
    wait()
    pos = log_pos()
    step("Triple-press the bud.")
    wait("Press Enter when done")
    keep_log("open_app", log_since(pos), r"orbit\.engine:|launch|open|Traceback")
    ask("Did Spotify launch?")
    step("Set Triple press back to what you had before, Save.")
    wait()


def test_gestures():
    header(5, "Gestures + now-playing (Spotify / Music)")
    step("Make sure the Volume tool is active, and PAUSE Spotify (in the Spotify app, not with the bud).")
    wait()
    say("  Loop 3 times: press → music plays · wait 1 s · double → wheel opens · press to close it · press → music pauses")
    for i in range(1, 4):
        pos = log_pos()
        step(f"Round {i}: single-press (play) … wait 1 s … double-press")
        wait("Press Enter once you've done the double-press")
        owner = now_playing()
        ask(f"Round {i}: did Spotify start AND did the wheel open on the double-press?")
        step("Press once to close the wheel, then single-press again to pause Spotify.")
        wait("Press Enter when done")
        report.append(f"- round {i}: now-playing owner after double = `{owner}`")
        keep_log(f"spotify_round{i}", log_since(pos), r"orbit\.engine:|orbit\.media|media:|reassert|Traceback")
        ask(f"Round {i}: did Spotify pause?")
    gestures = {}
    try:
        import json
        gestures = json.loads((Path.home() / "Library/Application Support/Orbit/settings.json").read_text()).get("gestures", {})
    except Exception:
        pass
    pos = log_pos()
    step(f"TRIPLE-press the bud (your setting: {gestures.get('triple', 'previous tool')}).")
    wait("Press Enter when done")
    keep_log("triple", log_since(pos), r"orbit\.engine:|orbit\.media|Traceback")
    ask("Did triple-press do what your setting says?")
    note("Anything else odd with gestures?")


def now_playing():
    r = subprocess.run(["nowplaying-cli", "get-raw"], capture_output=True, text=True)
    m = re.search(r'ClientBundleIdentifier" : "([^"]+)"', r.stdout)
    return m.group(1) if m else (r.stderr.strip() or "unknown")


def test_hud():
    header(6, "System UI")
    step("Turn the dial a couple of clicks and watch the screen.")
    wait()
    ask("Was macOS's own volume HUD the ONLY system UI that appeared?")
    note("Describe anything else that appeared")


def write_report(finished):
    md = OUT / "report.md"
    md.write_text("# Orbit macOS guided test\n\n"
                  f"{datetime.datetime.now():%Y-%m-%d %H:%M} · {APP}\n" + "\n".join(report) + "\n")
    if finished:
        say(f"\n{G}{B}All done!{X} Report: {md}\n  Tell Claude \"done\" and it will send the results over.")
    else:
        say(f"\n{Y}Stopped early — partial report saved:{X} {md}")


TESTS = [("1", "Click counting", test_clicks), ("2", "Scroll", test_scroll), ("3", "Wheel look", test_look),
         ("4", "Settings window", test_settings), ("5", "Gestures", test_gestures), ("6", "System UI", test_hud),
         ("7", "Shortcuts", test_shortcuts), ("8", "Icons + Settings preview", test_icons),
         ("9", "Slides", test_slides), ("10", "Timeline", test_timeline), ("11", "Camera", test_camera),
         ("12", "Scroll sliders", test_scroll_sliders), ("13", "Open app gesture", test_open_app)]

if __name__ == "__main__":
    say(f"{B}Orbit · Mac guided test{X}   {D}(Ctrl-C any time — progress so far is still saved){X}")
    finished = False
    try:
        preflight()
        valid = {num for num, _, _ in TESTS}
        say("\n" + "\n".join(f"    {num}. {name}" for num, name, _ in TESTS))
        while True:
            pick = input(f"  Run which tests? [Enter or 'all' = all, or e.g. 1 2 5] ").replace(",", " ").lower().split()
            if pick in ([], ["all"]):
                pick = []
                break
            if set(pick) <= valid:
                break
            say(f"  {R}Didn't understand that — type test numbers like 1 2 5, or just press Enter.{X}")
        for num, _, fn in TESTS:
            if not pick or num in pick:
                fn()
        finished = True
    except KeyboardInterrupt:
        say(f"\n{Y}Stopped early.{X}")
        report.append("\n_(stopped early)_")
    finally:
        if OUT.exists():
            write_report(finished)
