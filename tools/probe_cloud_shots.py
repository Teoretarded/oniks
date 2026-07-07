"""F3-P4 screenshot gate: render the cloud pass from 3 named viewpoints
hidden and save PNGs to renders/ for eyeball judgment against the
references (WT Dagor cumulus bank / Nubis figures).

Run:  python -m tools.probe_cloud_shots [seed]
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

VIEWS = (
    # name, cam pos (x, y, z), yaw, pitch
    ("ground_horizon", (0.0, 60.0, 5_000.0), 0.0, 0.12),
    ("inside_layer", (0.0, 1_400.0, 40_000.0), 0.3, 0.05),
    ("above_looking_down", (0.0, 9_000.0, 60_000.0), 0.0, -0.5),
)


def _save_frame(window, path):
    from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels
    w, h = window.size()
    buf = glReadPixels(0, 0, w, h, GL_RGB, GL_UNSIGNED_BYTE)
    surf = pygame.image.frombytes(buf, (w, h), "RGB", True)
    pygame.image.save(surf, str(path))
    print(f"[shots] wrote {path}")


def main(seed: int = 7) -> int:
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from main import App, PHYS_DT
    app = App(hidden=True)
    app.start_sandbox()
    s = app.state
    for _ in range(120):
        s.sim_step(PHYS_DT)          # settle particles / streams
    os.makedirs("renders", exist_ok=True)
    s.hud_visible = False
    s.rig.set_mode("free")
    for name, pos, yaw, pitch in VIEWS:
        s.rig.freecam.pos = np.array(pos, dtype=np.float64)
        s.rig.freecam.yaw = yaw
        s.rig.freecam.pitch = pitch
        s.rig.update(0.0, None)
        for _ in range(240):         # let terrain LOD stream for the view
            s.render(1 / 60)
            if not s.terrain._jobs:
                break
        s.render(1 / 60)
        _save_frame(s.window, f"renders/clouds_{name}_seed{seed}.png")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 7))
