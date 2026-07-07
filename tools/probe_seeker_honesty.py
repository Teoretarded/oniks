"""R-P1 probe: Oniks/Zircon seeker acquisition vs geometry (run-log
evidence).  Sweeps target range for a skimming and a diving seeker, open
water and behind a 140 m ridge, honest (scanned) vs legacy (functional).

Run:  python tools/probe_seeker_honesty.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from sim.arsenal import ONIKS
from sim.missile import Missile, SHIP_MAST_M
from sim.radar import radar_horizon_m


class _World:
    def __init__(self, ships, height_fn, radar_model):
        self.ships = ships
        self.terrain_height_at = height_fn
        self.radar_model = radar_model


class _Ship:
    def __init__(self, z):
        self.pos = np.array([0.0, 15.0, z])
        self.alive = True
        self.vel = np.zeros(3)

    def velocity(self):
        return self.vel


def _missile(alt, diving=False):
    m = Missile.__new__(Missile)
    m.weapon = ONIKS
    m.pos = np.array([0.0, alt, 0.0])
    m.vel = (np.array([0.0, -300.0, 600.0]) if diving
             else np.array([0.0, 0.0, 680.0]))
    m.locked_ship = None
    return m


def _max_acq_km(alt, height_fn, radar_model, diving=False):
    for rng_km in np.arange(50.0, 4.0, -0.5):
        m = _missile(alt, diving)
        w = _World([_Ship(rng_km * 1_000.0)], height_fn, radar_model)
        m._acquire_lock(w, speed=float(np.linalg.norm(m.vel)))
        if m.locked_ship is not None:
            return float(rng_km)
    return 0.0


def main():
    flat = lambda x, z: 0.0
    ridge = lambda x, z: 140.0 if 7_000.0 < z < 10_000.0 else 0.0
    print(f"theoretical horizon, 12 m skim vs {SHIP_MAST_M:.0f} m mast on a "
          f"15 m deck: {radar_horizon_m(12.0, 15.0 + SHIP_MAST_M)/1000:.1f} km")
    rows = [
        ("12 m skim, open water", 12.0, flat, False),
        ("60 m lo-cruise, open water", 60.0, flat, False),
        ("15 km dive, open water", 15_000.0, flat, True),
        ("12 m skim, 140 m ridge at 7-10 km", 12.0, ridge, False),
    ]
    print(f"{'geometry':38s} {'legacy':>8s} {'honest':>8s}")
    for name, alt, hfn, diving in rows:
        legacy = _max_acq_km(alt, hfn, "functional", diving)
        honest = _max_acq_km(alt, hfn, "scanned", diving)
        print(f"{name:38s} {legacy:7.1f}k {honest:7.1f}k")


if __name__ == "__main__":
    main()
