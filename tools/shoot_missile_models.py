"""Render the game's current missile models (6 angles each) into the asset
folder for new-model generation.

There are only TWO missile meshes in the game today (game/sandbox.py:943-958):
  _mesh_oniks         <- oniks, tomahawk, jassm, harm, aim9x
  _mesh_s300_missile  <- 48n6, 40n6, sm2, pantsir_57e6
We render each mesh cleanly (isolated, high over open sea, HUD off) from 6
orbit angles, then write a per-missile copy under every name the user asked for,
plus MAPPING.md describing the real missile each slot should become.
"""

import math
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from playtest_harness import Battle
from sim.missile import Missile, PH_CRUISE
from sim.sam import SamMissile
from sim.arsenal import ONIKS, S300

ASSETS = "C:/Users/teoti/OneDrive/Desktop/Assets of oinks"
ANGLES = [0, 60, 120, 180, 240, 300]
POS = np.array([0.0, 3000.0, 80_000.0])

ONIKS_FAMILY = ["oniks", "tomahawk", "jassm", "harm", "aim9x"]
S300_FAMILY = ["48n6", "40n6", "sm2", "pantsir_57e6"]


class StaticTarget:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.zeros(3)


def photograph(b, m, name):
    w = b.world
    w.missiles[:] = [m]
    m.pos = POS.copy()
    m.prev_pos = POS.copy()
    m.body_dir = np.array([0.0, 0.0, 1.0])
    m.vel = np.array([0.0, 0.0, 220.0])
    b.state.hud_visible = False
    b.state.map_open = False
    b.follow(m, "orbit", dist=13.0)
    out = []
    for i, az in enumerate(ANGLES, 1):
        rig = b.state.rig
        rig._orbit_az = math.radians(az)
        rig._orbit_el = math.radians(-12.0)
        rig._orbit_dist = rig._orbit_dist_target = 13.0
        rig._orbit_idle = 0.0
        rig._blend_t = 10.0        # skip the 0.6 s mode-blend; snap to orbit
        b.settle(6)
        p = os.path.join(ASSETS, f"{name}_a{i}.png")
        pygame.image.save(b.app.window.read_pixels_to_surface(), p)
        out.append(p)
    print(f"  rendered {name} x{len(out)}", flush=True)
    return out


MAPPING = """# oinks missile model map

The game currently has only TWO missile meshes. Every missile below is drawn
with one of them (game/sandbox.py `_draw_missiles`). These reference renders show
the CURRENT model; generate a new, distinct model per missile from the spec.

| file prefix | current mesh | real missile to model |
|---|---|---|
| oniks_*        | _mesh_oniks        | P-800 Oniks/Yakhont - ~8.9 m, 0.7 m dia, ramjet; ogive nose air-intake, 4 clipped-delta wings + 4 tail fins |
| tomahawk_*     | _mesh_oniks (reuse)| BGM-109 Tomahawk - ~6.25 m (+booster), 0.52 m, turbofan; cylindrical body, pop-out straight wings, cruciform tail |
| jassm_*        | _mesh_oniks (reuse)| AGM-158 JASSM - ~4.27 m; stealth faceted body, trapezoidal mid wings, flush dorsal intake |
| harm_*         | _mesh_oniks (reuse)| AGM-88 HARM - ~4.1 m, 0.25 m; slim tube, 4 cruciform mid-body wings + 4 tail fins |
| aim9x_*        | _mesh_oniks (reuse)| AIM-9X Sidewinder - ~3.0 m, 0.127 m; slim, forward double-delta canards + rear rolleron fins |
| 48n6_*         | _mesh_s300_missile | S-300 48N6 - ~7.5 m, 0.515 m; single-stage, cropped-delta tail control, no mid wings |
| 40n6_*         | _mesh_s300_missile | S-300V 40N6 - ~8.0 m (longer/heavier), 0.515 m; single-stage, tail control |
| sm2_*          | _mesh_s300_missile | SM-2 Block IIIB - ~6.55 m (~7.9 m w/ booster), 0.34 m; wingless, tail control, jettisonable booster |
| pantsir_57e6_* | _mesh_s300_missile | 57E6 - ~3.2 m; two-stage bicalibre (fat booster, thin dart), no wings |

6 angles per missile: _a1..a6 are orbit azimuth 0/60/120/180/240/300 deg.
"""


def main():
    os.makedirs(ASSETS, exist_ok=True)
    b = Battle(7)

    oniks = Missile(ONIKS, POS.copy(), 0.0, "hi-lo",
                    np.array([0.0, 0.0, 200_000.0]))
    oniks.phase = PH_CRUISE
    oniks_paths = photograph(b, oniks, ONIKS_FAMILY[0])

    sam = SamMissile(S300, POS.copy(), StaticTarget([0.0, 3000.0, 200_000.0]))
    s300_paths = photograph(b, sam, S300_FAMILY[0])

    b.close()

    for fam, src in ((ONIKS_FAMILY, oniks_paths), (S300_FAMILY, s300_paths)):
        for name in fam[1:]:
            for i, sp in enumerate(src, 1):
                shutil.copyfile(sp, os.path.join(ASSETS, f"{name}_a{i}.png"))
        print(f"  copied {fam[0]} render to: {', '.join(fam[1:])}", flush=True)

    with open(os.path.join(ASSETS, "MAPPING.md"), "w", encoding="utf-8") as fh:
        fh.write(MAPPING)
    print(f"[models] wrote 9 missiles x 6 angles + MAPPING.md to {ASSETS}",
          flush=True)


if __name__ == "__main__":
    main()
