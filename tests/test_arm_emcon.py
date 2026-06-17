"""tests/test_arm_emcon.py — M2-T3 enemy radar EMCON vs a sensed inbound ARM.

The enemy counter to the player Kh-31P anti-radiation missile (M2-T2). When an
enemy radar SENSES an inbound ARM-class missile track within a threat radius it
goes SILENT for an EMCON dwell (mirroring the AWACS EMCON) — which degrades the
live PlayerArmMissile to its seeded CEP miss ring, so a silenced radar usually
SURVIVES. This is the SEAD duel: the ARM forces the enemy to choose go-dark
(lose SM-2/detection coverage) or eat the ARM.

NO-CHEAT (load-bearing): the silence decision reads ONLY the SENSED missile
track in the EnemyPicture (``mt["pos"]``, ``mt["kind"]``) and the radar's OWN
position — NEVER the PlayerArmMissile's true ``.pos`` / ``.target_radar``. The
``kind`` is the enemy's sensor CLASSIFICATION (fed by the world when an enemy
radar detects the inbound), analogous to the player's contact stamps — fog
honest, not a truth read.

REGRESSION: with kh31p_ammo=0 (default) NO ARM is ever fired -> no kind=="kh31p"
track -> the ship/ground-radar silence doctrine never fires and the default
battle is byte-identical (the added ``kind`` field on tracks is additive). A
NON-ARM inbound (Oniks/None) keeps the existing emit-to-defend behavior.

Mirrors tests/test_awacs_emcon.py (commander-driven, sensor-fed picture).
"""

import math

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from sim.arsenal import KH31P
from sim.strike import HARM_MISS_MIN_M, HARM_MISS_MAX_M, PlayerArmMissile
from sim.commander import ARM_EMCON_RANGE_M, ARM_EMCON_DWELL_S
from world.generation import terrain_height_scalar

DT = 1.0 / 120.0   # 120 Hz fixed physics step


def _first_destroyer(w):
    """The first live destroyer (non-Carrier ship) and its SPY-1 radar."""
    for s in w.commander.destroyers:
        if s.alive and getattr(s, "radar", None) is not None:
            return s, s.radar
    raise AssertionError("no live destroyer in the world")


def _inject_track(pic, track_id, pos, kind, sim_time, vel=None):
    """Feed a SENSED missile track into the enemy picture (the channel the world
    populates when an enemy radar detects an inbound)."""
    if vel is None:
        vel = np.array([0.0, 0.0, 300.0], dtype=np.float64)
    pic.update_missile_track(track_id, np.asarray(pos, dtype=np.float64),
                             vel, sim_time=sim_time, kind=kind)


# ---------------------------------------------------------------------------
# 1. Ship EMCON on a sensed ARM track within range
# ---------------------------------------------------------------------------

def test_ship_emcon_on_sensed_arm_track():
    """A live missile track with kind=="kh31p" within ARM_EMCON_RANGE_M of a
    ship's SPY-1 -> the commander issues ship_silent for that ship and (after
    execution) the radar is silent."""
    w = CombatWorld(CombatConfig(seed=7))
    ship, radar = _first_destroyer(w)
    radar.emitting = True
    sx, _, sz = radar.pos
    # Sensed ARM track 30 km from the ship (< ARM_EMCON_RANGE_M).
    pos = np.array([sx, 4_000.0, sz - 30_000.0], dtype=np.float64)
    assert np.hypot(pos[0] - sx, pos[2] - sz) < ARM_EMCON_RANGE_M
    _inject_track(w.commander.picture, "arm_probe", pos, "kh31p", w.sim_time)

    for order in w.commander.step(w.sim_time, 1.0):
        w._execute_commander_order(order)

    silent = [o for o in w.commander.pending_orders
              if o["type"] == "ship_silent" and o["ship_id"] == ship.ship_id]
    assert silent, "commander must order ship_silent off a sensed ARM track"
    assert not radar.emitting, \
        "the ship radar must go SILENT vs a sensed ARM (deny the seeker its emission)"


# ---------------------------------------------------------------------------
# 2. Regression: a NON-ARM inbound still makes the ship EMIT (self-defense)
# ---------------------------------------------------------------------------

def test_ship_still_emits_on_nonarm_inbound():
    """A kind=="oniks" (non-ARM) inbound near a ship -> the ship EMITS
    (existing self-defense beats stealth), NOT silenced by the ARM path. The
    pre-feature behavior is preserved for non-ARM rounds."""
    w = CombatWorld(CombatConfig(seed=7))
    ship, radar = _first_destroyer(w)
    radar.emitting = False           # start dark so an emit order is observable
    sx, _, sz = radar.pos
    pos = np.array([sx, 4_000.0, sz - 30_000.0], dtype=np.float64)
    _inject_track(w.commander.picture, "oniks_probe", pos, "oniks", w.sim_time)

    for order in w.commander.step(w.sim_time, 1.0):
        w._execute_commander_order(order)

    assert radar.emitting, \
        "a non-ARM inbound must keep the existing self-defense EMIT behavior"
    silent = [o for o in w.commander.pending_orders
              if o["type"] == "ship_silent" and o["ship_id"] == ship.ship_id]
    assert not silent, "ARM-EMCON must NOT silence a ship vs a non-ARM inbound"


# ---------------------------------------------------------------------------
# 3. NO-CHEAT: the silence follows the SENSED track (belief), not ARM truth
# ---------------------------------------------------------------------------

def test_emcon_reads_sensed_track_not_truth():
    """The silence fires off the SENSED track, never the ARM's true position.

    Construct an ARM physically AT the radar but with NO sensed track in the
    picture -> NO EMCON (the enemy hasn't sensed it, so it cannot react). If the
    decision read truth, the radar would silence; it must NOT.
    """
    w = CombatWorld(CombatConfig(seed=7, kh31p_ammo=1, n_enemy_radars=1))
    ship, radar = _first_destroyer(w)
    radar.emitting = True
    # An ARM physically sitting right on top of the radar — TRUTH says "danger".
    real_arm = PlayerArmMissile(
        KH31P, radar.pos.copy(),
        np.array([0.0, 0.0, 60.0], dtype=np.float64), radar, w._arm_rng)
    w.missiles.append(real_arm)
    # But the picture holds NO sensed track for it.
    assert not w.commander.picture.live_missile_tracks(w.sim_time)

    for order in w.commander.step(w.sim_time, 1.0):
        w._execute_commander_order(order)

    assert radar.emitting, (
        "no SENSED track -> NO EMCON even with an ARM physically at the radar "
        "(the decision must read the picture, not truth)")


# ---------------------------------------------------------------------------
# 4. Ground radar EMCON on a sensed ARM track
# ---------------------------------------------------------------------------

def test_ground_radar_emcon_on_sensed_arm():
    """A sensed ARM track within ARM_EMCON_RANGE_M of a ground radar -> it goes
    silent (ground radars have no SAM defense; silence is their only counter)."""
    w = CombatWorld(CombatConfig(seed=7, n_enemy_radars=1))
    gr = w._enemy_ground_radars[0]
    gr.emitting = True
    gx, _, gz = gr.pos
    pos = np.array([gx, 3_000.0, gz - 40_000.0], dtype=np.float64)
    assert np.hypot(pos[0] - gx, pos[2] - gz) < ARM_EMCON_RANGE_M
    _inject_track(w.commander.picture, "arm_probe", pos, "kh31p", w.sim_time)

    for order in w.commander.step(w.sim_time, 1.0):
        w._execute_commander_order(order)

    gsilent = [o for o in w.commander.pending_orders
               if o["type"] == "ground_radar_silent"
               and o["radar_id"] == gr.radar_id]
    assert gsilent, "commander must order ground_radar_silent off a sensed ARM"
    assert not gr.emitting, "the ground radar must go SILENT vs a sensed ARM"


# ---------------------------------------------------------------------------
# 5. Anti-strobe dwell: hold silent across the dwell, no per-tick re-emit/spam
# ---------------------------------------------------------------------------

def test_emcon_dwell_no_strobe():
    """While the ARM threat is seen the radar holds silent across the dwell
    without strobing: one silent order, no re-emit until the dwell elapses with
    the threat gone (mirrors the AWACS EMCON anti-strobe)."""
    w = CombatWorld(CombatConfig(seed=7, n_enemy_radars=1))
    cmd = w.commander
    pic = cmd.picture
    ship, radar = _first_destroyer(w)
    radar.emitting = True
    sx, _, sz = radar.pos
    pos = np.array([sx, 4_000.0, sz - 30_000.0], dtype=np.float64)
    _inject_track(pic, "arm_probe", pos, "kh31p", 0.0)

    # First defend tick: enter silent, exactly one ship_silent order.
    cmd.pending_orders.clear()
    cmd._defend_ship_radars(0.0)
    s0 = [o for o in cmd.pending_orders
          if o["type"] == "ship_silent" and o["ship_id"] == ship.ship_id]
    assert len(s0) == 1
    for o in cmd.pending_orders:
        w._execute_commander_order(o)
    assert not radar.emitting

    # Threat still present a tick later: NO second silent order (anti-spam).
    cmd.pending_orders.clear()
    cmd._defend_ship_radars(1.0)
    s1 = [o for o in cmd.pending_orders
          if o["type"] == "ship_silent" and o["ship_id"] == ship.ship_id]
    assert s1 == [], "must not re-issue ship_silent every tick (anti-strobe)"

    # Threat track gone but WITHIN the dwell -> still silent, no emit order.
    pic.missile_tracks.clear()
    cmd.pending_orders.clear()
    cmd._defend_ship_radars(ARM_EMCON_DWELL_S * 0.5)
    e_mid = [o for o in cmd.pending_orders
             if o["type"] == "ship_emit" and o["ship_id"] == ship.ship_id]
    assert e_mid == [], "ship must hold silent through the ARM dwell (no strobe)"
    assert not radar.emitting

    # After the dwell with no threat -> normal logic resumes (no ARM hold).
    # (No inbound, no drone -> no order either way; the key is the dwell no
    # longer pins it silent — emitting is allowed again.)
    cmd.pending_orders.clear()
    cmd._defend_ship_radars(ARM_EMCON_DWELL_S + 2.0)
    # The ARM hold has released: a fresh non-ARM inbound would now EMIT.
    _inject_track(pic, "oniks_probe",
                  np.array([sx, 4_000.0, sz - 30_000.0]), "oniks",
                  ARM_EMCON_DWELL_S + 2.0)
    cmd.pending_orders.clear()
    cmd._defend_ship_radars(ARM_EMCON_DWELL_S + 3.0)
    for o in cmd.pending_orders:
        w._execute_commander_order(o)
    assert radar.emitting, "after the ARM dwell, self-defense EMIT works again"


# ---------------------------------------------------------------------------
# 6. End-to-end payoff: ARM degrades to CEP, the EMCON'd radar SURVIVES
# ---------------------------------------------------------------------------

def test_arm_emcon_degrades_arm_to_cep():
    """Fire a PlayerArmMissile at a ship SPY-1 that the enemy SENSES; the ship
    goes EMCON; the ARM loses the emission and degrades to its seeded CEP ring
    -> the radar SURVIVES. The counter is physics-not-dice: the silence is a
    real radar.emitting=False the ARM's homing reads, not a probability roll.
    """
    w = CombatWorld(CombatConfig(seed=1337, kh31p_ammo=1, n_enemy_radars=0))
    ship, radar = _first_destroyer(w)
    # Relocate the ship within ARM reach (~90 km down-range of the launcher).
    lp = w._oniks_tubes[0]["pos"]
    nx = float(lp[0])
    nz = float(lp[2]) + 90_000.0
    radar.pos = np.array([nx, 18.0, nz], dtype=np.float64)
    ship.pos = np.array([nx, 0.0, nz], dtype=np.float64)
    radar.emitting = True

    # Localize the ship's SPY-1 in the player's SIGINT picture (fog gate).
    w.emitter_contacts[radar.radar_id] = dict(
        pos=radar.pos.copy(), kind="SPY-1", quality=50.0,
        last_heard=w.sim_time, age=10.0)

    m = w.launch_arm(radar.radar_id)
    assert m is not None and m.target_radar is radar
    real_pos = radar.pos.copy()

    # Drive the battle. Each step, feed the SENSED ARM track into the picture
    # (the world's _feed_enemy_picture does this in a live battle; here we feed
    # it directly to localize the test to the EMCON mechanism) and tick the
    # commander so the ship silences off the SENSED track.
    track_id = f"hostile_{id(m):x}"
    silenced_seen = False
    for _ in range(int(260.0 / DT)):
        if not m.alive:
            break
        _inject_track(w.commander.picture, track_id, m.pos, "kh31p",
                      w.sim_time, vel=m.vel.copy())
        for order in w.commander.step(w.sim_time, DT):
            w._execute_commander_order(order)
        if not radar.emitting:
            silenced_seen = True
        w.step(DT)

    assert silenced_seen, "the ship must have gone EMCON off the sensed ARM"
    assert radar.alive, (
        "an EMCON'd radar must SURVIVE the ARM (degraded to the CEP ring)")
    assert m._miss_offset is not None, (
        "the ARM must have drawn its seeded CEP miss offset (silence path)")
    if m.impact_pos is not None:
        miss = float(np.linalg.norm(m.impact_pos - real_pos))
        assert miss >= HARM_MISS_MIN_M - KH31P.fuse_radius - 1.0, (
            f"CEP miss {miss:.1f} m below the {HARM_MISS_MIN_M} m floor")


# ---------------------------------------------------------------------------
# 7. Default battle byte-identical with no ARM (kh31p_ammo=0)
# ---------------------------------------------------------------------------

def _emit_states(w):
    """Snapshot of every ship + ground radar emitting state (the surface the
    ARM-EMCON would change)."""
    ships = tuple(sorted(
        (s.ship_id, bool(s.radar.emitting)) for s in w.ships
        if getattr(s, "radar", None) is not None))
    ground = tuple(sorted(
        (r.radar_id, bool(r.emitting))
        for r in getattr(w, "_enemy_ground_radars", [])))
    return ships, ground


def test_default_battle_byte_identical_no_arm():
    """With kh31p_ammo=0 (default) NO ARM is ever fired, so no kind=="kh31p"
    track exists and the ARM-EMCON never fires. Two same-seed default battles
    stepped identically produce identical ship/ground-radar emitting states —
    and the non-ARM self-defense path is unchanged."""
    def run():
        w = CombatWorld(CombatConfig(seed=42))   # default kh31p_ammo == 0
        assert w._kh31p_ammo == 0
        for _ in range(int(20.0 / DT)):
            w.step(DT)
        return _emit_states(w)

    a = run()
    b = run()
    assert a == b, f"default battle emit states diverged:\n  {a}\n  {b}"

    # And no kind=="kh31p" track ever appears (no ARM fired out of the box).
    w = CombatWorld(CombatConfig(seed=42))
    for _ in range(int(20.0 / DT)):
        w.step(DT)
        for mt in w.commander.picture.live_missile_tracks(w.sim_time):
            assert mt.get("kind") != "kh31p", \
                "no ARM is fired with kh31p_ammo=0 -> no kh31p track may exist"


# ---------------------------------------------------------------------------
# 8. Determinism: same seed + same injected ARM track -> identical orders
# ---------------------------------------------------------------------------

def test_emcon_determinism():
    """Two same-seed worlds with the same injected ARM track produce identical
    silence orders (the EMCON is a deterministic function of picture + time,
    no RNG)."""
    def run():
        w = CombatWorld(CombatConfig(seed=99, n_enemy_radars=1))
        ship, radar = _first_destroyer(w)
        gr = w._enemy_ground_radars[0]
        sx, _, sz = radar.pos
        gx, _, gz = gr.pos
        _inject_track(w.commander.picture, "arm_ship",
                      np.array([sx, 4_000.0, sz - 25_000.0]), "kh31p", 0.0)
        _inject_track(w.commander.picture, "arm_gnd",
                      np.array([gx, 3_000.0, gz - 25_000.0]), "kh31p", 0.0)
        orders = w.commander.step(0.0, 1.0)
        return tuple(sorted(
            (o["type"], o.get("ship_id") or o.get("radar_id") or "")
            for o in orders
            if o["type"] in ("ship_silent", "ship_emit",
                             "ground_radar_silent", "ground_radar_emit")))

    assert run() == run(), "same-seed ARM-EMCON orders must be identical"


# ===========================================================================
# REAL-ARM END-TO-END (M2 GATE): a PlayerArmMissile fired through the FULL
# world.step() loop — NO synthetic injected track. The enemy must SENSE the
# real round via _feed_enemy_picture (Finding 1), form a kind=="kh31p" track,
# and react. These are the contract both review agents flagged as missing; the
# synthetic-track unit tests above remain valid coverage of the doctrine in
# isolation.
#
# Geometry: relocate the first destroyer's SPY-1 down-range of the launcher,
# HOLD STATION (speed=0) for a stable, deterministic intercept, and localize
# its emitter (the fog gate launch_arm requires). The ARM kill envelope over
# real terrain at this offset is exercised by the closest-approach assertions.
# ===========================================================================

# Down-range offset (m) of the relocated ship SPY-1 from the Oniks launcher.
#   60 km: inside the ARM's terrain-flyoff fuse envelope for a STATIONARY ship
#   (probed closest ~11 m < fuse_radius) -> a clean kill when NOT EMCON'd.
_E2E_KILL_RANGE_M = 60_000.0
#   90 km: still well within ARM reach (the round arrives) but far enough that
#   the EMCON dwell has time to degrade it to the CEP ring before terminal.
_E2E_EMCON_RANGE_M = 90_000.0
_E2E_MAX_T_S = 260.0   # generous flight-time budget for the longest shot


def _place_ship_spy1(w, range_m):
    """Relocate the first destroyer + its SPY-1 ``range_m`` down-range of the
    launcher, hold it on station (speed 0 -> deterministic intercept), set it
    EMITTING, and localize the emitter so ``launch_arm`` passes the fog gate.
    Returns (ship, radar)."""
    ship, radar = _first_destroyer(w)
    ship.speed = 0.0                       # hold station: stable ARM intercept
    lp = w._oniks_tubes[0]["pos"]
    nx = float(lp[0])
    nz = float(lp[2]) + float(range_m)
    radar.pos = np.array([nx, 18.0, nz], dtype=np.float64)
    ship.pos = np.array([nx, 0.0, nz], dtype=np.float64)
    radar.emitting = True
    w.emitter_contacts[radar.radar_id] = dict(
        pos=radar.pos.copy(), kind="SPY-1", quality=50.0,
        last_heard=w.sim_time, age=10.0)
    return ship, radar


def test_real_arm_is_sensed_and_triggers_ship_emcon():
    """A REAL Kh-31P fired through the world step loop is SENSED by the enemy
    (a kind=="kh31p" track appears in the commander's picture, via
    _feed_enemy_picture — NOT injected) and the threatened ship goes EMCON
    (radar stops emitting). This is the integration the M2 gate restored:
    before Finding 1 the ARM was filtered out before classification, so no
    kh31p track ever formed in play and the EMCON doctrine was unreachable."""
    w = CombatWorld(CombatConfig(seed=1337, kh31p_ammo=1, n_enemy_radars=0))
    ship, radar = _place_ship_spy1(w, _E2E_EMCON_RANGE_M)

    m = w.launch_arm(radar.radar_id)
    assert m is not None and m.target_radar is radar

    saw_kh31p = False
    went_emcon = False
    for _ in range(int(_E2E_MAX_T_S / DT)):
        if not m.alive:
            break
        w.step(DT)            # FULL loop: _feed_enemy_picture senses the ARM
        if any(t.get("kind") == "kh31p"
               for t in w.commander.picture.live_missile_tracks(w.sim_time)):
            saw_kh31p = True
        if not radar.emitting:
            went_emcon = True

    assert saw_kh31p, (
        "the enemy must SENSE the real ARM (a kind=='kh31p' track must appear "
        "in commander.picture.missile_tracks via _feed_enemy_picture)")
    assert went_emcon, (
        "the threatened ship must go EMCON (radar.emitting -> False) off the "
        "sensed ARM track")


def test_real_arm_kills_ship_spy1_when_not_emcon():
    """With the ship's ARM-EMCON suppressed (the radar keeps emitting), a REAL
    ARM fired through the world loop FUSES and kills the SPY-1 — and the kill
    STAYS dead after another step. This proves Finding 2's resurrection fix:
    the previous unconditional ``ship.radar.alive = ship.alive`` revived an
    ARM-killed radar the same tick, so an ARM could only blink it, never kill
    it. The EMCON path is disabled here (not the SENSING path) so we isolate
    the kill+credit mechanism; the EMCON-saves duel is asserted separately."""
    w = CombatWorld(CombatConfig(seed=1337, kh31p_ammo=1, n_enemy_radars=0))
    ship, radar = _place_ship_spy1(w, _E2E_KILL_RANGE_M)
    # Deny the ship its EMCON counter so the radar keeps emitting and the ARM
    # homes to a fuse kill (we are testing the KILL + no-resurrection, not the
    # doctrine — that has its own e2e below). The SENSING feed stays live.
    w.commander._defend_ship_radars = lambda *a, **k: None

    m = w.launch_arm(radar.radar_id)
    assert m is not None and m.target_radar is radar

    for _ in range(int(_E2E_MAX_T_S / DT)):
        if not m.alive:
            break
        w.step(DT)

    assert not m.alive, "the ARM must have fused/expended"
    assert m._miss_offset is None, (
        "an emitting (non-EMCON) radar must NOT degrade the ARM to the CEP "
        "ring — the round homes on the live emission to a kill")
    assert not radar.alive, (
        "the ARM must KILL the emitting SPY-1 (radar.alive -> False)")

    # Resurrection guard: step further — the killed radar must STAY dead while
    # the hull still floats (the ShipDefenseController must not revive it).
    assert ship.alive, "the hull survives an anti-RADAR hit (only the SPY-1 dies)"
    for _ in range(int(5.0 / DT)):
        w.step(DT)
    assert not radar.alive, (
        "a radar killed by an ARM while the ship LIVES must STAY dead — no "
        "per-tick resurrection (Finding 2)")


def test_real_arm_emcon_saves_ship_spy1():
    """The full duel through the world loop: the ship SENSES the real inbound
    ARM, goes EMCON, the ARM loses the emission and degrades to its seeded CEP
    ring, and the SPY-1 SURVIVES (radar.alive stays True). Physics-not-dice:
    the save is a real radar.emitting=False the ARM's homing reads, not a
    probability roll. No track is injected — the enemy senses the round
    itself."""
    w = CombatWorld(CombatConfig(seed=1337, kh31p_ammo=1, n_enemy_radars=0))
    ship, radar = _place_ship_spy1(w, _E2E_EMCON_RANGE_M)

    m = w.launch_arm(radar.radar_id)
    assert m is not None and m.target_radar is radar

    went_emcon = False
    for _ in range(int(_E2E_MAX_T_S / DT)):
        if not m.alive:
            break
        w.step(DT)
        if not radar.emitting:
            went_emcon = True

    assert went_emcon, "the ship must have gone EMCON off the sensed real ARM"
    assert radar.alive, (
        "an EMCON'd SPY-1 must SURVIVE the ARM (degraded to the CEP ring)")
    assert m._miss_offset is not None, (
        "the silenced-emitter path must have drawn the seeded CEP miss offset")
