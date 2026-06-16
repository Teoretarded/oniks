"""Battle 2 - camera/zoom crash hunt (the user's #1 known crasher).

Develops one long battle until many object types exist, then follow+orbit+zooms
a representative of EACH distinct (class, hostile, weapon, phase) at a couple of
distances - plus ships, aircraft, drone and structures. Every crash is caught
and logged as a CRASHER; the sweep keeps going so one crash does not end the
hunt. The point is to find which followed objects blow up the renderer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from playtest_harness import Battle, finding, set_battle, write_report

DISTS = [8.0, 2.0]


def wid(m):
    w = getattr(m, "weapon", None)
    return getattr(w, "weapon_id", None)


def type_key(m):
    return (type(m).__name__, bool(getattr(m, "is_hostile", False)),
            wid(m), getattr(m, "phase", None))


def label(m):
    cls, host, w, ph = type_key(m)
    return f"{'ENM' if host else 'OWN'}-{cls}-{w}-ph{ph}"


def sweep_missiles(b, seen):
    for m in list(b.world.missiles):
        k = type_key(m)
        if k in seen or not getattr(m, "alive", True):
            continue
        seen.add(k)
        for d in DISTS:
            b.try_zoom(m, label(m), dist=d)
        print(f"[b2] zoomed {label(m)}", flush=True)


def main():
    set_battle("battle2-zoom-crash")
    b = Battle(7, n_destroyers=6, oniks_ammo=20)
    seen = set()

    # 1) static objects: ships, drone, structures
    for s in list(b.world.ships)[:3]:
        for d in DISTS:
            b.try_zoom(s, f"ship-{getattr(s, 'ship_type', '?')}", dist=d)
    if getattr(b.world, "drone", None) is not None:
        for d in DISTS:
            b.try_zoom(b.world.drone, "drone", dist=d)
    for st in list(getattr(b.world, "structures", []))[:4]:
        b.try_zoom(st, f"structure-{getattr(st, 'kind', '?')}", dist=6.0)
    print(f"[b2] static swept; {b.picture()}", flush=True)

    # 2) fire a player Oniks at the nearest ship -> OWN missile + provoke SM-2
    target = min(b.world.ships,
                 key=lambda s: float(np.hypot(s.pos[0], s.pos[2])))
    b.tab_to("bastion")
    b.key(pygame.K_1)                                  # hi-lo profile
    b.open_map()
    b.click((float(target.pos[0]), float(target.pos[2])), button=1)
    b.key(pygame.K_SPACE)
    b.close_map()
    sweep_missiles(b, seen)

    # 3) develop the battle: enemy raids bring strike rounds, SM-2s, Pantsir
    #    interceptors and fighters. Sweep each new type as it appears.
    for chunk in range(22):                            # up to ~22 min
        b.fast(60.0)
        sweep_missiles(b, seen)
        for ac in list(getattr(b.world, "aircraft", []))[:2]:
            k = ("aircraft", getattr(ac, "kind", "?"))
            if k not in seen:
                seen.add(k)
                for d in DISTS:
                    b.try_zoom(ac, f"aircraft-{getattr(ac, 'kind', '?')}",
                               dist=d)
                print(f"[b2] zoomed {k}", flush=True)
        if chunk % 5 == 0:
            print(f"[b2] t={b.world.sim_time:.0f}s types={len(seen)} "
                  f"{b.picture()}", flush=True)
        if getattr(b.world, "defeated", False) or \
                getattr(b.world, "victorious", False):
            print(f"[b2] battle ended t={b.world.sim_time:.0f}s", flush=True)
            break

    print(f"\n[b2] distinct object types zoomed: {len(seen)}", flush=True)
    for k in sorted(seen, key=str):
        print(f"      {k}", flush=True)
    b.shot("b2_final", "end of zoom sweep")
    b.close()
    write_report()


if __name__ == "__main__":
    main()
