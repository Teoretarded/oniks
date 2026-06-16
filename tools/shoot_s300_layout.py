"""Visual check of the 2-launcher S-300 battery placement (side by side)."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from playtest_harness import Battle
from world.world import SAM_TEL_POS


class Anchor:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True
        self.phase = 99

    def velocity(self):
        return np.zeros(3)


def main():
    b = Battle(7, n_s300=2)
    base = np.asarray(SAM_TEL_POS, dtype=np.float64)
    print("s300 launcher x:",
          [round(float(p[0]), 1) for p in b.world._s300_launcher_positions],
          flush=True)
    b.state.hud_visible = False
    b.state.map_open = False
    b.state.followed = Anchor(base + np.array([0.0, 6.0, 0.0]))
    rig = b.state.rig
    rig.set_mode("orbit")
    rig.retarget()
    rig._orbit_az = math.radians(20.0)
    rig._orbit_el = math.radians(22.0)
    rig._orbit_dist = rig._orbit_dist_target = 52.0
    rig._blend_t = 10.0
    b.settle(10)
    b.shot("salvo_s300_2tels", "2 S-300 launchers")
    b.close()


if __name__ == "__main__":
    main()
