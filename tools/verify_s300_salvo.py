"""Verify the S-300 per-tube salvo mechanic (2 launchers x 4 tubes = 8 tubes).

Steps a battle until an enemy air contact is tracked, then fires 8 S-300s at it
back-to-back and confirms each comes from its OWN distinct tube, the pool tracks,
and tubes re-cock on their own timers.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from playtest_harness import build_world

PHYS_DT = 1.0 / 120.0


def main():
    w = build_world(7, n_s300=2, s300_48n6_ammo=16)
    nl = len(w._s300_launcher_positions)
    nt = len(w._s300_tubes)
    ns = sum(1 for s in w.structures if s.kind == "s300_tel")
    print(f"s300 launchers={nl} tubes={nt} sam_ammo={w.sam_ammo} "
          f"s300_tel_structs={ns} armed={w.sam_launcher_armed}")
    print("launcher x:", [round(float(p[0]), 1)
                          for p in w._s300_launcher_positions])

    # advance until a trackable air contact above the 48N6 floor exists
    air_id = None
    for _ in range(30):                      # up to 15 min
        for _ in range(int(30.0 / PHYS_DT)):
            w.step(PHYS_DT)
        air = [cid for cid, t in w.contacts.tracks.items()
               if t.get("is_air") and float(t["pos"][1]) > 150.0
               and w._find_air_entity(cid) is not None]
        if air:
            air_id = air[0]
            break
    print(f"air contact={air_id} at t={w.sim_time:.0f}s "
          f"alt={float(w.contacts.tracks[air_id]['pos'][1]):.0f}m"
          if air_id else "no air contact formed")
    if air_id is None:
        return

    spawns = []
    for i in range(10):                      # 8 tubes -> 8 should fire
        m = w.launch_sam(air_id, "48n6")
        if m is not None:
            spawns.append(tuple(np.round(m.pos, 1)))
        print(f"  press {i + 1}: fired={m is not None} sam_ammo={w.sam_ammo} "
              f"armed={w.sam_launcher_armed}")
    distinct = len({tuple(np.round(s, 1)) for s in spawns})
    print(f"\nSALVO: {len(spawns)} S-300s from {distinct} distinct tubes "
          f"-> {'OK' if len(spawns) == 8 and distinct == 8 else 'CHECK'}")

    for _ in range(int(15.0 / PHYS_DT)):     # let tubes re-cock
        w.step(PHYS_DT)
    print(f"after reload: armed={w.sam_launcher_armed} sam_ammo={w.sam_ammo} "
          f"-> {'OK' if w.sam_launcher_armed else 'CHECK'}")


if __name__ == "__main__":
    main()
