"""Visual probe: the full nuclear impact timeline + crater + scorch.

Fires a Minuteman III (300 kt) at a mark ~5 km down-valley and shoots
the phases: flash, fireball, stem rising, mushroom cap, and the crater
after the smoke drifts off.

Usage: python tools/probe_nuke.py [lauterbrunnen]
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from tools.shoot_cinematic import aim, frames, shot, sim_only, wait_for_l0
from main import App, PHYS_DT


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "lauterbrunnen"
    app = App(hidden=True)
    app.open_testing_lab()
    app.open_cinematic(os.path.join("assets", "cinematic", scene))
    state = app.state
    frames(state, 10)
    wait_for_l0(state)
    sc = state.scene

    # Mark 5 km south down the valley floor.
    tx, tz = 700.0, -6200.0
    state.icbm_target = np.array([tx, sc.ground_h(tx, tz), tz])
    state.icbm_targets = [state.icbm_target]
    state.launcher_i = 1                       # MINUTEMAN III
    state._fire()
    m = state.launches[-1]
    print(f"away, toa {m._toa:.0f} s", flush=True)

    # Fly to impact (honest steps).
    guard = 0
    while not m.done and guard < 40000:
        state.sim_step(1.0 / 30.0)
        guard += 1
    print(f"impact at t={m.t:.1f}", flush=True)

    eye = np.array(state.walker.eye, dtype=np.float64)
    yaw = math.degrees(math.atan2(tx - eye[0], tz - eye[2]))

    # Flash + young fireball (0.5 s in).
    sim_only(state, 0.5)
    aim(state, yaw, 6.0)
    frames(state, 3, sim=False)
    shot(app, "60_nuke_flash")
    # Fireball at 3 s.
    sim_only(state, 2.5)
    frames(state, 3, sim=False)
    shot(app, "61_nuke_fireball_3s")
    # Stem + rising ball at 12 s.
    sim_only(state, 9.0)
    aim(state, yaw, 10.0)
    frames(state, 3, sim=False)
    shot(app, "62_nuke_stem_12s")
    # Mushroom at 40 s.
    sim_only(state, 28.0)
    aim(state, yaw, 14.0)
    frames(state, 3, sim=False)
    shot(app, "63_nuke_mushroom_40s")
    # Cap near ceiling at 90 s.
    sim_only(state, 50.0)
    aim(state, yaw, 18.0)
    frames(state, 3, sim=False)
    shot(app, "64_nuke_cap_90s")

    # The crater: freecam over ground zero after the burst retires.
    sim_only(state, 40.0)
    state._toggle_freecam()
    state.fc_pos = np.array([tx - 900.0, sc.ground_h(tx, tz) + 700.0,
                             tz + 900.0])
    state.walker.yaw = math.radians(math.degrees(
        math.atan2(tx - state.fc_pos[0], tz - state.fc_pos[2])))
    state.walker.pitch = math.radians(-35.0)
    frames(state, 8, sim=False)
    shot(app, "65_nuke_crater")
    print(f"craters in scene: {len(sc._craters)}", flush=True)

    app.close_cinematic()
    app.close_testing_lab()
    pygame.quit()
    print("nuke probe complete", flush=True)


if __name__ == "__main__":
    sys.exit(main())
