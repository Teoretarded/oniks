"""Render EVERY missile model from side / top / BOTTOM / quarter views.

Run: python tools/render_missile_views.py

The in-game camera rig ground-clamps and never looks straight up or down,
so model errors on the ventral side have historically been invisible
(user call-out 2026-07-06).  This tool drives the raw engine Camera with
an explicit up-hint, so true overhead and belly views render fine.
Output: documentation and research/01_missile_physics_and_models/renders/
<missile>_{side,top,bottom,quarter}.png — the review set for the fin/model
pass (compare against references/ in the same folder).
"""

from __future__ import annotations

import math
import os
import sys
import tempfile

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="oniks_missile_views_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from engine.mesh import Mesh
from main import App
from models.missiles import (build_40n6, build_48n6, build_57e6,
                             build_aim9x, build_harm, build_jassm,
                             build_kh31p, build_sm2, build_sm6,
                             build_tomahawk, build_zircon)
from models.oniks import build_oniks

OUT = os.path.join("documentation and research",
                   "01_missile_physics_and_models", "renders")

BUILDERS = {
    "oniks": build_oniks,
    "zircon": build_zircon,
    "tomahawk_kalibr": build_tomahawk,     # kalibr renders this alias
    "jassm": build_jassm,
    "harm": build_harm,
    "kh31p": build_kh31p,
    "s300_48n6": build_48n6,
    "s300_40n6": build_40n6,
    "sm2": build_sm2,
    "sm6": build_sm6,
    "pantsir_57e6": build_57e6,
    "aim9x": build_aim9x,
}

ALT = 500.0                     # render altitude: away from any terrain


def _views(dist):
    """(name, eye_offset, forward, up) — missile long axis is +Z."""
    return [
        ("side", (dist, 0.0, 0.0), (-1.0, 0.0, 0.0), (0, 1, 0)),
        ("top", (0.0, dist, 0.0), (0.0, -1.0, 0.0), (0, 0, 1)),
        ("bottom", (0.0, -dist, 0.0), (0.0, 1.0, 0.0), (0, 0, 1)),
        ("quarter", (dist * 0.7, dist * 0.5, -dist * 0.55),
         (-0.7, -0.5, 0.55), (0, 1, 0)),
    ]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = App(hidden=True)
    renderer = app.renderer
    cam = renderer.__class__  # noqa: F841 (renderer owns no camera; make one)
    from engine.camera import Camera
    camera = Camera()
    w, h = app.window.size()
    pos = np.array([0.0, ALT, 0.0])
    for name, builder in BUILDERS.items():
        mesh = Mesh(builder())
        dist = max(4.0, mesh.radius * 2.3)
        for vname, off, fwd, up in _views(dist):
            camera.eye = pos + np.asarray(off, dtype=np.float64)
            camera.set_orientation(np.asarray(fwd, dtype=np.float64),
                                   up=up)
            renderer.begin(camera, w / h)
            renderer.draw_mesh(mesh, pos)
            pygame.image.save(app.window.read_pixels_to_surface(),
                              os.path.join(OUT, f"{name}_{vname}.png"))
        mesh.delete()
        print(f"[views] {name} (radius {mesh.radius:.1f} m)")
    pygame.quit()
    print(f"[views] -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
