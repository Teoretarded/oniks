"""Verify the Phase 8 fighter evasion: a fighter with an incoming player S-300
inside the threat range breaks hard perpendicular and dives (vs flying straight)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from playtest_harness import build_world
from sim.enemy_air import Fighter
from sim.sam import SamMissile
from sim.arsenal import S300

PHYS_DT = 1.0 / 120.0


def main():
    w = build_world(7)
    fighter = None
    for _ in range(int(600.0 / PHYS_DT)):       # up to 10 min to get one up
        w.step(PHYS_DT)
        up = [e for e in w.enemy_air if isinstance(e, Fighter)
              and e.alive and e.pos[1] > 3000.0]
        if up:
            fighter = up[0]
            break
    if fighter is None:
        print("no airborne fighter formed")
        return
    print(f"fighter up: alt {fighter.pos[1]:.0f} m  "
          f"heading {np.degrees(fighter.heading):.0f} deg")

    # Spawn an INCOMING player S-300 10 km away (inside the 25 km evade range).
    mpos = np.array([fighter.pos[0] + 10_000.0, float(fighter.pos[1]),
                     float(fighter.pos[2])])
    w.missiles.append(SamMissile(S300, mpos, fighter))
    h0, alt0 = float(fighter.heading), float(fighter.pos[1])

    for _ in range(int(6.0 / PHYS_DT)):
        w.step(PHYS_DT)
        if not fighter.alive:
            break
    dh = np.degrees(abs((fighter.heading - h0 + np.pi) % (2 * np.pi) - np.pi))
    print(f"evade_threat set: {fighter._evade_threat is not None}")
    print(f"heading change:   {dh:.0f} deg")
    print(f"altitude change:  {fighter.pos[1] - alt0:.0f} m (negative = dove)")
    print(f"-> {'OK: fighter broke + dived' if dh > 10 and fighter.pos[1] < alt0 else 'CHECK'}")


if __name__ == "__main__":
    main()
