"""Verify the launch-visibility feature: enemy SM-2 / AIM-9X appear on the
player picture the instant they fire (launch_warning), while Tomahawk/JASSM/HARM
stay radar-gated. Develops a battle with hi-lo Oniks (which provoke SM-2s), then
checks how many of each channel are in contacts.tracks."""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from playtest_harness import build_world

PHYS_DT = 1.0 / 120.0


def main():
    w = build_world(7, n_destroyers=6, oniks_ammo=60, oniks_mag_reload_s=20.0)
    for chunk in range(24):                  # up to 12 min
        if w.launcher_armed:
            tgt = min(w.ships, key=lambda s: float(np.hypot(s.pos[0], s.pos[2])))
            w.launch("hi-lo", np.array([tgt.pos[0], 0.0, tgt.pos[2]]), ())
        for _ in range(int(30.0 / PHYS_DT)):
            w.step(PHYS_DT)
        lw = [m for m in w.missiles if getattr(m, "is_hostile", False)
              and getattr(m, "launch_warning", False)]
        if len(lw) >= 2:
            break

    tracks = w.contacts.tracks
    lw = [m for m in w.missiles if getattr(m, "is_hostile", False)
          and getattr(m, "launch_warning", False)]
    gated = [m for m in w.missiles if getattr(m, "is_hostile", False)
             and not getattr(m, "launch_warning", False)]
    lw_vis = sum(1 for m in lw if getattr(m, "aircraft_id", None) in tracks)
    g_vis = sum(1 for m in gated if getattr(m, "aircraft_id", None) in tracks)

    print(f"t={w.sim_time:.0f}s")
    print(f"launch_warning rounds (SM-2/AIM-9X): {len(lw)} | "
          f"visible immediately: {lw_vis} -> "
          f"{'OK' if lw and lw_vis == len(lw) else 'CHECK'}")
    print(f"gated rounds (Tomahawk/JASSM/HARM):  {len(gated)} | "
          f"in tracks (radar only): {g_vis}")
    print("lw types:   ", dict(Counter(type(m).__name__ for m in lw)))
    print("gated types:", dict(Counter(type(m).__name__ for m in gated)))


if __name__ == "__main__":
    main()
