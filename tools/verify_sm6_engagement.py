"""Verify the new SM-6 channel: route the recon drone to loiter ~26 km from a
destroyer (past the SM-2's 22 km drone cap), and confirm the ship now fires an
SM-6 at it - the fix for 'the ships never shot down my drone'."""

import os
import sys
from math import hypot

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playtest_harness import build_world
from sim.sam import SamMissile

PHYS_DT = 1.0 / 120.0


def sm6_used(w):
    return sum(max(0, 6 - getattr(s, "sm6_ammo", 6)) for s in w.ships)


def main():
    w = build_world(7, n_destroyers=6)
    ship = w.ships[0]
    lx = float(ship.pos[0]) + 20_000.0
    lz = float(ship.pos[2])
    w.drone.pos[0], w.drone.pos[2] = lx, lz   # start IN the band (skip transit)
    w.drone.pos[1] = 18_000.0
    w.drone.set_route([(lx, lz)])             # loiter 27 km from the destroyer
    print(f"drone placed 27km from {ship.ship_id}", flush=True)

    fired = 0
    for chunk in range(20):                 # up to 10 min
        for _ in range(int(30.0 / PHYS_DT)):
            w.step(PHYS_DT)
        used = sm6_used(w)
        tracked = sum(1 for u in w.defense.units
                      if w.drone is not None
                      and w.drone.aircraft_id in u._drone_tracks)
        sm2u = sum(max(0, 24 - getattr(s, "sm2_ammo", 24)) for s in w.ships)
        if chunk % 3 == 0:
            print(f"  [dbg t={w.sim_time:.0f}s tracked_by={tracked} "
                  f"sm2_used={sm2u} sm6_used={used}]", flush=True)
        if used > 0:
            sm6 = [m for m in w.missiles if isinstance(m, SamMissile)
                   and getattr(getattr(m, "weapon", None), "weapon_id", None)
                   == "sm6"]
            print(f"t={w.sim_time:.0f}s  SM-6 FIRED  rounds_used={used} "
                  f"inflight={len(sm6)}", flush=True)
            fired = used
            break
        if chunk % 6 == 0 and w.drone is not None and w.drone.alive:
            d = hypot(w.drone.pos[0] - ship.pos[0],
                      w.drone.pos[2] - ship.pos[2]) / 1000.0
            print(f"t={w.sim_time:5.0f}s drone {d:5.0f} km from ship "
                  f"alt {w.drone.pos[1]:.0f} m  sm6_used={used}", flush=True)

    print("RESULT:", "OK - ships engage the drone with SM-6"
          if fired else "no SM-6 fired (check envelope/detection)")


if __name__ == "__main__":
    main()
