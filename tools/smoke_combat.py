"""One-shot COMBAT smoke check: boot hidden, start combat, step, screenshot.

Run: python tools/smoke_combat.py   (exit code 0 = all checks passed)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from main import App, PHYS_DT


def main() -> int:
    app = App(hidden=True)
    app.start_combat()
    state = app.state
    world = state.world
    ok = True

    def check(name, cond):
        nonlocal ok
        print(f"[smoke] {'PASS' if cond else 'FAIL'}  {name}")
        ok = ok and cond

    check("state is CombatState", type(state).__name__ == "CombatState")
    check("two destroyers, nothing else",
          [s.ship_type for s in world.ships] == ["destroyer", "destroyer"])
    check("no aircraft", world.aircraft == [])
    check("one friendly radar site",
          [s["id"] for s in world.sites] == ["radar_player_00"])
    check("board is gated", world.contacts.visible_fn is not None)
    check("destroyer mesh registered", "destroyer" in state._ship_meshes)
    for _ in range(240):                      # 2 s of sim
        state.sim_step(PHYS_DT)
    check("destroyers alive after 2 s", all(s.alive for s in world.ships))
    # Fog of war end-to-end: the hulls sit ~330+ km out at sea level, far
    # past the mast-height radar's ~53 km horizon — no track may form.
    check("picture stays empty (hulls below the horizon)",
          world.contacts.tracks == {})
    check("S-300 refuses blind shot", world.launch_sam("x") is None)
    state.render(PHYS_DT)
    print(f"[smoke] screenshot {app._save_screenshot()}")
    pygame.quit()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
