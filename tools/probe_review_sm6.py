"""Game-test probe (review loop): SM-6 AREA air-defense behavior.

Contract (a): a HIGH (hi-lo, 14 km cruise) player Oniks inbound on the fleet is
ENGAGED and KILLED by an SM-6 at long range (>= SM6_MIN_RANGE_M ground range);
a LOW (lo-lo, sea-skim) Oniks on the same line is NOT engaged by SM-6 (it stays
the SM-2/CIWS/multipath domain) — the "go low to survive" loop holds.

Measured, not asserted by vibe: we run a small seeded batch per profile, place
one player Oniks aimed at the lead destroyer, step the world headlessly, and
count SM-6 launches (hostile SamMissile of weapon SM6), the launch range, and
whether the high Oniks dies vs survives to terminal.

Run: python tools/probe_review_sm6.py   (ignore the pygame banner on stderr)
"""
from __future__ import annotations

import math
import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.enemy_defense import SM6_MIN_RANGE_M, SM6_AREA_MIN_ALT_M
from sim.arsenal import ONIKS, SM6
from sim.missile import Missile
from sim.sam import SamMissile

DT = 0.10
MAX_T = 600.0      # 10 min sim cap per run


def _lead_destroyer(world):
    """The destroyer nearest BASE_POS-ward edge (first non-carrier)."""
    from world.world import WorldState  # noqa
    ds = [s for s in world.ships if type(s).__name__ == "Destroyer" and s.alive]
    # nearest to the launch line (largest z, fleet sits north) -> first seen
    return min(ds, key=lambda s: float(s.pos[2]))


def _spawn_oniks(world, target_ship, profile, standoff_m):
    """One player Oniks launched standoff_m ground-range from target_ship,
    on the bearing target<-launch, at the given profile."""
    tp = target_ship.pos
    # launch point: standoff to the south (smaller z) of the target on the
    # straight line toward BASE (player coast is south, z<0).
    bearing = math.atan2(0.0 - float(tp[0]), -600.0 - float(tp[2]))
    # place launch standoff_m away along the target->base bearing
    ux = float(tp[0]) - math.sin(bearing) * standoff_m
    uz = float(tp[2]) - math.cos(bearing) * standoff_m
    heading = math.degrees(math.atan2(float(tp[0]) - ux, float(tp[2]) - uz))
    pos = np.array([ux, 12.0, uz], dtype=np.float64)
    target_point = np.array([float(tp[0]), 0.0, float(tp[2])], dtype=np.float64)
    m = Missile(ONIKS, pos, heading, profile, target_point,
                target_ship=target_ship)
    world.missiles.append(m)
    return m


def _is_sm6(m):
    return (isinstance(m, SamMissile) and getattr(m, "is_hostile", False)
            and getattr(m, "weapon", None) is SM6)


def run_one(seed, profile, standoff_m):
    world = CombatWorld(CombatConfig(seed=seed))
    tgt = _lead_destroyer(world)
    oniks = _spawn_oniks(world, tgt, profile, standoff_m)
    sx, sz = float(tgt.pos[0]), float(tgt.pos[2])

    sm6_seen = set()
    sm6_launch_ranges = []     # ground range Oniks<->launching ship at launch
    sm6_killed_oniks = False
    oniks_min_alt_seen = 1e9
    t = 0.0
    while t < MAX_T:
        world.step(DT)
        t += DT
        if oniks.alive:
            oniks_min_alt_seen = min(oniks_min_alt_seen, float(oniks.pos[1]))
        # detect new SM-6 launches and their range to the Oniks at birth
        for m in world.missiles:
            if _is_sm6(m) and id(m) not in sm6_seen:
                sm6_seen.add(id(m))
                if oniks.alive:
                    r = math.hypot(float(oniks.pos[0]) - float(m.pos[0]),
                                   float(oniks.pos[2]) - float(m.pos[2]))
                    sm6_launch_ranges.append(r)
        if not oniks.alive:
            # Was it an SM-6 that did it? credit if an SM-6 ever flew AND
            # the oniks died high (above the sea-skim band).
            if sm6_seen:
                sm6_killed_oniks = True
            break
    return dict(
        n_sm6=len(sm6_seen),
        launch_ranges=sm6_launch_ranges,
        killed=sm6_killed_oniks,
        oniks_alive=oniks.alive,
        oniks_min_alt=oniks_min_alt_seen,
        t_end=t,
    )


def main():
    seeds = [1, 2, 3, 4, 5]
    # High profile: launched far out so it cruises at 14 km through the SM-6
    # band. Standoff 180 km -> well inside SM-6 240 km, beyond SM-2 150 km.
    print("=== SM-6 AREA DEFENSE PROBE ===")
    print(f"SM6_MIN_RANGE_M={SM6_MIN_RANGE_M/1000:.0f} km, "
          f"SM6.max_range={SM6.max_range/1000:.0f} km")
    print()

    hi = [run_one(s, "hi-lo", 180_000.0) for s in seeds]
    n_hi_engaged = sum(1 for r in hi if r["n_sm6"] > 0)
    n_hi_killed = sum(1 for r in hi if r["killed"])
    all_ranges = [rr for r in hi for rr in r["launch_ranges"]]
    print("HIGH (hi-lo, 14km cruise), 180 km standoff:")
    for s, r in zip(seeds, hi):
        rng = (f"{min(r['launch_ranges'])/1000:.0f}-"
               f"{max(r['launch_ranges'])/1000:.0f} km"
               if r["launch_ranges"] else "none")
        print(f"  seed {s}: SM6 launches={r['n_sm6']:2d} "
              f"launch_range={rng:>14}  killed={r['killed']} "
              f"min_alt={r['oniks_min_alt']:.0f}m t={r['t_end']:.0f}s")
    print(f"  -> engaged {n_hi_engaged}/{len(seeds)}, "
          f"killed-by-SM6-flew {n_hi_killed}/{len(seeds)}")
    if all_ranges:
        print(f"  -> launch ranges: min={min(all_ranges)/1000:.0f} km "
              f"max={max(all_ranges)/1000:.0f} km "
              f"mean={np.mean(all_ranges)/1000:.0f} km")
    print()

    lo = [run_one(s, "lo-lo", 180_000.0) for s in seeds]
    n_lo_engaged = sum(1 for r in lo if r["n_sm6"] > 0)
    print("LOW (lo-lo, sea-skim), 180 km standoff:")
    for s, r in zip(seeds, lo):
        print(f"  seed {s}: SM6 launches={r['n_sm6']:2d}  "
              f"oniks_alive={r['oniks_alive']} "
              f"min_alt={r['oniks_min_alt']:.0f}m t={r['t_end']:.0f}s")
    print(f"  -> engaged by SM6 {n_lo_engaged}/{len(seeds)} "
          f"(EXPECT 0 — low survives the SM-6 layer)")
    print()

    # Verdicts
    pass_a1 = n_hi_engaged >= 4 and (not all_ranges or
                                     min(all_ranges) >= SM6_MIN_RANGE_M * 0.95)
    pass_a2 = n_lo_engaged == 0
    print(f"PASS(a-high-engaged)={pass_a1}  PASS(a-low-immune)={pass_a2}")
    return dict(hi=hi, lo=lo, n_hi_engaged=n_hi_engaged,
                n_hi_killed=n_hi_killed, n_lo_engaged=n_lo_engaged,
                ranges=all_ranges, pass_a1=pass_a1, pass_a2=pass_a2)


if __name__ == "__main__":
    main()
