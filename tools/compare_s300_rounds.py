"""Show the 48N6 vs 40N6 difference with a controlled two-round flyoff.

Builds each SamMissile against the SAME static targets, steps the real flight
model, and reports apogee, peak speed, closest approach, time and outcome - so
the "they go the same speed and range" claim can be checked with numbers. Also
dumps each trajectory (downrange, altitude) to tools/flyoff_traj.json for a plot.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from playtest_harness import build_world
from sim.sam import SamMissile, SPH_TERMINAL
from sim.arsenal import S300, N40N6
from world.world import SAM_TEL_POS

PHYS_DT = 1.0 / 120.0
LAUNCH = np.asarray(SAM_TEL_POS, dtype=np.float64)   # the real S-300 pad


class StaticTarget:
    def __init__(self, pos):
        self.pos = np.array(pos, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return np.zeros(3)


def flyoff(world, sam_def, tgt_pos, max_t=420.0):
    target = StaticTarget(tgt_pos)
    m = SamMissile(sam_def, LAUNCH.copy(), target)
    apogee = vmax = 0.0
    closest = float("inf")
    handover_alt = None        # altitude when terminal PN takes over
    traj = []
    next_s = 0.0
    while m.alive and m.t < max_t:
        m.update(PHYS_DT, world)
        if handover_alt is None and m.phase >= SPH_TERMINAL:
            handover_alt = float(m.pos[1])
        apogee = max(apogee, float(m.pos[1]))
        vmax = max(vmax, float(np.linalg.norm(m.vel)))
        closest = min(closest, float(np.linalg.norm(m.pos - target.pos)))
        if m.t >= next_s:
            traj.append([round(float(m.pos[2] - LAUNCH[2]), 1),
                         round(float(m.pos[1]), 1)])
            next_s += 1.0
    outcome = ("KILL" if m.killed_target
               else "self-destruct" if m.self_destructed
               else "miss/impact")
    return dict(apogee_km=apogee / 1000.0, vmax=vmax, closest_m=closest,
                t=m.t, outcome=outcome, traj=traj,
                handover_km=(handover_alt / 1000.0
                             if handover_alt is not None else None))


def main():
    world = build_world(7, n_destroyers=4)
    lx, lz = float(LAUNCH[0]), float(LAUNCH[2])
    geometries = [
        ("close 60km @ 15km",        [lx, 15_000.0, lz + 60_000.0]),
        ("in-envelope 120km @ 18km", [lx, 18_000.0, lz + 120_000.0]),
        ("medium 200km @ 20km",      [lx, 20_000.0, lz + 200_000.0]),
        ("long 300km @ 24km",        [lx, 24_000.0, lz + 300_000.0]),
        ("v-long 360km @ 26km",      [lx, 26_000.0, lz + 360_000.0]),
    ]
    print(f"{'geometry':26} {'round':5} {'apogee':>8} {'handover':>9} "
          f"{'vmax':>9} {'closest':>9} {'time':>7}  outcome")
    print("-" * 90)
    dump = {}
    for name, tgt in geometries:
        rounds = {}
        for tag, sdef in (("48N6", S300), ("40N6", N40N6)):
            r = flyoff(world, sdef, tgt)
            rounds[tag] = r
            dump[f"{name} | {tag}"] = r["traj"]
            ho = f"{r['handover_km']:6.1f}km" if r["handover_km"] else "    --  "
            print(f"{name:26} {tag:5} {r['apogee_km']:6.1f}km {ho:>9} "
                  f"{r['vmax']:6.0f}m/s {r['closest_m']:8.0f}m "
                  f"{r['t']:6.1f}s  {r['outcome']}", flush=True)
        # Distinctness summary: how much higher did the 40N6 fly?
        d_apogee = rounds["40N6"]["apogee_km"] - rounds["48N6"]["apogee_km"]
        reach = ""
        if rounds["48N6"]["outcome"] != "KILL" and rounds["40N6"]["outcome"] == "KILL":
            reach = "  <-- 40N6 reaches where 48N6 cannot"
        print(f"{'':26} {'apo':5} {d_apogee:+5.1f}km vs 48N6 arc{reach}\n")
    with open("tools/flyoff_traj.json", "w", encoding="utf-8") as fh:
        json.dump(dump, fh)
    print("[traj] tools/flyoff_traj.json written")


if __name__ == "__main__":
    main()
