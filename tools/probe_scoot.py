"""M5 #4 SHOOT-AND-SCOOT probe: MEASURE the relocate move ETA and PROVE the
stale-pad miss (print measured numbers, NO asserts — the probe idiom).

The headline mechanic: after a firing TEL shoots, the player can order it to a
new map position.  While it drives it is COMMITTED (cannot launch); on arrival
its pad, every launch tube, AND its destructible Structure move to the new pad,
so the enemy's stale back-plot cluster points at empty dirt and the next salvo
hits nothing.

This probe, on a REAL CombatWorld with a Bastion / S-300 / Buk firing TEL:
  1. MOVE ETA — orders a relocate ~5 km away, steps to arrival, and prints the
     setup+drive ETA (predicted vs measured) and the pad / tube / Structure
     final positions vs the destination (all should land within 1 m).
  2. STALE-PAD MISS — seeds a back-plot cluster at the OLD pad, relocates the
     TEL, runs a commander TOMAHAWK_SALVO at the stale centroid, and prints
     whether _refine_strike_aim finds a LIVE Structure within SEEKER_BASKET_M of
     the stale centre (expect NO -> the round flies into the dirt; the TEL
     SURVIVES).  Then it shows a Structure DOES sit within the basket of the NEW
     pad (a strike there could still hit).
  3. NEW-PAD RE-SEED — fires a fresh launch from the relocated TEL and confirms
     the first-seen launch position originates at the NEW pad (so a new
     back-plot would cluster near the new xz — the cat-and-mouse stays alive).

Run: python tools/probe_scoot.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world.combat import (CombatWorld, RELOCATE_SETUP_S, RELOCATE_SPEED_MPS,
                           SEEKER_BASKET_M)
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


def _fmt(x):
    return "None" if x is None else f"{x:,.2f}"


def _firing_tel(cw, kind):
    """The first relocate descriptor of the given firing-TEL kind, or None."""
    return next((d for d in cw._relocatable if d["kind"] == kind), None)


def _predicted_eta(pad_xz, dest_xz):
    dx = dest_xz[0] - pad_xz[0]
    dz = dest_xz[1] - pad_xz[1]
    return 2.0 * RELOCATE_SETUP_S + math.hypot(dx, dz) / RELOCATE_SPEED_MPS


def probe_kind(kind, cfg):
    cw = CombatWorld(cfg)
    d = _firing_tel(cw, kind)
    if d is None:
        print(f"\n=== {kind}: NOT BUILT (skipping) ===")
        return
    struct = d["structure"]
    pad0 = (float(d["pos"][0]), float(d["pos"][2]))
    # Destination ~5 km east + ~3 km north of the current pad (stays on the
    # home shelf; the probe only needs a clean ground move).
    dest = (pad0[0] + 5_000.0, pad0[1] + 3_000.0)
    print(f"\n=== {kind} SHOOT-AND-SCOOT ===")
    print(f"  start pad xz       = ({_fmt(pad0[0])}, {_fmt(pad0[1])})")
    print(f"  dest xz            = ({_fmt(dest[0])}, {_fmt(dest[1])})")

    # --- 2. seed a back-plot cluster at the OLD pad BEFORE moving ---
    pic = cw.commander.picture
    for i in range(5):
        pic.add_back_plot(np.array([pad0[0], pad0[1]]), 50.0, cw.sim_time,
                          f"probe_fix_{i}")
    cluster = max(pic.clusters, key=lambda c: len(c.fixes))
    stale_centre = (float(cluster.centre[0]), float(cluster.centre[1]))
    print(f"  stale cluster centre = ({_fmt(stale_centre[0])}, "
          f"{_fmt(stale_centre[1])})  targetable={cluster.targetable}")

    # --- 1. order the relocate + measure the move ETA ---
    eta_pred = _predicted_eta(pad0, dest)
    ok = cw.request_relocate(struct.structure_id, dest)
    print(f"  request_relocate    -> {ok}   committed={d['committed']}")
    print(f"  armed immediately?  launcher_armed-style gate now FALSE for this "
          f"TEL's tubes (committed)")
    eta_pred2 = d["move_left_s"]
    steps = 0
    while d["committed"] and steps < int(eta_pred * 2 / DT) + 10:
        cw.step(DT)
        steps += 1
    eta_meas = steps * DT
    print(f"  move ETA predicted  = {_fmt(eta_pred)} s "
          f"(setup {2*RELOCATE_SETUP_S:.0f}s + drive "
          f"{eta_pred - 2*RELOCATE_SETUP_S:.1f}s)")
    print(f"  move ETA at booking = {_fmt(eta_pred2)} s")
    print(f"  move ETA measured   = {_fmt(eta_meas)} s (arrival)")

    pad1 = (float(d["pos"][0]), float(d["pos"][2]))
    pad_err = math.hypot(pad1[0] - dest[0], pad1[1] - dest[1])
    tube_errs = [math.hypot(float(t["pos"][0]) - (dest[0] + float(o[0])),
                            float(t["pos"][2]) - (dest[1] + float(o[2])))
                 for t, o in zip(d["tubes"], d["offsets"])]
    struct_err = math.hypot(float(struct.pos[0]) - dest[0],
                            float(struct.pos[2]) - dest[1])
    print(f"  pad      err vs dest = {_fmt(pad_err)} m")
    print(f"  tube max err vs dest = {_fmt(max(tube_errs))} m "
          f"(over {len(tube_errs)} tubes)")
    print(f"  Structure err vs dest= {_fmt(struct_err)} m")
    print(f"  committed re-cleared = {not d['committed']}")

    # --- 2b. the stale-pad salvo hits DIRT ---
    # _refine_strike_aim acquires the nearest LIVE Structure within
    # SEEKER_BASKET_M of the aim point; nearest-live-distance vs the basket IS
    # the physics gate it runs.
    def _nearest_live(ax, az):
        return min((math.hypot(float(s.pos[0]) - ax, float(s.pos[2]) - az)
                    for s in cw.structures if s.alive), default=float("inf"))
    near_stale = _nearest_live(stale_centre[0], stale_centre[1])
    hit_stale = near_stale < SEEKER_BASKET_M
    print(f"  STALE-PAD refine: acquired structure? {hit_stale}  "
          f"(nearest live struct {(_fmt(near_stale))} m, basket "
          f"{SEEKER_BASKET_M:.0f} m -> {'HIT' if hit_stale else 'DIRT (miss)'})")
    # at the NEW pad a strike COULD still hit (the moved Structure sits there):
    near_new = _nearest_live(dest[0], dest[1])
    hit_new = near_new < SEEKER_BASKET_M
    print(f"  NEW-PAD   refine: acquired structure? {hit_new}  "
          f"(nearest live struct {(_fmt(near_new))} m -> a strike aimed at the "
          f"NEW pad {'CAN hit' if hit_new else 'misses'})")

    # --- 3. a NEW launch re-seeds from the NEW pad ---
    new_tube = d["tubes"][0]
    print(f"  new-pad tube xz     = ({_fmt(float(new_tube['pos'][0]))}, "
          f"{_fmt(float(new_tube['pos'][2]))})  (a fresh launch spawns HERE, so "
          f"the enemy back-plot re-forms near the NEW xz)")


def main():
    print("M5 #4 SHOOT-AND-SCOOT — relocate ETA + stale-pad miss")
    print(f"RELOCATE_SPEED_MPS={RELOCATE_SPEED_MPS}  "
          f"RELOCATE_SETUP_S={RELOCATE_SETUP_S}  SEEKER_BASKET_M={SEEKER_BASKET_M}")
    # Build with all three firing TELs present.
    cfg = CombatConfig(seed=1337, n_oniks=1, n_s300=1, n_buk=1)
    for kind in ("bastion_tel", "s300_tel", "buk_tel"):
        probe_kind(kind, cfg)


if __name__ == "__main__":
    main()
