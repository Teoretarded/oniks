"""Visual check of the multi-launcher Oniks battery placement.

Renders the base for n_oniks = 2, 3, 5 from an elevated 3/4 angle so the TEL
spacing can be eyeballed: side by side, not overlapping, not too far apart.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from playtest_harness import Battle
from world.generation import BASE_POS


class Anchor:
    """A static camera subject at the base center."""

    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True
        self.phase = 99           # not PH_DEAD -> rig treats it as in-flight

    def velocity(self):
        return np.zeros(3)


def shoot(n):
    b = Battle(7, n_oniks=n)
    base = np.array(BASE_POS, dtype=np.float64)
    print(f"n_oniks={n} launchers="
          f"{[(round(float(p[0]), 1)) for p in b.world._oniks_launcher_positions]}",
          flush=True)
    b.state.hud_visible = False
    b.state.map_open = False
    b.state.followed = Anchor(base + np.array([0.0, 6.0, 0.0]))
    rig = b.state.rig
    rig.set_mode("orbit")
    rig.retarget()
    rig._orbit_az = math.radians(20.0)
    rig._orbit_el = math.radians(22.0)      # camera above, looking down
    rig._orbit_dist = rig._orbit_dist_target = 42.0
    rig._blend_t = 10.0
    b.settle(10)
    b.shot(f"salvo_battery_{n}oniks", f"{n} Oniks launchers")
    b.close()


def main():
    for n in (2, 3, 5):
        shoot(n)


if __name__ == "__main__":
    main()
