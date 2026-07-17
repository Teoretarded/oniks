"""One-shot probe: stand 40 m from the surveyed silo site and screenshot
the compound (drawn? placed right? readable?).  Usage:
python tools/probe_silo_render.py [scene]"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math

import numpy as np
import pygame

from tools.shoot_cinematic import aim, frames, shot, wait_for_l0
from main import App


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "lauterbrunnen"
    app = App(hidden=True)
    app.open_testing_lab()
    app.open_cinematic(os.path.join("assets", "cinematic", scene))
    state = app.state
    frames(state, 10)
    wait_for_l0(state)
    silo = state._silo_site
    print("silo site:", silo, flush=True)
    wk = state.walker
    (sx0, sz0), _yaw = state.scene.spawn_pos_yaw()
    d = np.array([sx0 - silo[0], 0.0, sz0 - silo[2]])
    d /= max(float(np.linalg.norm(d)), 1e-6)
    for dist, tag in ((40.0, "40m"), (200.0, "200m")):
        wk.x = float(silo[0] + d[0] * dist)
        wk.z = float(silo[2] + d[2] * dist)
        wk.y = state.scene.ground_h(wk.x, wk.z)
        wk.vx = wk.vy = wk.vz = 0.0
        wk.on_ground = True
        eye = np.array(wk.eye, dtype=np.float64)
        yaw = math.degrees(math.atan2(silo[0] - eye[0], silo[2] - eye[2]))
        state.launcher_i = 1
        aim(state, yaw, math.degrees(math.atan2(
            float(silo[1] - eye[1]), dist)))
        frames(state, 5)
        shot(app, f"probe_mm3_silo_{tag}")
        state.launcher_i = 2
        frames(state, 3)
        shot(app, f"probe_sarmat_silo_{tag}")
    print("sid would draw:", state._silo_draw_id(),
          "meshes:", list(state.silo_meshes.keys()), flush=True)
    app.close_cinematic()
    app.close_testing_lab()
    pygame.quit()


if __name__ == "__main__":
    main()
