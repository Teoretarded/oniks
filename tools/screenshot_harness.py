"""Scripted scenes -> renders/<scene>.png for visual review.

usage: python -m tools.screenshot_harness [scene ...]   (default: all)

Creates App(hidden=True) at 1600x900, sets up the named scene, steps the sim
N times (so ocean waves have phase), lets the streamed terrain LODs finish,
renders ONE final frame and saves it via window.read_pixels_to_surface() +
pygame.image.save. Prints saved paths.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pygame

from main import PHYS_DT, App
from world.generation import BASE_POS

OUT_DIR = "renders"
SIM_STEPS = 240                  # 2 s of ocean-wave phase
MAX_WARMUP_FRAMES = 1200         # cap on terrain LOD streaming warm-up


def _set_cam(state, pos, yaw: float, pitch: float) -> None:
    state.freecam.pos = np.asarray(pos, dtype=np.float64).copy()
    state.freecam.yaw = float(yaw)
    state.freecam.pitch = float(pitch)


_BX, _BY, _BZ = BASE_POS
# Sun azimuth (heading of renderer SUN_DIR's horizontal component).
_SUN_YAW = float(np.arctan2(0.35, 0.55))

SCENES = {
    # cam 3000 m above base looking north (whole bay in view; pulled 1.4 km
    # south of the base point so the home headland frames the bottom)
    "overview": lambda s: _set_cam(s, (_BX, _BY + 3000.0, -2_000.0),
                                   0.0, -0.42),
    # cam 80 m alt, 2 km offshore (coast at x=0 sits at z~1000), looking
    # back south at the cliffs
    "coast": lambda s: _set_cam(s, (_BX, 80.0, 3_000.0), np.pi, -0.04),
    # cam 8 m above water mid-ocean looking at the sun (wave/glint check;
    # slight pitch up puts the sun disc at the frame top)
    "ocean_low": lambda s: _set_cam(s, (40_000.0, 8.0, 200_000.0),
                                    _SUN_YAW, 0.04),
}


def shoot(app: App, name: str) -> str:
    SCENES[name](app.state)
    for _ in range(SIM_STEPS):
        app.state.sim_step(PHYS_DT)
    # Terrain LOD0/LOD1 meshes stream in over frames (budgeted builds);
    # draw until the build queue drains so the still shows full detail.
    for _ in range(MAX_WARMUP_FRAMES):
        app.state.render(0.0)
        if not app.state.terrain._jobs:
            break
    app.state.render(0.0)
    surf = app.window.read_pixels_to_surface()
    path = os.path.join(OUT_DIR, f"{name}.png")
    pygame.image.save(surf, path)
    return os.path.abspath(path)


def main(argv: list[str]) -> None:
    names = argv or list(SCENES)
    unknown = [n for n in names if n not in SCENES]
    if unknown:
        raise SystemExit(
            f"unknown scene(s) {unknown}; choose from {list(SCENES)}")
    os.makedirs(OUT_DIR, exist_ok=True)
    app = App(hidden=True)
    for name in names:
        print(f"saved {shoot(app, name)}")
    pygame.quit()


if __name__ == "__main__":
    main(sys.argv[1:])
