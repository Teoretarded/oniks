"""One-shot COMBAT smoke check: boot hidden, start combat, step, screenshot.

Run: python tools/smoke_combat.py   (exit code 0 = all checks passed)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT
from sim.recon import RWR_LOCK, RWR_SPIKE
from world.combat import DRONE_RESPAWN_S, CombatWorld
from world.generation import BASE_POS


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

    # --- Phase 4: recon drone (pure sim — a FRESH CombatWorld so the
    # seeded sensor/engagement randomness is deterministic regardless of
    # what the sections above consumed).
    drone = world.drone
    check("drone platform in the TAB cycle",
          state.PLATFORMS == ("bastion", "s300", "drone"))
    # 5 km box: untasked, it orbits the base on the 4 km loiter circle
    # (the world above has already simmed minutes of Phase-3 sections).
    check("drone loiters over the base, airborne, route clear",
          drone is not None and drone.alive
          and abs(drone.pos[0] - BASE_POS[0]) < 5_000.0
          and abs(drone.pos[2] - BASE_POS[2]) < 5_000.0
          and drone.pos[1] == 18_000.0 and drone.route == [])
    check("drone is NOT in the aircraft list", world.aircraft == [])

    w4 = CombatWorld()
    d4 = w4.drone
    check("destroyers EMIT at spawn",
          all(s.radar.emitting for s in w4.ships))
    # ELINT: a 120 km crossing leg south of the fleet — bearings sweep a
    # wide angle while the hulls stay far past the ground radar horizon.
    d4.pos[0], d4.pos[2] = -60_000.0, 80_000.0
    d4.set_route([(60_000.0, 80_000.0)])
    DT4 = 0.25                              # coarse: nothing ballistic flies
    fix_t = None
    for _ in range(int(600.0 / DT4)):
        w4.step(DT4)
        if w4.elint.is_actionable("destroyer_00_spy1"):
            fix_t = w4.sim_time
            break
    for _ in range(8):                      # a couple of injection periods
        w4.step(DT4)
    check("ELINT fix actionable within sim minutes",
          fix_t is not None and fix_t < 600.0)
    ship00 = w4.ships[0]
    est = w4.elint.est_pos("destroyer_00_spy1")
    err = (float("inf") if est is None else
           float(np.hypot(est[0] - ship00.pos[0], est[2] - ship00.pos[2])))
    check("ELINT fix lands near the true hull", err < 5_000.0)
    check("ELINT track in the player picture, hulls past the horizon",
          "destroyer_00" in w4.contacts.tracks
          and not w4.radar_net.visible(ship00.pos, "ship"))

    # SAR: a SILENT ship found by overflight (fresh world: no ELINT help).
    w5 = CombatWorld()
    d5 = w5.drone
    w5.ships[1].radar.emitting = False      # destroyer_01 goes dark
    d5.pos[0], d5.pos[2] = 20_000.0, 140_000.0
    d5.set_route([(20_000.0, 200_000.0)])   # overfly its anchor
    sar_t = None
    for _ in range(int(400.0 / DT4)):
        w5.step(DT4)
        if "destroyer_01" in w5.contacts.tracks:
            sar_t = w5.sim_time
            break
    check("SAR overflight tracks the silent ship",
          sar_t is not None and d5.alive
          and not w5.radar_net.visible(w5.ships[1].pos, "ship"))

    # Engagement: the silent ship lights up with the drone inside its
    # 30 km stealth bubble — RWR SPIKE, then SM-2s and LOCK (120 Hz: a
    # round is flying).
    w5.ships[1].radar.emitting = True
    saw_spike = saw_lock = False
    max_inflight = 0
    killed = False
    for _ in range(int(240.0 / PHYS_DT)):
        w5.step(PHYS_DT)
        if w5.drone is None:
            killed = True
            break
        levels = [a[0] for a in w5.rwr.alerts()]
        saw_spike = saw_spike or RWR_SPIKE in levels
        saw_lock = saw_lock or RWR_LOCK in levels
        max_inflight = max(max_inflight, sum(
            1 for m in w5.missiles
            if m.alive and getattr(m, "target", None) is w5.drone))
    check("RWR SPIKE then LOCK inside the stealth bubble",
          saw_spike and saw_lock)
    check("drone engaged (<= 2 SM-2 per drone in flight)",
          1 <= max_inflight <= 2)
    check("close-in SM-2s kill the drone; respawn timer runs",
          killed and w5.drone_respawn_left == DRONE_RESPAWN_S
          and len(w5.drone_wrecks) == 1)
    events5 = [k for k, _ in w5.drain_events()]
    check("the kill classifies as a sam_kill air burst",
          "sam_kill" in events5)
    w5._drone_respawn_left = 0.5            # fast-forward the cooldown
    for _ in range(int(1.0 / DT4)):
        w5.step(DT4)
    check("replacement drone at the base, route cleared",
          w5.drone is not None and w5.drone.alive
          and abs(w5.drone.pos[0] - BASE_POS[0]) < 5_000.0
          and w5.drone.route == [])

    # --- GL pass over the Phase-4 UI: TAB cycle, drone HUD panel, map
    # overlays (drone diamond/route + ELINT rays/circles) and the [ / ]
    # subject swap — exercises the draw paths a human would hit first.
    state.cycle_platform()                  # bastion -> s300
    check("TAB reaches the drone platform",
          state.cycle_platform() == "drone")
    subject = state.cycle_camera_subject()
    check("[ / ] cycles onto the flying drone", subject is world.drone)
    state.render(PHYS_DT)                   # HUD: RECON DRONE panel
    state.map_open = True
    state.render(PHYS_DT)                   # map: drone + ELINT overlays
    state.map_open = False
    state.followed = None
    check("TAB wraps back to bastion", state.cycle_platform() == "bastion")

    state.render(PHYS_DT)
    print(f"[smoke] screenshot {app._save_screenshot()}")
    pygame.quit()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
