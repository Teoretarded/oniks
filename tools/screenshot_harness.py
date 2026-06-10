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


def _aim(state, pos, target) -> None:
    """Place the free camera at ``pos`` looking at ``target``."""
    d = np.asarray(target, np.float64) - np.asarray(pos, np.float64)
    yaw = float(np.arctan2(d[0], d[2]))
    pitch = float(np.arctan2(d[1], np.hypot(d[0], d[2])))
    _set_cam(state, pos, yaw, pitch)


_BX, _BY, _BZ = BASE_POS
# Sun azimuth (heading of renderer SUN_DIR's horizontal component).
_SUN_YAW = float(np.arctan2(0.35, 0.55))

# --- models showcase: every vehicle/weapon model on a flat concrete pad ----
# The pad is a quay just offshore (water ~50 m deep, home cliffs as backdrop):
# low land cameras hit the log-depth near-plane artifact on huge terrain
# triangles, while near-camera ocean rings are fine-grained and render clean.
PAD_X, PAD_Z = 800.0, 3_000.0
PAD_TOP = 2.5                       # quay deck height above sea level (m)

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
    # models lineup from 3 orbit angles (models face north = +Z)
    "models_front": lambda s: _aim(s, (PAD_X + 20.0, PAD_TOP + 7.0, PAD_Z + 26.0),
                                   (PAD_X - 1.0, PAD_TOP + 2.5, PAD_Z - 1.0)),
    "models_side": lambda s: _aim(s, (PAD_X + 28.0, PAD_TOP + 4.5, PAD_Z - 12.0),
                                  (PAD_X + 9.0, PAD_TOP + 1.5, PAD_Z + 1.0)),
    "models_high": lambda s: _aim(s, (PAD_X + 26.0, PAD_TOP + 25.0, PAD_Z - 28.0),
                                  (PAD_X - 2.0, PAD_TOP, PAD_Z + 1.0)),
}
MODEL_SCENES = ("models_front", "models_side", "models_high")

_model_draws: list | None = None    # [(Mesh, pos_f64), ...] built lazily


def _ensure_model_draws() -> list:
    """Build the showcase meshes once (needs the GL context to exist)."""
    global _model_draws
    if _model_draws is not None:
        return _model_draws
    from engine.mesh import Mesh
    from engine.meshdata import MeshBuilder, make_box, make_grid
    from models.bastion import build_bastion_tel
    from models.common import PALETTE
    from models.oniks import build_oniks, build_oniks_booster

    # Quay deck: tessellated ~4 m cells. One giant quad would interpolate the
    # vertex-shader log depth so far off at grazing angles that the (finely
    # tessellated) ocean wins the depth test and eats the deck.
    hx, hz = 24.0, 15.0
    b = MeshBuilder()
    xs = np.linspace(-hx, hx, 13)
    zs = np.linspace(-hz, hz, 9)
    cols = np.empty((9, 13, 3), dtype=np.float32)
    cols[:] = PALETTE["concrete"]
    b.add_mesh(make_grid(xs, zs, np.zeros((9, 13)), cols))
    # skirt walls down past the waves, in short segments (same depth reason)
    for i in range(6):                            # north + south walls
        x0 = -hx + 4.0 + 8.0 * i
        for sz in (1.0, -1.0):
            b.add_mesh(make_box((8.0, 4.0, 0.6), PALETTE["concrete"],
                                offset=(x0, -2.02, sz * (hz - 0.3))))
    for i in range(4):                            # east + west walls
        z0 = -hz + 3.75 + 7.5 * i
        for sx in (1.0, -1.0):
            b.add_mesh(make_box((0.6, 4.0, 7.5), PALETTE["concrete"],
                                offset=(sx * (hx - 0.3), -2.02, z0)))
    pad = b.build()
    # display stands under the missile + booster assembly
    stands = MeshBuilder()
    for z in (-5.2, -2.0, 2.0):
        stands.add_mesh(make_box((0.35, 0.95, 0.5), PALETTE["concrete"],
                                 offset=(0.0, 0.475, z)))
    p = np.array([PAD_X, PAD_TOP, PAD_Z], dtype=np.float64)
    # diagonal spread so the NE "front" camera sees each silhouette clear
    _model_draws = [
        (Mesh(pad), p),                                          # deck at PAD_TOP
        (Mesh(build_bastion_tel(elevation_deg=88.0)), p + (-12.0, 0.0, 7.0)),
        (Mesh(build_bastion_tel(elevation_deg=0.0)), p + (1.0, 0.0, 1.0)),
        (Mesh(stands.build()), p + (13.0, 0.0, -5.0)),
        (Mesh(build_oniks()), p + (13.0, 0.95, -5.0)),
        (Mesh(build_oniks_booster()), p + (13.0, 0.95, -10.45)),  # behind tail
    ]
    return _model_draws


def _render_frame(app: App, name: str) -> None:
    app.state.render(0.0)
    if name in MODEL_SCENES:
        for mesh, pos in _ensure_model_draws():
            app.renderer.draw_mesh(mesh, pos)


def shoot(app: App, name: str) -> str:
    SCENES[name](app.state)
    for _ in range(SIM_STEPS):
        app.state.sim_step(PHYS_DT)
    # Terrain LOD0/LOD1 meshes stream in over frames (budgeted builds);
    # draw until the build queue drains so the still shows full detail.
    for _ in range(MAX_WARMUP_FRAMES):
        _render_frame(app, name)
        if not app.state.terrain._jobs:
            break
    _render_frame(app, name)
    surf = app.window.read_pixels_to_surface()
    path = os.path.join(OUT_DIR, f"{name}.png")
    pygame.image.save(surf, path)
    return os.path.abspath(path)


def main(argv: list[str]) -> None:
    names = argv or list(SCENES)
    # "models" expands to the three orbit angles of the showcase pad
    names = [m for n in names
             for m in (MODEL_SCENES if n == "models" else (n,))]
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
