"""Game-test probe (review loop): fighter RWR-driven evasion.

Contract (c): a fighter with a player SAM GUIDING ON it (the SAM's .target IS
that airframe) breaks (changes heading AND dives) EARLIER than the old 25 km
geometric backstop — i.e. it reacts out to FIGHTER_RWR_REACT_RANGE_M (60 km).

We take an airborne enemy fighter from a real CombatWorld, launch a player
SamMissile (S-300 class) whose .target IS that fighter, position it ~45 km away
(between the 25 km geometry and the 60 km RWR react range), and measure: does
_evade_threat get flagged, and does the fighter change heading + lose altitude
while the SAM is still > 25 km out? We compare against a NO-LOCK control SAM at
the same range that does NOT target the fighter (only the 25 km backstop should
fire, so no break at 45 km).

No cheat: the lock is a real RWR event (a SAM whose .target is the fighter); the
fighter reads only its own _evade_threat flag set from that.

Run: python tools/probe_review_fighter.py   (ignore the pygame banner on stderr)
"""
from __future__ import annotations

import math
import numpy as np

from world.combat import CombatWorld, FIGHTER_RWR_REACT_RANGE_M
from world.combat_config import CombatConfig
from sim.enemy_air import (Fighter, FS_TRANSIT, FS_ON_STATION)
from sim.arsenal import S300
from sim.sam import SamMissile

DT = 0.10


def _airborne_fighter(world, max_t=360.0):
    """Step the world until a Fighter is at CRUISE altitude (TRANSIT/ON_STATION,
    >3 km) so its takeoff climb does not mask the evasive dive; return it."""
    t = 0.0
    while t < max_t:
        world.step(DT)
        t += DT
        for e in world.enemy_air:
            if (isinstance(e, Fighter)
                    and e.state in (FS_TRANSIT, FS_ON_STATION)
                    and float(e.pos[1]) > 3_000.0):
                return e, t
    return None, t


def _place_sam_near(fighter, range_m, target=None):
    """A player S-300 SamMissile placed range_m (ground) from the fighter on
    the bearing fighter<-launch, pointed at the fighter. target=fighter makes
    it a true RWR lock; target=None (a dummy) is the no-lock control."""
    fx, fz = float(fighter.pos[0]), float(fighter.pos[2])
    # place it due south of the fighter, flying north toward it
    sx, sz = fx, fz - range_m
    pos = np.array([sx, float(fighter.pos[1]), sz], dtype=np.float64)
    tgt = target if target is not None else fighter
    sam = SamMissile(S300, pos, tgt,
                     rng=np.random.default_rng(0))
    # ensure it is NOT flagged hostile (player round) and is alive
    sam.is_hostile = False
    sam.alive = True
    # point velocity toward the fighter so it reads as "incoming"
    d = np.array([fx - sx, 0.0, fz - sz])
    n = np.linalg.norm(d)
    if n > 0:
        sam.vel = d / n * 900.0
    return sam


class _DummyTarget:
    """A non-fighter target so the SAM is inbound but NOT an RWR lock on the
    fighter (its .aircraft_id won't match)."""
    def __init__(self, pos):
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        self.aircraft_id = "decoy_not_a_fighter"
        self.alive = True

    def velocity(self):
        return np.zeros(3)


def run_lock(seed, sam_range_m):
    """Lock case: SAM targets the fighter at sam_range_m. Measure break."""
    world = CombatWorld(CombatConfig(seed=seed))
    fighter, t0 = _airborne_fighter(world)
    if fighter is None:
        return None
    hdg0 = fighter.heading
    alt0 = float(fighter.pos[1])
    sam = _place_sam_near(fighter, sam_range_m, target=fighter)
    world.missiles.append(sam)

    flagged_at_range = None
    break_dheading = 0.0
    break_dalt = 0.0
    measured = False
    t = 0.0
    while t < 12.0:                 # short window: just enough to see the break
        # keep the SAM pinned at range and on the fighter (we are testing the
        # AI reaction to the LOCK, not the SAM's flyout) — freeze its position.
        sam.pos = np.array([float(fighter.pos[0]),
                            float(fighter.pos[1]),
                            float(fighter.pos[2]) - sam_range_m],
                           dtype=np.float64)
        world.step(DT)
        t += DT
        rng = math.hypot(float(fighter.pos[0]) - float(sam.pos[0]),
                         float(fighter.pos[2]) - float(sam.pos[2]))
        if fighter._evade_threat is not None and flagged_at_range is None:
            flagged_at_range = rng
        if not measured and t >= 4.0:
            # 4 s of reaction: measure heading change + altitude drop
            break_dheading = abs(((fighter.heading - hdg0 + math.pi)
                                  % (2 * math.pi)) - math.pi)
            break_dalt = alt0 - float(fighter.pos[1])
            measured = True
            break
    return dict(flagged_range=flagged_at_range, dheading_deg=math.degrees(break_dheading),
                dalt=break_dalt, t0=t0)


def run_nolock(seed, sam_range_m):
    """No-lock control: SAM at the same range but targets a decoy, so only the
    25 km geometric backstop can fire. At 45 km the fighter should NOT break."""
    world = CombatWorld(CombatConfig(seed=seed))
    fighter, _ = _airborne_fighter(world)
    if fighter is None:
        return None
    decoy_pos = np.array([float(fighter.pos[0]), float(fighter.pos[1]),
                          float(fighter.pos[2]) - sam_range_m])
    decoy = _DummyTarget(decoy_pos)
    sam = _place_sam_near(fighter, sam_range_m, target=decoy)
    world.missiles.append(sam)
    flagged = False
    t = 0.0
    while t < 6.0:
        sam.pos = decoy_pos.copy()
        world.step(DT)
        t += DT
        if fighter._evade_threat is not None:
            flagged = True
            break
    return dict(flagged=flagged)


def main():
    print("=== FIGHTER RWR EVASION PROBE ===")
    print(f"FIGHTER_RWR_REACT_RANGE_M={FIGHTER_RWR_REACT_RANGE_M/1000:.0f} km")
    print()
    seeds = [1, 2, 3]
    RNG = 45_000.0    # between the 25 km geometry and the 60 km RWR range
    print(f"LOCK at {RNG/1000:.0f} km (player SAM guiding ON the fighter):")
    n_break = 0
    for s in seeds:
        r = run_lock(s, RNG)
        if r is None:
            print(f"  seed {s}: no airborne fighter")
            continue
        broke = (r["flagged_range"] is not None
                 and r["dheading_deg"] > 2.0 and r["dalt"] > 5.0)
        n_break += int(broke)
        fr = (f"{r['flagged_range']/1000:.1f} km" if r["flagged_range"]
              else "never")
        print(f"  seed {s}: flagged_at={fr:>9} "
              f"dHeading={r['dheading_deg']:5.1f} deg dAlt={r['dalt']:6.1f} m "
              f"(broke={broke})")
    print(f"  -> broke early (>25 km) {n_break}/{len(seeds)}")
    print()

    print(f"NO-LOCK control at {RNG/1000:.0f} km (SAM targets a decoy):")
    n_quiet = 0
    for s in seeds:
        r = run_nolock(s, RNG)
        if r is None:
            print(f"  seed {s}: no airborne fighter")
            continue
        quiet = not r["flagged"]
        n_quiet += int(quiet)
        print(f"  seed {s}: evade_flagged={r['flagged']} (quiet={quiet})")
    print(f"  -> stayed un-flagged at 45 km {n_quiet}/{len(seeds)} "
          f"(EXPECT all — only the 25 km backstop, no lock)")
    print()

    pass_c_lock = n_break == len(seeds)
    pass_c_ctrl = n_quiet == len(seeds)
    print(f"PASS(c-rwr-breaks-early)={pass_c_lock}  "
          f"PASS(c-no-lock-no-early-break)={pass_c_ctrl}")


if __name__ == "__main__":
    main()
