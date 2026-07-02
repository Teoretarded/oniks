"""One-shot GL probe: the full CAMPAIGN loop end-to-end.

menu -> CAMPAIGN -> hub (fresh) -> START CAMPAIGN -> battle 1 -> forced
victory -> end overlay (CONTINUE CAMPAIGN / MAIN MENU) -> CONTINUE -> hub
(battle 2, ledger carried, grade on the ladder) -> START BATTLE -> battle 2
seed differs.  Screenshots each surface.

APPDATA is redirected to a temp dir FIRST so the probe can never touch a real
campaign save.

Run: python tools/probe_campaign_flow.py
"""

import os
import sys
import tempfile

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="oniks_probe_")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from main import App, PHYS_DT


def save(app, name):
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join("renders", name))
    print(f"[camp] renders/{name}")


def key(app, k):
    app.state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0,
                                              unicode=""))
    app.state.handle_event(pygame.event.Event(pygame.KEYUP, key=k, mod=0))


def settle(app, frames=10):
    for _ in range(frames):
        app.state.render(1.0 / 60.0)


def main() -> int:
    app = App(hidden=True)
    settle(app)

    # Menu -> CAMPAIGN (row 2)
    key(app, pygame.K_DOWN)
    key(app, pygame.K_DOWN)
    key(app, pygame.K_RETURN)
    settle(app)
    print("[camp] state:", type(app.state).__name__,
          "mode:", getattr(app.state, "mode", "?"))
    save(app, "camp_01_hub_fresh.png")

    # Fresh hub: DOWN DOWN to START CAMPAIGN, ENTER
    key(app, pygame.K_DOWN)
    key(app, pygame.K_DOWN)
    key(app, pygame.K_RETURN)
    settle(app, 30)
    print("[camp] state:", type(app.state).__name__,
          "battle_flag:", app.campaign_battle,
          "idx:", app.campaign.battle_idx)
    seed1 = app.sandbox.world._config.seed
    print("[camp] battle 1 seed:", seed1)

    # Run a bit, then force a decided battle (kill every enemy structure the
    # victory condition reads -- the probe is about the FLOW, not the fight).
    for _ in range(120):
        app.state.sim_step(PHYS_DT)
    w = app.sandbox.world
    from sim.ships import ST_GONE
    for s in w.ships:
        s.hp = 0
        s.state = ST_GONE          # alive is a property of state
    w.airfield.alive = False
    for struct, _r in getattr(w, "enemy_radars", []):
        struct.alive = False
    for _ in range(240):
        app.state.sim_step(PHYS_DT)
        if getattr(w, "victorious", False):
            break
    print("[camp] victorious:", getattr(w, "victorious", False))
    settle(app, 3)
    save(app, "camp_02_end_overlay.png")
    overlay = app.sandbox._end_overlay
    print("[camp] overlay options:", overlay.options if overlay else None)

    # CONTINUE CAMPAIGN (row 0)
    key(app, pygame.K_RETURN)
    settle(app, 30)
    print("[camp] state:", type(app.state).__name__,
          "mode:", getattr(app.state, "mode", "?"),
          "idx:", app.campaign.battle_idx,
          "grades:", app.campaign.grades,
          "ledger oniks:", app.campaign.ledger.get("oniks"))
    save(app, "camp_03_hub_battle2.png")

    # START BATTLE (row 0) -> battle 2 must run a DIFFERENT derived seed
    key(app, pygame.K_RETURN)
    settle(app, 30)
    seed2 = app.sandbox.world._config.seed
    print("[camp] battle 2 seed:", seed2, "(differs:", seed2 != seed1, ")")
    for _ in range(60):
        app.state.sim_step(PHYS_DT)
    settle(app, 3)
    save(app, "camp_04_battle2.png")

    ok = (seed2 != seed1 and app.campaign.battle_idx == 1
          and len(app.campaign.grades) == 1)
    print("[camp]", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
