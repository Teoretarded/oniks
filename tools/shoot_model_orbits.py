"""360-degree orbit contact sheets for every VEHICLE model in the game.

For each model: 8 azimuth shots (45-degree steps, slight down-tilt) framed
from the mesh's own bounding box, downscaled and stitched into ONE 4x2
contact sheet per model — the reference-driven model-critique input (each
sheet is reviewed by eye against the real platform's visual signatures).

Outputs: <Assets of oinks>/model_360/<name>_orbit.png  (one per model)

Run: python tools/shoot_model_orbits.py [name ...]   (default: all)
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

OUT_DIR = "C:/Users/teoti/OneDrive/Desktop/Assets of oinks/model_360"
POS = np.array([0.0, 3000.0, 80_000.0], dtype=np.float64)   # clean sky bg
TILE_W, TILE_H = 640, 360
COLS, ROWS = 4, 2
AZIMUTHS = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)
ELEVATION = -10.0


def _builders():
    """name -> zero-arg mesh builder for every vehicle model."""
    from models.bastion import build_bastion_tel
    from models.s300 import build_s300_tel
    from models.pantsir import build_pantsir
    from models.drone import build_recon_drone
    from models.fighter import build_fighter
    from models.awacs import build_awacs
    from models.jammer import build_jammer
    from models.destroyer import build_destroyer
    from models.carrier import build_carrier
    from models.ships_models import build_cargo, build_tanker, build_warship

    return {
        "bastion_tel": lambda: build_bastion_tel(elevation_deg=90.0),
        "s300_tel":    lambda: build_s300_tel(elevation_deg=90.0),
        "pantsir":     build_pantsir,
        "drone":       build_recon_drone,
        "fighter":     build_fighter,
        "awacs":       build_awacs,
        "jammer":      build_jammer,
        "destroyer":   build_destroyer,
        "carrier":     build_carrier,
        "cargo":       build_cargo,
        "tanker":      build_tanker,
        "warship":     build_warship,
    }


class StaticModel:
    """Frozen level 'flyer' carrying the bare mesh for the orbit camera."""

    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.prev_pos = self.pos.copy()
        self.body_dir = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self.vel = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self.alive = True


def _extent(meshdata) -> tuple[float, np.ndarray]:
    """(framing radius, center offset) from the mesh bbox."""
    v = meshdata.vertices[:, :3]
    lo, hi = v.min(axis=0), v.max(axis=0)
    center = (lo + hi) * 0.5
    radius = float(np.linalg.norm(hi - lo)) * 0.5
    return max(radius, 2.0), center


def shoot(b: Battle, name: str, meshdata) -> str:
    radius, center = _extent(meshdata)
    anchor = StaticModel(POS)
    # Park the mesh so its bbox CENTER sits at the camera anchor point (a
    # ship's origin is the keel/waterline — uncentred, half the frame is sky).
    draw_pos = POS - center
    b.world.missiles[:] = []
    b.state.hud_visible = False
    b.state.map_open = False
    added = (Mesh(meshdata), draw_pos)
    b.state._site_draws.append(added)

    sheet = pygame.Surface((TILE_W * COLS, TILE_H * ROWS))
    dist = radius * 2.6
    rig = b.state.rig
    for i, az in enumerate(AZIMUTHS):
        b.follow(anchor, "orbit", dist=dist)
        rig._orbit_az = math.radians(az)
        rig._orbit_el = math.radians(ELEVATION)
        rig._orbit_dist = rig._orbit_dist_target = dist
        rig._orbit_idle = 0.0
        rig._blend_t = 10.0
        b.settle(8)
        frame = b.app.window.read_pixels_to_surface()
        tile = pygame.transform.smoothscale(frame, (TILE_W, TILE_H))
        sheet.blit(tile, ((i % COLS) * TILE_W, (i // COLS) * TILE_H))

    path = os.path.join(OUT_DIR, f"{name}_orbit.png")
    pygame.image.save(sheet, path)
    mesh, _ = b.state._site_draws.pop()
    mesh.delete()
    print(f"[orbit] {path}")
    return path


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    wanted = sys.argv[1:]
    builders = _builders()
    names = wanted or list(builders)
    b = Battle(7)
    try:
        for name in names:
            shoot(b, name, builders[name]())
    finally:
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
