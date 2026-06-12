"""One-shot COMBAT smoke check: boot hidden, start combat, step, screenshot.

Run: python tools/smoke_combat.py   (exit code 0 = all checks passed)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pygame

from main import App, PHYS_DT
from sim.a2a import IrMissile
from sim.commander import (AIRFIELD_HARM, AIRFIELD_JASSM, CARRIER_HARM,
                           CARRIER_JASSM)
from sim.enemy_air import (FIGHTER_ALT_M, FS_PARKED, FS_REARMING, FS_RTB,
                           Fighter)
from sim.recon import RWR_LOCK, RWR_SPIKE
from sim.strike import HarmMissile, StrikeMissile
from world.combat import (AIRFIELD_XZ, DRONE_RESPAWN_S, SEEKER_BASKET_M,
                          CombatWorld)
from world.generation import BASE_POS
from world.world import SAM_TEL_POS


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
    check("two destroyers + exactly one carrier, nothing else",
          [s.ship_type for s in world.ships]
          == ["destroyer", "destroyer", "carrier"])
    check("no legacy aircraft (enemy air lives in enemy_air)",
          world.aircraft == [])
    check("carrier + fighter + awacs + airfield meshes registered",
          "carrier" in state._ship_meshes
          and state._mesh_fighter is not None
          and state._mesh_awacs is not None)
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
    check("destroyers EMIT at spawn; carrier runs silent (5a doctrine)",
          all(s.radar.emitting for s in w4.ships
              if s.ship_type == "destroyer")
          and not w4.carrier.radar.emitting)
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

    # --- Phase 5a: the air war scaffolding (pure sim, coarse DT — no
    # weapons employment in 5a: fighters fly and rearm, the AWACS senses).
    w6 = CombatWorld()
    carriers = [s for s in w6.ships if s.ship_type == "carrier"]
    check("exactly one carrier, targetable in ships",
          len(carriers) == 1 and carriers[0].alive
          and carriers[0] is w6.carrier)
    for _ in range(int(120.0 / DT4)):           # CAP scheduler spins up
        w6.step(DT4)
    airborne = [f for f in w6.enemy_air
                if isinstance(f, Fighter) and f.alive]
    check(">=1 fighter airborne after CAP spin-up", len(airborne) >= 1)
    check("AWACS emitting and the drone ELINT hears it (LOS-honest)",
          w6.awacs.alive and w6.awacs.radar.emitting
          and w6.elint.last_heard("awacs_00_radar") is not None)
    f6 = airborne[0]
    f6._fuel_s = f6._bingo_s + 1.0              # force bingo
    f6.pos[1] = min(f6.pos[1], 600.0)           # skip the 5 m/s descent
    landed = rearmed = False
    for _ in range(int(2_500.0 / DT4)):
        w6.step(DT4)
        landed = landed or f6.state == FS_REARMING
        if landed and f6.state == FS_PARKED:
            rearmed = True
            break
    check("bingo fighter RTBs, lands and rearms", landed and rearmed)
    # Airfield killable -> airborne fighters divert to the carrier.
    w7 = CombatWorld()
    for _ in range(int(120.0 / DT4)):
        w7.step(DT4)
    f7 = next(f for f in w7.enemy_air if isinstance(f, Fighter) and f.alive)
    f7.pos[0], f7.pos[2] = AIRFIELD_XZ          # overhead its home plate
    while w7.airfield.alive:
        w7.airfield.hit()
    f7._fuel_s = f7._bingo_s + 1.0
    for _ in range(int(10.0 / DT4)):
        w7.step(DT4)
    check("airfield killed -> fighter diverts to the carrier",
          not w7.air_bases[0].alive and f7.state == FS_RTB
          and f7._base is w7.air_bases[1])

    # --- Phase 5b: the commander runs the war (pure sim; coarse DT where
    # nothing ballistic flies; tests/test_phase5b_e2e.py carries the full
    # assertion set — this is the cockpit-check version).
    PHYS_DT_120 = PHYS_DT

    # BLIND: the ESM fix generates a HARM mission while the radar emits.
    w8 = CombatWorld()
    for _ in range(int(120.0 / DT4)):
        w8.step(DT4)
        if any(m["kind"] == "harm_package" for m in w8._cmd_missions):
            break
    mission = next((m for m in w8._cmd_missions
                    if m["kind"] == "harm_package"), None)
    check("commander schedules a HARM mission off the 90 s ESM fix",
          mission is not None and w8.sim_time < 100.0
          and w8.commander.stock.total_harm
          == AIRFIELD_HARM + CARRIER_HARM - 4)
    jets = mission["fighters"] if mission else []
    check("SEAD jets armed with 2 HARM each, silent ingress",
          len(jets) == 2 and all(f.hardpoints.count("harm") == 2
                                 and not f.radar.emitting for f in jets))
    rp = w8.radar_station.pos
    for f in jets:                       # forcing: climb done, 99 km out
        f.pos[1] = FIGHTER_ALT_M
    w8.step(DT4)
    for f in jets:
        dx, dz = float(f.pos[0] - rp[0]), float(f.pos[2] - rp[2])
        d = float(np.hypot(dx, dz))
        f.pos[0] = rp[0] + dx / d * 99_000.0
        f.pos[2] = rp[2] + dz / d * 99_000.0
    for _ in range(int(4.0 / DT4)):
        w8.step(DT4)
    harms = [m for m in w8.missiles if isinstance(m, HarmMissile)]
    check("4 HARMs in flight homing on the radar EMITTER",
          len(harms) == 4
          and all(m.target_radar is w8.radar_station for m in harms))
    for _ in range(int(40.0 / PHYS_DT_120)):
        w8.step(PHYS_DT_120)
    w8.radar_station.emitting = False    # SILENT mid-ingress
    for _ in range(int(150.0 / PHYS_DT_120)):
        w8.step(PHYS_DT_120)
        if (all(not m.alive for m in harms)
                and mission not in w8._cmd_missions):
            break
    rid = w8.radar_station.radar_id
    check("silence degrades every HARM to its CEP offset; radar survives",
          all(not m.alive for m in harms)
          and all(m._miss_offset is not None for m in harms)
          and w8.radar_station.alive)
    check("BDA: emitter believed dead after the package",
          w8.commander.picture.emitters[rid].alive is False)
    w8.radar_station.emitting = True
    for _ in range(int(2.0 / DT4)):
        w8.step(DT4)
    check("re-emission flips the believed-alive state back",
          w8.commander.picture.emitters[rid].alive is True)

    # FIND -> KILL: 3 Oniks launches back-plot the Bastion; JASSM + TLAM
    # missions are scheduled at the cluster.
    w9 = CombatWorld()
    w9.radar_station.emitting = False    # never located: KILL ungated
    for s in w9.ships:
        s.sm2_ammo = 0
        s.ciws_ammo = 0
    tlam0 = sum(s.tomahawk_ammo for s in w9.ships)
    tgt9 = w9.ships[0].pos.copy()
    tgt9[1] = 0.0
    for _ in range(3):
        w9.reload_left = 0.0
        m9 = w9.launch("hi-lo", tgt9)
        for _ in range(int(40.0 / PHYS_DT_120)):
            w9.step(PHYS_DT_120)
        m9.alive = False
        for _ in range(4):
            w9.step(PHYS_DT_120)
    clusters = w9.commander.picture.targetable_clusters()
    err9 = (float("inf") if not clusters else float(
        np.hypot(clusters[0].centre[0] - BASE_POS[0],
                 clusters[0].centre[1] - BASE_POS[2])))
    check("3 Oniks launches -> bastion cluster targetable inside the basket",
          len(clusters) == 1 and err9 < SEEKER_BASKET_M)
    for _ in range(int(10.0 / DT4)):
        w9.step(DT4)
        if any(m["kind"] == "jassm_package" for m in w9._cmd_missions):
            break
    bastion9 = next(s for s in w9.structures if s.kind == "bastion_tel")
    jm9 = next((m for m in w9._cmd_missions
                if m["kind"] == "jassm_package"), None)
    check("JASSM mission scheduled, aim refined onto the TEL",
          jm9 is not None
          and w9.commander.stock.total_jassm
          == AIRFIELD_JASSM + CARRIER_JASSM - 4
          and all(np.allclose(f._strike_target_xz,
                              [bastion9.pos[0], bastion9.pos[2]])
                  for f in jm9["fighters"]))
    check("Tomahawk salvo drawn from the destroyer magazines",
          any(m["kind"] == "tomahawk_salvo" for m in w9._cmd_missions)
          and sum(s.tomahawk_ammo for s in w9.ships) < tlam0)

    # DEFEND: the AIM-9X drone hunt — kill with NO RWR LOCK beforehand.
    w10 = CombatWorld()
    for s in w10.ships:
        s.sm2_ammo = 0                  # isolate the passive IR channel
        s.ciws_ammo = 0
    d10 = w10.drone
    d10.pos[0], d10.pos[2] = -40_000.0, 128_000.0
    d10.set_route([(60_000.0, 128_000.0)])
    f10 = w10._fighter_list[0]
    f10.launch((0.0, 160_000.0))
    f10.pos[1] = FIGHTER_ALT_M
    w10.step(DT4)
    f10.pos[0], f10.pos[1], f10.pos[2] = -50_000.0, 15_000.0, 128_000.0
    saw_lock10 = False
    ir10 = None
    for _ in range(int(240.0 / DT4)):
        w10.step(DT4)
        saw_lock10 = saw_lock10 or any(a[0] == RWR_LOCK
                                       for a in w10.rwr.alerts())
        ir10 = next((m for m in w10.missiles
                     if isinstance(m, IrMissile)), None)
        if ir10 is not None:
            break
    killed10 = False
    if ir10 is not None:
        for _ in range(int(60.0 / PHYS_DT_120)):
            w10.step(PHYS_DT_120)
            saw_lock10 = saw_lock10 or any(a[0] == RWR_LOCK
                                           for a in w10.rwr.alerts())
            if w10.drone is None:
                killed10 = True
                break
    check("drone IR-killed with NO RWR LOCK warning at any point",
          killed10 and not saw_lock10
          and "sam_kill" in [k for k, _ in w10.drain_events()])

    # 40N6: the AWACS dies beyond 200 km on a forced ELINT-grade track.
    w11 = CombatWorld()
    a11 = w11.awacs
    a11._corners = ((-20_000.0, 240_000.0), (-20_000.0, 280_000.0),
                    (20_000.0, 280_000.0), (20_000.0, 240_000.0))
    a11._wp = 1
    a11.pos[0], a11.pos[2] = -20_000.0, 240_000.0
    w11.radar_station.emitting = False  # the forced fix is the ONLY source
    rng11 = float(np.hypot(a11.pos[0] - SAM_TEL_POS[0],
                           a11.pos[2] - SAM_TEL_POS[2]))

    def _track11():
        w11.contacts.tracks["awacs_00"] = dict(
            pos=a11.pos.copy(), vel=a11.velocity(), age=5.0,
            t_next=w11.sim_time + 1.0, is_air=True)

    _track11()
    sam11 = w11.launch_sam("awacs_00", round_id="40n6")
    for _ in range(int(400.0 / PHYS_DT_120)):
        w11.step(PHYS_DT_120)
        _track11()
        if sam11 is None or not sam11.alive:
            break
    check("40N6 kills the AWACS beyond 200 km on the forced track",
          rng11 > 200_000.0 and sam11 is not None
          and sam11.killed_target and not a11.alive)

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
