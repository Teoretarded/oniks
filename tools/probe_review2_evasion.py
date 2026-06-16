"""REVIEW 2 / check (a): Fighter evasion AFTER the no-cheat rewrite.

Two questions, measured:

  A1 (works): in a REAL battle, when a player S-300 locks AND the fleet picture
     holds the SAM as a track, the targeted fighter BREAKS (heading + altitude
     change) driven by the sensor track, and dodges meaningfully.

  A2 (no-cheat): a SAM that is LOCKED on the fighter but is NOT held in the
     commander picture (no track geometry) must yield NO break. We force this by
     emptying the picture's missile_tracks each step while keeping the lock.

Also A3 (trigger = RWR lock, not bare geometry): a tracked SAM whose .target is
NOT this fighter (no RWR lock) must yield no break even though its geometry is
in the picture.

Run: python tools/probe_review2_evasion.py   (ignore the pygame banner)
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world.combat import CombatWorld, FIGHTER_RWR_REACT_RANGE_M
from world.combat_config import CombatConfig
from sim.enemy_air import Fighter, FS_ON_STATION, FS_TRANSIT
from sim.sam import SamMissile
from sim.arsenal import S300

DT = 1.0 / 120.0


def _airborne_fighter(w, max_s=600.0):
    """Run the world until at least one Fighter is airborne; return it."""
    t = 0.0
    while t < max_s:
        w.step(DT)
        t += DT
        for e in w.enemy_air:
            if isinstance(e, Fighter) and e.alive and e.state in (
                    FS_ON_STATION, FS_TRANSIT):
                return e, t
    return None, t


def _make_locked_sam(w, fighter, dist_m, tracked: bool):
    """Spawn a player SamMissile locked on `fighter`, dist_m south of it.
    If tracked, also inject a matching track into the commander picture so the
    geometry exists (mimics _feed_enemy_picture). Returns the sam."""
    fx, fz = float(fighter.pos[0]), float(fighter.pos[2])
    pos = np.array([fx, float(fighter.pos[1]), fz - dist_m], dtype=np.float64)
    sam = SamMissile(S300, pos, fighter)
    sam.is_hostile = False
    w.missiles.append(sam)
    if tracked:
        tid = f"hostile_{id(sam):x}"
        vel = np.array([0.0, 0.0, 250.0], dtype=np.float64)   # closing +z
        w.commander.picture.update_missile_track(
            tid, pos.copy(), vel, w.sim_time)
    return sam


def _refresh_track(w, sam, vel=(0.0, 0.0, 250.0)):
    tid = f"hostile_{id(sam):x}"
    w.commander.picture.update_missile_track(
        tid, sam.pos.copy(), np.array(vel, dtype=np.float64), w.sim_time)


def run():
    results = {}

    # ---- A1: real battle, tracked lock -> break -------------------------------
    w = CombatWorld(CombatConfig(seed=20260615))
    fighter, t0 = _airborne_fighter(w)
    if fighter is None:
        print("A1 SETUP FAIL: no airborne fighter within 600 s")
        return 1
    hdg0 = fighter.heading
    alt0 = float(fighter.pos[1])
    # Spawn a tracked, locked SAM 30 km south (inside the 60 km RWR react band).
    sam = _make_locked_sam(w, fighter, 30_000.0, tracked=True)
    # Step ~12 s; refresh the track each commander feed window so geometry stays.
    n = int(12.0 / DT)
    evade_flag_seen = 0
    for _ in range(n):
        _refresh_track(w, sam)              # keep the track fresh (sensor cue)
        w.step(DT)
        if getattr(fighter, "_evade_threat", None) is not None:
            evade_flag_seen += 1
        if not fighter.alive:
            break
    hdg_chg = abs(((fighter.heading - hdg0 + math.pi) % (2 * math.pi)) - math.pi)
    alt_chg = alt0 - float(fighter.pos[1])
    a1_break = evade_flag_seen > 0 and (math.degrees(hdg_chg) > 5.0
                                        or alt_chg > 200.0)
    results["A1"] = a1_break
    print(f"A1 tracked-lock break: evade_ticks={evade_flag_seen} "
          f"hdg_chg={math.degrees(hdg_chg):.1f} deg alt_drop={alt_chg:.0f} m "
          f"alt_now={float(fighter.pos[1]):.0f} -> {'PASS' if a1_break else 'FAIL'}")

    # ---- A2: locked but NOT tracked -> NO break (no-cheat) ---------------------
    w2 = CombatWorld(CombatConfig(seed=20260615))
    f2, _ = _airborne_fighter(w2)
    hdg0 = f2.heading
    alt0 = float(f2.pos[1])
    sam2 = _make_locked_sam(w2, f2, 20_000.0, tracked=False)  # close, no track
    n = int(12.0 / DT)
    evade_ticks = 0
    for _ in range(n):
        # Aggressively guarantee the picture has NO missile track at all so the
        # only thing 'visible' would be ground truth (which the code must ignore).
        w2.commander.picture.missile_tracks.clear()
        w2.step(DT)
        # re-clear in case the feed re-detected it (it shouldn't help A2, but we
        # want to isolate: NO geometry available to the evade logic).
        if getattr(f2, "_evade_threat", None) is not None:
            evade_ticks += 1
    hdg_chg = abs(((f2.heading - hdg0 + math.pi) % (2 * math.pi)) - math.pi)
    alt_chg = alt0 - float(f2.pos[1])
    # With the world's own radar the SAM MAY become a legit track; to truly test
    # no-cheat we report whether a break occurred ONLY on ticks where no track
    # existed. evade_ticks counts ticks the flag was set; we cleared tracks each
    # tick BEFORE step, so any evade flag means truth was read. Expect 0.
    a2_nocheat = evade_ticks == 0
    results["A2"] = a2_nocheat
    print(f"A2 locked-but-untracked: evade_ticks(no-track)={evade_ticks} "
          f"hdg_chg={math.degrees(hdg_chg):.1f} deg "
          f"-> {'PASS (no-cheat)' if a2_nocheat else 'FAIL (CHEAT!)'}")

    # ---- A3: tracked SAM NOT locked on this fighter -> NO break ----------------
    w3 = CombatWorld(CombatConfig(seed=20260615))
    f3, _ = _airborne_fighter(w3)
    # A decoy target object with a different aircraft_id (the SAM locks IT).
    decoy = Fighter("decoy_99", f3._base, (0.0, 160_000.0))
    hdg0 = f3.heading
    sam3 = SamMissile(S300, np.array([float(f3.pos[0]), float(f3.pos[1]),
                                      float(f3.pos[2]) - 20_000.0]), decoy)
    sam3.is_hostile = False
    w3.missiles.append(sam3)
    n = int(12.0 / DT)
    evade_ticks = 0
    for _ in range(n):
        _refresh_track(w3, sam3)           # geometry IS in the picture
        w3.step(DT)
        if getattr(f3, "_evade_threat", None) is not None:
            evade_ticks += 1
    a3_nolock = evade_ticks == 0
    results["A3"] = a3_nolock
    print(f"A3 tracked-but-locked-on-decoy: evade_ticks={evade_ticks} "
          f"-> {'PASS (no false break)' if a3_nolock else 'FAIL'}")

    ok = all(results.values())
    print(f"\n(a) EVASION OVERALL: {'PASS' if ok else 'FAIL'}  {results}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
