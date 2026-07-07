"""Cloud 360-degree screenshot sweep (v6 gate; playtest 2026-07-07 round 2
caught artifacts only visible at oblique angles/altitudes the 5-view probe
never rendered).

Per altitude (2/10/30/50 km): four compass headings at a shallow down
pitch, one straight up, one straight down — stitched into ONE contact
sheet per altitude (renders/cloud_sweep_{alt}km_seed{N}.png) so a
reviewer reads 4 images, not 24.

Run:  python -m tools.probe_cloud_sweep [seed]
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

ALTS_M = (2_000.0, 10_000.0, 30_000.0, 50_000.0)
CAM_XZ = (0.0, 40_000.0)
TILE_W, TILE_H = 500, 281          # per-view thumbnail in the sheet


def _grab(window):
    from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels
    w, h = window.size()
    buf = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    return pygame.image.frombytes(buf, (w, h), "RGB", True)


def main(seed: int = 7) -> int:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from main import App, PHYS_DT
    app = App(hidden=True)
    app.start_sandbox()
    s = app.state
    for _ in range(120):
        s.sim_step(PHYS_DT)
    os.makedirs("renders", exist_ok=True)
    s.hud_visible = False
    s.rig.set_mode("free")

    views = [(f"N", 0.0, -0.15), ("E", math.pi / 2, -0.15),
             ("S", math.pi, -0.15), ("W", 3 * math.pi / 2, -0.15),
             ("UP", 0.0, 1.45), ("DOWN", 0.0, -1.50)]
    font = pygame.font.SysFont("consolas", 16)
    for alt in ALTS_M:
        sheet = pygame.Surface((TILE_W * 3, TILE_H * 2))
        for idx, (label, yaw, pitch) in enumerate(views):
            s.rig.freecam.pos = np.array([CAM_XZ[0], alt, CAM_XZ[1]],
                                         dtype=np.float64)
            s.rig.freecam.yaw = yaw
            s.rig.freecam.pitch = pitch
            s.rig.update(0.0, None)
            settle = 240 if idx == 0 else 40   # LOD streams once per altitude
            for _ in range(settle):
                s.render(1 / 60)
                if not s.terrain._jobs:
                    break
            s.render(1 / 60)
            thumb = pygame.transform.smoothscale(_grab(s.window),
                                                 (TILE_W, TILE_H))
            thumb.blit(font.render(f"{label} {alt/1000:.0f}km", True,
                                   (255, 220, 40), (0, 0, 0)), (6, 6))
            sheet.blit(thumb, ((idx % 3) * TILE_W, (idx // 3) * TILE_H))
        path = f"renders/cloud_sweep_{alt/1000:.0f}km_seed{seed}.png"
        pygame.image.save(sheet, path)
        print(f"[sweep] wrote {path}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 7))
