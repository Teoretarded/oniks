"""One-shot Phase 5a visual probe: orbit shots of carrier, airborne fighter,
AWACS, and the enemy airfield.

Run: python tools/probe_air_force_views.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT


def save(app, name):
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join("renders", name))
    print(f"[probe] renders/{name}")


def orbit_shot(app, state, subject, name, frames=150, dist=None):
    state.followed = subject
    state.rig.set_mode("orbit")
    state.rig.retarget()
    if dist is not None:                    # big subjects need a wide frame
        state.rig._orbit_dist = dist
        state.rig._orbit_dist_target = dist
    for _ in range(frames):
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
    save(app, name)


def main() -> int:
    from game.cameras import StaticSubject
    from sim.enemy_air import Fighter
    from world.combat import AIRFIELD_XZ
    from world.generation import terrain_height_scalar

    app = App(hidden=True)
    app.start_combat()
    state = app.state
    world = state.world

    # Let the CAP scheduler put a fighter in the air (coarse steps).
    fighter = None
    for _ in range(int(900.0 / 0.25)):
        world.step(0.25)
        world.drain_events()
        fighter = next((e for e in world.enemy_air
                        if isinstance(e, Fighter) and e.alive
                        and e.pos[1] > 1_000.0), None)
        if fighter is not None:
            break

    carrier = next(s for s in world.ships if s.ship_id == "carrier_00")
    orbit_shot(app, state, carrier, "probe_carrier.png", dist=520.0)
    if fighter is not None:
        orbit_shot(app, state, fighter, "probe_fighter.png")
    else:
        print("[probe] WARN no airborne fighter after 900 s")
    orbit_shot(app, state, world.awacs, "probe_awacs.png")
    ax, az = AIRFIELD_XZ
    ay = max(terrain_height_scalar(ax, az), 0.0)
    orbit_shot(app, state,
               StaticSubject(np.array([ax, ay + 40.0, az]), "AIRFIELD"),
               "probe_airfield.png")
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
