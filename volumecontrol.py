
#!/usr/bin/env python3
"""Diagnostic: observe system-volume changes while using the CMF dial."""

import re
import subprocess
import time


def get_volume():
    result = subprocess.run(
        ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"(\d+)%", result.stdout)
    if not match:
        raise RuntimeError(f"Cannot parse volume: {result.stdout}")
    return int(match.group(1))


def main():
    previous = get_volume()
    print(f"Initial system volume: {previous}%")
    print("Rotate the CMF dial. Press Ctrl+C to stop.")

    process = subprocess.Popen(
        ["pactl", "subscribe"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    try:
        for line in process.stdout:
            # A sink change may be volume, mute, or another property.
            if "Event 'change' on sink #" not in line:
                continue

            time.sleep(0.08)
            try:
                current = get_volume()
            except (subprocess.CalledProcessError, RuntimeError):
                continue

            if current != previous:
                direction = "UP" if current > previous else "DOWN"
                print(
                    f"{time.strftime('%H:%M:%S')} "
                    f"{direction}: {previous}% -> {current}%"
                )
                previous = current

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        process.terminate()
        process.wait()


if __name__ == "__main__":
    main()
