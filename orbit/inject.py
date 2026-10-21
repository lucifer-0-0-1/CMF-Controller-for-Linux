"""python -m orbit.inject <rotate N | click | double | triple | hold | press | release>"""
import sys

from orbit.platform.dev import send

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    send(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0)
