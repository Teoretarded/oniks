"""COMBAT Phase 5b end-to-end (GL-free): the commander runs the war.

Covers the integration wired in world/combat.py (sim/commander.py brain,
sim/a2a.py AIM-9X, sim/arsenal.py 40N6, sim/enemy_air.py employment):

  * BLIND: the 90 s ESM fix on the emitting player radar generates a HARM
    package (2 jets, SEAD loadout, silent ingress); the released rounds
    are true HarmMissiles homing on the radar EMITTER; going SILENT
    mid-flight degrades every round to its seeded CEP offset (the radar
    survives), the completed package runs BDA (believed dead) and
    re-emission flips the belief back (evidence beats assumption).
  * FIND -> KILL: three real Oniks launches back-plot into one targetable
    cluster inside the terminal seeker basket of the true base; the
    commander schedules a JASSM package + a Tomahawk salvo at it, the
    aim refines onto the Bastion TEL, and the JASSMs reach DEFEAT
    (spec 2.2 lose condition) end-to-end.
  * DEFEND: a drone track vectors an armed fighter (snap-up climb to the
    intercept ceiling, own-nose-radar reacquire) into an AIM-9X kill with
    ZERO RWR LOCK events — the IR seeker is passive (spec 5.1).
  * 40N6: the player kills the AWACS beyond 200 km on a forced
    ELINT-grade track (the picture holds it; the radar net never does).
  * Win condition (spec 2.2): all enemy ships + the airfield dead ->
    ``victorious`` (enemy ground radars join in Phase 7); HUD helpers.
  * SANDBOX untouched: WorldState carries none of the 5b machinery.

Physics at the locked 120 Hz step where rounds fly; coarse steps where
nothing ballistic is in the air (the established e2e pattern).  Scenario
forcing (teleports/finished climbs) compresses multi-hundred-km transits
the slow probes already measured end-to-end (tools/probe_5b_*).
"""

import numpy as np
import pytest

from game.hud import DEFEAT_TEXT, VICTORY_TEXT, s300_round_panel
from sim.a2a import IrMissile
from sim.commander import AIRFIELD_HARM, AIRFIELD_JASSM, CARRIER_HARM, CARRIER_JASSM
from sim.enemy_air import (FIGHTER_ALT_M, FS_ON_STATION, FS_TAKEOFF,
                           FS_TRANSIT, Fighter)
from sim.recon import RWR_LOCK
from sim.ships import ST_SINKING
from sim.strike import HarmMissile, StrikeMissile
from world.combat import SEEKER_BASKET_M, CombatWorld
from world.combat_config import CombatConfig
from world.generation import BASE_POS
from world.world import SAM_TEL_POS, WorldState

DT = 1.0 / 120.0
DT_COARSE = 0.25    # nothing ballistic flies: rate-based machinery only

AIRBORNE = (FS_TAKEOFF, FS_TRANSIT, FS_ON_STATION)


def _disarm_ships(w):
    """Empty the escorts' magazines (isolates the chain under test)."""
    for s in w.ships:
        s.sm2_ammo = 0
        s.ciws_ammo = 0


def _disarm_pantsirs(w):
    """Empty Pantsir magazines so Phase 5b kill-chain tests run unaffected
    by the Phase 6 point defense (the two phases are tested independently).
    This mirrors how _disarm_ships isolates the player offensive chain from
    the enemy SM-2/CIWS defenses."""
    for p in getattr(w, "pantsirs", []):
        p.missile_ammo = 0
        p.gun.ammo = 0


def _plot_three_oniks(w):
    """Launch 3 real Oniks; fly each missile long enough for the enemy
    sensors to catch the climb below the 2 km back-plot ceiling, then
    expend it (the plots are recorded at first detection — the long
    cruise adds nothing to the FIND chain under test).

    Updated for Phase 7 (seeded fleet): the closest destroyer is targeted
    so the SPY-1 (300 km range) physically detects the climb; 100 s of
    flight moves the missile ~30 km downrange — well inside the sensor
    envelope regardless of fleet seed placement."""
    # Target the destroyer closest to BASE_POS so detection is reliable.
    from world.generation import BASE_POS
    closest = min(w.ships, key=lambda s: float(
        np.hypot(s.pos[0] - BASE_POS[0], s.pos[2] - BASE_POS[2])))
    target = closest.pos.copy()
    target[1] = 0.0
    for _ in range(3):
        w.reload_left = 0.0
        m = w.launch("hi-lo", target)
        assert m is not None
        for _ in range(int(100.0 / DT)):   # 100 s -> ~30 km, inside any SPY-1 horizon
            w.step(DT)
        m.alive = False
        for _ in range(4):
            w.step(DT)


# ---------------------------------------------------------------------------
# Order of battle / determinism seam
# ---------------------------------------------------------------------------

def test_commander_wired_with_full_stocks():
    w = CombatWorld()
    assert w.commander.fighters == [e for e in w.enemy_air
                                    if isinstance(e, Fighter)]
    assert w.commander.awacs is w.awacs
    assert w.commander.stock.total_harm == AIRFIELD_HARM + CARRIER_HARM
    assert w.commander.stock.total_jassm == AIRFIELD_JASSM + CARRIER_JASSM
    # No intel at spawn: nothing emitted, nothing launched, nothing seen.
    assert w.commander.picture.emitters == {}
    assert w.commander.picture.clusters == []
    assert w._cmd_missions == []


# ---------------------------------------------------------------------------
# BLIND: HARM package + radar-silence loop
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_harm_mission_silence_degrades_and_belief_flips_back():
    w = CombatWorld()
    rid = w.radar_station.radar_id
    for _ in range(int(120.0 / DT_COARSE)):
        w.step(DT_COARSE)
        if any(m["kind"] == "harm_package" for m in w._cmd_missions):
            break
    mission = next(m for m in w._cmd_missions if m["kind"] == "harm_package")
    assert w.sim_time < 100.0                  # ~the 90 s ESM fix
    assert w.commander.stock.total_harm == AIRFIELD_HARM + CARRIER_HARM - 4
    jets = mission["fighters"]
    assert len(jets) == 2
    for f in jets:
        assert f.hardpoints.count("harm") == 2     # SEAD loadout armed
        assert not f.radar.emitting                # silent ingress
    # Scenario forcing: finish the climb, teleport to 99 km off the radar
    # (inside the 100 km release gate; the 430+ km ingress legs were
    # measured end-to-end by tools/probe_5b_harm_ir.py).
    rp = w.radar_station.pos
    for f in jets:
        f.pos[1] = FIGHTER_ALT_M
    w.step(DT_COARSE)
    for f in jets:
        dx, dz = float(f.pos[0] - rp[0]), float(f.pos[2] - rp[2])
        d = float(np.hypot(dx, dz))
        f.pos[0] = rp[0] + dx / d * 99_000.0
        f.pos[2] = rp[2] + dz / d * 99_000.0
    for _ in range(int(4.0 / DT_COARSE)):
        w.step(DT_COARSE)
    harms = [m for m in w.missiles if isinstance(m, HarmMissile)]
    assert len(harms) == 4                     # 2 jets x 2 rounds
    assert all(m.target_radar is w.radar_station for m in harms)
    # Released jets EGRESS (a2g expended -> RTB; spec 5.1 behavior loop).
    assert all(f.state not in (FS_TRANSIT, FS_ON_STATION)
               or f._strike_target_xz is None for f in jets)
    for _ in range(int(40.0 / DT)):            # mid-ingress...
        w.step(DT)
    w.radar_station.emitting = False           # ...the player goes SILENT
    for _ in range(int(150.0 / DT)):
        w.step(DT)
        if (all(not m.alive for m in harms)
                and mission not in w._cmd_missions):
            break
    assert all(not m.alive for m in harms)
    # Silence degraded every round to its seeded CEP offset (150-400 m):
    # the radar STRUCTURE survives the strike.
    assert all(m._miss_offset is not None for m in harms)
    assert w.radar_station.alive
    # BDA: the completed package believes the emitter dead...
    assert mission not in w._cmd_missions
    assert w.commander.picture.emitters[rid].alive is False
    # ...until it is heard emitting again (evidence resets the belief).
    w.radar_station.emitting = True
    for _ in range(int(2.0 / DT_COARSE)):
        w.step(DT_COARSE)
    assert w.commander.picture.emitters[rid].alive is True


# ---------------------------------------------------------------------------
# FIND -> KILL: back-plot -> JASSM/Tomahawk -> defeat
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_backplot_jassm_strike_reaches_defeat():
    # Phase 7 (updated): use seed=5 which places a destroyer at ~135 km so
    # the Oniks back-plot detects the missile below the 2 km ceiling.
    # DEFAULT seed=1337 places all destroyers at 260-340 km; the back-plot
    # threshold requires first detection at < 2 km altitude, which needs
    # the ship's SPY-1 to see the missile during its early climb (< 200 km).
    # Seed=5 is the canonical probe-measured geometry for this test.
    w = CombatWorld(CombatConfig(seed=5))
    w.radar_station.emitting = False    # never located: KILL ungated (the
    #                                     blind-before-kill gate is covered
    #                                     by tests/test_commander.py)
    _disarm_ships(w)                    # the Oniks flights fly clean
    _disarm_pantsirs(w)                 # Phase 6 point-defense isolated from
    #                                     the Phase 5b kill chain (the Pantsir
    #                                     interception physics is covered by
    #                                     tests/test_pantsir_phase6.py)
    tlam0 = sum(s.tomahawk_ammo for s in w.ships)
    _plot_three_oniks(w)
    clusters = w.commander.picture.targetable_clusters()
    assert len(clusters) == 1
    # The back-plot physics lands the cluster INSIDE the terminal seeker
    # basket of the true base (the whole kill chain hinges on this pin).
    err = float(np.hypot(clusters[0].centre[0] - BASE_POS[0],
                         clusters[0].centre[1] - BASE_POS[2]))
    assert 0.0 < err < SEEKER_BASKET_M
    for _ in range(int(10.0 / DT_COARSE)):
        w.step(DT_COARSE)
        if any(m["kind"] == "jassm_package" for m in w._cmd_missions):
            break
    mission = next(m for m in w._cmd_missions
                   if m["kind"] == "jassm_package")
    assert w.commander.stock.total_jassm == (AIRFIELD_JASSM
                                             + CARRIER_JASSM - 4)
    # The Tomahawk salvo fires alongside, drawn from the destroyers' mags.
    assert any(m["kind"] == "tomahawk_salvo" for m in w._cmd_missions)
    assert sum(s.tomahawk_ammo for s in w.ships) < tlam0
    bastion = next(s for s in w.structures if s.kind == "bastion_tel")
    jets = mission["fighters"]
    assert len(jets) == 2
    for f in jets:
        # Terminal scene-matching refinement: the believed cluster centre
        # acquired the REAL TEL (sub-km back-plot error vs the 1 km basket).
        assert np.allclose(f._strike_target_xz,
                           [bastion.pos[0], bastion.pos[2]])
        assert f._strike_target_y > float(bastion.pos[1])   # mid-OBB aim
    # Scenario forcing: finish climbs, release from 100 km north (the
    # full 280-520 km ingress is probe-measured; flight from the real
    # 150 km gate is the same terminal physics).
    for f in jets:
        f.pos[1] = FIGHTER_ALT_M
    w.step(DT_COARSE)
    for f in jets:
        f.pos[0], f.pos[2] = 0.0, BASE_POS[2] + 100_000.0
    for _ in range(int(4.0 / DT_COARSE)):
        w.step(DT_COARSE)
    jassms = [m for m in w.missiles if isinstance(m, StrikeMissile)
              and m.weapon.weapon_id == "jassm"]
    assert len(jassms) == 4
    hits = []
    for _ in range(int(500.0 / DT)):
        w.step(DT)
        hits += [k for k, _ in w.drain_events()
                 if k in ("base_hit", "base_destroyed")]
        if w.defeated:
            break
    assert w.defeated                       # spec 2.2 lose condition
    assert not bastion.alive
    assert "base_destroyed" in hits
    assert w.launch("hi-lo", np.zeros(3)) is None   # launcher locked
    w.step(DT_COARSE)                       # the sim keeps running


# ---------------------------------------------------------------------------
# DEFEND: the AIM-9X drone hunt — passive kill, zero RWR LOCK
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_ir_drone_hunt_kills_with_no_rwr_lock():
    # Phase 7 (updated): seed=5 places a destroyer at ~135 km — close enough
    # for the drone to cross inside its 30 km stealth bubble at a plausible
    # crossing leg computed from the live fleet position.
    w = CombatWorld(CombatConfig(seed=5))
    _disarm_ships(w)                    # isolate the IR channel (the SM-2
    #                                     hunt is pinned by phase-4 e2e)
    d = w.drone
    # Crossing leg inside the closest destroyer's 30 km stealth bubble:
    # the track forms, the commander vectors the hunter.
    # Updated for Phase 7: use the seeded fleet position rather than the
    # old hardcoded DESTROYER_SPAWNS pin — the drone crosses 15 km ahead
    # of the closest destroyer at its Z depth (within stealth range).
    close_ship = min(w.ships, key=lambda s: float(
        np.hypot(s.pos[0], s.pos[2])))
    sx, sz = float(close_ship.pos[0]), float(close_ship.pos[2])
    # Position drone 15 km ahead (lower z) of the closest ship, crossing
    # from sx-40 km to sx+40 km — the 80 km leg crosses the stealth bubble.
    d.pos[0], d.pos[2] = sx - 40_000.0, sz - 15_000.0
    d.set_route([(sx + 40_000.0, sz - 15_000.0)])
    f = w._fighter_list[0]
    f.launch((sx, sz))
    f.pos[1] = FIGHTER_ALT_M
    w.step(DT_COARSE)                   # takeoff completes -> TRANSIT
    assert f.state == FS_TRANSIT
    # Scenario forcing: the tail-chase already at the snap-up ceiling band
    # 10 km behind the drone (the full 9->15.5 km climb + 40 km chase is
    # probe-measured: tools/probe_5b_harm_ir.py).
    f.pos[0], f.pos[1], f.pos[2] = sx - 50_000.0, 15_000.0, sz - 15_000.0
    saw_lock = False
    ir = None
    for _ in range(int(240.0 / DT_COARSE)):
        w.step(DT_COARSE)
        saw_lock = saw_lock or any(a[0] == RWR_LOCK for a in w.rwr.alerts())
        ir = next((m for m in w.missiles if isinstance(m, IrMissile)), None)
        if ir is not None:
            break
    assert ir is not None, "AIM-9X never fired"
    assert not saw_lock                 # nothing radar-guided ever flew
    assert f._intercept_target is d     # own-nose-radar entity pursuit
    assert f.pos[1] > FIGHTER_ALT_M     # snap-up climb happened
    killed = False
    for _ in range(int(60.0 / DT)):     # the round flies: 120 Hz
        w.step(DT)
        saw_lock = saw_lock or any(a[0] == RWR_LOCK for a in w.rwr.alerts())
        if w.drone is None:
            killed = True
            break
    assert killed, "AIM-9X never killed the drone"
    # The PASSIVE-seeker headline: the drone died with ZERO LOCK warnings
    # (spec 5.1 — IR ignores radar stealth and rings no RWR bell).
    assert not saw_lock
    assert "sam_kill" in [k for k, _ in w.drain_events()]
    assert len(w.drone_wrecks) == 1     # wreck/respawn flow engaged
    assert w.drone_respawn_left > 0.0


# ---------------------------------------------------------------------------
# 40N6: the AWACS dies beyond 200 km when the picture holds it
# ---------------------------------------------------------------------------

def _force_awacs_track(w):
    """ELINT-grade forced track (the scenario's drone fix): refreshed at
    a 1 Hz cadence with a 5 s staleness, exactly the degraded-age shape
    world/combat.py ELINT injection produces for ships."""
    a = w.awacs
    w.contacts.tracks["awacs_00"] = dict(
        pos=a.pos.copy(), vel=a.velocity(), age=5.0,
        t_next=w.sim_time + 1.0, is_air=True)


@pytest.mark.slow
def test_40n6_kills_awacs_beyond_200km_on_forced_track():
    w = CombatWorld()
    a = w.awacs
    # The fled-orbit case: re-anchor the racetrack at z 205-245 km (the
    # spawn orbit at 405-435 km sits outside even the design envelope —
    # the 40N6 forces the AWACS deep, it does not delete it).
    # Energy-model re-pin (2026-07-06, argued): the old 240-280 km anchor
    # only ever died because the free-energy round could stern-chase a
    # FLEEING AWACS at any range; honestly flown, the coast arrives at
    # ~360 m/s at 240+ km and a 230 m/s flee outruns it — which is REAL
    # (it is why AWACS stand off). The contract this test exists for —
    # a kill BEYOND 200 km on a forced ELINT track, with the DEFEND flee
    # ordered — holds at the deepest honest anchor: launch range measured
    # 233 km, kill at 25.7 m closest with the flee under way.
    a._corners = ((-20_000.0, 205_000.0), (-20_000.0, 245_000.0),
                  (20_000.0, 245_000.0), (20_000.0, 205_000.0))
    a._wp = 1
    a.pos[0], a.pos[2] = -20_000.0, 205_000.0
    rng0 = float(np.hypot(a.pos[0] - SAM_TEL_POS[0],
                          a.pos[2] - SAM_TEL_POS[2]))
    assert rng0 > 200_000.0
    # The player radar runs SILENT: the net cannot see anything (silent
    # radars are blind — spec section 3), so the forced ELINT-grade track
    # is the ONLY source the 40N6 flies on (fog honesty).
    w.radar_station.emitting = False
    assert not w.radar_net.visible(a.pos, "fighter")
    _force_awacs_track(w)
    sam = w.launch_sam("awacs_00", round_id="40n6")
    assert sam is not None
    assert w.sam_ammo_40n6 == 1
    fled = False
    for _ in range(int(400.0 / DT)):
        w.step(DT)
        _force_awacs_track(w)
        fled = fled or a._fleeing
        if not sam.alive:
            break
    assert sam.killed_target, "40N6 never killed the AWACS"
    assert not a.alive
    assert fled        # DEFEND doctrine: the commander ordered the flee


# ---------------------------------------------------------------------------
# Win condition + HUD seams
# ---------------------------------------------------------------------------

def test_victory_all_ships_and_airfield_dead():
    """Phase 7 (updated): win condition now requires all ships + airfield +
    all enemy ground radar structures (DEFAULT config: n_enemy_radars=2)."""
    w = CombatWorld()
    assert not w.victorious
    for s in w.ships:
        s.hp = 0
        s.state = ST_SINKING
    assert not w.victorious             # airfield + radars still stand
    while w.airfield.alive:
        w.airfield.hit()
    # Phase 7: enemy ground radars also part of the win condition.
    for struct, r in w.enemy_radars:
        while struct.alive:
            struct.hit()
    assert w.victorious
    assert not w.defeated               # outcomes are independent
    for _ in range(8):                  # the sim keeps running (spec 2.2)
        w.step(DT_COARSE)
    assert w.victorious


def test_s300_round_panel_and_banner_texts():
    w = WorldState()
    status, _col, name, ammo = s300_round_panel(w, "48n6")
    assert status == "ARMED" and "48N6" in ammo and "40N6" in ammo
    status40, _c, name40, _a = s300_round_panel(w, "40n6")
    assert status40 == "ARMED" and name40 != name
    w.sam_ammo_40n6 = 0
    assert s300_round_panel(w, "40n6")[0] == "EMPTY"
    assert s300_round_panel(w, "48n6")[0] == "ARMED"   # pools independent
    assert VICTORY_TEXT and VICTORY_TEXT != DEFEAT_TEXT


def test_sandbox_untouched():
    w = WorldState()
    assert not hasattr(w, "commander")
    assert not hasattr(w, "_cmd_missions")
    assert not hasattr(w, "victorious")
    # The 40N6 stock exists in every world (the TEL carries it), but no
    # commander machinery rides along.
    assert w.sam_ammo_40n6 == 2
