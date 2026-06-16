"""End-to-end balance probe: does the enemy now localize and STRIKE the player
base after the back-plot fix? Fire lo-lo Oniks from the base with the radar ON,
run a full battle, and measure how close hostile land-attack rounds get to the
bastion TEL (and whether the base is ever destroyed)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.missile import Missile
from sim.sam import SamMissile

DT = 1.0 / 120.0


def nearest_tel(world):
    return [s for s in world.structures if s.kind == "bastion_tel"]


def run(seed=1337, minutes=32.0, n_pantsir=2):
    cfg = CombatConfig(seed=seed, n_pantsir=n_pantsir)
    w = CombatWorld(cfg)
    tels = nearest_tel(w)
    tel_pos = [s.pos.copy() for s in tels]
    # A fixed surface aim point at the fleet (first destroyer), for lo-lo fire.
    ships = [s for s in w.ships if getattr(s, "alive", True)]
    tgt = ships[0].pos.copy(); tgt[1] = 0.0

    closest_strike = 1e18
    closest_kind = "-"
    fired = 0
    next_fire_t = 5.0
    steps = int(minutes * 60.0 / DT)
    cluster_err = None
    _per = {}                       # weapon_id -> closest approach to a TEL
    next_prog = 240.0
    print(f"--- battle seed={seed} pantsir={n_pantsir} ({minutes} min) ---",
          flush=True)
    for i in range(steps):
        now = w.sim_time
        if now >= next_fire_t and fired < 12:
            for t in w._oniks_tubes:
                t["reload_left"] = 0.0
            w._step_oniks_tubes(0.0)
            m = w.launch("lo-lo", tgt)
            if m is not None:
                fired += 1
                next_fire_t = now + 75.0
        w.step(DT)
        for mm in w.missiles:
            if not mm.alive or not getattr(mm, "is_hostile", False):
                continue
            if isinstance(mm, SamMissile):
                continue
            wid = getattr(getattr(mm, "weapon", None), "weapon_id", "?")
            for tp in tel_pos:
                d = float(np.linalg.norm(mm.pos - tp))
                if d < closest_strike:
                    closest_strike = d
                    closest_kind = wid
                kd = _per.get(wid, 1e18)
                if d < kd:
                    _per[wid] = d
        if cluster_err is None:
            cl = w.commander.picture.targetable_clusters()
            if cl:
                cluster_err = min(
                    float(np.hypot(c.centre[0] - tp[0], c.centre[1] - tp[2]))
                    for c in cl for tp in tel_pos)
                print(f"  t={now:.0f}s: base LOCALIZED, cluster_err="
                      f"{cluster_err:.0f}m", flush=True)
        if now >= next_prog:
            next_prog += 240.0
            print(f"  t={now:.0f}s closest_strike={closest_strike:.0f}m "
                  f"({closest_kind}) TELs={sum(s.alive for s in tels)}/{len(tels)}"
                  f" defeated={w.defeated}", flush=True)
        if w.defeated:
            print(f"  t={now:.0f}s *** BASE DEFEATED ***", flush=True)
            break
    alive_tels = sum(1 for s in tels if s.alive)
    per = {k: round(v) for k, v in _per.items()}
    print(f"RESULT seed={seed} pantsir={n_pantsir} fired={fired} "
          f"cluster_err={None if cluster_err is None else round(cluster_err)} "
          f"closest_strike={closest_strike:.0f}m({closest_kind}) "
          f"per_weapon_closest={per} "
          f"TELs_alive={alive_tels}/{len(tels)} defeated={w.defeated}", flush=True)


def main():
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1337
    pantsir = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    mins = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    run(seed=seed, n_pantsir=pantsir, minutes=mins)


if __name__ == "__main__":
    main()
