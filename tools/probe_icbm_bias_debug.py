"""Debug probe: per-iteration drag-bias behavior on the 700 km shot."""

from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game.cinematic_icbm as ci                     # noqa: E402

DT = 1.0 / 120.0

lch = ci.IcbmLaunch(ci.ICBM_BY_ID["mm3"], silo=(0.0, 0.0, 0.0),
                    target=(700_000.0, 0.0, 0.0), ground_h=lambda x, z: 0.0)
print(f"toa={lch._toa:.1f}")

orig = ci.IcbmLaunch._ballistic_impact


def spy(self, pos, vel, t_max=2400.0):
    hit = orig(self, pos, vel, t_max)
    aim_off = float(lch._aim[0] - lch._target[0])
    hx = None if hit is None else float(hit[0])
    print(f"  predict: aim_dx={aim_off:12.0f}  vel=({vel[0]:7.0f},"
          f"{vel[1]:7.0f})  hit_x={hx}")
    return hit


ci.IcbmLaunch._ballistic_impact = spy

t = 0.0
imp = None
while not lch.done and t < 1200.0:
    evs = []
    lch.step(DT, evs)
    t += DT
    for k, p in evs:
        if k in ("term", "cutoff"):
            print(f"t={t:.1f} {k} v={np.linalg.norm(lch.vel):.0f} "
                  f"alt={lch.pos[1]:.0f} pos_x={lch.pos[0]:.0f} "
                  f"aim_dx={lch._aim[0] - lch._target[0]:.0f}")
            coast = orig(lch, lch.pos, lch.vel)
            print(f"  coast-from-term predicts x="
                  f"{None if coast is None else round(float(coast[0]))}")
        if k == "impact":
            imp = p
if imp is not None:
    print(f"impact x={imp[0]:.0f} miss={imp[0] - 700_000.0:.0f}")
