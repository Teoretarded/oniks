"""One-shot Phase 4 visual probe: (1) 3D orbit view of the flying drone,
(2) tactical map with ELINT bearing rays / fix overlays after a recon leg.

Run: python tools/probe_drone_view.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT


def save(app, name):
    surf = app.window.read_pixels_to_surface()
    path = os.path.join("renders", name)
    pygame.image.save(surf, path)
    print(f"[probe] {os.path.abspath(path)}")


def main() -> int:
    from game import tactical_map as tm
    from game.cameras import StaticSubject

    app = App(hidden=True)
    app.start_combat()
    state = app.state
    world = state.world
    drone = world.drone

    # Recon leg: crossing south of the fleet while destroyers emit.
    drone.pos[0], drone.pos[2] = -60_000.0, 80_000.0
    drone.set_route([(60_000.0, 80_000.0)])
    for _ in range(int(420.0 / 0.25)):       # coarse sim: ELINT fix forms
        world.step(0.25)
        world.drain_events()

    # Shot 1: 3D orbit of the drone in flight (follow the entity itself —
    # a static snapshot point falls behind a 160 m/s subject immediately).
    _ = StaticSubject                        # kept for reference
    state.followed = drone
    state.rig.set_mode("orbit")
    state.rig.retarget()
    for _ in range(240):
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
    save(app, "probe_drone_3d.png")

    # Shot 2: the tactical map with ELINT overlays.
    state.map_open = True
    deadline = time.time() + 120.0
    while time.time() < deadline and tm.get_map_pixels() is None:
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
    for _ in range(5):
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
    save(app, "probe_drone_map.png")
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
