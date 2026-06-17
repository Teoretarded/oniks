"""Render the player Kh-31P anti-radiation missile to reference photos.

Adapts tools/shoot_updated_missile_models.py to shoot just the Kh-31P mesh
(models.missiles.build_kh31p) from a SIDE view and a FRONT/nose view against
the sky, matching the clean style of the existing model montage.

Outputs EXACTLY two files, labeled by model name:
  .../New models 1 needs improving and updating/kh31p_side.png
  .../New models 1 needs improving and updating/kh31p_front.png
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np
import pygame

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playtest_harness import Battle
from engine.mesh import Mesh
from models.missiles import build_kh31p

OUT_DIR = ("C:/Users/teoti/OneDrive/Desktop/Assets of oinks/"
           "New models 1 needs improving and updating")
POS = np.array([0.0, 3000.0, 80_000.0], dtype=np.float64)
KH31P_LEN = 4.7


class StaticModel:
    """A frozen, level-flying carrier for the bare mesh draw."""

    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.prev_pos = self.pos.copy()
        self.body_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self.vel = np.array([0.0, 0.0, 260.0], dtype=np.float64)
        self.alive = True


def _shot(b: Battle, missile, meshdata, length: float, az_deg: float,
          el_deg: float, suffix: str) -> str:
    b.world.missiles[:] = []
    missile.pos = POS.copy()
    missile.prev_pos = POS.copy()
    missile.body_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    missile.vel = np.array([0.0, 0.0, 260.0], dtype=np.float64)
    missile.alive = True
    b.state.hud_visible = False
    b.state.map_open = False

    added = (Mesh(meshdata), missile.pos.copy())
    b.state._site_draws.append(added)
    # Front/nose view sits a touch further back than the body radius so the
    # cruciform intake + tail-fin layout reads around the nose rather than
    # filling the frame with the ogive.
    dist = max(4.0, length * 0.92) if suffix == "front" else max(5.0, length * 1.65)
    b.follow(missile, "orbit", dist=dist)
    rig = b.state.rig
    rig._orbit_az = math.radians(az_deg)
    rig._orbit_el = math.radians(el_deg)
    rig._orbit_dist = rig._orbit_dist_target = dist
    rig._orbit_idle = 0.0
    rig._blend_t = 10.0
    b.settle(10)
    path = os.path.join(OUT_DIR, f"kh31p_{suffix}.png")
    pygame.image.save(b.app.window.read_pixels_to_surface(), path)
    mesh, _ = b.state._site_draws.pop()
    mesh.delete()
    return path


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    b = Battle(7)
    md = build_kh31p()
    try:
        # Side: a slight 3/4 azimuth + small down-tilt so the 45-deg-mounted
        # ramjet scoops show in profile instead of edge-on. Front: a 3/4
        # forward hero angle (off-nose) so the cruciform of four ramjet
        # intakes + four tail fins reads around the body instead of the bare
        # ogive occluding everything in a pure head-on shot.
        side = _shot(b, StaticModel(POS), md, KH31P_LEN, 68.0, -6.0, "side")
        front = _shot(b, StaticModel(POS), md, KH31P_LEN, 32.0, -10.0, "front")
        print(f"rendered {side}")
        print(f"rendered {front}")
    finally:
        b.close()


if __name__ == "__main__":
    main()
