"""Instrument a Zircon (or Oniks) hi-lo flight: log phase/alt/speed/dist-to-go
over time so we can SEE where a missing shot diverges from a hitting one."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from playtest_harness import build_world
from sim.missile import Missile, PHASE_LABELS
from sim.arsenal import ZIRCON, ONIKS
from world.generation import BASE_POS

PHYS_DT = 1.0 / 120.0


class Ship:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True
        self.ship_id = "tgt"

    def velocity(self):
        return np.zeros(3)


def fly(world, weapon, profile, rng_km, label):
    base = np.array(BASE_POS, dtype=np.float64)
    tp = np.array([base[0], 0.0, base[2] + rng_km * 1000.0])
    ship = Ship(tp)
    m = Missile(weapon, base + np.array([0.0, 5.0, 0.0]), 0.0, profile, tp,
                target_ship=ship)
    print(f"\n=== {label}: {weapon.weapon_id} {profile} {rng_km}km ===")
    print(f"    descent_range={m.descent_range/1000:.1f}km "
          f"cruise_alt={m.cruise_alt/1000:.1f}km")
    closest = 1e18
    last_phase = -1
    next_log_t = 0.0
    while m.alive and m.t < 700.0:
        m.update(PHYS_DT, world)
        d = float(np.hypot(m.pos[0] - tp[0], m.pos[2] - tp[2]))
        closest = min(closest, float(np.linalg.norm(m.pos - tp)))
        spd = float(np.linalg.norm(m.vel))
        if m.phase != last_phase or m.t >= next_log_t:
            tag = "  <-- PHASE" if m.phase != last_phase else ""
            print(f"    t={m.t:6.1f}s {PHASE_LABELS.get(m.phase,'?'):9} "
                  f"alt={m.pos[1]/1000:6.2f}km dgo={d/1000:6.1f}km "
                  f"spd={spd:6.0f} closest={closest:7.0f}{tag}")
            last_phase = m.phase
            next_log_t = m.t + 10.0
    print(f"    RESULT closest={closest:.0f}m t={m.t:.0f}s "
          f"{'HIT' if closest < 120 else 'MISS'}")
    return closest


def sweep(world, weapon, profile, ranges):
    print(f"\n### {weapon.weapon_id} {profile} envelope sweep ###")
    for rng in ranges:
        base = np.array(BASE_POS, dtype=np.float64)
        tp = np.array([base[0], 0.0, base[2] + rng * 1000.0])
        ship = Ship(tp)
        m = Missile(weapon, base + np.array([0.0, 5.0, 0.0]), 0.0, profile, tp,
                    target_ship=ship)
        closest = 1e18
        fuel_at_descent = None
        while m.alive and m.t < 700.0:
            m.update(PHYS_DT, world)
            from sim.missile import PH_DESCENT
            if m.phase >= PH_DESCENT and fuel_at_descent is None:
                fuel_at_descent = m.fuel
            closest = min(closest, float(np.linalg.norm(m.pos - tp)))
        print(f"  {rng:4}km: closest={closest:7.0f}m t={m.t:5.0f}s "
              f"fuel_left={m.fuel:5.0f}kg fuel@descent={fuel_at_descent} "
              f"{'HIT' if closest < 120 else 'MISS'}")


def main():
    world = build_world(7)
    sweep(world, ZIRCON, "hi-lo", (80, 100, 120, 150, 200, 250, 300))
    sweep(world, ZIRCON, "lo-lo", (80, 120, 150, 200))
    fly(world, ZIRCON, "hi-lo", 150, "ZIRCON 150 detail")
    fly(world, ZIRCON, "hi-lo", 300, "ZIRCON 300 detail")


if __name__ == "__main__":
    main()
