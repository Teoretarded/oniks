"""Probe: ICBM drag/bias flight numbers (GL-free, prints a table).

Run: python tools/probe_icbm_physics.py
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game.cinematic_icbm import ICBM_BY_ID, IcbmLaunch   # noqa: E402

DT = 1.0 / 120.0


def fly(label, silo, target, ground, max_s=2400.0):
    lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=silo, target=target,
                     ground_h=ground)
    print(f"--- {label}: toa={lch._toa:.1f}s")
    t = 0.0
    prev_v = 0.0
    peak_dec = 0.0
    peak_alt = 0.0
    impact = None
    last_report = -10.0
    while not lch.done and t < max_s:
        evs = []
        lch.step(DT, evs)
        t += DT
        sp = float(np.linalg.norm(lch.vel))
        if lch.rv_only and lch.vel[1] < 0.0 and prev_v:
            dec = (prev_v - sp) / DT
            if dec > peak_dec:
                peak_dec, peak_alt = dec, float(lch.pos[1])
        prev_v = sp
        for k, p in evs:
            if k in ("term", "cutoff", "stage") and t - last_report > 1:
                last_report = t
                aim_off = math.hypot(lch._aim[0] - lch._target[0],
                                     lch._aim[2] - lch._target[2])
                print(f"  t={t:7.1f} {k:6s} v={sp:7.1f} "
                      f"alt={lch.pos[1]:9.0f} aim_off={aim_off:8.0f}")
            if k == "impact":
                impact = p
        if impact is not None:
            break
    if lch.burnout_t and lch.ignite_t:
        print(f"  powered={lch.burnout_t - lch.ignite_t:.1f}s")
    if impact is not None:
        miss = math.hypot(impact[0] - target[0], impact[2] - target[2])
        print(f"  impact t={t:.1f} v={prev_v:.0f} miss={miss:.0f} m "
              f"peak_dec={peak_dec / 9.81:.1f} g @ {peak_alt:.0f} m")
    else:
        print(f"  NO IMPACT (t={t:.1f}, pos={lch.pos}, done={lch.done})")


fly("60 km map shot", (0.0, 800.0, 0.0), (60_000.0, 800.0, 20_000.0),
    lambda x, z: 800.0)
fly("3500 km range shot", (0.0, 0.0, 0.0), (3_500_000.0, 0.0, 0.0),
    lambda x, z: 0.0)
