"""X-ray hit-cam visual gate: render the animated cutaway at key beats.

Run: python tools/shoot_hitcam.py
Saves renders/hitcam_*.png through the REAL CombatState render path:
tracer beat, fragment-fan frame, settled frame for an Oniks engine hit;
settled frames for an ARM non-pen mission-kill and a magazine catastrophe.
"""

from __future__ import annotations

import os
import sys
import tempfile

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="oniks_hitcam_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from game.hitcam import HITCAM_S
from main import App
from sim.damage_model import BURKE_GRID, TOUGHNESS

OUT = "renders"


def _snap(new_dead, all_dead, dose, flood, fire, fire_z, entry, det, ke,
          pen, breach, weapon, cat, diw, blast_frac=0.075):
    return {"ship_type": "destroyer", "grid": BURKE_GRID,
            "kinds": {r[0]: r[6] for r in BURKE_GRID},
            "toughness": {r[0]: TOUGHNESS.get(r[6], 1e9) for r in BURKE_GRID},
            "new_dead": new_dead, "all_dead": all_dead, "dose": dose,
            "flood": flood, "fire": fire, "fire_z": fire_z,
            "impact": entry, "entry": entry, "det": det,
            "blast_frac": blast_frac, "ke": ke, "penetrated": pen,
            "breach_m2": breach, "weapon": weapon,
            "catastrophe": cat, "dead_in_water": diw}


ONIKS = _snap(["mer2_port", "fuel_f76", "aux2"],
              ["mer2_port", "fuel_f76", "aux2"],
              {"mer1_stbd": 250.0},                 # partial dose: orange
              [0.0, 0.0, 0.55, 0.1, 0.0, 0.0], 0.72, 0.38,
              (0.30, -0.30, -1.0), (0.42, -0.55, -0.2),
              5.8e8, True, 3.9, "oniks", False, False)
ARM = _snap(["mast", "spy_aft"], ["mast", "spy_aft"], {},
            [0.0] * 6, 0.0, 0.5,
            (0.70, 1.10, -1.0), (0.63, 1.05, -0.1),
            1.5e8, False, 0.0, "kh31p", False, False)
BOOM = _snap(["vls_aft_64"],
             ["vls_aft_64", "mer2_port", "fuel_f76"],
             {},
             [0.9] * 6, 1.0, 0.65,
             (0.60, 0.35, -1.0), (0.65, -0.10, 0.0),
             3.6e9, True, 14.0, "zircon", True, True, blast_frac=0.12)

SHOTS = [  # (filename, snapshot, playback time seconds)
    ("hitcam_1_tracer.png", ONIKS, 0.25),
    ("hitcam_2_fan.png", ONIKS, 1.15),
    ("hitcam_3_settled.png", ONIKS, 3.5),
    ("hitcam_4_arm_stopped.png", ARM, 3.5),
    ("hitcam_5_magazine.png", BOOM, 3.5),
]


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = App(hidden=True)
    app.start_combat()
    state = app.sandbox
    for _ in range(4):
        state.render(1.0 / 60.0)
    for name, snap, t in SHOTS:
        state.hitcam.notify(snap)
        state.hitcam.left = HITCAM_S - t          # scrub to the beat
        state.render(1.0 / 60.0)
        pygame.image.save(app.window.read_pixels_to_surface(),
                          os.path.join(OUT, name))
        state.hitcam.dismiss()
        print(f"[hitcam] {name}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
