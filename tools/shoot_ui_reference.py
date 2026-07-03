"""UI reference pack for design work: every player-facing surface, staged in
a RICH battle state (contacts, inbounds, own missiles, buoys, sub fix), saved
to <Assets of oinks>/ui_reference/ with self-describing names.

Run: python tools/shoot_ui_reference.py
"""

from __future__ import annotations

import math
import os
import sys
import tempfile

os.environ["APPDATA"] = tempfile.mkdtemp(prefix="oniks_uiref_")   # save-safe

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT
from world.combat_config import CombatConfig
from world.generation import BASE_POS

OUT = "C:/Users/teoti/OneDrive/Desktop/Assets of oinks/ui_reference"


def save(app, name):
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join(OUT, name))
    print(f"[uiref] {name}")


def key(app, k):
    app.state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0,
                                              unicode=""))
    app.state.handle_event(pygame.event.Event(pygame.KEYUP, key=k, mod=0))


def settle(app, frames=6):
    for _ in range(frames):
        app.state.render(1.0 / 60.0)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = App(hidden=True)

    # ---------- menu ----------
    settle(app)
    save(app, "00_main_menu.png")

    # ---------- setup pages ----------
    app.open_combat_setup()
    for name in ("01_setup_world.png", "02_setup_enemy.png",
                 "03_setup_armory.png", "04_setup_defense.png"):
        settle(app)
        save(app, name)
        key(app, pygame.K_TAB)

    # ---------- rich battle ----------
    cfg = CombatConfig(seed=1337, n_subs=1, n_sonobuoys=4, asw_ammo=2,
                       sub_kalibr_ammo=4, n_buk=1, n_transports=1,
                       oniks_ammo=12)
    app.start_combat(cfg)
    st = app.state
    world = st.world
    base = np.array(BASE_POS, dtype=np.float64)

    # own salvo out + let the battle breathe so tracks form
    world.launch("lo-lo", base + np.array([20_000.0, 0.0, 240_000.0]))
    world.launch("hi-lo", base + np.array([-30_000.0, 0.0, 260_000.0]))
    for _ in range(int(75.0 / PHYS_DT)):
        st.sim_step(PHYS_DT)
    # enemy pressure: a Tomahawk salvo inbound (real machinery)
    world._fire_tomahawk_salvo(dict(
        target_pos=np.array([base[0], 0.0, base[2]]), target_id="uiref"))
    for _ in range(int(45.0 / PHYS_DT)):
        st.sim_step(PHYS_DT)

    # sub picture: buoys around the boat + hold it loud one pass
    if world.subs:
        from sim.submarine import SUB_LAUNCH
        sub = world.subs[0]
        sx, sz = float(sub.pos[0]), float(sub.pos[2])
        for bxz in ((sx - 14_000.0, sz - 9_000.0), (sx + 14_000.0, sz - 9_000.0),
                    (sx, sz + 7_000.0)):
            world.place_sonobuoy(bxz)
        sub.state = SUB_LAUNCH
        for _ in range(int(6.0 / PHYS_DT)):
            sub.launch_transient = True
            st.sim_step(PHYS_DT)

    # ---------- 3D HUD ----------
    settle(app)
    save(app, "10_battle_hud_3d.png")

    # battery panel over the 3D view
    key(app, pygame.K_o)
    settle(app)
    save(app, "11_battery_panel.png")
    key(app, pygame.K_o)

    # ---------- tactical map, crisis state ----------
    key(app, pygame.K_m)
    settle(app)
    save(app, "12_tactical_map_crisis.png")

    # zoomed to the base area (threat + defense picture)
    view = st.tactical_map.view
    view.center = np.array([float(base[0]), float(base[2]) + 60_000.0])
    view.meters_per_px = 260.0
    settle(app)
    save(app, "13_tactical_map_base_zoom.png")

    # ASW corner: frame the buoy field + SSK fix
    if world.subs:
        sub = world.subs[0]
        view.center = np.array([float(sub.pos[0]), float(sub.pos[2])])
        view.meters_per_px = 120.0
        settle(app)
        save(app, "14_tactical_map_asw.png")

    # F1 overlay over the map
    key(app, pygame.K_F1)
    settle(app)
    save(app, "15_controls_overlay.png")
    key(app, pygame.K_F1)

    # ---------- forensics / shot debrief ledger (J or map rail button) ----
    # Let the opening salvo RESOLVE first so the ledger shows CLOSED sheets
    # (death anchors + cause attribution), not just IN AIR rounds.  Bails
    # early if the battle decides itself (the end overlay owns input then).
    for _ in range(int(240.0 / PHYS_DT)):
        st.sim_step(PHYS_DT)
        if st._end_overlay is not None:
            break
        recs = st.flight_recorder.rounds()
        if recs and all(r["death"] is not None for r in recs):
            break
    key(app, pygame.K_j)
    settle(app)
    save(app, "16_forensics_ledger.png")
    key(app, pygame.K_DOWN)                 # leaf to the next sheet
    settle(app)
    save(app, "17_forensics_sheet2.png")
    key(app, pygame.K_2)                    # BLACK BOX tab: AWAITING DESIGN
    settle(app)
    save(app, "18_forensics_blackbox_placeholder.png")
    key(app, pygame.K_1)
    key(app, pygame.K_ESCAPE)               # close the sheet (back to map)
    key(app, pygame.K_m)                    # close the map

    # ---------- AAR / end overlay ----------
    from sim.ships import ST_GONE
    for s in world.ships:
        s.hp = 0
        s.state = ST_GONE
    world.airfield.alive = False
    for struct, _r in getattr(world, "enemy_radars", []):
        struct.alive = False
    for boat in getattr(world, "subs", []):
        boat.kill()
    for _ in range(int(3.0 / PHYS_DT)):
        st.sim_step(PHYS_DT)
    settle(app, 12)
    save(app, "20_aar_victory_grade.png")

    # DEBRIEF row (first AAR row): the ledger opens OVER the end screen.
    key(app, pygame.K_RETURN)
    settle(app, 14)                         # 80 ms press-flash then callback
    save(app, "21_aar_debrief_ledger.png")
    key(app, pygame.K_ESCAPE)               # leaf back to the AAR

    # ---------- campaign hub ----------
    app.open_campaign()
    settle(app)
    save(app, "30_campaign_hub_fresh.png")
    import game.campaign as campaign
    app.campaign = campaign.new_campaign(1337, n_battles=6)
    app.campaign.grades.extend(["S", "B"])
    app.campaign.battle_idx = 2
    app.campaign.ledger = {"oniks": 5, "zircon": 2, "asbm": 0, "kh31p": 0,
                           "s300_48n6": 3, "s300_40n6": 1}
    app.open_campaign()
    settle(app)
    save(app, "31_campaign_hub_battle3.png")

    print("[uiref] done ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
