"""Capture 60 fps frame sequences of a launch (user order 2026-07-17:
"sixty FPS for fifteen seconds, get that video footage, compare that
to IRL values").

Writes renders/launch_video/<weapon>_<phase>/frame_%04d.png at a real
60 Hz sim/render lockstep, tracking the bird with the spotter aim so
the whole sequence keeps the airframe in frame.  Turn into a video
with e.g.:  ffmpeg -framerate 60 -i frame_%04d.png -c:v libx264 out.mp4

Usage:
  python tools/capture_launch_video.py mm3      [seconds=15]
  python tools/capture_launch_video.py sarmat   [seconds=15]
  python tools/capture_launch_video.py trident  [seconds=15]
  python tools/capture_launch_video.py s300     [seconds=15]
  python tools/capture_launch_video.py impact   [seconds=15]  (300 kt)
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from tools.shoot_cinematic import aim, frames, wait_for_l0
from main import App, PHYS_DT

OUT_ROOT = os.path.join("renders", "launch_video")


def capture(state, app, name: str, seconds: float, track=None) -> None:
    out = os.path.join(OUT_ROOT, name)
    os.makedirs(out, exist_ok=True)
    n = int(seconds * 60)
    for i in range(n):
        state.sim_step(PHYS_DT)
        state.sim_step(PHYS_DT)
        if track is not None:
            track()
        state.render(1.0 / 60.0)
        pygame.image.save(app.window.read_pixels_to_surface(),
                          os.path.join(out, f"frame_{i:04d}.png"))
        if i % 120 == 0:
            print(f"  {name}: {i}/{n}", flush=True)
    print(f"[capture] {name}: {n} frames -> {out}", flush=True)


def main() -> None:
    weapon = sys.argv[1] if len(sys.argv) > 1 else "mm3"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 15.0
    scene = "lauterbrunnen"
    app = App(hidden=True)
    app.open_testing_lab()
    app.open_cinematic(os.path.join("assets", "cinematic", scene))
    state = app.state
    frames(state, 10)
    wait_for_l0(state)
    sc = state.scene
    wk = state.walker

    def look_at(p, eye=None):
        e = np.array(eye if eye is not None else wk.eye, dtype=np.float64)
        d = np.asarray(p, dtype=np.float64) - e
        wk.yaw = math.atan2(d[0], d[2])
        wk.pitch = math.atan2(d[1], math.hypot(d[0], d[2]))

    if weapon == "s300":
        tx, tz = 4000.0, -12000.0
        state.icbm_target = np.array([tx, sc.ground_h(tx, tz), tz])
        state.icbm_targets = [state.icbm_target]
        state.launcher_i = 0
        state._fire()
        m = state.launches[-1]
        capture(state, app, "s300_launch", seconds,
                track=lambda: look_at(m.pos))
    elif weapon == "impact":
        tx, tz = 700.0, -6200.0
        state.icbm_target = np.array([tx, sc.ground_h(tx, tz), tz])
        state.icbm_targets = [state.icbm_target]
        state.launcher_i = 1
        state._fire()
        m = state.launches[-1]
        while not m.done:
            state.sim_step(1.0 / 30.0)
        look_at([tx, sc.ground_h(tx, tz) + 400.0, tz])
        capture(state, app, "impact_300kt", seconds)
    else:
        ids = {"mm3": 1, "sarmat": 2, "trident": 3}
        state.launcher_i = ids.get(weapon, 1)
        lid = weapon
        site = state._launch_site(lid)
        if site is None:
            print("no launch site for", weapon)
            return
        # Stand 260 m off the launcher, mark 12 km away.
        (sx0, sz0), _ = sc.spawn_pos_yaw()
        d = np.array([sx0 - site[0], 0.0, sz0 - site[2]])
        d /= max(float(np.linalg.norm(d)), 1e-6)
        wk.x = float(site[0] + d[0] * 260.0)
        wk.z = float(site[2] + d[2] * 260.0)
        wk.y = sc.ground_h(wk.x, wk.z)
        wk.on_ground = True
        tx, tz = float(site[0] - d[0] * 12000.0), \
            float(site[2] - d[2] * 12000.0)
        g = sc.ground_h(tx, tz)
        if not np.isfinite(g):
            tx, tz = 4000.0, -12000.0
            g = sc.ground_h(tx, tz)
        state.icbm_target = np.array([tx, g, tz])
        state.icbm_targets = [state.icbm_target]
        state._fire()
        m = state.launches[-1]
        capture(state, app, f"{weapon}_launch", seconds,
                track=lambda: look_at(m.pos + np.array([0.0, 8.0, 0.0])))

    app.close_cinematic()
    app.close_testing_lab()
    pygame.quit()


if __name__ == "__main__":
    sys.exit(main())
