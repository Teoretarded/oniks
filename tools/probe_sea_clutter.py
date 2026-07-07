"""F3-P2 probe: detection range vs Douglas sea state (run-log evidence).

Bisects the Radar.detects boundary for three victim profiles against a
SPY-1-class fixture (20 m antenna, 30 km missile ring) and the player
station geometry (18 m antenna, 120 km missile ring).

Run:  python tools/probe_sea_clutter.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from sim.radar import Radar

PROFILES = (("Oniks skim", 12.0), ("TLAM skim", 15.0), ("drone", 60.0))


def _radar(antenna_m, missile_km, sea_state):
    return Radar("probe", (0.0, 0.0, 0.0), antenna_m,
                 {"missile": missile_km * 1_000.0},
                 height_fn=lambda x, z: 0.0, sea_state=sea_state)


def _detect_range_km(radar, alt):
    lo, hi = 0.1, 400_000.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if radar.detects(np.array([0.0, alt, mid]), "missile"):
            lo = mid
        else:
            hi = mid
    return lo / 1_000.0


def main():
    for name, ant, rng_km in (("SPY-1 fixture", 20.0, 30.0),
                              ("player station", 18.0, 120.0)):
        print(f"\n=== {name} ({ant:.0f} m antenna, {rng_km:.0f} km missile "
              f"ring) — detection km by sea state ===")
        hdr = "target           " + "".join(f"  s{s}" .rjust(7)
                                            for s in range(10))
        print(hdr)
        for pname, alt in PROFILES:
            row = f"{pname:14s} {alt:4.0f}m"
            for s in range(10):
                row += f"{_detect_range_km(_radar(ant, rng_km, s), alt):7.1f}"
            print(row)


if __name__ == "__main__":
    main()
