"""CLI entrypoint for CMF Controller."""
import sys
from cmf.daemon import run

if __name__ == "__main__":
    sys.exit(run())
