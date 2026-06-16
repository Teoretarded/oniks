"""Probe: drone RWR + ELINT — detect AND geolocate enemy emitters.

Measures, never trusts comments:
  A. RWR SPIKE — does an enemy radar illuminating the drone raise a SPIKE?
  B. RWR LOCK  — does an enemy SAM guiding on the drone raise a LOCK?
  C. ELINT triangulation ACCURACY — error in metres vs true emitter position,
     for several geometries (loiter-only vs real cross-track flight), and how
     many bearings / how much flight time are needed to go ACTIONABLE.
  D. ELINT gates — does a base-loitering drone produce a confident WRONG fix
     (the failure the gates claim to prevent)?
  E. Determinism — same seed => identical triangulated position.
  F. End-to-end in CombatWorld — does a real battle ever inject an ELINT track?

Run: python tools/probe_audit_drone_rwr_elint.py   (ignore pygame stderr banner)
"""

import os
import sys
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from sim.recon import (
    ElintReceiver, RwrReceiver, ReconDrone,
    ELINT_BEARING_SIGMA_RAD, ELINT_FIX_ACTIONABLE_M, ELINT_RANGE_M,
    ELINT_MIN_PAIR_SPACING_M, ELINT_MIN_GEOMETRY_RAD, DRONE_ALT_M,
    DRONE_SPEED_MPS,
)
from sim.radar import Radar, radar_horizon_m

FLAT = lambda x, z: 0.0   # flat terrain so LOS never blocks (isolate ELINT math)


def mk_radar(rid, x, z, antenna=18.0, rng_m=300_000.0):
    r = Radar(rid, pos=np.array([x, 0.0, z], dtype=np.float64),
              antenna_m=antenna,
              ranges={"ship": 250_000.0, "fighter": 150_000.0,
                      "missile": 60_000.0, "stealth": rng_m})
    return r


def fly_straight_elint(emitter, start_xz, heading_rad, seconds,
                       seed=0, listen_dt=0.5):
    """Fly a straight track at cruise alt, listen at listen_dt cadence,
    return (elint, positions_flown). Emitter is (eid, radar)."""
    eid, radar = emitter
    rng = np.random.default_rng(seed)
    elint = ElintReceiver(rng=rng, height_fn=FLAT)
    x, z = float(start_xz[0]), float(start_xz[1])
    vx = math.sin(heading_rad) * DRONE_SPEED_MPS
    vz = math.cos(heading_rad) * DRONE_SPEED_MPS
    t = 0.0
    n_steps = int(seconds / listen_dt)
    for _ in range(n_steps):
        pos = np.array([x, DRONE_ALT_M, z], dtype=np.float64)
        elint.update(pos, [(eid, radar)], sim_time=t)
        x += vx * listen_dt
        z += vz * listen_dt
        t += listen_dt
    return elint


def err_m(est, radar):
    if est is None:
        return float("inf")
    return math.hypot(float(est[0]) - float(radar.pos[0]),
                      float(est[2]) - float(radar.pos[2]))


def n_pairs(elint, eid):
    return len(elint._pairs.get(eid, []))


print("=" * 78)
print("A. RWR SPIKE — enemy radar illuminating the drone")
print("=" * 78)
# Drone at base near origin; a ship radar at 80 km with 'stealth' range 120 km.
drone_pos = np.array([0.0, DRONE_ALT_M, 0.0], dtype=np.float64)
ship_close = mk_radar("ship0_spy1", 0.0, 80_000.0, antenna=30.0, rng_m=120_000.0)
ship_far = mk_radar("ship1_spy1", 0.0, 200_000.0, antenna=30.0, rng_m=120_000.0)
rwr = RwrReceiver(drone_id="drone_00", height_fn=FLAT)
rwr.update(drone_pos, [ship_close, ship_far], [])
print(f"  ship @80km stealth-range 120km -> detects drone? "
      f"{ship_close.detects(drone_pos, 'stealth')}")
print(f"  ship @200km stealth-range 120km -> detects drone? "
      f"{ship_far.detects(drone_pos, 'stealth')}")
print(f"  RWR state ship0={rwr.threat_state('ship0_spy1')} "
      f"ship1={rwr.threat_state('ship1_spy1')}")
alerts = rwr.alerts()
print(f"  alerts={alerts}")
true_brg = math.degrees(math.atan2(0.0 - 0.0, 80_000.0 - 0.0)) % 360.0
spike_brg = next((b for lvl, b in alerts if lvl == 'SPIKE'), None)
print(f"  SPIKE bearing reported={spike_brg} true(to emitter)={true_brg:.1f}")

# Silent radar must NOT spike
ship_close.emitting = False
rwr.update(drone_pos, [ship_close, ship_far], [])
print(f"  after emitting=False -> ship0 state={rwr.threat_state('ship0_spy1')} "
      f"(silent radar must NOT spike)")
ship_close.emitting = True

print()
print("=" * 78)
print("B. RWR LOCK — enemy SAM guiding on the drone")
print("=" * 78)


class FakeMissile:
    def __init__(self, mid, tgt_id, pos, rwr_lock=True):
        self.missile_id = mid
        self.alive = True
        self.pos = np.array(pos, dtype=np.float64)
        self.rwr_generates_lock = rwr_lock

        class T:
            aircraft_id = tgt_id
        self.target = T()


sam_at_drone = FakeMissile("sm2_7", "drone_00", [5_000.0, 9_000.0, 40_000.0])
sam_other = FakeMissile("sm2_8", "oniks_3", [1_000.0, 100.0, 10_000.0])
ir_at_drone = FakeMissile("aim9_2", "drone_00", [2_000.0, 12_000.0, 8_000.0],
                          rwr_lock=False)
rwr2 = RwrReceiver(drone_id="drone_00", height_fn=FLAT)
rwr2.update(drone_pos, [], [sam_at_drone, sam_other, ir_at_drone])
print(f"  SM2 targeting drone -> {rwr2.threat_state('sm2_7')} (expect LOCK)")
print(f"  SM2 targeting oniks (not drone) -> {rwr2.threat_state('sm2_8')} "
      f"(expect CLEAR)")
print(f"  IR (passive, rwr_generates_lock=False) at drone -> "
      f"{rwr2.threat_state('aim9_2')} (expect CLEAR — IR is passive)")
print(f"  alerts (LOCK first)={rwr2.alerts()}")

print()
print("=" * 78)
print("C. ELINT TRIANGULATION ACCURACY — error (m) vs true emitter position")
print("=" * 78)
print(f"  bearing sigma = {ELINT_BEARING_SIGMA_RAD} rad "
      f"({math.degrees(ELINT_BEARING_SIGMA_RAD):.2f} deg); "
      f"actionable threshold = {ELINT_FIX_ACTIONABLE_M:.0f} m")
print()

# Emitter ~80 km north of the start. Drone flies EAST (cross-track) so it
# builds a real baseline perpendicular to the line of sight.
emit = mk_radar("E", 0.0, 80_000.0, antenna=30.0, rng_m=ELINT_RANGE_M)
print(f"  --- geometry 1: emitter at (0, 80km), drone flies EAST (good "
      f"cross-track baseline) ---")
print(f"  {'flight_s':>9} {'pairs':>6} {'err_m':>12} {'quality_m':>12} "
      f"{'actionable':>11}")
for secs in (10, 30, 60, 120, 240, 360, 600):
    el = fly_straight_elint(("E", emit), (0.0, 0.0), math.pi / 2, secs, seed=1)
    est = el.est_pos("E")
    q = el.fix_quality("E")
    e = err_m(est, emit)
    print(f"  {secs:>9} {n_pairs(el, 'E'):>6} {e:>12.0f} {q:>12.1f} "
        f"{str(el.is_actionable('E')):>11}")

print()
print(f"  --- geometry 2: emitter at (0, 80km), drone flies NORTH "
      f"(toward emitter — degenerate baseline) ---")
print(f"  {'flight_s':>9} {'pairs':>6} {'err_m':>12} {'quality_m':>12} "
      f"{'actionable':>11}")
for secs in (60, 240, 600):
    el = fly_straight_elint(("E", emit), (0.0, 0.0), 0.0, secs, seed=2)
    est = el.est_pos("E")
    q = el.fix_quality("E")
    e = err_m(est, emit)
    print(f"  {secs:>9} {n_pairs(el, 'E'):>6} {e:>12.0f} {q:>12.1f} "
        f"{str(el.is_actionable('E')):>11}")

print()
# Time-to-actionable: when does the EAST flight first cross the threshold?
print(f"  --- time-to-first-actionable (EAST flight, fine cadence) ---")
for seed in range(5):
    el = ElintReceiver(rng=np.random.default_rng(seed), height_fn=FLAT)
    x, z, t = 0.0, 0.0, 0.0
    first = None
    first_err = None
    while t < 600:
        el.update(np.array([x, DRONE_ALT_M, z]), [("E", emit)], sim_time=t)
        if first is None and el.is_actionable("E"):
            first = t
            first_err = err_m(el.est_pos("E"), emit)
        x += DRONE_SPEED_MPS * 0.5
        t += 0.5
    base = abs(x)  # east displacement == baseline
    print(f"   seed={seed} first_actionable_at={first}s "
          f"err_at_that_time={None if first_err is None else round(first_err)}m "
          f"final_err={round(err_m(el.est_pos('E'), emit))}m "
          f"final_pairs={n_pairs(el,'E')}")

print()
print("=" * 78)
print("D. GATE TEST — base-loitering drone vs a FAR emitter (must NOT pin)")
print("=" * 78)
# This is the documented failure mode: a drone orbiting a 4 km circle 150 km
# from an emitter. The gates must keep quality = inf (never actionable).
emit_far = mk_radar("F", 0.0, 150_000.0, antenna=30.0, rng_m=ELINT_RANGE_M)
for seed in (0, 1, 2):
    el = ElintReceiver(rng=np.random.default_rng(seed), height_fn=FLAT)
    t = 0.0
    ang = 0.0
    R = 4_000.0
    omega = DRONE_SPEED_MPS / R
    bad = 0
    sampled = 0
    worst_confident_err = 0.0
    while t < 600:
        x = math.sin(ang) * R
        z = math.cos(ang) * R
        el.update(np.array([x, DRONE_ALT_M, z]), [("F", emit_far)], sim_time=t)
        if el.is_actionable("F"):
            bad += 1
            worst_confident_err = max(worst_confident_err,
                                      err_m(el.est_pos("F"), emit_far))
        sampled += 1
        ang = (ang + omega * 0.5) % (2 * math.pi)
        t += 0.5
    print(f"  seed={seed} loiter R=4km vs emitter@150km: "
          f"actionable_samples={bad}/{sampled} "
          f"worst_confident_err={round(worst_confident_err)}m "
          f"final_quality={el.fix_quality('F'):.1f}")

print()
print("=" * 78)
print("E. DETERMINISM — same seed => identical fix")
print("=" * 78)
e1 = fly_straight_elint(("E", emit), (0.0, 0.0), math.pi / 2, 300, seed=42)
e2 = fly_straight_elint(("E", emit), (0.0, 0.0), math.pi / 2, 300, seed=42)
e3 = fly_straight_elint(("E", emit), (0.0, 0.0), math.pi / 2, 300, seed=43)
p1, p2, p3 = e1.est_pos("E"), e2.est_pos("E"), e3.est_pos("E")
print(f"  seed42 run1 est=({p1[0]:.3f},{p1[2]:.3f}) q={e1.fix_quality('E'):.4f}")
print(f"  seed42 run2 est=({p2[0]:.3f},{p2[2]:.3f}) q={e2.fix_quality('E'):.4f}")
print(f"  seed43      est=({p3[0]:.3f},{p3[2]:.3f}) q={e3.fix_quality('E'):.4f}")
print(f"  run1==run2 (same seed)? {np.allclose(p1, p2)}")
print(f"  run1!=run3 (diff seed)? {not np.allclose(p1, p3)}")

print()
print("=" * 78)
print("F. END-TO-END in CombatWorld — does a real battle inject ELINT tracks?")
print("=" * 78)
try:
    from tools.playtest_harness import build_world
    for seed in (1, 7):
        w = build_world(seed)
        ships = w.ships
        print(f"  seed={seed}: {len(ships)} ships; drone @ "
              f"({w.drone.pos[0]:.0f},{w.drone.pos[2]:.0f})")
        for s in ships[:4]:
            d = math.hypot(float(s.pos[0]) - float(w.drone.pos[0]),
                           float(s.pos[2]) - float(w.drone.pos[2]))
            print(f"     {s.ship_id} @ ({s.pos[0]:.0f},{s.pos[2]:.0f}) "
                  f"dist_to_drone={d/1000:.1f}km emitting={s.radar.emitting}")
        # Task the drone to fly a long cross-track leg near the ships so it
        # builds geometry, then run the sim and watch for an ELINT-injected
        # ship track.
        # Send it on a wide east-west sweep across the group's bearing.
        cx = float(np.mean([s.pos[0] for s in ships]))
        cz = float(np.mean([s.pos[2] for s in ships]))
        # Fly to a point offset cross-track from the centroid, then sweep.
        w.drone.set_route([(cx - 60_000.0, cz - 90_000.0),
                           (cx + 60_000.0, cz - 90_000.0),
                           (cx - 60_000.0, cz - 90_000.0)])
        dt = 0.1
        injected = {}
        heard_any = set()
        actionable_seen = {}
        drone_lost_at = None
        for step in range(int(1200 / dt)):
            w.step(dt)
            if w.drone is None:
                if drone_lost_at is None:
                    drone_lost_at = round(w.sim_time)
                continue
            for eid in w.elint.heard_emitters():
                heard_any.add(eid)
                q = w.elint.fix_quality(eid)
                if q < ELINT_FIX_ACTIONABLE_M:
                    prev = actionable_seen.get(eid)
                    est = w.elint.est_pos(eid)
                    # error vs the matching ship true pos (ships only;
                    # airborne emitters have no fixed truth here)
                    sh = next((s for s in ships if s.radar.radar_id == eid),
                              None)
                    e = err_m(est, sh.radar) if sh else None
                    e_round = (round(e) if (e is not None and math.isfinite(e))
                               else "n/a")
                    e_cmp = e if (e is not None and math.isfinite(e)) \
                        else float("inf")
                    if prev is None or e_cmp < prev[3]:
                        actionable_seen[eid] = (round(q, 1), e_round,
                                                round(w.sim_time), e_cmp)
            # ELINT injects onto ship_id track; detect by checking tracks that
            # came from elint (we can't easily distinguish source, so just
            # report final track picture below).
        print(f"     drone shot down at t={drone_lost_at}s "
              f"(None = survived 1200s)")
        print(f"     heard emitters over 1200s: {sorted(heard_any)}")
        print(f"     ELINT actionable fixes (eid -> (quality_m, err_m, "
              f"t_first)): {actionable_seen}")
        surf = [cid for cid, t in w.contacts.tracks.items()
                if not t.get('is_air')]
        print(f"     final surface tracks in player picture: {surf}")
except Exception as ex:
    import traceback
    print("  END-TO-END FAILED:")
    traceback.print_exc()

print()
print("=" * 78)
print("G. SANITY — horizon / range caps")
print("=" * 78)
print(f"  radar_horizon(drone 18km, antenna 30m) = "
      f"{radar_horizon_m(DRONE_ALT_M, 30.0)/1000:.0f} km")
print(f"  ELINT_RANGE_M cap = {ELINT_RANGE_M/1000:.0f} km; "
      f"min pair spacing = {ELINT_MIN_PAIR_SPACING_M:.0f} m; "
      f"min geometry = {math.degrees(ELINT_MIN_GEOMETRY_RAD):.1f} deg")
print("DONE")
