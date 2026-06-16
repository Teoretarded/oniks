"""Scripted COMBAT playtest: drive a real battle through real inputs, save a
storyboard of screenshots + a state/event log for review.

This is a HARNESS for the orchestrator's hands-on playtest — it plays like a
player (key events, map clicks, camera) rather than poking the sim API, so it
exercises the real UI paths (the crash recipe included). Headless GL.

Run: python tools/playtest_combat.py
Outputs: renders/pt_*.png  +  a printed beat log.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT
from game import tactical_map as tm
from world.combat_config import CombatConfig

SHOTS = []


def shot(app, name, note="", settle_frames=18):
    state = app.state
    for _ in range(settle_frames):           # settle the camera/effects
        state.render(PHYS_DT)
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join("renders", f"pt_{name}.png"))
    SHOTS.append((name, note))
    print(f"[shot] pt_{name}.png  {note}")


def key(state, k):
    state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k,
                                          unicode="", mod=0))
    state.handle_event(pygame.event.Event(pygame.KEYUP, key=k, mod=0))


def click(state, world_xz, button=1):
    sx, sy = state.tactical_map.view.world_to_screen(
        (float(world_xz[0]), float(world_xz[1])))
    for et in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        state.handle_event(pygame.event.Event(et, button=button,
                                              pos=(int(sx), int(sy))))
    return int(sx), int(sy)


def run_sim(state, seconds, scale=1.0):
    """Fast-forward: step the sim only (no per-frame render — that is what
    made the naive harness take tens of thousands of renders). A handful of
    render frames are issued right before each shot() to settle the camera."""
    for _ in range(int(seconds / PHYS_DT)):
        state.sim_step(PHYS_DT)


def settle(state, frames=18):
    """Render a few frames so the camera rig/effects catch up before a shot."""
    for _ in range(frames):
        state.render(PHYS_DT)


def wait_map_ready(state):
    deadline = 0
    while tm.get_map_pixels() is None and deadline < 120 * 90:
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
        deadline += 1


def picture(world):
    """One-line summary of the player's fog-of-war picture + ammo + base."""
    trk = world.contacts.tracks
    air = sum(1 for t in trk.values() if t.get("is_air"))
    surf = len(trk) - air
    oniks = getattr(world, "_oniks_ammo", None)
    alive_struct = [s.kind for s in world.structures if s.alive]
    return (f"t={world.sim_time:6.0f}s tracks={len(trk)}(surf {surf}/air {air}) "
            f"oniks_ammo={oniks} missiles={len(world.missiles)} "
            f"base={'/'.join(alive_struct)} "
            f"def={world.defeated} vic={world.victorious}")


def main() -> int:
    app = App(hidden=True)
    # A brisk, eventful battle: a few destroyers a touch closer-weighted by
    # seed, generous Oniks so the playtest can shoot freely.
    cfg = CombatConfig(seed=7, n_destroyers=4, n_enemy_radars=2,
                       oniks_ammo=20, oniks_mag_reload_s=30.0)
    app.start_combat(cfg)
    state = app.state
    world = state.world
    print("[playtest] battle:", cfg)
    print("[playtest] enemy ships:",
          [(s.ship_id, round(float(s.pos[0])/1000), round(float(s.pos[2])/1000))
           for s in world.ships])

    # ---- Beat 1: opening battlespace (3D) ----
    run_sim(state, 2.0)
    shot(app, "01_open_3d", "opening 3D view at the Bastion")
    print("[beat1]", picture(world))

    # ---- Beat 2: tactical map, fog of war (should be near-empty) ----
    state.map_open = True
    wait_map_ready(state)
    run_sim(state, 0.5)
    shot(app, "02_map_initial", "tactical map - fog of war at start")
    print("[beat2]", picture(world))

    # ---- Beat 3: task the recon drone toward the fleet ----
    key(state, pygame.K_TAB)          # bastion -> s300
    key(state, pygame.K_TAB)          # s300 -> drone
    print("[beat3] active platform:", state.active_platform)
    # Route the drone out toward the believed fleet bearing (+z, toward enemy).
    for wp in ((20_000.0, 120_000.0), (0.0, 220_000.0), (-30_000.0, 300_000.0)):
        click(state, wp, button=3)    # RMB waypoint
    drone = world.drone
    print("[beat3] drone route len:", len(drone.route) if drone else None)
    shot(app, "03_drone_tasked", "drone route plotted toward the fleet")

    # ---- Beat 4: fly the recon leg, watch ELINT build a picture ----
    run_sim(state, 240.0, scale=8.0)  # ~4 min of recon at 8x
    shot(app, "04_recon_picture", "after the recon leg - ELINT/SAR picture")
    print("[beat4]", picture(world))
    elint = getattr(world, "elint", None)
    if elint is not None:
        fixes = [eid for eid in getattr(elint, "_pairs", {})
                 if elint.is_actionable(eid)]
        print("[beat4] actionable ELINT fixes:", fixes)

    # ---- Beat 5: launch a lo-lo Oniks at a surface track ----
    key(state, pygame.K_TAB)          # drone -> bastion
    key(state, pygame.K_TAB)          # ... wrap: bastion? confirm below
    print("[beat5] active platform:", state.active_platform)
    surf_tracks = [(cid, t) for cid, t in world.contacts.tracks.items()
                   if not t.get("is_air")]
    fired = None
    if surf_tracks:
        cid, t = surf_tracks[0]
        est = world.contacts.estimated_pos(cid, world.sim_time)
        key(state, pygame.K_2)        # lo-lo profile
        click(state, (est[0], est[2]), button=1)   # LMB target the contact
        key(state, pygame.K_SPACE)    # launch
        fired = next((m for m in world.missiles
                      if not getattr(m, "is_hostile", False)
                      and getattr(m, "weapon", None) is not None), None)
        print(f"[beat5] launched at {cid} est=({est[0]:.0f},{est[2]:.0f})")
    else:
        print("[beat5] no surface track yet - launching on a map coordinate")
        key(state, pygame.K_2)
        click(state, (0.0, 200_000.0), button=1)
        key(state, pygame.K_SPACE)
    shot(app, "05_oniks_launched", "lo-lo Oniks away")
    print("[beat5]", picture(world))

    # ---- Beat 6: follow the Oniks (camera cycle), watch the engagement ----
    key(state, pygame.K_RIGHTBRACKET)  # cycle subject onto a missile
    run_sim(state, 60.0, scale=4.0)
    shot(app, "06_oniks_enroute", "Oniks en route (chase cam)")
    print("[beat6]", picture(world))

    # ---- Beat 7: radar silence toggle ----
    key(state, pygame.K_r)
    run_sim(state, 1.0)
    shot(app, "07_radar_silent", "radar emissions toggled")
    rs = getattr(world, "radar_station", None)
    print("[beat7] radar emitting:", rs.emitting if rs else None)
    key(state, pygame.K_r)            # back on

    # ---- Beat 8: let the battle develop, capture any engagement ----
    run_sim(state, 300.0, scale=8.0)
    shot(app, "08_midbattle_map", "mid-battle picture")
    print("[beat8]", picture(world))

    # ---- Beat 9: orbit-zoom an enemy interceptor if one exists (crash recipe) ----
    from sim.sam import SamMissile
    hostile_sam = next((m for m in world.missiles
                        if isinstance(m, SamMissile)
                        and getattr(m, "is_hostile", False)), None)
    if hostile_sam is not None:
        state.map_open = False
        state.followed = hostile_sam
        state.rig.set_mode("orbit")
        state.rig.retarget()
        state.rig._orbit_dist = 8.0
        state.rig._orbit_dist_target = 8.0
        run_sim(state, 3.0)
        shot(app, "09_orbit_enemy_sam", "orbit+zoom enemy SM-2 (crash recipe)")
        print("[beat9] survived orbit-zoom of enemy SM-2")
    else:
        print("[beat9] no enemy SM-2 in flight to orbit")

    # ---- Beat 10: fast-forward toward an outcome ----
    state.map_open = True
    for _ in range(20):
        run_sim(state, 120.0, scale=16.0)
        if world.defeated or world.victorious:
            break
    shot(app, "10_outcome", "battle outcome")
    print("[beat10]", picture(world))

    print("\n[playtest] storyboard:")
    for name, note in SHOTS:
        print(f"  pt_{name}.png  {note}")
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
