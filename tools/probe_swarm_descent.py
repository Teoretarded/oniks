"""M4-B probe: does a REAL subsonic SWARM round splash a ship in a lo-lo run?

The diagnosed bug (sim/missile.py): ``self._descent_scale = max(1.0, ...)``.
The floor forces a slower-than-Oniks weapon to use the FULL Mach-2.5 Oniks
descent authority (ramp 220 m/s, sink clamp 260 m/s, pull-down 60 m/s^2). For
the subsonic SWARM (cruise_mach_hi 0.45 -> ground speed ~110-150 m/s) that is a
near-vertical plunge: the round over-dives and hits the sea SHORT of the hull.

This probe flies a REAL Missile(SWARM, ...) lo-lo at a stationary destroyer at a
few ranges, under SEVERAL candidate descent-scale schemes, and prints the
closest-approach-to-hull and the impact range for each. It MEASURES which scheme
puts the round on the hull at sea-skim without overflying or sea-slamming short.

No _LevelSwarm stub anywhere — the round flies the honest phase machine
(eject/boost/cruise/descent/terminal/seeker) end-to-end via Missile.update.

Run: python tools/probe_swarm_descent.py
"""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sim.missile as M
from sim.arsenal import SWARM
from sim.damage import segment_hits_obb
from sim.ships import Ship


DT = 1.0 / 120.0
BASELINE = M.DESCENT_BASELINE_MACH   # 2.55


class _OpenSea:
    """Deep open ocean, no terrain — one stationary destroyer."""

    def __init__(self, ship):
        self.ships = [ship]

    def terrain_height_at(self, x, z):
        return -500.0

    def surface_height_at(self, x, z):
        return 0.0


def _make_ship(aim_xz):
    """A stationary destroyer at ``aim_xz`` heading north (beam-on to a round
    flying due north up the +Z axis -> the 155 m hull broadside is the target).
    Lane is a tiny segment so it sits put; speed is forced to zero."""
    s = Ship("probe_dd", "destroyer",
             [[aim_xz[0], aim_xz[1] - 1.0], [aim_xz[0], aim_xz[1] + 1.0]],
             0.5, direction=1)
    s.pos[:] = (aim_xz[0], 0.0, aim_xz[1])
    s.speed = 0.0
    s.heading = math.radians(90.0)   # beam-on to a north-bound round
    return s


def closest_approach_and_impact(scale_scheme, run_in_m, frames=200_000):
    """Fly a REAL SWARM round lo-lo from the coast (z=0) due north at a
    stationary destroyer ``run_in_m`` away. ``scale_scheme`` is a callable
    weapon -> descent scale, installed by monkey-patching the one line under
    test. Returns (closest_hull_m, impacted_ship, impact_range_m, end_phase,
    min_alt_after_descent)."""
    aim = np.array([0.0, 0.0, run_in_m], dtype=np.float64)
    ship = _make_ship((0.0, run_in_m))
    world = _OpenSea(ship)
    center, half, rot = ship.obb()

    m = M.Missile(SWARM, np.array([0.0, 0.0, 0.0]), 0.0, "lo-lo", aim,
                  target_ship=ship)
    m.is_hostile = False
    # Install the candidate descent scale (the line under test).
    m._descent_scale = float(scale_scheme(SWARM))

    closest = float("inf")
    impacted = False
    impact_range = None
    entered_descent = False
    min_alt = float("inf")
    for _ in range(frames):
        prev = m.pos.copy()
        m.update(DT, world)
        # closest approach of the swept segment midpoint to the hull center,
        # measured as point-distance to the OBB surface (approx via center dist
        # minus half-diagonal is too loose; use the genuine hit test for the
        # splash and a hull-center horizontal range for "how close").
        seg_mid = (prev + m.pos) * 0.5
        local = rot.T @ (seg_mid - center)
        # distance from the box surface (0 inside):
        dx = max(abs(local[0]) - half[0], 0.0)
        dy = max(abs(local[1]) - half[1], 0.0)
        dz = max(abs(local[2]) - half[2], 0.0)
        d_surf = math.sqrt(dx * dx + dy * dy + dz * dz)
        closest = min(closest, d_surf)
        if m.phase == M.PH_DESCENT or m.phase == M.PH_TERMINAL:
            entered_descent = True
        if entered_descent:
            min_alt = min(min_alt, float(m.pos[1]))
        # real OBB splash test (same predicate as sim/damage.apply_missile_hits)
        if segment_hits_obb(prev, m.pos, center, half, rot):
            impacted = True
            impact_range = run_in_m - float(m.pos[2])
            break
        if not m.alive:
            impact_range = run_in_m - float(m.pos[2])
            break
    return closest, impacted, impact_range, int(m.phase), min_alt


# --- candidate descent-scale schemes ----------------------------------------

SCHEMES = {
    # The CURRENT floored scale: max(1.0, mach/baseline). For SWARM this is the
    # full Oniks authority (1.0) — the bug.
    "current_floored":
        lambda w: max(1.0, w.cruise_mach_hi / BASELINE),
    # Floor REMOVED: the raw ratio. Subsonic -> gentle dive (~0.18 for SWARM).
    "raw_ratio":
        lambda w: w.cruise_mach_hi / BASELINE,
    # Raw ratio but using the LO cruise mach (the lo-lo band the swarm flies).
    "raw_ratio_lo":
        lambda w: w.cruise_mach_lo / BASELINE,
    # A mild clamp floor (so a near-Oniks weapon is unchanged but the subsonic
    # round still gets a softened authority).
    "clamp_0p35":
        lambda w: max(0.35, w.cruise_mach_hi / BASELINE),
    "clamp_0p5":
        lambda w: max(0.5, w.cruise_mach_hi / BASELINE),
}


def main():
    ranges = [25_000.0, 35_000.0, 45_000.0]
    print(f"SWARM cruise_mach_hi={SWARM.cruise_mach_hi} "
          f"cruise_mach_lo={SWARM.cruise_mach_lo} "
          f"baseline={BASELINE} terminal_range={SWARM.terminal_range} "
          f"skim_alt={SWARM.skim_alt} lo_alt={SWARM.lo_alt}")
    print(f"raw_ratio_hi={SWARM.cruise_mach_hi / BASELINE:.4f} "
          f"raw_ratio_lo={SWARM.cruise_mach_lo / BASELINE:.4f}")
    # The LOAD-BEARING fix (MEASURED): the per-weapon stall speed. A flat
    # STALL_SPEED=200 faded the subsonic round's gravity-comp lift to ~0.42 and
    # sagged it ~38 m under every commanded altitude -> sank ~7.5 km short. With
    # the per-weapon stall the round holds skim and the descent scheme barely
    # matters (every scheme below SPLASHES at 25 km). Beyond ~25 km the round is
    # capped by the Oniks-sized boost OVERSHOOT (it zooms to Mach ~6 / ~3.7 km
    # and crashes back down at z~24.6 km) — a separate, documented concern.
    probe_m = M.Missile(SWARM, np.array([0.0, 0.0, 0.0]), 0.0, "lo-lo",
                        np.array([0.0, 0.0, 25_000.0]))
    print(f"per-weapon stall_speed={probe_m._stall_speed:.3f} m/s "
          f"(flat STALL_SPEED={M.STALL_SPEED})")
    print()
    hdr = (f"{'scheme':<18}{'range_km':>9}{'scale':>8}{'closest_m':>11}"
           f"{'SPLASH':>8}{'impact_km':>11}{'min_alt_m':>11}{'end_ph':>8}")
    print(hdr)
    print("-" * len(hdr))
    for name, fn in SCHEMES.items():
        scale = fn(SWARM)
        for r in ranges:
            closest, hit, imp, ph, min_alt = closest_approach_and_impact(fn, r)
            imp_km = "n/a" if imp is None else f"{imp / 1000.0:.2f}"
            ma = "n/a" if min_alt == float("inf") else f"{min_alt:.1f}"
            print(f"{name:<18}{r/1000:>9.0f}{scale:>8.3f}{closest:>11.1f}"
                  f"{('YES' if hit else 'no'):>8}{imp_km:>11}{ma:>11}"
                  f"{ph:>8}")
        print()


if __name__ == "__main__":
    main()
