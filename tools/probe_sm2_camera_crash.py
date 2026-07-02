"""Reproduce the user-reported crash: orbit an enemy SM-2 zoomed in close.

Run: python tools/probe_sm2_camera_crash.py
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT


def main() -> int:
    from sim.sam import SamMissile

    app = App(hidden=True)
    app.start_combat()
    state = app.state
    world = state.world

    # Provoke an enemy SM-2: hi-lo Oniks at destroyer_00.
    dd = world.ships[0]
    world.launch("hi-lo", np.array([dd.pos[0], 0.0, dd.pos[2]]))
    sam = None
    for _ in range(int(600.0 / PHYS_DT)):
        state.sim_step(PHYS_DT)
        sam = next((m for m in world.missiles
                    if isinstance(m, SamMissile) and m.alive
                    and getattr(m, "rng", None) is not None), None)
        if sam is not None:
            break
    if sam is None:
        print("[probe] no enemy SM-2 appeared - cannot reproduce")
        return 1
    print(f"[probe] enemy SM-2 in flight, phase={sam.phase}")

    # Faithful UI path: open the map, CLICK the SM-2 like the user did,
    # then orbit it zoomed in with the map still open part of the time.
    state.map_open = True
    import time as _t
    from game import tactical_map as tm
    deadline = _t.time() + 120.0
    while _t.time() < deadline and tm.get_map_pixels() is None:
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
    state.sim_step(PHYS_DT)
    state.render(PHYS_DT)
    sx, sy = state.tactical_map.view.world_to_screen(
        (float(sam.pos[0]), float(sam.pos[2])))
    for etype in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        state.handle_event(pygame.event.Event(etype, button=1,
                                              pos=(int(sx), int(sy))))
    print(f"[probe] clicked map at ({int(sx)}, {int(sy)}); "
          f"selected={state.tactical_map.selected_missile is sam}, "
          f"followed={state.followed is sam}")
    if state.followed is not sam:
        state.tactical_map.selected_missile = sam
        state.followed = sam
        state.rig.retarget()
        print("[probe] direct-selected hostile SM-2 for camera coverage")
    keep_map_open = os.environ.get("PROBE_MAP_OPEN") == "1"
    for _ in range(240):                     # 2 s with the map open
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
    if not keep_map_open:
        state.map_open = False
    state.rig.set_mode("orbit")
    state.rig.retarget()
    state.rig._orbit_dist = 8.0
    state.rig._orbit_dist_target = 8.0
    frames = 0
    after_death = 0
    try:
        while frames < 120 * 300 and after_death < 120 * 10:
            state.sim_step(PHYS_DT)
            state.render(PHYS_DT)
            frames += 1
            if not sam.alive:
                after_death += 1
        print(f"[probe] NO CRASH after {frames} frames "
              f"(sam alive={sam.alive}, {after_death} frames past death)")
        return 0
    except Exception:
        print(f"[probe] CRASH at frame {frames}:")
        traceback.print_exc()
        return 2
    finally:
        pygame.quit()


if __name__ == "__main__":
    sys.exit(main())
