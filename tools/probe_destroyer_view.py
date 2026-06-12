"""One-shot visual probe: frame destroyer_00 with the orbit camera, save PNG.

Run: python tools/probe_destroyer_view.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT


def main() -> int:
    app = App(hidden=True)
    app.start_combat()
    state = app.state
    dd = state.world.ships[0]
    try:
        from game.cameras import StaticSubject
    except ImportError:
        from game.sandbox import StaticSubject
    state.followed = StaticSubject(dd.pos + np.array([0.0, 12.0, 0.0]),
                                   "DESTROYER")
    state.rig.set_mode("orbit")
    state.rig.retarget()
    for _ in range(180):                  # let the rig blend onto the subject
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
    print(f"[probe] {app._save_screenshot()}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
