"""Dev viz: render each map preset's terrain as a top-down heightmap PNG so the
island / strait / fjord LAYOUTS can be eyeballed. Not a test. Saves to renders/.

Run: python tools/render_preset_maps.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from world.combat_config import MAP_PRESET_NAMES
from world.generation import make_field

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "renders")
os.makedirs(OUT, exist_ok=True)

# Map extent (x east-west, z toward the enemy coast).
X0, X1 = -300_000.0, 300_000.0
Z0, Z1 = -20_000.0, 540_000.0
W = H = 512

xs = np.linspace(X0, X1, W)
zs = np.linspace(Z0, Z1, H)
X, Z = np.meshgrid(xs, zs)        # Z rows (north up), X cols

pygame.init()
for preset in range(len(MAP_PRESET_NAMES)):
    field = make_field(preset, 1337)
    h = field.height(X, Z)        # (H, W) float metres
    img = np.zeros((H, W, 3), dtype=np.uint8)
    sea = h <= 0.0
    # Sea: deep blue -> shallow teal by depth; land: green -> brown -> white by height.
    depth = np.clip(-h[sea] / 200.0, 0.0, 1.0)
    img[sea] = np.stack([(10 + 20 * depth), (40 + 80 * (1 - depth)),
                         (70 + 120 * (1 - depth))], axis=-1).astype(np.uint8)
    land = ~sea
    lh = np.clip(h[land] / max(field.max_height, 1.0), 0.0, 1.0)
    img[land] = np.stack([80 + 175 * lh, 140 - 60 * lh, 60 + 40 * lh],
                         axis=-1).astype(np.uint8)
    # Flip so north (high z) is at the top.
    surf = pygame.surfarray.make_surface(np.transpose(img[::-1], (1, 0, 2)))
    path = os.path.join(OUT, f"preset_{preset}_{MAP_PRESET_NAMES[preset].replace(' ', '_').lower()}.png")
    pygame.image.save(surf, path)
    n_islands = len(field.islands)
    print(f"preset {preset} {MAP_PRESET_NAMES[preset]:14} islands={n_islands:2} "
          f"land%={100.0 * land.mean():4.1f}  -> {path}")
pygame.quit()
