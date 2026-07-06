"""X-ray hit-cam visual gate: render the cutaway with staged snapshots.

Run: python tools/shoot_hitcam.py
Saves renders/hitcam_*.png — a normal Oniks engine-room hit, an ARM
mission-kill, and a magazine-detonation catastrophe, drawn through the
REAL CombatState render path (hidden GL window).
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="oniks_hitcam_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from main import App
from sim.damage_model import BURKE_GRID

OUT = "renders"


def _snap(new_dead, all_dead, flood, fire, fire_z, impact, ke, pen,
          breach, weapon, cat, diw):
    return {"ship_type": "destroyer", "grid": BURKE_GRID,
            "kinds": {r[0]: r[6] for r in BURKE_GRID},
            "new_dead": new_dead, "all_dead": all_dead, "flood": flood,
            "fire": fire, "fire_z": fire_z, "impact": impact, "ke": ke,
            "penetrated": pen, "breach_m2": breach, "weapon": weapon,
            "catastrophe": cat, "dead_in_water": diw}


SNAPS = [
    ("hitcam_oniks_engine.png", _snap(
        ["mer2_port", "fuel_f76"], ["mer2_port", "fuel_f76"],
        [0.0, 0.0, 0.55, 0.1, 0.0, 0.0], 0.72, 0.38, (0.36, -0.3, -1.0),
        5.8e8, True, 3.9, "oniks", False, False)),
    ("hitcam_arm_mast.png", _snap(
        ["mast"], ["mast"], [0.0] * 6, 0.0, 0.5, (0.63, 1.05, -1.0),
        1.5e8, False, 0.0, "kh31p", False, False)),
    ("hitcam_magazine.png", _snap(
        ["vls_aft_64"], ["vls_aft_64", "mer2_port", "fuel_f76"],
        [0.9, 0.9, 0.9, 0.9, 0.9, 0.9], 1.0, 0.65, (0.65, 0.0, -1.0),
        3.6e9, True, 14.0, "zircon", True, True)),
]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = App(hidden=True)
    app.start_combat()                       # subsystem fallback config
    state = app.sandbox
    for _ in range(4):
        state.render(1.0 / 60.0)
    for name, snap in SNAPS:
        state.hitcam.notify(snap)
        state.render(1.0 / 60.0)
        pygame.image.save(app.window.read_pixels_to_surface(),
                          os.path.join(OUT, name))
        state.hitcam.dismiss()
        print(f"[hitcam] {name}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
