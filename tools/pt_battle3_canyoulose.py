"""Battle 3 - CAN YOU LOSE? In-game verification of the enemy-AI F1/F2 finding.

The only lose condition is the Bastion being destroyed by an enemy strike. That
requires the enemy to back-plot your missile tracks to a launch cluster and
order a JASSM/Tomahawk package at the base. This runs a long battle with the
radar EMITTING, periodically firing Oniks at the fleet to provoke the back-plot,
and tracks whether any hostile strike is ever aimed at the base / whether the
base is ever damaged / whether `defeated` ever becomes reachable.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from playtest_harness import Battle, finding, set_battle, write_report
from world.generation import BASE_POS


def main():
    n_pantsir = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    set_battle(f"battle3-can-you-lose-pantsir{n_pantsir}")
    b = Battle(7, n_destroyers=8, oniks_ammo=60, n_pantsir=n_pantsir)
    w = b.world
    print(f"[b3] n_pantsir={n_pantsir}", flush=True)
    bx, bz = float(BASE_POS[0]), float(BASE_POS[2])
    strikes_at_base_max = 0
    clusters_max = 0
    ever_defeated = False
    shots = 0
    print(f"[b3] structures: {[s.kind for s in w.structures]}", flush=True)

    def fire_oniks():
        nonlocal shots
        target = min(w.ships, key=lambda s: float(np.hypot(s.pos[0], s.pos[2])))
        if b.tab_to("bastion"):
            b.key(pygame.K_1)
            b.open_map()
            b.click((float(target.pos[0]), float(target.pos[2])), button=1)
            b.key(pygame.K_SPACE)
            b.close_map()
            shots += 1

    for chunk in range(60):                     # up to 60 min sim
        if chunk % 3 == 0:
            fire_oniks()
        b.fast(60.0)

        strikes_at_base = 0
        for m in w.missiles:
            if getattr(m, "is_hostile", False) and hasattr(m, "target_x"):
                if np.hypot(m.target_x - bx, m.target_z - bz) < 5000.0:
                    strikes_at_base += 1
        strikes_at_base_max = max(strikes_at_base_max, strikes_at_base)

        clusters = -1
        try:
            clusters = len(w.commander.picture.targetable_clusters())
            clusters_max = max(clusters_max, clusters)
        except Exception:
            pass

        if getattr(w, "defeated", False):
            ever_defeated = True
        if chunk % 6 == 0:
            alive = "/".join(s.kind for s in w.structures if s.alive)
            print(f"[b3] t={w.sim_time:5.0f}s shots={shots} base=[{alive}] "
                  f"strikes_at_base={strikes_at_base} clusters={clusters} "
                  f"def={getattr(w, 'defeated', '?')}", flush=True)
        if getattr(w, "defeated", False) or getattr(w, "victorious", False):
            print(f"[b3] ended t={w.sim_time:.0f}s def={w.defeated} "
                  f"vic={w.victorious}", flush=True)
            break

    bastion_alive = any(s.kind == "bastion_tel" and s.alive
                        for s in w.structures)
    print(f"\n[b3] RESULT after {w.sim_time:.0f}s, {shots} Oniks fired:",
          flush=True)
    print(f"[b3]   bastion_alive={bastion_alive} ever_defeated={ever_defeated}",
          flush=True)
    print(f"[b3]   max strikes aimed at base={strikes_at_base_max} "
          f"max targetable_clusters={clusters_max}", flush=True)
    if not ever_defeated and strikes_at_base_max == 0:
        finding("LOGIC", "battle appears unlosable - enemy never strikes the base",
                detail=f"{w.sim_time:.0f}s radar-on, {shots} Oniks fired, "
                       f"0 strikes aimed at base, max clusters={clusters_max}")
    b.close()
    write_report()


if __name__ == "__main__":
    main()
