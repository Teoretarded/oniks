"""Render updated non-Oniks missile models into the user's asset folder.

Outputs two images per model:
  C:/Users/teoti/OneDrive/Desktop/Assets of oinks/updated models/<id>_front.png
  C:/Users/teoti/OneDrive/Desktop/Assets of oinks/updated models/<id>_side.png
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
from models.missiles import build_sm6, build_zircon
from sim.a2a import IrMissile
from sim.arsenal import (HARM, JASSM, N40N6, PANTSIR_57E6, S300, SM2,
                         TOMAHAWK)
from sim.sam import SamMissile
from sim.strike import StrikeMissile

ASSETS = "C:/Users/teoti/OneDrive/Desktop/Assets of oinks"
OUT_DIR = os.path.join(ASSETS, "updated models")
POS = np.array([0.0, 3000.0, 80_000.0], dtype=np.float64)


class StaticTarget:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.zeros(3)


class StaticModel:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.prev_pos = self.pos.copy()
        self.body_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self.vel = np.array([0.0, 0.0, 260.0], dtype=np.float64)
        self.alive = True


def _strike(weapon):
    return StrikeMissile(
        weapon,
        POS.copy(),
        np.array([0.0, 0.0, 260.0], dtype=np.float64),
        (0.0, 200_000.0),
    )


def _sam(weapon):
    return SamMissile(weapon, POS.copy(),
                      StaticTarget([0.0, 3000.0, 200_000.0]))


def _aim9x():
    return IrMissile(POS.copy(), np.array([0.0, 0.0, 300.0]),
                     StaticTarget([0.0, 3000.0, 200_000.0]))


def _stage(b: Battle, missile) -> None:
    b.world.missiles[:] = [missile]
    missile.pos = POS.copy()
    missile.prev_pos = POS.copy()
    missile.body_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    missile.vel = np.array([0.0, 0.0, 260.0], dtype=np.float64)
    missile.alive = True
    b.state.hud_visible = False
    b.state.map_open = False


def _shot(b: Battle, missile, name: str, length: float, az_deg: float,
          suffix: str, meshdata=None) -> str:
    _stage(b, missile)
    added = None
    if meshdata is not None:
        b.world.missiles[:] = []
        added = (Mesh(meshdata), missile.pos.copy())
        b.state._site_draws.append(added)
    dist = max(2.8, length * 0.62) if suffix == "front" else max(5.0, length * 1.65)
    b.follow(missile, "orbit", dist=dist)
    rig = b.state.rig
    rig._orbit_az = math.radians(az_deg)
    rig._orbit_el = math.radians(-8.0)
    rig._orbit_dist = rig._orbit_dist_target = dist
    rig._orbit_idle = 0.0
    rig._blend_t = 10.0
    b.settle(10)
    path = os.path.join(OUT_DIR, f"{name}_{suffix}.png")
    pygame.image.save(b.app.window.read_pixels_to_surface(), path)
    if added is not None:
        mesh, _ = b.state._site_draws.pop()
        mesh.delete()
    return path


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    b = Battle(7)
    specs = [
        ("tomahawk", _strike(TOMAHAWK), TOMAHAWK.length),
        ("jassm", _strike(JASSM), JASSM.length),
        ("harm", _strike(HARM), HARM.length),
        ("aim9x", _aim9x(), 3.0),
        ("48n6", _sam(S300), S300.length),
        ("40n6", _sam(N40N6), N40N6.length),
        ("sm2", _sam(SM2), SM2.length),
        ("pantsir_57e6", _sam(PANTSIR_57E6), PANTSIR_57E6.length),
        ("zircon", StaticModel(POS), 9.0, build_zircon()),
        ("sm6", StaticModel(POS), 6.55, build_sm6()),
    ]
    try:
        for spec in specs:
            name, missile, length = spec[:3]
            meshdata = spec[3] if len(spec) > 3 else None
            front = _shot(b, missile, name, length, 0.0, "front", meshdata)
            side = _shot(b, missile, name, length, 90.0, "side", meshdata)
            print(f"rendered {front}")
            print(f"rendered {side}")
    finally:
        b.close()


if __name__ == "__main__":
    main()
