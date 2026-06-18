"""Probe: measure the M5 acoustic detection floor + the buoy cross-fix quality
BEFORE locking the sonobuoy/ASW test bands (measure-don't-guess).

Reports:
  1. Detection range vs noise state (quiet APPROACH vs loud LAUNCH transient).
  2. ONE buoy -> bearing only (no actionable fix); TWO/THREE buoys -> cross-fix
     quality, and how it sharpens with a wider baseline + more buoys.

Run: python tools/probe_acoustic_asw.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.recon import (AcousticReceiver, SONOBUOY_RANGE_M,
                       ACOUSTIC_DETECT_FLOOR, ACOUSTIC_FIX_ACTIONABLE_M)
from sim.submarine import (Submarine, SUB_APPROACH, SUB_LAUNCH, SUB_DEEP_TRANSIT,
                          SUB_NOISE_APPROACH, SUB_NOISE_LAUNCH,
                          SUB_LAUNCH_TRANSIENT)

DT = 1.0 / 120.0


def _sub_at(xz, state, transient=False, seed=1337):
    s = Submarine(anchor_xz=xz, rng=np.random.default_rng([seed, 13]),
                  kalibr_ammo=4, base_xz=(0.0, 0.0))
    s.state = state
    s.launch_transient = transient
    return s


def detection_ranges():
    print("== Detection range vs noise state "
          f"(floor={ACOUSTIC_DETECT_FLOOR}, cap={SONOBUOY_RANGE_M/1e3:.0f} km) ==")
    for label, state, transient in (
            ("APPROACH (quiet creep)", SUB_APPROACH, False),
            ("DEEP TRANSIT", SUB_DEEP_TRANSIT, False),
            ("LAUNCH (steady)", SUB_LAUNCH, False),
            ("LAUNCH TRANSIENT (spike)", SUB_LAUNCH, True)):
        sub = _sub_at((0.0, 100_000.0), state, transient)
        noise = sub.radiated_noise()
        if transient:
            noise = max(noise, SUB_LAUNCH_TRANSIENT)
        # Binary-search the heard range.
        lo, hi = 0.0, SONOBUOY_RANGE_M + 5_000.0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if AcousticReceiver.heard(noise, mid):
                lo = mid
            else:
                hi = mid
        print(f"  {label:28s} noise={noise:6.1f}  heard within {lo/1e3:6.2f} km")
    print()


def crossfix_quality():
    print("== Buoy cross-fix quality (sub truth at (0, 100 km)) ==")
    sub = _sub_at((0.0, 100_000.0), SUB_LAUNCH, transient=True)
    truth = (float(sub.pos[0]), float(sub.pos[2]))

    layouts = {
        "1 buoy (bearing only)": [(0.0, 80_000.0)],
        "2 buoys, 10 km baseline": [(-5_000.0, 85_000.0), (5_000.0, 85_000.0)],
        "2 buoys, 30 km baseline": [(-15_000.0, 85_000.0), (15_000.0, 85_000.0)],
        "3 buoys, 30 km baseline": [(-15_000.0, 85_000.0), (0.0, 80_000.0),
                                    (15_000.0, 85_000.0)],
        "4 buoys box": [(-15_000.0, 85_000.0), (15_000.0, 85_000.0),
                        (-12_000.0, 110_000.0), (12_000.0, 110_000.0)],
    }
    for label, buoys in layouts.items():
        ar = AcousticReceiver(rng=np.random.default_rng([1337, 14]))
        # Average over several passes to smooth the noisy draw.
        q_samples = []
        est = None
        for _ in range(30):
            ar.update([sub], [np.array([b[0], -15.0, b[1]]) for b in buoys],
                      sim_time=0.0)
            q = ar.fix_quality(sub.sub_id)
            if math.isfinite(q):
                q_samples.append(q)
                est = ar.est_pos(sub.sub_id)
        n = ar.hearing_count(sub.sub_id)
        if not q_samples:
            print(f"  {label:28s} buoys-hearing={n}  NO actionable fix (inf)")
            continue
        q_med = float(np.median(q_samples))
        err = (math.hypot(est[0] - truth[0], est[2] - truth[1])
               if est is not None else float("nan"))
        act = "ACTIONABLE" if q_med < ACOUSTIC_FIX_ACTIONABLE_M else "coarse"
        print(f"  {label:28s} buoys-hearing={n}  q~{q_med/1e3:5.2f} km  "
              f"err={err/1e3:5.2f} km  [{act}]")
    print(f"  (actionable threshold = {ACOUSTIC_FIX_ACTIONABLE_M/1e3:.0f} km)")
    print()


if __name__ == "__main__":
    detection_ranges()
    crossfix_quality()
