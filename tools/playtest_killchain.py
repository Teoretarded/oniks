"""Focused COMBAT playtest: the core kill chain end-to-end through real UI —
drone SAR-finds a ship, the Bastion fires a hi-lo Oniks at the track, the
engagement plays out, and the crash recipe (orbit+zoom an enemy SM-2) runs.

Run: python tools/playtest_killchain.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT
from game import tactical_map as tm
from sim.missile import Missile
from sim.sam import SamMissile
from world.combat_config import CombatConfig


def shot(app, name, note=""):
    st = app.state
    for _ in range(18):
        st.render(PHYS_DT)
    pygame.image.save(app.window.read_pixels_to_surface(),
                      os.path.join("renders", f"pk_{name}.png"))
    print(f"[shot] pk_{name}.png  {note}")


def key(state, k):
    state.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k, unicode="",
                                          mod=0))
    state.handle_event(pygame.event.Event(pygame.KEYUP, key=k, mod=0))


def click(state, xz, button=1):
    sx, sy = state.tactical_map.view.world_to_screen((float(xz[0]),
                                                      float(xz[1])))
    for et in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        state.handle_event(pygame.event.Event(et, button=button,
                                              pos=(int(sx), int(sy))))


def step(state, seconds):
    for _ in range(int(seconds / PHYS_DT)):
        state.sim_step(PHYS_DT)


def main() -> int:
    app = App(hidden=True)
    cfg = CombatConfig(seed=7, n_destroyers=4, oniks_ammo=20)
    app.start_combat(cfg)
    state, world = app.state, app.state.world
    target_ship = min(world.ships, key=lambda s: float(np.hypot(s.pos[0],
                                                                s.pos[2])))
    tx, tz = float(target_ship.pos[0]), float(target_ship.pos[2])
    rng_km = (tx**2 + tz**2) ** 0.5 / 1000
    print(f"[kc] target {target_ship.ship_id} at ({tx/1000:.0f},{tz/1000:.0f}) "
          f"km, range {rng_km:.0f} km from base")

    # Map up; drone active; route it straight over the target for a SAR find.
    # Wait on the MapView, not on get_map_pixels(). view is created on the first
    # map draw (tactical_map.draw) and is exactly what click() needs; the pixel
    # raster builds on a background thread and can already be ready, so waiting
    # on it lets the loop exit before any map frame draws and view stays None.
    state.map_open = True
    deadline = 0
    while (state.tactical_map.view is None or tm.get_map_pixels() is None) \
            and deadline < 120 * 90:
        state.sim_step(PHYS_DT)
        state.render(PHYS_DT)
        deadline += 1
    while state.active_platform != "drone":
        key(state, pygame.K_TAB)
    click(state, (tx, tz - 30_000.0), button=3)
    click(state, (tx, tz), button=3)
    print(f"[kc] drone routed over the target; flying out...")

    # Fast-forward until a SURFACE track forms (SAR) or the drone dies / times out.
    surf_cid = None
    for _ in range(int(2400.0 / PHYS_DT)):       # up to 40 min sim
        state.sim_step(PHYS_DT)
        surf = [c for c, t in world.contacts.tracks.items()
                if not t.get("is_air")]
        if surf:
            surf_cid = surf[0]
            break
        if world.drone is None or not world.drone.alive:
            print("[kc] drone lost before a surface fix")
            break
    print(f"[kc] t={world.sim_time:.0f}s surface_track={surf_cid} "
          f"drone_alive={world.drone is not None and world.drone.alive}")
    shot(app, "01_sar_find", "SAR/ELINT surface track on the fleet")

    if surf_cid is None:
        print("[kc] no surface fix — recon outcome (see findings)")
        pygame.quit()
        return 0

    # Switch to the Bastion, target the track, fire a hi-lo Oniks at it.
    while state.active_platform != "bastion":
        key(state, pygame.K_TAB)
    est = world.contacts.estimated_pos(surf_cid, world.sim_time)
    key(state, pygame.K_1)                       # hi-lo (range > lo-lo fuel)
    click(state, (est[0], est[2]), button=1)     # LMB target the contact
    ammo0 = world._oniks_ammo
    key(state, pygame.K_SPACE)
    fired = world._oniks_ammo < ammo0
    print(f"[kc] hi-lo Oniks fired={fired} ammo {ammo0}->{world._oniks_ammo}")
    shot(app, "02_oniks_away", "hi-lo Oniks launched at the surface track")

    # Grab the round we just fired so we can read its fate at the end. The
    # player Oniks is sim.missile.Missile (the enemy's strike rounds are the
    # separate sim.strike.StrikeMissile), so filter on Missile + not hostile.
    oniks = next((m for m in world.missiles if isinstance(m, Missile)
                  and not getattr(m, "is_hostile", False)), None)
    min_to_ship = float("inf")   # Oniks closest 3D approach to the target ship
    min_sam_gap = float("inf")   # closest any hostile SM-2 got to the Oniks

    # Fly it out; watch the SM-2 engagement and record what kills the Oniks.
    saw_sam = False
    grace = -1                   # after the Oniks resolves, watch a beat then stop
    for _ in range(int(900.0 / PHYS_DT)):        # up to 15 min flight
        state.sim_step(PHYS_DT)
        if oniks is not None and oniks.alive:
            min_to_ship = min(min_to_ship,
                              float(np.linalg.norm(oniks.pos - target_ship.pos)))
            for m in world.missiles:
                if isinstance(m, SamMissile) and getattr(m, "is_hostile", False):
                    min_sam_gap = min(min_sam_gap,
                                      float(np.linalg.norm(m.pos - oniks.pos)))
        sam = next((m for m in world.missiles if isinstance(m, SamMissile)
                    and getattr(m, "is_hostile", False)), None)
        if sam is not None and not saw_sam:
            saw_sam = True
            # Crash recipe: close the map, orbit + zoom the enemy SM-2.
            state.map_open = False
            state.followed = sam
            state.rig.set_mode("orbit")
            state.rig.retarget()
            state.rig._orbit_dist = 8.0
            state.rig._orbit_dist_target = 8.0
            step(state, 2.0)
            shot(app, "03_orbit_enemy_sam", "orbit+zoom enemy SM-2 (crash recipe)")
            print("[kc] survived orbit+zoom of the enemy SM-2")
            state.map_open = True
        if not target_ship.alive:
            break
        if oniks is not None and not oniks.alive:   # round resolved — settle, stop
            grace = int(3.0 / PHYS_DT) if grace < 0 else grace - 1
            if grace <= 0:
                break

    # Classify the Oniks's fate from the geometry we recorded.
    if not target_ship.alive:
        fate = "TARGET KILLED"
    elif oniks is None:
        fate = "no Oniks tracked (launch failed?)"
    elif oniks.alive:
        fate = f"still in flight at window close ({min_to_ship/1000:.0f} km from ship)"
    else:
        impact = oniks.impact_pos if oniks.impact_pos is not None else oniks.pos
        from_ship = float(np.linalg.norm(impact - target_ship.pos))
        if min_sam_gap <= 50.0:
            fate = f"INTERCEPTED by SM-2 (closest gap {min_sam_gap:.0f} m, fuse 20 m)"
        elif getattr(oniks, "fuel", 1.0) <= 1.0:
            fate = f"FUEL-EXHAUSTED, fell {from_ship/1000:.0f} km short"
        elif from_ship <= 80.0:
            fate = f"HIT the ship but it survived (impact {from_ship:.0f} m)"
        else:
            fate = f"terminal miss, died {from_ship/1000:.0f} km from target"

    print(f"[kc] t={world.sim_time:.0f}s target_alive={target_ship.alive} "
          f"saw_enemy_sam={saw_sam}")
    print(f"[kc] Oniks closest_to_ship={min_to_ship/1000:.1f} km  "
          f"closest_SM2_gap={min_sam_gap:.0f} m  "
          f"fuel_left={getattr(oniks, 'fuel', float('nan')):.0f} kg")
    print(f"[kc] FATE: {fate}")
    shot(app, "04_engagement", "after the engagement")
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
