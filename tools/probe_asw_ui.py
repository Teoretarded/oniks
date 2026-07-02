"""One-shot GL probe: the M5 ASW player UI end-to-end in a real battle.

Boots a COMBAT battle with a sub + buoys + ASW rounds, arms buoy-drop mode
(U), drops a bracketing field around the boat's area with map LMB clicks,
waits for the acoustic cross-fix, fires the ASW round (K), and screenshots
the tactical map at each stage.  Verifies (a) the modal drop flow consumes
clicks, (b) the SSK FIX glyph + uncertainty ring render, (c) the ASW round
flies and the kill lands — all through the real input path.

Run: python tools/probe_asw_ui.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT
from world.combat_config import CombatConfig


def save(app, name):
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join("renders", name))
    print(f"[asw] renders/{name}")


def key(app, k):
    app.state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0,
                                              unicode=""))
    app.state.handle_event(pygame.event.Event(pygame.KEYUP, key=k, mod=0))


def click_map(state, world_xz):
    sx, sy = state.tactical_map.view.world_to_screen(
        (float(world_xz[0]), float(world_xz[1])))
    state.handle_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=(int(sx), int(sy))))


def main() -> int:
    app = App(hidden=True)
    app.start_combat(CombatConfig(seed=1337, n_subs=1, n_sonobuoys=3,
                                  asw_ammo=2, sub_kalibr_ammo=4))
    state = app.state
    world = state.world
    sub = world.subs[0]
    sx, sz = float(sub.pos[0]), float(sub.pos[2])
    print(f"[asw] sub spawned {np.hypot(sx, sz)/1e3:.0f} km out")

    # Open the map, arm buoy-drop, drop a bracketing field via real clicks.
    key(app, pygame.K_m)
    state.render(1 / 60)
    key(app, pygame.K_u)                      # arm drop mode
    print("[asw] armed:", state.buoy_drop_armed)
    state.render(1 / 60)
    save(app, "asw_01_armed.png")
    for bx, bz in ((sx - 15_000.0, sz - 10_000.0),
                   (sx + 15_000.0, sz - 10_000.0),
                   (sx, sz + 8_000.0)):
        click_map(state, (bx, bz))
    print("[asw] buoys placed:", len(world.sonobuoys),
          "armed after exhaust:", state.buoy_drop_armed)

    # Hold the boat loud until the cross-fix forms (probe shortcut: state
    # forcing is for the PROBE only, the sensors do the localizing).
    from sim.submarine import SUB_LAUNCH
    sub.state = SUB_LAUNCH
    fixed = False
    for _ in range(int(8.0 / PHYS_DT)):
        sub.launch_transient = True
        state.sim_step(PHYS_DT)
        if sub.sub_id in world.sub_contacts:
            fixed = True
            break
    print("[asw] cross-fix formed:", fixed,
          "quality:", world.sub_contacts.get(sub.sub_id, {}).get("quality"))
    state.render(1 / 60)
    save(app, "asw_02_fix.png")

    # Fire the ASW round through the real key.
    key(app, pygame.K_k)
    print("[asw] asw rounds in flight:", len(world.asw_rounds),
          "ammo left:", world.asw_ammo_left)
    for _ in range(30):
        state.sim_step(PHYS_DT)
    state.render(1 / 60)
    save(app, "asw_03_round_out.png")

    # Run the prosecution out.
    for _ in range(int(400.0 / PHYS_DT)):
        state.sim_step(PHYS_DT)
        if not world.asw_rounds:
            break
    print("[asw] sub alive:", sub.alive)
    state.render(1 / 60)
    save(app, "asw_04_after.png")

    ok = fixed and not sub.alive and len(world.sonobuoys) == 3
    print("[asw]", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
