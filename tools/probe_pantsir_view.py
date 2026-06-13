"""One-shot Phase 6 visual probe: orbit the Bastion-guard Pantsir.

Run: python tools/probe_pantsir_view.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT


def main() -> int:
    from game.cameras import StaticSubject

    app = App(hidden=True)
    app.start_combat()
    state = app.state
    world = state.world

    pantsir = world.pantsirs[0]
    state.followed = StaticSubject(pantsir.pos + np.array([0.0, 3.0, 0.0]),
                                   "PANTSIR-S1")
    state.rig.set_mode("orbit")
    state.rig.retarget()
    state.rig._orbit_dist = 26.0
    state.rig._orbit_dist_target = 26.0
    for _ in range(150):
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join("renders", "probe_pantsir.png"))
    print("[probe] renders/probe_pantsir.png")
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
