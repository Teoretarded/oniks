"""Battle 1 - seed & generation integrity (GL-free, fast).

Targets the user-reported "make a new seed -> never loads" bug at the
generation layer, plus the determinism contract and cross-seed variety.
Builds many seeds, prints each fleet signature, then checks same-seed
determinism and that different seeds give different fleet layouts.

If a seed hangs in generation, this process hangs -> the run's wall-clock
timeout names the culprit. A clean run means generation is NOT where the
"never loads" bug lives (look at the GL/asset/setup-UI load path next).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playtest_harness import (build_world, world_signature, finding,
                              set_battle, reset_findings, write_report)

SEEDS = [1, 2, 3, 7, 13, 42, 99, 123, 777, 1000, 31337, 999999]


def main():
    reset_findings()
    set_battle("battle1-seed-generation")
    sigs = {}
    for sd in SEEDS:
        print(f"[b1] build seed {sd} ...", flush=True)
        w = build_world(sd, n_destroyers=4)
        sig = world_signature(w)
        sigs[sd] = sig
        print(f"[b1]   seed {sd}: ships={sig['n_ships']} {sig['ships_km']} "
              f"sites={sig['n_sites']} acft={sig['n_aircraft']} "
              f"pantsir={sig['n_pantsir']} radars={sig['n_enemy_radar']}",
              flush=True)

    # determinism: rebuild a few seeds, compare the full signature.
    for sd in (7, 42, 1000):
        sig2 = world_signature(build_world(sd, n_destroyers=4))
        if sig2 != sigs[sd]:
            finding("LOGIC", f"seed {sd} not deterministic",
                    detail=f"rebuild differs: {sigs[sd]} vs {sig2}")
        else:
            print(f"[b1] determinism OK: seed {sd} identical on rebuild",
                  flush=True)

    # variety: fleet layouts should differ across seeds.
    layouts = {tuple(s["ships_km"]) for s in sigs.values()}
    if len(layouts) < len(SEEDS):
        finding("LOGIC", "seeds produce duplicate fleet layouts",
                detail=f"only {len(layouts)} unique layouts across "
                       f"{len(SEEDS)} seeds")
    else:
        print(f"[b1] variety OK: {len(layouts)} unique layouts / "
              f"{len(SEEDS)} seeds", flush=True)

    write_report()
    print("[b1] done", flush=True)


if __name__ == "__main__":
    main()
