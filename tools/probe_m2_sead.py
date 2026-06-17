"""GAME-TEST probe for Milestone 2 (SEAD / Anti-Radiation Warfare).

Drives REAL headless CombatWorld battles and MEASURES the SEAD duel with
numbers — no source/test edits, this probe is read-only against the game.

Sections (mirror the M2-T1/T2/T3 surfaces):
  1. Emitter ELINT channel in a live battle (world.emitter_contacts):
     which enemy emitters localize, the fix error (est vs truth), and that a
     silenced emitter AGES OUT of the store.
  2. ARM kills a lit emitter (the offensive verb): localize -> launch_arm ->
     step to impact; HIT + fuse miss distance; refuses (None) when un-localized
     and when kh31p_ammo==0.
  3. The SEAD duel (the payoff): same ARM shot at a ship SPY-1 — once where the
     enemy SENSES the inbound (-> EMCON -> ARM degrades to CEP -> radar SURVIVES)
     and once where it does NOT sense it (-> radar KILLED). Sensor-driven, not a
     roll.
  4. Determinism with ARM activity: two same-seed worlds, identical ARM shot at a
     silenced emitter, step ~3000 -> bit-identical (max positional delta == 0).
     Plus the default (kh31p_ammo=0) battle is bit-identical between two worlds.
  5. No crashes: a multi-minute battle with ARMs in flight, hammering the M2
     surfaces; total calls + any exception.

Run:  python tools/probe_m2_sead.py
"""

import math
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.arsenal import KH31P
from sim.commander import ARM_EMCON_RANGE_M, ARM_EMCON_DWELL_S
from sim.strike import HARM_MISS_MIN_M, HARM_MISS_MAX_M, PlayerArmMissile
from world.combat import CombatWorld
from world.combat_config import CombatConfig
from world.generation import terrain_height_scalar

DT = 1.0 / 120.0


def _localize(w, radar, kind="GND RADAR", quality=100.0, age=10.0):
    """Inject a localized emitter contact (the channel the drone ELINT fills)."""
    w.emitter_contacts[radar.radar_id] = dict(
        pos=radar.pos.copy(), kind=kind, quality=quality,
        last_heard=w.sim_time, age=age)


def _relocate_radar(w, radar, struct, downrange_m):
    """Move a radar (and its Structure, if any) downrange_m north of the first
    Oniks tube so it sits inside the measured ARM envelope (~130 km)."""
    lp = w._oniks_tubes[0]["pos"]
    nx = float(lp[0])
    nz = float(lp[2]) + downrange_m
    ny = max(terrain_height_scalar(nx, nz), 0.0)
    radar.pos = np.array([nx, ny + 18.0, nz], dtype=np.float64)
    if struct is not None:
        struct.pos = np.array([nx, ny, nz], dtype=np.float64)
    return radar.pos.copy()


def _first_destroyer(w):
    for s in w.commander.destroyers:
        if s.alive and getattr(s, "radar", None) is not None:
            return s, s.radar
    raise AssertionError("no live destroyer")


# ===========================================================================
# 1. Emitter ELINT channel in a live battle
# ===========================================================================

def section1_emitter_channel():
    print("=" * 74)
    print("1. EMITTER ELINT CHANNEL  (world.emitter_contacts in a live battle)")
    print("=" * 74)

    # A live battle with an extra ground radar; fly the recon drone on a wide
    # crossing leg so its ELINT triangulates the emitters (mirrors smoke_combat).
    w = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=1))
    drone = w.drone
    # Resolver: what the world considers ARM-targetable right now.
    resolver = w._player_targetable_emitters()
    print(f"  targetable emitters at t=0: {len(resolver)}")
    for eid, (kind, _r, _o) in sorted(resolver.items()):
        print(f"    {eid:<28} kind={kind}")

    # Aim a long ELINT crossing leg in front of destroyer_00 (its SPY-1 emits)
    # AND wide enough to also hear the AWACS / ground radar.
    ship00 = next(s for s in w.ships if s.ship_id == "destroyer_00")
    hx, hz = float(ship00.pos[0]), float(ship00.pos[2])
    leg_z = hz - 40_000.0
    drone.pos[0], drone.pos[2] = hx - 120_000.0, leg_z
    drone.set_route([(hx + 120_000.0, leg_z)])

    print()
    print("  stepping a live battle; emitters as they localize "
          "(est-vs-truth fix error):")
    seen = {}            # eid -> (t_first, err_m, kind)
    DT4 = 0.25
    for i in range(int(900.0 / DT4)):
        w.step(DT4)
        if i % 8 != 0:
            continue
        resolver = w._player_targetable_emitters()
        for eid, c in w.emitter_contacts.items():
            if eid in seen:
                continue
            entry = resolver.get(eid)
            truth = entry[1].pos if entry else None
            err = (float("inf") if truth is None else
                   float(np.hypot(c["pos"][0] - truth[0],
                                  c["pos"][2] - truth[2])))
            seen[eid] = (w.sim_time, err, c["kind"])
            print(f"    t={w.sim_time:6.1f}s  {eid:<28} kind={c['kind']:<10} "
                  f"fix_err={err:8.1f} m")

    if not seen:
        print("    (no emitter localized over the run — see notes)")
    else:
        print(f"\n  localized {len(seen)} distinct emitter(s) over the battle.")

    # Age-out: take a currently-localized emitter, force its source silent, and
    # confirm it drops from the store after ELINT_FRESH_S.
    print()
    print("  age-out check (silence an emitter -> it leaves the store):")
    if w.emitter_contacts:
        eid = next(iter(w.emitter_contacts))
        present_before = eid in w.emitter_contacts
        # Force the ELINT to report nothing heard, then inject at a far-future
        # time so the freshness gate ages the stored fix out.
        w.elint.heard_emitters = lambda: []
        w._inject_emitter_contacts(w.sim_time + 1000.0)
        present_after = eid in w.emitter_contacts
        print(f"    {eid}: in store before={present_before}, "
              f"after silence+age={present_after}  "
              f"-> {'AGED OUT (PASS)' if present_before and not present_after else 'FAIL'}")
    else:
        print("    (no emitter to age out)")
    return len(seen)


# ===========================================================================
# 2. ARM kills a lit emitter + fog/ammo refusals
# ===========================================================================

def section2_arm_kills_emitter():
    print()
    print("=" * 74)
    print("2. ARM KILLS A LIT EMITTER  (the offensive verb) + refusals")
    print("=" * 74)

    # --- Refusal: un-localized emitter ---
    w = CombatWorld(CombatConfig(seed=1337, kh31p_ammo=4, n_enemy_radars=1))
    struct, radar = w.enemy_radars[0]
    eid = radar.radar_id
    r_unloc = w.launch_arm(eid)
    print(f"  launch_arm(un-localized emitter)      -> {r_unloc}  "
          f"(ammo now {w._kh31p_ammo})  "
          f"{'REFUSED (PASS)' if r_unloc is None and w._kh31p_ammo == 4 else 'FAIL'}")
    r_none = w.launch_arm(None)
    print(f"  launch_arm(None)                      -> {r_none}  "
          f"{'REFUSED (PASS)' if r_none is None else 'FAIL'}")

    # --- Refusal: kh31p_ammo == 0 (default) ---
    w0 = CombatWorld(CombatConfig(seed=1337, n_enemy_radars=1))  # default ammo 0
    s0, rdr0 = w0.enemy_radars[0]
    _localize(w0, rdr0)
    r_empty = w0.launch_arm(rdr0.radar_id)
    print(f"  launch_arm(localized, ammo==0)        -> {r_empty}  "
          f"(default kh31p_ammo={w0._kh31p_ammo})  "
          f"{'REFUSED (PASS)' if r_empty is None else 'FAIL'}")

    # --- The kill: relocate a ground radar within reach, localize, fire ---
    print()
    print("  KILL a lit ground radar (relocated to ~110 km, emitting):")
    real_pos = _relocate_radar(w, radar, struct, 110_000.0)
    radar.emitting = True
    _localize(w, radar)
    ammo_before = w._kh31p_ammo
    m = w.launch_arm(eid)
    print(f"    launch_arm -> {type(m).__name__ if m else None}; "
          f"ammo {ammo_before} -> {w._kh31p_ammo}; "
          f"target is live radar: {m.target_radar is radar}")
    tof = None
    for i in range(int(320.0 / DT)):
        w.step(DT)
        if not radar.alive:
            tof = w.sim_time
            break
        if m.impact_pos is not None and not m.alive:
            break
    miss = (None if m.impact_pos is None else
            float(np.linalg.norm(m.impact_pos - real_pos)))
    print(f"    radar.alive after flight = {radar.alive}  "
          f"(struct.alive = {struct.alive})")
    print(f"    fuse miss distance = "
          f"{('%.1f m' % miss) if miss is not None else 'n/a'}  "
          f"(fuse_radius {KH31P.fuse_radius:.0f} m)  ToF~{tof}")
    verdict = (not radar.alive) and (not struct.alive) and (miss is not None
                                                            and miss < KH31P.fuse_radius + 1.0)
    print(f"    -> {'HIT + victory-credit Structure killed (PASS)' if verdict else 'CONCERN'}")
    return verdict


# ===========================================================================
# 3. The SEAD duel: EMCON saves the radar, no-EMCON lets it die
# ===========================================================================

def _sead_shot_ground(seed, sense_arm, downrange_m=100_000.0):
    """The SEAD duel on a GROUND radar (the path that actually credits a kill).
    Relocate one enemy ground radar within ARM reach, localize it, fire. If
    sense_arm, feed the SENSED ARM track each step so the commander silences the
    ground radar (EMCON); otherwise withhold the track. Returns a result dict.

    A ground radar is used because its kill credit flows through
    _apply_arm_radar_kills (Structure HP), and — unlike a ship SPY-1 — nothing
    resurrects it every tick (see the ship finding below)."""
    w = CombatWorld(CombatConfig(seed=seed, kh31p_ammo=1, n_enemy_radars=1))
    struct, radar = w.enemy_radars[0]
    real_pos = _relocate_radar(w, radar, struct, downrange_m)
    radar.emitting = True
    _localize(w, radar, kind="GND RADAR")
    m = w.launch_arm(radar.radar_id)
    assert m is not None and m.target_radar is radar

    track_id = f"hostile_{id(m):x}"
    silenced_seen = False
    for _ in range(int(320.0 / DT)):
        if not m.alive:
            break
        if sense_arm:
            # Feed the SENSED ARM track (kind=="kh31p") the way the world's
            # _feed_enemy_picture stamps a physical detection, then tick the
            # commander so the ground radar silences off the SENSED track.
            w.commander.picture.update_missile_track(
                track_id, m.pos.copy(), m.vel.copy(),
                sim_time=w.sim_time, kind="kh31p")
            for order in w.commander.step(w.sim_time, DT):
                w._execute_commander_order(order)
        if not radar.emitting:
            silenced_seen = True
        w.step(DT)

    miss = (None if m.impact_pos is None else
            float(np.linalg.norm(m.impact_pos - real_pos)))
    return dict(silenced_seen=silenced_seen, radar_alive=radar.alive,
                struct_alive=struct.alive, miss=miss,
                miss_offset=m._miss_offset)


def _ship_spy1_arm_kill(seed=1337, downrange_m=60_000.0):
    """Isolation test for the ship-SPY-1 ARM-kill path: fire a clean ARM at a
    PINNED, emitting destroyer SPY-1 (no EMCON, no ship motion) and report
    whether the fuse kill STICKS. Returns (fuse_fired, radar_alive_after)."""
    w = CombatWorld(CombatConfig(seed=seed, kh31p_ammo=1, n_enemy_radars=0))
    ship, radar = _first_destroyer(w)
    lp = w._oniks_tubes[0]["pos"]
    nx, nz = float(lp[0]), float(lp[2]) + downrange_m
    radar.pos = np.array([nx, 0.0, nz], dtype=np.float64)
    ship.pos = np.array([nx, 0.0, nz], dtype=np.float64)
    radar.emitting = True
    ship.speed = 0.0                                  # pin the hull stationary
    anchor_s, anchor_r = ship.pos.copy(), radar.pos.copy()
    _localize(w, radar, kind="SPY-1", quality=50.0)
    m = w.launch_arm(radar.radar_id)
    fuse_fired = False
    orig = m._fuse_check

    def wrapped():
        nonlocal fuse_fired
        r = orig()
        fuse_fired = fuse_fired or r
        return r
    m._fuse_check = wrapped
    for _ in range(int(220.0 / DT)):
        if not m.alive:
            break
        w.step(DT)
        ship.pos, radar.pos = anchor_s.copy(), anchor_r.copy()
    return fuse_fired, radar.alive


def section3_sead_duel():
    print()
    print("=" * 74)
    print("3. THE SEAD DUEL  (sensor-driven counter, not a roll)")
    print("=" * 74)
    print(f"   ARM_EMCON_RANGE_M={ARM_EMCON_RANGE_M/1e3:.0f} km  "
          f"dwell={ARM_EMCON_DWELL_S:.0f} s  "
          f"CEP ring {HARM_MISS_MIN_M:.0f}..{HARM_MISS_MAX_M:.0f} m")
    print("   (run on a GROUND radar — the path with a real kill-credit)")

    emcon = _sead_shot_ground(seed=1337, sense_arm=True)
    print()
    print("  A) ENEMY SENSES the ARM (EMCON path):")
    print(f"     radar went EMCON (emitting False seen)   = {emcon['silenced_seen']}")
    print(f"     radar.alive after the shot               = {emcon['radar_alive']}")
    print(f"     ARM drew a CEP miss offset               = "
          f"{emcon['miss_offset'] is not None}")
    print(f"     fuse/CEP miss distance                   = "
          f"{('%.1f m' % emcon['miss']) if emcon['miss'] is not None else 'n/a'}")
    a_pass = (emcon['silenced_seen'] and emcon['radar_alive']
              and emcon['miss_offset'] is not None)
    print(f"     -> {'EMCON SAVED the radar (PASS)' if a_pass else 'CONCERN'}")

    noemcon = _sead_shot_ground(seed=1337, sense_arm=False)
    print()
    print("  B) ENEMY does NOT sense the ARM (no track -> no EMCON):")
    print(f"     radar went EMCON                         = {noemcon['silenced_seen']}")
    print(f"     radar.alive after the shot               = {noemcon['radar_alive']}")
    print(f"     ARM CEP miss offset (should be None)     = {noemcon['miss_offset']}")
    print(f"     fuse miss distance                       = "
          f"{('%.1f m' % noemcon['miss']) if noemcon['miss'] is not None else 'n/a'}")
    b_pass = (not noemcon['silenced_seen']) and (not noemcon['radar_alive'])
    print(f"     -> {'NO EMCON let the radar DIE (PASS)' if b_pass else 'CONCERN'}")

    print()
    print("  SEAD-DUEL VERDICT (ground radar): EMCON saves the radar = "
          f"{a_pass}; no-EMCON lets it die = {b_pass}")

    # --- FINDING: the ship SPY-1 ARM-kill path is broken ------------------
    print()
    print("  C) SHIP SPY-1 ARM-kill isolation (FINDING):")
    fuse_fired, ship_radar_alive = _ship_spy1_arm_kill()
    print(f"     ARM fuse fired on the SPY-1              = {fuse_fired}")
    print(f"     ship SPY-1 radar.alive after fuse kill  = {ship_radar_alive}")
    ship_bug = fuse_fired and ship_radar_alive
    if ship_bug:
        print("     -> BUG: the fuse sets radar.alive=False but the ship is")
        print("        immediately RESURRECTED each tick by ShipDefense"
              "Controller.step")
        print("        (sim/enemy_defense.py:614  ship.radar.alive = ship.alive)")
        print("        => a Kh-31P can NEVER kill a destroyer/carrier SPY-1;")
        print("        ship EMCON is moot (radar survives regardless).")
    else:
        print("     -> ship SPY-1 ARM kill behaves "
              f"(fuse_fired={fuse_fired}, alive={ship_radar_alive})")
    return a_pass and b_pass, ship_bug


# ===========================================================================
# 4. Determinism with ARM activity
# ===========================================================================

def _snapshot(w):
    """Bit-comparable positional snapshot of the whole battle state."""
    ships = [tuple(np.asarray(s.pos, dtype=np.float64)) for s in w.ships]
    miss = [tuple(np.asarray(m.pos, dtype=np.float64)) for m in w.missiles]
    air = [tuple(np.asarray(e.pos, dtype=np.float64)) for e in w.enemy_air]
    return ships, miss, air


def _max_delta(a, b):
    md = 0.0
    for la, lb in zip(a, b):
        for pa, pb in zip(la, lb):
            md = max(md, float(np.max(np.abs(np.array(pa) - np.array(pb)))))
    return md


def _arm_world(seed):
    """Build a world, relocate+localize an enemy ground radar, fire an ARM at
    it, then SILENCE it (forces the seeded CEP offset draw — the [seed,8] path)."""
    w = CombatWorld(CombatConfig(seed=seed, kh31p_ammo=4, n_enemy_radars=1))
    struct, radar = w.enemy_radars[0]
    _relocate_radar(w, radar, struct, 90_000.0)
    _localize(w, radar)
    m = w.launch_arm(radar.radar_id)
    radar.emitting = False        # silence -> seeded CEP miss offset
    return w, m


def section4_determinism():
    print()
    print("=" * 74)
    print("4. DETERMINISM WITH ARM ACTIVITY")
    print("=" * 74)

    wa, ma = _arm_world(2024)
    wb, mb = _arm_world(2024)
    for _ in range(3000):
        wa.step(DT)
        wb.step(DT)
    md = _max_delta(_snapshot(wa), _snapshot(wb))
    off_eq = (ma._miss_offset is not None and mb._miss_offset is not None
              and np.array_equal(ma._miss_offset, mb._miss_offset))
    print(f"  two same-seed worlds w/ ARM fired+silenced, 3000 steps:")
    print(f"    max positional delta = {md:.6g}  "
          f"(state count: ships+missiles+air)")
    print(f"    seeded CEP miss offset identical = {off_eq}  "
          f"(a={ma._miss_offset}, b={mb._miss_offset})")
    arm_det = (md == 0.0) and off_eq
    print(f"    -> {'BIT-IDENTICAL (PASS)' if arm_det else 'NON-DETERMINISTIC (FAIL)'}")

    # Default config (kh31p_ammo=0) bit-identical between two worlds.
    print()
    print("  default config (kh31p_ammo=0) determinism:")
    da = CombatWorld(CombatConfig(seed=42))
    db = CombatWorld(CombatConfig(seed=42))
    for _ in range(3000):
        da.step(DT)
        db.step(DT)
    md0 = _max_delta(_snapshot(da), _snapshot(db))
    print(f"    max positional delta = {md0:.6g}  "
          f"(_kh31p_ammo={da._kh31p_ammo})")
    def_det = md0 == 0.0
    print(f"    -> {'BIT-IDENTICAL (PASS)' if def_det else 'FAIL'}")
    return arm_det, def_det


# ===========================================================================
# 5. No crashes hammering the M2 surfaces over a multi-minute battle
# ===========================================================================

def section5_no_crashes():
    print()
    print("=" * 74)
    print("5. NO CRASHES  (multi-minute battle, ARMs in flight, M2 surfaces)")
    print("=" * 74)
    calls = 0
    exc = None
    try:
        w = CombatWorld(CombatConfig(seed=11, kh31p_ammo=4, n_enemy_radars=2))
        # Localize + fire ARMs at the two ground radars and a destroyer SPY-1.
        targets = []
        for struct, radar in w.enemy_radars:
            _relocate_radar(w, radar, struct, 100_000.0)
            radar.emitting = True
            _localize(w, radar)
            targets.append(radar.radar_id)
        ship, srad = _first_destroyer(w)
        _relocate_radar(w, srad, None, 95_000.0)
        srad.emitting = True
        _localize(w, srad, kind="SPY-1")
        targets.append(srad.radar_id)

        fired = 0
        DT4 = 0.25
        for i in range(int(240.0 / DT)):
            # Hammer the M2 query surfaces every step.
            w._player_targetable_emitters(); calls += 1
            w._inject_emitter_contacts(w.sim_time); calls += 1
            _ = dict(w.emitter_contacts); calls += 1
            # Fire the remaining ARMs spread over the first few seconds.
            if fired < len(targets) and i == fired * 200:
                w.launch_arm(targets[fired]); calls += 1
                fired += 1
            w.step(DT); calls += 1
        # A few coarse steps to flush anything in flight.
        for _ in range(int(120.0 / DT4)):
            w._player_targetable_emitters(); calls += 1
            w.step(DT4); calls += 1
    except Exception as e:  # noqa: BLE001
        exc = e
        traceback.print_exc()
    print(f"  total M2-surface + step calls = {calls}")
    print(f"  exception = {exc!r}")
    print(f"  -> {'NO CRASHES (PASS)' if exc is None else 'CRASH (FAIL)'}")
    return exc is None, calls


def main():
    n_emitters = section1_emitter_channel()
    s2 = section2_arm_kills_emitter()
    s3_duel, ship_bug = section3_sead_duel()
    s4_arm, s4_def = section4_determinism()
    s5_ok, s5_calls = section5_no_crashes()

    print()
    print("#" * 74)
    print("# M2 SEAD PROBE SUMMARY")
    print("#" * 74)
    print(f"  1. emitter ELINT channel : {n_emitters} emitter(s) localized + age-out")
    print(f"  2. ARM kills a lit emitter + refusals : {'PASS' if s2 else 'CONCERN'}")
    print(f"  3. SEAD duel on GROUND radar (EMCON saves / no-EMCON kills) : "
          f"{'PASS' if s3_duel else 'CONCERN'}")
    print(f"     SHIP SPY-1 ARM kill : "
          f"{'BROKEN — radar resurrected each tick (FINDING)' if ship_bug else 'OK'}")
    print(f"  4. determinism: ARM={'PASS' if s4_arm else 'FAIL'}  "
          f"default={'PASS' if s4_def else 'FAIL'}")
    print(f"  5. no crashes ({s5_calls} calls) : {'PASS' if s5_ok else 'FAIL'}")
    # The ship-SPY-1 ARM-kill bug is a real regression in M2's measured
    # behavior, so it pulls the overall verdict to CONCERNS even though every
    # other surface measures clean.
    core_ok = s2 and s3_duel and s4_arm and s4_def and s5_ok and n_emitters > 0
    overall = core_ok and not ship_bug
    print()
    print(f"  OVERALL M2 VERDICT: {'PASS' if overall else 'CONCERNS'}"
          + ("  (core surfaces PASS; ship-SPY-1 ARM kill is the open finding)"
             if core_ok and ship_bug else ""))


if __name__ == "__main__":
    main()
