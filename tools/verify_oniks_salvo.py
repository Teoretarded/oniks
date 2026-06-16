"""Verify the Oniks per-tube salvo mechanic (GL-free).

3 launchers x 2 tubes = 6 ready tubes, magazine 18. Confirms: 6 missiles fire
back-to-back each from its OWN distinct tube position, the 7th press is blocked
(all tubes spent), ammo tracks, and tubes reload from the pool after the timer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from playtest_harness import build_world

PHYS_DT = 1.0 / 120.0


def main():
    w = build_world(7, n_oniks=3, oniks_ammo=18, oniks_mag_reload_s=30.0)
    tubes = w._oniks_tubes
    bastions = [s for s in w.structures if s.kind == "bastion_tel"]
    print(f"launchers={len(w._oniks_launcher_positions)} tubes={len(tubes)} "
          f"ammo={w._oniks_ammo} armed={w.launcher_armed} "
          f"bastion_structs={len(bastions)}")
    print("launcher positions (x,z):",
          [(round(float(p[0]), 1), round(float(p[2]), 1))
           for p in w._oniks_launcher_positions])

    target = np.array([0.0, 0.0, 200_000.0])
    spawns = []
    for i in range(8):                       # 8 presses; only 6 should fire
        m = w.launch("hi-lo", target, ())
        if m is not None:
            spawns.append(tuple(np.round(m.pos, 2)))
        print(f"  press {i + 1}: fired={m is not None} ammo={w._oniks_ammo} "
              f"armed={w.launcher_armed} missiles={len(w.missiles)}")

    distinct = len({tuple(np.round(s, 1)) for s in spawns})
    print(f"\nSALVO: {len(spawns)} missiles from {distinct} distinct tubes")
    for p in spawns:
        print(f"    tube spawn {p}")
    ok_salvo = (len(spawns) == 6 and distinct == 6)
    print(f"  -> {'OK' if ok_salvo else 'FAIL'}: 6 missiles, 6 distinct tubes")

    for _ in range(int(31.0 / PHYS_DT)):     # let the tubes reload (30 s)
        w.step(PHYS_DT)
    loaded = sum(1 for t in tubes if t["loaded"])
    print(f"\nafter 31 s reload: armed={w.launcher_armed} ammo={w._oniks_ammo} "
          f"loaded_tubes={loaded}")
    print(f"  -> {'OK' if w.launcher_armed and loaded == 6 else 'FAIL'}: "
          f"battery re-armed from the pool")


if __name__ == "__main__":
    main()
