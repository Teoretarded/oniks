"""Throwaway probes for the 5b kill chains: back-plot accuracy + 40N6 reach."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world.combat import CombatWorld
from world.generation import BASE_POS

DT = 1.0 / 120.0

# --- 1. back-plot accuracy from 3 real Oniks launches ----------------------
w = CombatWorld()
w.radar_station.emitting = False          # never located -> JASSM ungated
for s in w.ships:                          # disarm: the rounds must fly free
    s.sm2_ammo = 0
    s.ciws_ammo = 0
target = w.ships[0].pos.copy()
target[1] = 0.0
t0 = time.time()
for i in range(3):
    w.reload_left = 0.0
    m = w.launch("hi-lo", target)
    assert m is not None, f"launch {i} refused"
    # fly ~40 s at 120 Hz so the round climbs through the back-plot band
    for _ in range(int(40.0 / DT)):
        w.step(DT)
    m.alive = False                        # scenario forcing: plot recorded
    for _ in range(8):
        w.step(DT)
print("probe1 sim walltime", round(time.time() - t0, 1), "s")
clusters = w.commander.picture.clusters
for c in clusters:
    err = float(np.hypot(c.centre[0] - BASE_POS[0], c.centre[1] - BASE_POS[2]))
    print(f"cluster fixes={len(c.fixes)} targetable={c.targetable} "
          f"centre=({c.centre[0]:.0f},{c.centre[1]:.0f}) err_vs_base={err:.0f} m")
print("targetable:", len(w.commander.picture.targetable_clusters()))
print("intel recs:", [(r['track_id'], round(float(r['first_pos'][1]), 0))
                      for r in w._cmd_missile_intel.values()])

# --- 2. 40N6 vs the AWACS at ~250-290 km -----------------------------------
w2 = CombatWorld()
a = w2.awacs
# re-anchor the racetrack at z 240-280 km (the scenario's fled-orbit case)
a._corners = ((-20_000.0, 240_000.0), (-20_000.0, 280_000.0),
              (20_000.0, 280_000.0), (20_000.0, 240_000.0))
a._wp = 1
a.pos[0], a.pos[2] = -20_000.0, 240_000.0
from world.world import SAM_TEL_POS
d0 = float(np.hypot(a.pos[0] - SAM_TEL_POS[0], a.pos[2] - SAM_TEL_POS[2]))
print("40n6 shot initial range:", round(d0 / 1e3, 1), "km")
# forced ELINT-style track refresh each second
now = w2.sim_time
w2.contacts.tracks["awacs_00"] = dict(pos=a.pos.copy(), vel=a.velocity(),
                                      age=5.0, t_next=now + 1.0, is_air=True)
sam = w2.launch_sam("awacs_00", round_id="40n6")
print("sam launched:", sam is not None)
t0 = time.time()
killed_t = None
for _ in range(int(400.0 / DT)):
    w2.step(DT)
    # refresh the forced track (ELINT fix cadence)
    w2.contacts.tracks["awacs_00"] = dict(
        pos=a.pos.copy(), vel=a.velocity(), age=5.0,
        t_next=w2.sim_time + 1.0, is_air=True)
    if sam is not None and not sam.alive:
        break
print("probe2 walltime", round(time.time() - t0, 1), "s")
if sam is not None:
    print("sam dead t=", round(sam.t, 1), "killed_target=", sam.killed_target,
          "self_destructed=", sam.self_destructed,
          "apogee-ish pos:", np.round(sam.pos, 0).tolist())
print("awacs alive:", a.alive, "fleeing:", a._fleeing)
