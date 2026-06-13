"""Throwaway probes: HARM mission + silence loop; IR drone hunt."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.a2a import IrMissile
from sim.enemy_air import (FIGHTER_ALT_M, FS_ON_STATION, FS_RTB, FS_TRANSIT,
                           Fighter)
from sim.recon import RWR_LOCK
from sim.strike import HarmMissile
from world.combat import CombatWorld

DT = 1.0 / 120.0
DTC = 0.25

# --- 1. HARM mission + silence loop ----------------------------------------
w = CombatWorld()
rid = w.radar_station.radar_id
t0 = time.time()
for _ in range(int(120.0 / DTC)):
    w.step(DTC)
    if any(m["kind"] == "harm_package" for m in w._cmd_missions):
        break
mission = next(m for m in w._cmd_missions if m["kind"] == "harm_package")
print("harm mission at t=", w.sim_time, "fighters",
      [f.aircraft_id for f in mission["fighters"]],
      "stock", w.commander.stock.total_harm)
# scenario forcing: finish the climb, teleport to 99 km from the radar
rp = w.radar_station.pos
for f in mission["fighters"]:
    f.pos[1] = FIGHTER_ALT_M
w.step(DTC)
for f in mission["fighters"]:
    dx = float(f.pos[0] - rp[0]); dz = float(f.pos[2] - rp[2])
    d = np.hypot(dx, dz)
    f.pos[0] = rp[0] + dx / d * 99_000.0
    f.pos[2] = rp[2] + dz / d * 99_000.0
for _ in range(int(4.0 / DTC)):
    w.step(DTC)
harms = [m for m in w.missiles if isinstance(m, HarmMissile)]
print("harms in flight:", len(harms),
      "fighter states:", [f.state for f in mission["fighters"]])
# fly 40 s at 120 Hz, then silence mid-ingress
for _ in range(int(40.0 / DT)):
    w.step(DT)
w.radar_station.emitting = False
for _ in range(int(150.0 / DT)):
    w.step(DT)
    if all(not m.alive for m in harms) and mission not in w._cmd_missions:
        break
print("walltime", round(time.time() - t0, 1))
print("harms dead:", [not m.alive for m in harms],
      "offsets:", [m._miss_offset is not None for m in harms])
print("radar alive:", w.radar_station.alive)
ei = w.commander.picture.emitters.get(rid)
print("believed alive:", ei.alive, "mission closed:",
      mission not in w._cmd_missions)
w.radar_station.emitting = True
for _ in range(int(2.0 / DTC)):
    w.step(DTC)
print("believed alive after re-emit:", ei.alive)

# --- 2. IR drone hunt --------------------------------------------------------
w2 = CombatWorld()
for s in w2.ships:
    s.sm2_ammo = 0          # isolate the IR channel
    s.ciws_ammo = 0
d = w2.drone
dd = w2.ships[0]            # destroyer_00 at (-20, 150) km
# drone crossing 25 km south of the destroyer, heading east
d.pos[0], d.pos[2] = -45_000.0, 125_000.0
d.set_route([(60_000.0, 125_000.0)])
# scenario-force a CAP fighter into the area: finish climb at ~20 km behind
f = w2._fighter_list[0]
f.assign_loadout(("aim9x", "aim9x", "aim9x", "aim9x"))
f.launch((0.0, 160_000.0))
f.pos[0], f.pos[1], f.pos[2] = -60_000.0, FIGHTER_ALT_M, 120_000.0
t0 = time.time()
saw_lock = False
killed = False
fired_ir = None
for i in range(int(700.0 / DTC)):
    w2.step(DTC)
    if any(a[0] == RWR_LOCK for a in w2.rwr.alerts()):
        saw_lock = True
    irs = [m for m in w2.missiles if isinstance(m, IrMissile)]
    if irs:
        fired_ir = w2.sim_time
        break
print("ir fired at t:", fired_ir, "drone tracked:",
      len(w2.commander.picture.drone_tracks))
if fired_ir is not None:
    for _ in range(int(60.0 / DT)):
        w2.step(DT)
        if any(a[0] == RWR_LOCK for a in w2.rwr.alerts()):
            saw_lock = True
        if w2.drone is None:
            killed = True
            break
print("walltime", round(time.time() - t0, 1))
print("killed:", killed, "saw_lock:", saw_lock,
      "fighter state:", f.state, "hardpoints:", f.hardpoints)
