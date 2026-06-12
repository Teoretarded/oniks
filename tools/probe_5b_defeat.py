"""Throwaway probe: the defeat-reachable JASSM kill chain."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.enemy_air import FIGHTER_ALT_M
from sim.strike import StrikeMissile
from world.combat import CombatWorld
from world.generation import BASE_POS

DT = 1.0 / 120.0
DTC = 0.25

w = CombatWorld()
w.radar_station.emitting = False
for s in w.ships:
    s.sm2_ammo = 0
    s.ciws_ammo = 0
target = w.ships[0].pos.copy()
target[1] = 0.0
t0 = time.time()
for i in range(3):
    w.reload_left = 0.0
    m = w.launch("hi-lo", target)
    for _ in range(int(40.0 / DT)):
        w.step(DT)
    m.alive = False
    for _ in range(4):
        w.step(DT)
print("clusters targetable:", len(w.commander.picture.targetable_clusters()))
for _ in range(int(10.0 / DTC)):
    w.step(DTC)
    if any(m["kind"] == "jassm_package" for m in w._cmd_missions):
        break
jm = next((m for m in w._cmd_missions if m["kind"] == "jassm_package"), None)
tlam = next((m for m in w._cmd_missions if m["kind"] == "tomahawk_salvo"), None)
print("jassm mission:", jm is not None, "tlam salvo:", tlam is not None,
      "jassm stock:", w.commander.stock.total_jassm)
if jm:
    print("strike aim:", [None if f._strike_target_xz is None
                          else np.round(f._strike_target_xz, 0).tolist()
                          for f in jm["fighters"]],
          "aim_y:", [f._strike_target_y for f in jm["fighters"]])
    bastion = w.structures[0]
    print("bastion pos:", np.round(bastion.pos, 1).tolist(), "hp", bastion.hp)
    # scenario forcing: finish climb, teleport to 100 km north of the base
    for f in jm["fighters"]:
        f.pos[1] = FIGHTER_ALT_M
    w.step(DTC)
    for f in jm["fighters"]:
        f.pos[0], f.pos[2] = 0.0, BASE_POS[2] + 100_000.0
    for _ in range(int(4.0 / DTC)):
        w.step(DTC)
    jassms = [m for m in w.missiles if isinstance(m, StrikeMissile)
              and m.weapon.weapon_id == "jassm"]
    print("jassms in flight:", len(jassms))
    hit = []
    for _ in range(int(500.0 / DT)):
        w.step(DT)
        hit += [k for k, _ in w.drain_events()
                if k in ("base_hit", "base_destroyed")]
        if w.defeated:
            break
    print("walltime", round(time.time() - t0, 1))
    print("events:", hit, "defeated:", w.defeated,
          "bastion alive:", bastion.alive, "t=", round(w.sim_time, 1))
