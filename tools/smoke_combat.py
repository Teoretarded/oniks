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

    # --- Phase 3: ESM localization -> Tomahawk strikes (pure sim steps,
    # no rendering — the world is GL-free; the GL parts stay above/below).
    check("radar station starts EMITTING",
          world.radar_station.alive and world.radar_station.emitting)
    check("base structures standing",
          all(s.alive for s in world.structures))
    ammo0 = sum(d.tomahawk_ammo for d in world.ships)
    for _ in range(int(120.0 / PHYS_DT)):   # 90 s fix + launch margin
        world.step(PHYS_DT)
    world.drain_events()
    check("ESM full fix after 90 s of emission",
          world.strikes.progress >= 1.0)
    fired = ammo0 - sum(d.tomahawk_ammo for d in world.ships)
    toms = [m for m in world.missiles if getattr(m, "is_hostile", False)]
    check(">=1 Tomahawk in flight after the fix",
          fired >= 1 and len(toms) >= 1)
    world.radar_station.emitting = False    # radar silence = the counter
    for _ in range(int(130.0 / PHYS_DT)):   # past the 120 s salvo period
        world.step(PHYS_DT)
    world.drain_events()
    check("radar silence halts further salvos",
          ammo0 - sum(d.tomahawk_ammo for d in world.ships) == fired)
    world.radar_station.emitting = True     # leave it on for the screenshot

    state.render(PHYS_DT)
    print(f"[smoke] screenshot {app._save_screenshot()}")
    pygame.quit()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
