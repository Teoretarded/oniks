"""MEASURE the two Buk rounds with a controlled two-round flyoff (mirror of
tools/compare_s300_rounds.py).

Builds each SamMissile (9M317 long reach / 9M338 agile) against the SAME
targets, steps the real flight model, and reports apogee, peak speed, closest
approach, terminal-handover altitude, time and outcome — so the
"distinct behaviour" claim (agile turns harder -> smaller miss; long reaches
farther -> kills beyond the agile envelope) is checked with NUMBERS before the
bands are locked in tests/test_buk.py.

Two probe panels:
  (A) STATIC REACH  — static targets at increasing range, both rounds: shows
      where the agile 9M338 starts to fall short and the long 9M317 still
      kills.
  (B) HARD CROSSER  — a fast crossing target inside both envelopes: shows the
      agile round's tighter terminal miss (the max_g discriminator).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.sam import SamMissile, SPH_TERMINAL
from sim.arsenal import BUK_LONG, BUK_AGILE

PHYS_DT = 1.0 / 120.0
LAUNCH = np.array([0.0, 5.0, 0.0], dtype=np.float64)


class _World:
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0


class StaticTarget:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.zeros(3)

    def kill(self):
        self.alive = False


class MovingTarget:
    def __init__(self, pos, vel):
        self.pos = np.array(pos, dtype=np.float64)
        self.vel = np.array(vel, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return self.vel

    def kill(self):
        self.alive = False

    def update(self, dt):
        self.pos = self.pos + self.vel * dt


def flyoff(sam_def, target, max_t=200.0):
    world = _World()
    m = SamMissile(sam_def, LAUNCH.copy(), target)
    apogee = vmax = 0.0
    closest = float("inf")
    handover_alt = None
    while m.alive and m.t < max_t:
        if hasattr(target, "update"):
            target.update(PHYS_DT)
        m.update(PHYS_DT, world)
        if handover_alt is None and m.phase >= SPH_TERMINAL:
            handover_alt = float(m.pos[1])
        apogee = max(apogee, float(m.pos[1]))
        vmax = max(vmax, float(np.linalg.norm(m.vel)))
        closest = min(closest, float(np.linalg.norm(m.pos - target.pos)))
    outcome = ("KILL" if m.killed_target
               else "self-destruct" if m.self_destructed
               else "miss/impact")
    return dict(apogee_km=apogee / 1000.0, vmax=vmax, closest_m=closest,
                t=m.t, outcome=outcome,
                handover_km=(handover_alt / 1000.0
                             if handover_alt is not None else None))


def _row(tag, r):
    ho = f"{r['handover_km']:6.1f}km" if r["handover_km"] else "    --  "
    print(f"  {tag:6} {r['apogee_km']:6.1f}km {ho:>9} {r['vmax']:6.0f}m/s "
          f"{r['closest_m']:9.0f}m {r['t']:6.1f}s  {r['outcome']}", flush=True)


def main():
    lx, lz = float(LAUNCH[0]), float(LAUNCH[2])

    print("=== (A) STATIC REACH (where 9M338 falls short, 9M317 still kills) ===")
    print(f"  {'round':6} {'apogee':>8} {'handover':>9} {'vmax':>9} "
          f"{'closest':>9} {'time':>7}  outcome")
    static_geo = [
        ("close 20km @ 4km",   [lx, 4_000.0, lz + 20_000.0]),
        ("med  30km @ 6km",    [lx, 6_000.0, lz + 30_000.0]),
        ("med  40km @ 8km",    [lx, 8_000.0, lz + 40_000.0]),
        ("far  50km @ 8km",    [lx, 8_000.0, lz + 50_000.0]),
        ("far  60km @ 8km",    [lx, 8_000.0, lz + 60_000.0]),
        ("vfar 70km @ 10km",   [lx, 10_000.0, lz + 70_000.0]),
    ]
    for name, tgt in static_geo:
        print(f"-- {name}")
        for tag, sdef in (("9M317", BUK_LONG), ("9M338", BUK_AGILE)):
            _row(tag, flyoff(sdef, StaticTarget(tgt)))

    print("\n=== (B) HARD CROSSER (agile 9M338 turns tighter -> smaller miss) ===")
    print(f"  {'round':6} {'apogee':>8} {'handover':>9} {'vmax':>9} "
          f"{'closest':>9} {'time':>7}  outcome")
    cross_geo = [
        ("20km @ 5km x300", [lx, 5_000.0, lz + 20_000.0], [300.0, 0.0, 0.0]),
        ("25km @ 5km x350", [lx, 5_000.0, lz + 25_000.0], [350.0, 0.0, 0.0]),
        ("30km @ 6km x350", [lx, 6_000.0, lz + 30_000.0], [350.0, 0.0, 0.0]),
    ]
    for name, pos, vel in cross_geo:
        print(f"-- {name}")
        for tag, sdef in (("9M317", BUK_LONG), ("9M338", BUK_AGILE)):
            _row(tag, flyoff(sdef, MovingTarget(pos, vel)))


if __name__ == "__main__":
    main()
