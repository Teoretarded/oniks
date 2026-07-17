"""Visual + physics probe for the map-expansion rings (2026-07-17).

Shots into renders/cinematic_audit/: the horizon from the valley, ring
seams from altitude, boots on ring-2 ground 25 km out, and a 60 km
Minuteman shot with the target marker on far terrain.

Usage: python tools/probe_expansion.py [lauterbrunnen]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math

import numpy as np
import pygame

from tools.shoot_cinematic import aim, frames, shot, sim_only, wait_for_l0
from main import App


def main() -> None:
    scene = sys.argv[1] if len(sys.argv) > 1 else "lauterbrunnen"
    app = App(hidden=True)
    app.open_testing_lab()
    app.open_cinematic(os.path.join("assets", "cinematic", scene))
    state = app.state
    frames(state, 10)
    wait_for_l0(state)
    sc = state.scene
    print(f"ext bounds: x {sc.ext_x0/1000:.0f}..{sc.ext_x1/1000:.0f} km, "
          f"z {sc.ext_z0/1000:.0f}..{sc.ext_z1/1000:.0f} km", flush=True)
    print(f"ground at +30 km east: {sc.ground_h(30000.0, 0.0):.0f}",
          flush=True)
    print(f"ground at -70 km: {sc.ground_h(-70000.0, -20000.0):.0f}",
          flush=True)

    # 1) From the spawn: the horizon must be RANGES now, not void.
    aim(state, 0.0, 6.0)
    frames(state, 5)
    shot(app, "40_expansion_north_horizon")
    aim(state, 180.0, 6.0)
    frames(state, 5)
    shot(app, "41_expansion_south_horizon")

    # 2) Freecam 6 km up: ring seams + the massif layout.
    state._toggle_freecam()
    state.fc_pos = np.array([0.0, sc.ground_h(0.0, 0.0) + 6000.0, 0.0])
    state.walker.pitch = math.radians(-18.0)
    state.walker.yaw = math.radians(135.0)
    frames(state, 8)
    shot(app, "42_rings_from_6km")
    state.fc_pos[1] += 14000.0
    state.walker.pitch = math.radians(-38.0)
    frames(state, 8)
    shot(app, "43_rings_from_20km")

    # 3) Boots on ring-2 ground 25 km south (walkable expansion).
    wk = state.walker
    gx, gz = 4000.0, -25000.0
    wk.x, wk.z = gx, gz
    wk.y = sc.ground_h(gx, gz)
    wk.vx = wk.vy = wk.vz = 0.0
    wk.on_ground = True
    state.freecam = False
    aim(state, 0.0, 4.0)
    frames(state, 8)
    shot(app, "44_standing_25km_out")

    # 4) The 60 km shot: designate far terrain, fire, watch the marker.
    tx, tz = 30000.0, -52000.0                 # ~60 km from the silo
    state.icbm_target = np.array([tx, sc.ground_h(tx, tz), tz])
    state.launcher_i = 1
    (sx0, sz0), _yaw = sc.spawn_pos_yaw()
    wk.x, wk.z = sx0, sz0
    wk.y = sc.ground_h(wk.x, wk.z)
    wk.on_ground = True
    state._fire()
    m = state.launches[-1]
    print(f"60 km shot away: {m.spec.label}", flush=True)
    sim_only(state, 25.0)
    silo = state._silo_site
    eye = np.array(wk.eye, dtype=np.float64)
    yaw_silo = math.degrees(math.atan2(silo[0] - eye[0], silo[2] - eye[2]))
    aim(state, yaw_silo, 35.0)
    frames(state, 5)
    shot(app, "45_long_shot_boost")
    guard = 0
    while not m.done and guard < 80000:
        state.sim_step(1.0 / 30.0)
        guard += 1
    err = math.hypot(m.pos[0] - tx, m.pos[2] - tz)
    print(f"60 km impact error: {err:.1f} m (t={m.t:.1f} s)", flush=True)
    app.close_cinematic()
    app.close_testing_lab()
    pygame.quit()


if __name__ == "__main__":
    sys.exit(main())
