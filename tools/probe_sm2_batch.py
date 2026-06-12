"""Measure SM-2 vs Oniks engagement statistics in REAL CombatWorld battles.

Phase 3 gate measure-don't-guess harness: per profile (lo-lo / hi-lo) it
spawns N seeded CombatWorlds, fires a REAL player Oniks (world.launch — the
terminal weave, the contact-picture SM-2 shots, the CIWS inner layer are all
in the loop) at destroyer_00, steps the world at the locked 120 Hz until the
round resolves, and reports per battle: SM-2s fired, who killed the Oniks
(SM-2 fuse / CIWS / nobody), and each SM-2's closest point of approach.

Used to TUNE sim/sam.py MULTIPATH_SIGMA_M (the only knob): the gate locks
hi-lo kill-per-engagement >= 0.8 and lo-lo (60 m cruise) in 0.25-0.60.

Run:  python tools/probe_sm2_batch.py [--n 20] [--sigma 18.0] [--seed0 100]
      --sigma 0 measures the no-noise baseline (the 'before' column).
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import sim.sam as sam_mod
from sim.missile import Missile
from sim.sam import SamMissile
from world.combat import CombatWorld

PHYS_DT = 1.0 / 120.0
BATTLE_T_MAX = 420.0      # s: lo-lo needs ~260 s for the 151 km run


def run_battle(seed: int, ordinal: int, profile: str) -> dict:
    """One seeded battle: real CombatWorld, one real Oniks at destroyer_00.

    ordinal varies the salvo weave phase exactly like consecutive player
    launches would (world.oniks_fired seeds Missile.weave_phi)."""
    world = CombatWorld(rng_seed=seed)
    world.oniks_fired = ordinal
    dd = world.ships[0]
    assert dd.ship_id == "destroyer_00"
    target = np.array([float(dd.pos[0]), 0.0, float(dd.pos[2])])
    oniks = world.launch(profile, target)
    assert isinstance(oniks, Missile)

    sams = {}                 # id(sam) -> [sam, closest_approach_m]
    events = []
    t = 0.0
    while t < BATTLE_T_MAX:
        world.step(PHYS_DT)
        t += PHYS_DT
        events.extend(k for k, _ in world.drain_events())
        for m in world.missiles:
            if isinstance(m, SamMissile) and id(m) not in sams:
                sams[id(m)] = [m, float("inf")]
        if oniks.alive:
            ox, oy, oz = oniks.pos.tolist()
            for rec in sams.values():
                s = rec[0]
                if s.alive and s.target is oniks:
                    d = ((s.pos[0] - ox) ** 2 + (s.pos[1] - oy) ** 2
                         + (s.pos[2] - oz) ** 2) ** 0.5
                    rec[1] = min(rec[1], d)
        else:
            break

    sm2_kill = any(rec[0].killed_target for rec in sams.values())
    return {
        "seed": seed,
        "fired": len(sams),
        "sm2_kill": sm2_kill,
        "ciws_kill": "ciws_kill" in events,
        "ship_hit": "ship_hit" in events,
        "timeout": oniks.alive,
        "cpa": sorted(rec[1] for rec in sams.values()),
        "t_end": t,
    }


def run_profile(profile: str, n: int, seed0: int) -> list[dict]:
    rows = []
    for k in range(n):
        t0 = time.perf_counter()
        r = run_battle(seed0 + k, k, profile)
        wall = time.perf_counter() - t0
        cpa_txt = ", ".join(f"{d:7.1f}" for d in r["cpa"]) or "-"
        outcome = ("SM2-KILL" if r["sm2_kill"] else
                   "CIWS-KILL" if r["ciws_kill"] else
                   "SHIP-HIT" if r["ship_hit"] else
                   "TIMEOUT" if r["timeout"] else "SELF-MISS")
        print(f"  [{profile}] seed={r['seed']:<4d} fired={r['fired']} "
              f"{outcome:<9s} t={r['t_end']:6.1f}s wall={wall:5.1f}s "
              f"cpa=[{cpa_txt}]")
        rows.append(r)
    return rows


def summarize(profile: str, rows: list[dict]) -> None:
    n = len(rows)
    engaged = [r for r in rows if r["fired"] > 0]
    sm2_kills = sum(r["sm2_kill"] for r in engaged)
    fired = sum(r["fired"] for r in rows)
    ciws = sum(r["ciws_kill"] for r in rows)
    hits = sum(r["ship_hit"] for r in rows)
    cpas = [d for r in rows for d in r["cpa"] if d != float("inf")]
    kpe = sm2_kills / len(engaged) if engaged else float("nan")
    print(f"\n=== {profile}: {n} battles, {len(engaged)} engagements, "
          f"{fired} SM-2s fired ===")
    print(f"  SM-2 kill-per-engagement : {kpe:.3f} "
          f"({sm2_kills}/{len(engaged)})")
    print(f"  leaked to CIWS kill      : {ciws}")
    print(f"  leaked to SHIP HIT       : {hits}")
    if cpas:
        print(f"  SM-2 closest approaches  : median {np.median(cpas):8.1f} m"
              f"  p25 {np.percentile(cpas, 25):8.1f}"
              f"  p75 {np.percentile(cpas, 75):8.1f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=20, help="battles per profile")
    ap.add_argument("--sigma", type=float, default=None,
                    help="override sim.sam.MULTIPATH_SIGMA_M (0 = baseline)")
    ap.add_argument("--seed0", type=int, default=100, help="first world seed")
    ap.add_argument("--profiles", nargs="+", default=["lo-lo", "hi-lo"])
    args = ap.parse_args()

    if args.sigma is not None:
        sam_mod.MULTIPATH_SIGMA_M = args.sigma
    print(f"MULTIPATH_SIGMA_M = {sam_mod.MULTIPATH_SIGMA_M} m, "
          f"ALT = {sam_mod.MULTIPATH_ALT_M} m, "
          f"TAU = {sam_mod.MULTIPATH_TAU_S} s, "
          f"SM2 floor = {__import__('sim.arsenal', fromlist=['SM2']).SM2.min_intercept_alt} m")
    all_rows = {}
    for profile in args.profiles:
        all_rows[profile] = run_profile(profile, args.n, args.seed0)
    for profile in args.profiles:
        summarize(profile, all_rows[profile])
    return 0


if __name__ == "__main__":
    sys.exit(main())
