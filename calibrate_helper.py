#!/usr/bin/env python3
"""Compatibility helper for magnet filename calibration.

The original repository referenced this helper but did not ship a complete
external filename resolver.  The route is kept so the Web UI remains intact.
"""

import sys


def main():
    if len(sys.argv) < 2:
        print("missing info hash", file=sys.stderr)
        return 1

    # Returning no filename keeps failed tasks safe instead of writing a fake
    # name into user notes. Replace this with a real resolver if needed.
    print("", end="")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
