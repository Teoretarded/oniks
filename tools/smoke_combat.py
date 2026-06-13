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
from sim.arsenal import JASSM, TOMAHAWK
from sim.commander import (AIRFIELD_HARM, AIRFIELD_JASSM, CARRIER_HARM,
                           CARRIER_JASSM)
from sim.enemy_air import (FIGHTER_ALT_M, FS_PARKED, FS_REARMING, FS_RTB,
                           Fighter)
from sim.recon import RWR_LOCK, RWR_SPIKE
from sim.ships import ST_GONE
from sim.strike import HarmMissile, StrikeMissile
from world.combat import (AIRFIELD_XZ, DRONE_RESPAWN_S, SEEKER_BASKET_M,
                          CombatWorld)
from world.combat_config import CombatConfig
from world.generation import BASE_POS, terrain_height_scalar
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
    # DEFAULT config (Phase 7 seeded fleet): 3 destroyers + exactly 1 carrier
    # (carrier is always 1), nothing else.
    check("3 destroyers + exactly one carrier, nothing else",
          [s.ship_type for s in world.ships]
          == ["destroyer", "destroyer", "destroyer", "carrier"])
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

    # Phase 7: the fleet is SEEDED (sample_fleet) — hull anchors vary with
    # the seed, so these drone legs are built RELATIVE to the live hulls
    # (the retired DESTROYER_SPAWNS fixed-anchor geometry no longer holds).
    DT4 = 0.25                              # coarse: nothing ballistic flies
    w4 = CombatWorld()
    d4 = w4.drone
    check("destroyers EMIT at spawn; carrier runs silent (5a doctrine)",
          all(s.radar.emitting for s in w4.ships
              if s.ship_type == "destroyer")
          and not w4.carrier.radar.emitting)
    # ELINT: a wide crossing leg ~40 km in FRONT of destroyer_00 (toward
    # the base — still 40 km clear of the hull's 30 km stealth bubble so the
    # drone survives, and past the ground-radar horizon) — the 180 km leg
    # sweeps a wide bearing angle so the triangulation converges tightly for
    # whatever seed placed the hull.
    ship00 = next(s for s in w4.ships if s.ship_id == "destroyer_00")
    hx, hz = float(ship00.pos[0]), float(ship00.pos[2])
    leg_z = hz - 40_000.0                   # in front of the hull, toward base
    d4.pos[0], d4.pos[2] = hx - 90_000.0, leg_z
    d4.set_route([(hx + 90_000.0, leg_z)])
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
    est = w4.elint.est_pos("destroyer_00_spy1")
    err = (float("inf") if est is None else
           float(np.hypot(est[0] - ship00.pos[0], est[2] - ship00.pos[2])))
    check("ELINT fix lands near the true hull", err < 5_000.0)
    check("ELINT track in the player picture, hulls past the horizon",
          "destroyer_00" in w4.contacts.tracks
          and not w4.radar_net.visible(ship00.pos, "ship"))

    # SAR: a SILENT ship found by overflight (fresh world: no ELINT help).
    # Overfly the live destroyer_01 hull on a north-running leg through it.
    w5 = CombatWorld()
    d5 = w5.drone
    ship01 = next(s for s in w5.ships if s.ship_id == "destroyer_01")
    s1x, s1z = float(ship01.pos[0]), float(ship01.pos[2])
    ship01.radar.emitting = False           # destroyer_01 goes dark
    d5.pos[0], d5.pos[2] = s1x, s1z - 30_000.0
    d5.set_route([(s1x, s1z + 30_000.0)])   # overfly its hull
    sar_t = None
    for _ in range(int(400.0 / DT4)):
        w5.step(DT4)
        if "destroyer_01" in w5.contacts.tracks:
            sar_t = w5.sim_time
            break
    check("SAR overflight tracks the silent ship",
          sar_t is not None and d5.alive
          and not w5.radar_net.visible(ship01.pos, "ship"))

    # Engagement: the silent ship lights up with the drone inside its
    # 30 km stealth bubble — RWR SPIKE, then SM-2s and LOCK (120 Hz: a
    # round is flying).
    ship01.radar.emitting = True
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
    # missions are scheduled at the cluster.  Phase 7: seed=5 places a
    # destroyer at ~135 km so a SPY-1 catches the Oniks climb below the 2 km
    # back-plot ceiling (DEFAULT seed=1337 spreads the fleet to 260-340 km —
    # the canonical probe-measured geometry, mirrors test_phase5b_e2e.py).
    w9 = CombatWorld(CombatConfig(seed=5))
    w9.radar_station.emitting = False    # never located: KILL ungated
    for s in w9.ships:
        s.sm2_ammo = 0
        s.ciws_ammo = 0
    for p in w9.pantsirs:                # isolate from the Phase-6 layer
        p.missile_ammo = 0
        p.gun.ammo = 0
    tlam0 = sum(s.tomahawk_ammo for s in w9.ships)
    tgt9 = next(s for s in w9.ships
                if s.ship_id == "destroyer_00").pos.copy()
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
    # Phase 7: seed=5 (a destroyer at ~135 km), drone crossing 15 km ahead
    # of the CLOSEST hull so an enemy radar forms the drone track and the
    # commander vectors the hunter (mirrors test_phase5b_e2e.py — the old
    # hardcoded z=128 km leg assumed the retired DESTROYER_SPAWNS anchors).
    w10 = CombatWorld(CombatConfig(seed=5))
    for s in w10.ships:
        s.sm2_ammo = 0                  # isolate the passive IR channel
        s.ciws_ammo = 0
    d10 = w10.drone
    close10 = min(w10.ships, key=lambda s: float(
        np.hypot(s.pos[0], s.pos[2])))
    cx10, cz10 = float(close10.pos[0]), float(close10.pos[2])
    d10.pos[0], d10.pos[2] = cx10 - 40_000.0, cz10 - 15_000.0
    d10.set_route([(cx10 + 40_000.0, cz10 - 15_000.0)])
    f10 = w10._fighter_list[0]
    f10.launch((cx10, cz10))
    f10.pos[1] = FIGHTER_ALT_M
    w10.step(DT4)
    # Tail-chase forcing: 50 km behind the drone at the snap-up ceiling band.
    f10.pos[0], f10.pos[1], f10.pos[2] = cx10 - 50_000.0, 15_000.0, cz10 - 15_000.0
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

    # --- Phase 6: the Pantsir-S1 point defense (pure sim; 120 Hz where a
    # 57E6 actually flies, coarse steps for the rate-based machinery).
    w12 = CombatWorld()
    check("two Pantsirs guard the base, radars in the player net",
          len(w12.pantsirs) == 2
          and all(p.radar in w12.radar_net.radars for p in w12.pantsirs)
          and all(p.missile_ammo == 12 and p.gun_ammo == 700
                  for p in w12.pantsirs))
    # An inbound hostile Tomahawk at the Bastion guard: the Pantsir forms a
    # track and a 57E6 kills it before it can run the structure sweep.
    w12.radar_station.emitting = False      # isolate from the commander
    for s in w12.ships:
        s.tomahawk_ammo = 0
    p_bastion = w12.pantsirs[0]
    inbound = StrikeMissile(
        TOMAHAWK,
        np.array([BASE_POS[0], 50.0, p_bastion.pos[2] + 18_000.0]),
        np.zeros(3), (BASE_POS[0], BASE_POS[2]), target_y=0.0)
    inbound.launch_platform = None
    w12.missiles.append(inbound)
    saw_launch = False
    for _ in range(int(120.0 / PHYS_DT)):
        w12.step(PHYS_DT)
        saw_launch = saw_launch or any(
            k == "pantsir_launch" for k, _ in w12.drain_events())
        if not inbound.alive:
            break
    check("a 57E6 launches and kills the inbound Tomahawk",
          saw_launch and not inbound.alive
          and all(s.alive for s in w12.structures if s.kind == "bastion_tel"))

    # Saturation: more diving JASSMs than the 57E6 + gun can service still
    # leaks and ends the battle (the Pantsir is a shield, not a magic wall).
    w13 = CombatWorld()
    w13.radar_station.emitting = False
    for s in w13.ships:
        s.tomahawk_ammo = 0
        s.sm2_ammo = 0
        s.ciws_ammo = 0
    bastion13 = next(s for s in w13.structures if s.kind == "bastion_tel")
    aim_y13 = float(bastion13.pos[1]) + bastion13.dims[2] * 0.5
    for i in range(4):                       # 4 divers > the measured leak
        w13.missiles.append(StrikeMissile(  # threshold (probe: 3+ leak)
            JASSM,
            np.array([BASE_POS[0] + (i - 2) * 40.0, 9_000.0,
                      BASE_POS[2] + 100_000.0]),
            np.array([0.0, 0.0, -272.0]),
            (BASE_POS[0], BASE_POS[2]), target_y=aim_y13))
        w13.missiles[-1].launch_platform = None
    defeated13 = False
    for _ in range(int(520.0 / PHYS_DT)):
        w13.step(PHYS_DT)
        w13.drain_events()
        if w13.defeated:
            defeated13 = True
            break
    check("a saturation JASSM raid leaks past the Pantsir -> DEFEAT",
          defeated13)

    # A Pantsir killed (its destructible Structure demolished) stops
    # defending and its radar drops from the player network.
    w14 = CombatWorld()
    pk = w14.pantsirs[0]
    struct14 = next(s for s in w14.structures
                    if s.structure_id == f"{pk.unit_id}_struct")
    while struct14.alive:                     # the real damage entry point
        struct14.hit()
    tgt14 = np.array([pk.pos[0], pk.pos[1] + 300.0, pk.pos[2] + 8_000.0])
    check("a destroyed Pantsir goes dark and leaves the radar net",
          (not pk.alive) and (not pk.radar.alive)
          and not any(r is pk.radar and r.detects(tgt14, "missile")
                      for r in w14.radar_net.radars)
          and w14.pantsirs[1].alive)

    # --- Phase 7: the setup-screen config drives the world (pure sim).
    # Build a non-default battle and assert the order of battle, the finite
    # Oniks magazine refill cycle, the full victory condition and seeded
    # determinism — the contracts the setup screen relies on.
    cfg7 = CombatConfig(seed=7, n_destroyers=6, n_enemy_radars=3,
                        oniks_ammo=3, oniks_mag_reload_s=30.0)
    w15 = CombatWorld(cfg7)
    check("config: 6 destroyers + 1 carrier placed",
          [s.ship_type for s in w15.ships]
          == ["destroyer"] * 6 + ["carrier"])
    for s in w15.ships:                      # all hulls in open water
        check(f"  {s.ship_id} in open water",
              terrain_height_scalar(float(s.pos[0]), float(s.pos[2])) < -5.0)
    check("config: 3 enemy radars on dry land, in the enemy picture",
          len(w15.enemy_radars) == 3
          and all(terrain_height_scalar(float(st.pos[0]),
                                        float(st.pos[2])) > 0.0
                  for st, _r in w15.enemy_radars)
          and all(r in w15._enemy_cue_radars()
                  for _st, r in w15.enemy_radars))
    check("enemy radars absent from the player map until imaged (fog)",
          w15.known_enemy_sites == [])

    # Oniks magazine: 3 rounds -> 0 -> locked -> refills after 30 s.
    tgt15 = np.array([0.0, 0.0, 150_000.0])
    check("Oniks magazine loaded to 3", w15._oniks_ammo == 3)
    for _ in range(3):
        m15 = w15.launch("hi-lo", tgt15)
        w15.reload_left = 0.0               # skip the per-shot tube reload
        if m15 is None:
            break
    check("Oniks magazine drains to 0 and locks",
          w15._oniks_ammo == 0 and not w15.launcher_armed
          and w15.launch("hi-lo", tgt15) is None)
    for _ in range(int(30.5 / PHYS_DT)):    # run past the 30 s refill
        w15.step(PHYS_DT)
    check("Oniks magazine refills to 3 after 30 s",
          w15._oniks_ammo == 3 and w15.launcher_armed)

    # Victory needs EVERY enemy ship + radar + airfield dead.
    w16 = CombatWorld(cfg7)
    for s in w16.ships:
        s.state = ST_GONE
    check("victory withheld while airfield + radars stand",
          not w16.victorious)
    w16.airfield.alive = False
    check("victory withheld while radars stand", not w16.victorious)
    for st, r in w16.enemy_radars:
        st.alive = False
        r.alive = False
    check("victory once ALL ships + airfield + radars are dead",
          w16.victorious)

    # Seeded determinism: same config -> identical fleet anchors; a different
    # seed diverges.
    def _anchors(cw):
        return sorted((round(float(s.pos[0])), round(float(s.pos[2])))
                      for s in cw.ships)
    check("same config -> identical fleet anchors",
          _anchors(CombatWorld(cfg7)) == _anchors(CombatWorld(cfg7)))
    cfg7b = CombatConfig(seed=8, n_destroyers=6, n_enemy_radars=3)
    check("different seed -> different fleet anchors",
          _anchors(CombatWorld(cfg7)) != _anchors(CombatWorld(cfg7b)))

    # The full determinism contract: same config -> bit-identical battle after
    # stepping (ships + missiles + structures + enemy air all line up).
    def _battle_snapshot(cw):
        return (
            [tuple(np.round(s.pos, 6)) for s in cw.ships],
            [tuple(np.round(m.pos, 6)) for m in cw.missiles],
            sorted(s.structure_id for s in cw.structures if s.alive),
            [tuple(np.round(e.pos, 6)) for e in cw.enemy_air])
    da, db = CombatWorld(cfg7), CombatWorld(cfg7)
    for _ in range(600):                     # 5 s with commander + defenses
        da.step(PHYS_DT)
        db.step(PHYS_DT)
    check("same config -> bit-identical battle after 5 s of stepping",
          _battle_snapshot(da) == _battle_snapshot(db))

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
