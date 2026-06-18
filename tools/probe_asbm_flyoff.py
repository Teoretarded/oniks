"""M4-A ASBM flyoff probe — MEASURE the quasi-ballistic top-attack profile
BEFORE locking the envelope test (project law: physics not dice, measure first).

Mirrors tools/compare_s300_rounds.py: builds an AsbmMissile against a static
SHIP target at a sweep of ranges, steps the real SamMissile loft+PN+fuse
machine, and prints apogee / terminal flight-path-angle / peak Mach / closest
approach / outcome.  The ASBM must LOFT high (apogee >= 40 km) then DIVE
near-vertically onto the SEA (terminal FPA steeper than -60 deg), unlike the
40N6 which holds a 4 km floor.

The draft SamDef lives HERE so the loft/motor numbers can be swept without
touching arsenal.py until the measured profile is known.  Once tuned, the
final values are copied into sim/arsenal.py BASTION_K and the env test is
locked to the band this probe reports.

Run:  python tools/probe_asbm_flyoff.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.arsenal import BASTION_K
from sim.asbm import AsbmMissile
from sim.sam import SPH_TERMINAL

PHYS_DT = 1.0 / 120.0
LAUNCH = np.array([0.0, 5.0, 0.0], dtype=np.float64)

# The LOCKED def from sim/arsenal.py — this probe measures the real round so it
# stays in sync with the env test's band (re-run it after any SamDef edit).
ASBM_DRAFT = BASTION_K


class _World:
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0     # open ocean: surface is sea level (y=0)


class StaticShip:
    """A stationary hull at sea level (deck ~12 m) — the ASBM's anti-ship prey.
    Carries ship_id + is_air=False so it duck-types as a ContactBoard ship and
    is found by the MaRV terminal ship-cone seeker (world.ships)."""

    is_air = False

    def __init__(self, pos, ship_id="tgt"):
        self.pos = np.array(pos, dtype=np.float64)
        self.ship_id = ship_id
        self.alive = True

    def velocity(self):
        return np.zeros(3)

    def kill(self):
        self.alive = False


def _fpa(vel):
    """Flight-path angle (deg): atan2(vy, horizontal speed). Negative = diving."""
    vh = math.hypot(float(vel[0]), float(vel[2]))
    return math.degrees(math.atan2(float(vel[1]), vh))


def flyoff(sam_def, ship, max_t=400.0):
    from sim.physics import mach_scalar
    from sim.sam import SPH_MIDCOURSE
    w = _World()
    w.ships = [ship]
    m = AsbmMissile(sam_def, LAUNCH.copy(), ship)
    apogee = 0.0
    peak_mach = 0.0
    reentry_mach = 0.0          # peak Mach during the terminal dive (< 25 km)
    closest = float("inf")
    handover_fpa = None
    handover_alt = None
    terminal_min_fpa = 0.0      # steepest (most negative) terminal FPA
    midcourse_min_alt = float("inf")   # SM-6 targetability contract (> 1500 m)
    while m.alive and m.t < max_t:
        m.update(PHYS_DT, w)
        spd = float(np.linalg.norm(m.vel))
        alt = float(m.pos[1])
        mach = mach_scalar(spd, alt)
        peak_mach = max(peak_mach, mach)
        apogee = max(apogee, alt)
        closest = min(closest, float(np.linalg.norm(m.pos - ship.pos)))
        if m.phase == SPH_MIDCOURSE:
            midcourse_min_alt = min(midcourse_min_alt, alt)
        if m.phase >= SPH_TERMINAL:
            if alt < 25_000.0:
                reentry_mach = max(reentry_mach, mach)
            f = _fpa(m.vel)
            if handover_fpa is None:
                handover_fpa = f
                handover_alt = alt
            terminal_min_fpa = min(terminal_min_fpa, f)
    outcome = ("KILL" if m.killed_target
               else "self-destruct" if m.self_destructed
               else "miss/impact")
    return dict(apogee_km=apogee / 1000.0, peak_mach=peak_mach,
                reentry_mach=reentry_mach,
                closest_m=closest, t=m.t, outcome=outcome,
                handover_fpa=handover_fpa, handover_alt_km=(
                    handover_alt / 1000.0 if handover_alt is not None else None),
                terminal_min_fpa=terminal_min_fpa,
                midcourse_min_alt=(midcourse_min_alt
                                   if midcourse_min_alt != float("inf")
                                   else None))


def main():
    deck = 12.0
    geometries = [
        ("100 km", [0.0, deck, 100_000.0]),
        ("150 km", [0.0, deck, 150_000.0]),
        ("200 km", [0.0, deck, 200_000.0]),
        ("250 km", [0.0, deck, 250_000.0]),
        ("300 km", [0.0, deck, 300_000.0]),
    ]
    print(f"{'range':8} {'apogee':>8} {'handFPA':>8} {'handAlt':>8} "
          f"{'termFPA':>8} {'pkMach':>7} {'reentM':>7} {'midMin':>8} "
          f"{'closest':>9} {'t':>7}  outcome")
    print("-" * 104)
    for name, tgt in geometries:
        r = flyoff(ASBM_DRAFT, StaticShip(tgt))
        hf = f"{r['handover_fpa']:6.1f}d" if r["handover_fpa"] is not None \
            else "   --  "
        ha = f"{r['handover_alt_km']:6.1f}km" if r["handover_alt_km"] \
            is not None else "   --  "
        mm = f"{r['midcourse_min_alt']:6.0f}m" if r["midcourse_min_alt"] \
            is not None else "   --  "
        print(f"{name:8} {r['apogee_km']:6.1f}km {hf:>8} {ha:>8} "
              f"{r['terminal_min_fpa']:6.1f}d {r['peak_mach']:6.2f} "
              f"{r['reentry_mach']:6.2f} {mm:>8} "
              f"{r['closest_m']:8.0f}m {r['t']:6.1f}s  {r['outcome']}",
              flush=True)


if __name__ == "__main__":
    main()
