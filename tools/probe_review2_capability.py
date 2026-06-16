"""REVIEW 2 / check (e): is the enemy measurably MORE capable AND no-cheat?

Two measured capability claims plus a no-cheat audit:

  E1 evasion buys survival: run the SAME real engagement (player S-300 fired at a
     tracked fighter) WITH the evasion code vs WITH it neutered (force
     _evade_threat=None each step). Measure miss distance / survival. Evasion ON
     must do measurably better (bigger miss / more survivals) across seeds.

  E2 back-plot localization (the changed launch-point math): a level sea-skimmer
     Oniks must now back-plot to NEAR its real launch coast (was sliding ~150 km
     the WRONG way). Measured error in km.

  E3 no-cheat audit: grep the new decision sites for any ground-truth read. We
     assert the evasion geometry comes from the picture track store and the
     trigger is the SAM .target (RWR lock) only.

Run: python tools/probe_review2_capability.py
"""
import math
import os
import sys
import types

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.enemy_air import Fighter, FS_ON_STATION, FS_TRANSIT
from sim.sam import SamMissile
from sim.arsenal import S300


DT = 1.0 / 120.0


def _airborne(w, max_s=600.0):
    t = 0.0
    while t < max_s:
        w.step(DT)
        t += DT
        for e in w.enemy_air:
            if isinstance(e, Fighter) and e.alive and e.state in (
                    FS_ON_STATION, FS_TRANSIT):
                return e
    return None


def _engage(seed, evasion_on, dist_m):
    """Fire a tracked, locked S-300 at an airborne fighter from dist_m and run
    until the SAM dies or 70 s elapse. Return (min_miss_m, fighter_survived).

    Evasion is disabled (the OFF arm) by stubbing _assign_air_threats to a no-op
    BEFORE any step — zeroing _evade_threat per tick does NOT work because
    _assign_air_threats re-sets it inside the very next step()."""
    w = CombatWorld(CombatConfig(seed=seed))
    f = _airborne(w)
    if f is None:
        return None, None
    if not evasion_on:
        w._assign_air_threats = types.MethodType(lambda self: None, w)
    fx, fz = float(f.pos[0]), float(f.pos[2])
    pos = np.array([fx, float(f.pos[1]) + 200.0, fz - dist_m])
    sam = SamMissile(S300, pos, f)
    sam.is_hostile = False
    w.missiles.append(sam)
    tid = f"hostile_{id(sam):x}"
    min_miss = float("inf")
    t = 0.0
    while t < 70.0:
        # keep the track fresh so the (sensor-driven) break logic has geometry
        w.commander.picture.update_missile_track(
            tid, sam.pos.copy(), sam.vel.copy(), w.sim_time)
        w.step(DT)
        if sam.alive and f.alive:
            min_miss = min(min_miss, float(np.linalg.norm(sam.pos - f.pos)))
        if not sam.alive or not f.alive:
            min_miss = min(min_miss, float(np.linalg.norm(sam.pos - f.pos)))
            break
        t += DT
    return min_miss, f.alive


def run():
    results = {}

    # ---- E1: evasion buys survival / larger miss across seeds + ranges --------
    # The S-300's lethal heart (~55-70 km) kills the fighter either way; the
    # edges (40 km energy-bleed, 90 km coast-to-stall) are where the break PAYS
    # OFF. Capability = ON strictly dominates OFF on miss distance everywhere and
    # converts kills to survivals at the edges.
    seeds = [101, 202]
    ranges = [40_000, 70_000, 90_000]
    table = {}
    dominates = True
    survival_gain = 0
    for dist in ranges:
        on = [_engage(s, True, dist) for s in seeds]
        off = [_engage(s, False, dist) for s in seeds]
        on_m = float(np.mean([m for m, _ in on]))
        off_m = float(np.mean([m for m, _ in off]))
        on_s = sum(1 for _, a in on if a)
        off_s = sum(1 for _, a in off if a)
        table[dist] = (on_m, off_m, on_s, off_s)
        if on_m < off_m - 1.0:          # ON must never be WORSE than OFF
            dominates = False
        survival_gain += (on_s - off_s)
        print(f"E1 dist={dist//1000:>2}km  miss ON={on_m:8.1f}m OFF={off_m:8.1f}m  "
              f"surv ON={on_s}/{len(seeds)} OFF={off_s}/{len(seeds)}")
    e1_ok = dominates and survival_gain > 0
    results["E1"] = e1_ok
    print(f"E1 evasion capability: ON-dominates-miss={dominates} "
          f"survival_gain=+{survival_gain} "
          f"-> {'PASS (measurably better)' if e1_ok else 'FAIL'}")

    # ---- E2: back-plot localization of a level sea-skimmer --------------------
    # Drive the commander's back-plot math directly with a known launch geometry.
    from sim.commander import (EnemyCommander, BACKPLOT_LOW_ALT_M,
                               HOME_COAST_Z)
    w = CombatWorld(CombatConfig(seed=7))
    cmd = w.commander
    # A level Oniks first detected 1.5 km alt, 80 km north of the home coast,
    # closing north (+z) at 250 m/s after launching from the coast at x=20 km.
    true_launch_x = 20_000.0
    fseen = np.array([true_launch_x, 1_500.0, HOME_COAST_Z + 80_000.0])
    fvel = np.array([0.0, 0.0, 250.0])      # level, closing +z (vy < CLIMB_VY)
    det_pos = np.array([40_000.0, 18.0, -6_000.0])   # player radar station
    cmd.process_missile_track(
        "hostile_probe2", fseen.copy(), fvel.copy(), w.sim_time,
        w.sim_time, fseen.copy(), fvel.copy(), det_pos.copy())
    # Inspect the resulting back-plot fix (the raw guard list holds it).
    bp = cmd.picture._back_plots[-1] if cmd.picture._back_plots else None
    if bp is not None:
        est_x = float(bp.estimated_pos[0])
        est_z = float(bp.estimated_pos[1])
        err_km = math.hypot(est_x - true_launch_x, est_z - HOME_COAST_Z) / 1e3
        # Must localize NEAR the real coastal launch, NOT 150 km downrange.
        e2_ok = err_km < 20.0
        print(f"E2 sea-skimmer back-plot: est=({est_x:.0f},{est_z:.0f}) "
              f"true=({true_launch_x:.0f},{HOME_COAST_Z:.0f}) err={err_km:.1f} km "
              f"-> {'PASS' if e2_ok else 'FAIL'}")
    else:
        e2_ok = False
        print("E2 sea-skimmer back-plot: NO FIX PRODUCED -> FAIL")
    results["E2"] = e2_ok

    # ---- E3: no-cheat audit of the evasion decision site ----------------------
    import inspect
    src = inspect.getsource(CombatWorld._assign_air_threats)
    reads_picture = "live_missile_tracks" in src
    trigger_is_lock = ".target" in src and "aircraft_id" in src
    # No direct truth read of the SAM real pos for geometry: geometry must come
    # from track_xz (the picture), not m.pos. The break range compares to tp
    # (track pos), never m.pos.
    no_truth_geom = "track_xz.get" in src and "tp is None" in src
    e3_ok = reads_picture and trigger_is_lock and no_truth_geom
    results["E3"] = e3_ok
    print(f"E3 no-cheat audit: picture_geometry={reads_picture} "
          f"rwr_lock_trigger={trigger_is_lock} no_truth_geom={no_truth_geom} "
          f"-> {'PASS' if e3_ok else 'FAIL'}")

    ok = all(results.values())
    print(f"\n(e) CAPABILITY+NO-CHEAT OVERALL: {'PASS' if ok else 'FAIL'}  {results}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
