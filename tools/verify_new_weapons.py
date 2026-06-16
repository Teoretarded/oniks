"""Verify the new weapons fly + hit, reusing the existing flight machines:
ZIRCON (player, Missile machine, anti-ship) and SM-6 (enemy, SamMissile, anti-air).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from playtest_harness import build_world
from sim.missile import Missile
from sim.sam import SamMissile
from sim.arsenal import ZIRCON, SM6, ONIKS
from world.world import SAM_TEL_POS
from world.generation import BASE_POS

PHYS_DT = 1.0 / 120.0


class Ship:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True
        self.ship_id = "tgt"

    def velocity(self):
        return np.zeros(3)


class Air:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.zeros(3)


def fly_missile(world, weapon, profile, rng_km):
    base = np.array(BASE_POS, dtype=np.float64)
    tp = np.array([base[0], 0.0, base[2] + rng_km * 1000.0])
    ship = Ship(tp)
    m = Missile(weapon, base + np.array([0.0, 5.0, 0.0]), 0.0, profile, tp,
                target_ship=ship)
    apogee = vmax = 0.0
    closest = 1e18
    while m.alive and m.t < 700.0:
        m.update(PHYS_DT, world)
        apogee = max(apogee, float(m.pos[1]))
        vmax = max(vmax, float(np.linalg.norm(m.vel)))
        closest = min(closest, float(np.linalg.norm(m.pos - tp)))
    return apogee / 1000.0, vmax, closest, m.t


def fly_sam(world, sam_def, rng_km, alt):
    base = np.array(SAM_TEL_POS, dtype=np.float64)
    tp = np.array([base[0], alt, base[2] + rng_km * 1000.0])
    air = Air(tp)
    m = SamMissile(sam_def, base, air)
    apogee = vmax = 0.0
    closest = 1e18
    while m.alive and m.t < 400.0:
        m.update(PHYS_DT, world)
        apogee = max(apogee, float(m.pos[1]))
        vmax = max(vmax, float(np.linalg.norm(m.vel)))
        closest = min(closest, float(np.linalg.norm(m.pos - tp)))
    return apogee / 1000.0, vmax, closest, m.t, (not air.alive)


def main():
    world = build_world(7)
    # Envelope (measured tools/probe_zircon_traj.py): the Zircon is fuel-starved
    # past ~100 km and coasts, so hi-lo reaches ~250 km and lo-lo ~150 km; the
    # steeper speed-scaled terminal dive (sim/missile.DESCENT_BASELINE_MACH) lets
    # it hit across that band instead of overflying. 300 km hi-lo is an honest
    # out-of-range MISS.
    print("ZIRCON vs ship (anti-ship):")
    for prof, rng in (("hi-lo", 150), ("hi-lo", 250), ("lo-lo", 120),
                      ("hi-lo", 300)):
        a, v, c, t = fly_missile(world, ZIRCON, prof, rng)
        print(f"  {prof:5} {rng}km: apogee {a:5.1f}km vmax {v:5.0f}m/s "
              f"closest {c:7.0f}m t{t:5.0f}s "
              f"{'HIT' if c < 120 else 'MISS'}")
    a, v, c, t = fly_missile(world, ONIKS, "hi-lo", 150)
    print(f"  (oniks hi-lo 150km baseline: vmax {v:.0f}m/s closest {c:.0f}m)")
    print("SM-6 vs air target:")
    for rng, alt in ((150, 18000), (220, 22000)):
        a, v, c, t, k = fly_sam(world, SM6, rng, alt)
        print(f"  {rng}km @ {alt}m: apogee {a:5.1f}km vmax {v:5.0f}m/s "
              f"closest {c:6.0f}m t{t:5.0f}s "
              f"{'KILL' if k or c < 60 else 'MISS'}")


if __name__ == "__main__":
    main()
