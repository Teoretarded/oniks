"""Render the EA-18G Growler escort jammer to reference photos.

Adapts tools/shoot_kh31p.py to shoot the jammer mesh (models.jammer.build_jammer)
from a SIDE view and a 3/4-FRONT view against the sky, matching the clean style
of the existing model montage. The Growler is a Super Hornet derivative, so the
shots are framed to show the airframe AND the electronic-attack signature
(underwing ALQ-99/ALQ-249 pods, centreline pod, ALQ-218 wingtip receivers).

Outputs EXACTLY two files, labeled by model name:
  .../New models 1 needs improving and updating/jammer_side.png
  .../New models 1 needs improving and updating/jammer_front.png
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
from models.jammer import build_jammer

OUT_DIR = ("C:/Users/teoti/OneDrive/Desktop/Assets of oinks/"
           "New models 1 needs improving and updating")
POS = np.array([0.0, 3000.0, 80_000.0], dtype=np.float64)
JAMMER_LEN = 18.3   # m (Super Hornet airframe)


class StaticModel:
    """A frozen, level-flying carrier for the bare mesh draw."""

    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.prev_pos = self.pos.copy()
        self.body_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self.vel = np.array([0.0, 0.0, 260.0], dtype=np.float64)
        self.alive = True


def _shot(b: Battle, ent, meshdata, length: float, az_deg: float,
          el_deg: float, dist: float, suffix: str) -> str:
    b.world.missiles[:] = []
    ent.pos = POS.copy()
    ent.prev_pos = POS.copy()
    ent.body_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    ent.vel = np.array([0.0, 0.0, 260.0], dtype=np.float64)
    ent.alive = True
    b.state.hud_visible = False
    b.state.map_open = False

    b.state._site_draws.append((Mesh(meshdata), ent.pos.copy()))
    b.follow(ent, "orbit", dist=dist)
    rig = b.state.rig
    rig._orbit_az = math.radians(az_deg)
    rig._orbit_el = math.radians(el_deg)
    rig._orbit_dist = rig._orbit_dist_target = dist
    rig._orbit_idle = 0.0
    rig._blend_t = 10.0
    b.settle(10)
    path = os.path.join(OUT_DIR, f"jammer_{suffix}.png")
    pygame.image.save(b.app.window.read_pixels_to_surface(), path)
    mesh, _ = b.state._site_draws.pop()
    mesh.delete()
    return path


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    b = Battle(7)
    md = build_jammer()
    try:
        # Side: near-profile (slight 3/4) + small down-tilt so the underwing
        # pods + the wingtip ALQ-218 receivers read against the haze-grey body.
        side = _shot(b, StaticModel(POS), md, JAMMER_LEN, 78.0, -7.0,
                     JAMMER_LEN * 1.45, "side")
        # Front: a 3/4 forward hero angle showing the wingspan, the two
        # underwing pods + centreline pod, and the wingtip receiver fairings.
        front = _shot(b, StaticModel(POS), md, JAMMER_LEN, 30.0, -13.0,
                      JAMMER_LEN * 1.25, "front")
        print(f"rendered {side}")
        print(f"rendered {front}")
    finally:
        b.close()


if __name__ == "__main__":
    main()
