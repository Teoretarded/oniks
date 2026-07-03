"""MEASURE the player's S-300 vs an inbound sea-skimming Tomahawk (live
playtest report 2026-07-03: 'I can't intercept the missiles').

Spawns a real hostile StrikeMissile (Tomahawk def, cruise ~50 m) inbound to
the base at several start ranges, waits for the radar to form the AIR track,
fires one 48N6 (and separately one 40N6) at the track through the real
world.launch_sam verb, and logs closest approach / outcome / where the SAM
died.  Also reports WHEN the track formed (the radar-horizon detection range
vs a 50 m skimmer) — the intercept window is detection-limited.

Run: python tools/probe_s300_vs_tomahawk.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.arsenal import TOMAHAWK
from sim.strike import StrikeMissile
from world.combat import CombatWorld
from world.combat_config import CombatConfig
from world.generation import BASE_POS

DT = 1.0 / 120.0


def run(start_km: float, round_id: str) -> None:
    cfg = CombatConfig(seed=1337)
    w = CombatWorld(cfg)
    base = np.array(BASE_POS, dtype=np.float64)
    # Inbound skimmer from the north at cruise, aimed at the base.
    start = base + np.array([0.0, 50.0, start_km * 1000.0])
    tlam = StrikeMissile(
        TOMAHAWK,
        pos_f64=start.copy(),
        vel_f64=np.array([0.0, 0.0, -250.0]),
        target_xz=(float(base[0]), float(base[2])),
        target_y=float(base[1]))
    w.missiles.append(tlam)

    track_id, track_t = None, None
    fired = False
    sam = None
    closest = 1e18
    for i in range(int(600.0 / DT)):
        w.step(DT)
        if not tlam.alive:
            break
        d = float(np.linalg.norm(
            np.asarray(tlam.pos) - base))
        # Wait for the AIR track on the skimmer
        if track_id is None:
            for cid, tr in w.contacts.tracks.items():
                if tr.get("is_air"):
                    est = w.contacts.estimated_pos(cid, w.sim_time)
                    if est is not None and abs(float(est[2]) - float(tlam.pos[2])) < 20_000.0:
                        track_id, track_t = cid, w.sim_time
                        break
        if track_id is not None and not fired:
            sam = w.launch_sam(track_id, round_id=round_id)
            fired = sam is not None
        if sam is not None and getattr(sam, "alive", False):
            closest = min(closest, float(np.linalg.norm(
                np.asarray(sam.pos) - np.asarray(tlam.pos))))
        if sam is not None and not sam.alive and not tlam.alive:
            break
        if sam is not None and not sam.alive and fired and i % 1200 == 0:
            pass
    det_rng = (float(np.linalg.norm(
        np.array([0.0, 50.0, 0.0]))) if track_t is None else None)
    trk = ("never" if track_t is None
           else f"t={track_t:5.1f}s")
    print(f"  start {start_km:5.0f} km  {round_id:5s}  track {trk}  "
          f"fired={fired}  closest={closest if closest < 1e17 else -1:8.1f} m  "
          f"tlam_alive={tlam.alive}  "
          f"outcome={'KILLED' if not tlam.alive else 'LEAKED/ALIVE'}")


def main() -> int:
    print("=== S-300 vs sea-skimming Tomahawk (real world verbs) ===")
    for rid in ("48n6", "40n6"):
        for km in (80.0, 60.0, 40.0, 25.0):
            run(km, rid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
