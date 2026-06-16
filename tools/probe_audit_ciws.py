"""Audit probe: enemy ship CIWS gun point defense.

Measures:
  A) The Ciws gun engine in isolation (sim/ciws.py): Pk ramp vs slant range,
     burst cadence, rounds drawn, kill-per-burst statistics over many seeds.
  B) The ShipDefense integration path (sim/enemy_defense.py _run_ciws): does a
     real close inbound Oniks get tracked, enter the 2 km bubble, and get killed
     by the gun? Measures TRACK_FORM_S latency, engagement bubble, and outcome.
  C) Reachability: how close does the Oniks geometry put the missile to the
     ship before SM-2 / S-300 normally kill it, and whether the 2 km CIWS
     bubble is ever entered in normal play.

Run: python tools/probe_audit_ciws.py   (pygame banner on stderr -- ignore)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import numpy as np

from sim.ciws import (Ciws, ENGAGE_RANGE, R_NEAR, R_FAR, P_NEAR, P_FAR,
                      BURST_FIRE_TIME, BURST_PAUSE_TIME, ROUNDS_PER_SECOND)
from sim.enemy_defense import (ShipDefense, CIWS_MOUNT_M, SM2_MIN_RANGE_M,
                               TRACK_FORM_S, VIS_CHECK_PERIOD)
from sim.enemy_ships import Destroyer, _CIWS_AMMO_DEFAULT
from sim.missile import Missile
from sim.arsenal import ONIKS, SM2


DT = 1.0 / 120.0


# ----------------------------------------------------------------- helpers ----

class FakeTarget:
    """Minimal CIWS target: pos is RELATIVE to the gun mount (the engine
    measures slant straight off .pos)."""

    def __init__(self, pos, vel):
        self.pos = np.array(pos, dtype=np.float64)
        self.vel = np.array(vel, dtype=np.float64)
        self.alive = True

    def velocity(self):
        return self.vel


class FakeOniks(Missile):
    """A constant-velocity sea-skimmer that IS a Missile (so the ShipDefense
    controller classifies it as a hostile via isinstance) but skips the heavy
    flight-machine constructor.  We drive .pos by hand each substep."""

    def __init__(self, pos, vel):
        self.weapon = ONIKS
        self.pos = np.array(pos, dtype=np.float64)
        self.prev_pos = self.pos.copy()
        self.vel = np.array(vel, dtype=np.float64)
        self.alive = True
        self.impact_pos = None
        self.is_hostile = False

    def velocity(self):
        return self.vel


def measure_pk_curve():
    print("=" * 70)
    print("A) Ciws ENGINE — Pk ramp + envelope (sim/ciws.py)")
    print("=" * 70)
    print(f"  ENGAGE_RANGE={ENGAGE_RANGE} m  R_NEAR={R_NEAR}  R_FAR={R_FAR}")
    print(f"  P_NEAR={P_NEAR}  P_FAR={P_FAR}")
    print(f"  burst_fire={BURST_FIRE_TIME}s pause={BURST_PAUSE_TIME}s "
          f"rate={ROUNDS_PER_SECOND} rd/s  -> {int(ROUNDS_PER_SECOND*BURST_FIRE_TIME)} rd/burst")
    # The _kill_prob ramp at representative ranges.
    c = Ciws(9999, np.random.default_rng(0))
    print("\n  Pk(slant) ramp:")
    for r in (300, 800, 1000, 1400, 2000, 2500):
        print(f"    {r:5d} m -> Pk = {c._kill_prob(float(r)):.3f}")

    # Empirical kill-per-burst over many seeds at fixed range, head-on closer.
    print("\n  Empirical kill-per-FIRST-BURST (fixed-slant target, N=2000):")
    for r in (800.0, 1400.0, 2000.0):
        kills = 0
        N = 2000
        for seed in range(N):
            ciws = Ciws(9999, np.random.default_rng(seed))
            tgt = FakeTarget([0.0, 0.0, r], [0.0, 0.0, -680.0])  # closing
            for _ in range(int(2.5 / DT)):
                evs = ciws.engage(tgt, DT)
                if any(k == "ciws_kill" for k, _ in evs):
                    kills += 1
                if any(k == "ciws_burst" for k, _ in evs):
                    break  # one burst resolved
        print(f"    {r:5.0f} m: {kills}/{N} = {kills/N:.3f}  "
              f"(nominal {c._kill_prob(r):.3f})")


def measure_cadence_and_ammo():
    print("\n" + "=" * 70)
    print("A2) Burst cadence + ammo draw + receding/lateral gating")
    print("=" * 70)
    ciws = Ciws(_CIWS_AMMO_DEFAULT, np.random.default_rng(1))
    tgt = FakeTarget([0.0, 0.0, 1500.0], [0.0, 0.0, -680.0])
    bursts = 0
    t = 0.0
    first_burst_t = None
    for _ in range(int(10.0 / DT)):
        evs = ciws.engage(tgt, DT)
        t += DT
        if any(k == "ciws_burst" for k, _ in evs):
            bursts += 1
            if first_burst_t is None:
                first_burst_t = t
    print(f"  closing target: first burst at t={first_burst_t:.3f}s "
          f"(expect ~{BURST_PAUSE_TIME+BURST_FIRE_TIME:.2f}s), "
          f"bursts in 10s = {bursts}")
    print(f"  ammo {_CIWS_AMMO_DEFAULT} -> {ciws.ammo} "
          f"(drew {_CIWS_AMMO_DEFAULT - ciws.ammo} rd; "
          f"{(_CIWS_AMMO_DEFAULT-ciws.ammo)//bursts if bursts else 0} rd/burst)")

    # Receding target: must NOT fire.
    ciws2 = Ciws(9999, np.random.default_rng(2))
    rec = FakeTarget([0.0, 0.0, 1500.0], [0.0, 0.0, +680.0])  # moving away
    b = sum(1 for _ in range(int(5.0 / DT))
            for k, _ in ciws2.engage(rec, DT) if k == "ciws_burst")
    print(f"  RECEDING target: bursts in 5s = {b}  (expect 0)")

    # Pure lateral target inside bubble: closing ~0 -> no fire.
    ciws3 = Ciws(9999, np.random.default_rng(3))
    lat = FakeTarget([0.0, 0.0, 1500.0], [680.0, 0.0, 0.0])
    b = sum(1 for _ in range(int(5.0 / DT))
            for k, _ in ciws3.engage(lat, DT) if k == "ciws_burst")
    print(f"  PURE-LATERAL target: bursts in 5s = {b}  (expect 0)")

    # Just outside the bubble.
    ciws4 = Ciws(9999, np.random.default_rng(4))
    out = FakeTarget([0.0, 0.0, 2100.0], [0.0, 0.0, -680.0])
    b = sum(1 for _ in range(int(5.0 / DT))
            for k, _ in ciws4.engage(out, DT) if k == "ciws_burst")
    print(f"  OUTSIDE 2 km (2100 m): bursts in 5s = {b}  (expect 0)")


class MiniWorld:
    """Minimal world for ShipDefense.step: missiles list, events, sim_time."""

    def __init__(self):
        self.missiles = []
        self.events = []
        self.sim_time = 0.0
        self.drone = None


def measure_integration_kill():
    print("\n" + "=" * 70)
    print("B) INTEGRATION — close inbound Oniks vs ShipDefense._run_ciws")
    print("=" * 70)
    print(f"  CIWS_MOUNT_M={CIWS_MOUNT_M}  TRACK_FORM_S={TRACK_FORM_S}  "
          f"VIS_CHECK_PERIOD={VIS_CHECK_PERIOD}  SM2_MIN_RANGE_M={SM2_MIN_RANGE_M}")

    # Build one destroyer at origin. Confirm SPY-1 detects an inbound missile.
    ship = Destroyer("dd_probe", np.array([0.0, 0.0]), heading_deg=0.0,
                     sm2_ammo=0, ciws_ammo=_CIWS_AMMO_DEFAULT)
    ship.pos[1] = 0.0  # waterline
    ship.radar.pos[:] = ship.pos
    # Confirm radar detect of a sea-skimmer at 1.5 km, 12 m alt.
    probe_pos = np.array([0.0, 12.0, 1500.0])
    det = ship.radar.detects(probe_pos, "missile")
    print(f"  SPY-1 detects sea-skimmer at 1500 m / 12 m alt: {det}")

    outcomes = {"killed": 0, "leaked": 0}
    kill_ranges = []
    track_form_lat = []
    bubble_entry_t = []
    N = 60
    for seed in range(N):
        ship = Destroyer("dd", np.array([0.0, 0.0]), heading_deg=0.0,
                         sm2_ammo=0, ciws_ammo=_CIWS_AMMO_DEFAULT)
        ship.pos[1] = 0.0
        ship.radar.pos[:] = ship.pos
        defense = ShipDefense(ship, np.random.default_rng(seed))
        world = MiniWorld()

        # Oniks: sea-skimmer, 12 m alt, M2 (~680 m/s) head-on from +Z,
        # starting at 3.5 km so it crosses the whole 2 km bubble.
        m = FakeOniks([0.0, 12.0, 3500.0], [0.0, 0.0, -680.0])
        world.missiles.append(m)

        t = 0.0
        first_track = None
        first_bubble = None
        killed = False
        kill_r = None
        # March the missile straight in; step defense each substep.
        for _ in range(int(8.0 / DT)):
            # advance missile kinematics by hand (constant velocity skimmer)
            m.pos = m.pos + m.vel * DT
            world.sim_time = t
            # gun-relative slant
            gun = ship.pos + np.array([0.0, CIWS_MOUNT_M, 0.0])
            slant = math.sqrt(float((m.pos[0]-gun[0])**2 +
                                    (m.pos[1]-gun[1])**2 +
                                    (m.pos[2]-gun[2])**2))
            if first_bubble is None and slant <= ENGAGE_RANGE:
                first_bubble = (t, slant)
            defense.step(world, DT)
            # has a track formed?
            if first_track is None:
                for st in defense._tracks.values():
                    if defense._tracked(st, t):
                        first_track = t
                        break
            if not m.alive and not killed:
                killed = True
                kill_r = slant
                break
            if m.pos[2] < -500.0:   # passed the ship, leaked
                break
            t += DT

        if killed:
            outcomes["killed"] += 1
            kill_ranges.append(kill_r)
        else:
            outcomes["leaked"] += 1
        if first_track is not None:
            track_form_lat.append(first_track)
        if first_bubble is not None:
            bubble_entry_t.append(first_bubble)

    print(f"\n  N={N} seeded runs, head-on M2 Oniks, ammo={_CIWS_AMMO_DEFAULT}, "
          f"SM-2 disabled (gun only):")
    print(f"    KILLED by CIWS: {outcomes['killed']}/{N} "
          f"= {outcomes['killed']/N:.3f}  (single-engagement Pk)")
    print(f"    LEAKED (passed the ship): {outcomes['leaked']}/{N}")
    if track_form_lat:
        print(f"    track-form latency: mean={np.mean(track_form_lat):.2f}s "
              f"min={min(track_form_lat):.2f} max={max(track_form_lat):.2f}")
    if bubble_entry_t:
        bt = [b[0] for b in bubble_entry_t]
        print(f"    bubble (<=2km) entry t: mean={np.mean(bt):.2f}s")
    if kill_ranges:
        print(f"    kill slant range: mean={np.mean(kill_ranges):.0f} m "
              f"min={min(kill_ranges):.0f} max={max(kill_ranges):.0f}")

    # Determinism check: same seed twice -> identical outcome.
    def run_once(seed):
        ship = Destroyer("dd", np.array([0.0, 0.0]), sm2_ammo=0,
                         ciws_ammo=_CIWS_AMMO_DEFAULT)
        ship.pos[1] = 0.0
        ship.radar.pos[:] = ship.pos
        d = ShipDefense(ship, np.random.default_rng(seed))
        w = MiniWorld()
        m = FakeOniks([0.0, 12.0, 3500.0], [0.0, 0.0, -680.0])
        w.missiles.append(m)
        t = 0.0
        for _ in range(int(8.0/DT)):
            m.pos = m.pos + m.vel*DT
            w.sim_time = t
            d.step(w, DT)
            if not m.alive:
                return ("kill", round(float(m.pos[2]), 3), ship.ciws_ammo)
            if m.pos[2] < -500:
                return ("leak", round(float(m.pos[2]), 3), ship.ciws_ammo)
            t += DT
        return ("none", None, ship.ciws_ammo)
    r1 = run_once(7)
    r2 = run_once(7)
    print(f"\n  determinism: seed7 run1={r1} run2={r2} "
          f"-> {'MATCH' if r1 == r2 else 'DIVERGE'}")


def measure_reachability():
    """Does an Oniks reach the 2 km CIWS bubble in NORMAL play, or does the
    SM-2 / S-300 / multipath layer end it first?  Build a real combat world,
    fire the whole Oniks battery at the nearest destroyer, and track the
    closest approach of each inbound Oniks to ANY destroyer."""
    print("\n" + "=" * 70)
    print("C) REACHABILITY — does an Oniks reach the CIWS bubble in real play?")
    print("=" * 70)
    from tools.playtest_harness import build_world

    bubble_entries = 0
    ciws_bursts_total = 0
    ciws_kills_total = 0
    n_seeds = 3
    min_slants = []
    for seed in (1, 2, 3):
        w = build_world(seed)
        destroyers = [s for s in w.ships if isinstance(s, Destroyer)]
        if not destroyers:
            print(f"  seed {seed}: no destroyers")
            continue
        # Aim every tube at the nearest destroyer.
        base = np.array([float(w._oniks_launcher_positions[0][0]),
                         float(w._oniks_launcher_positions[0][2])])
        dd = min(destroyers, key=lambda s: math.hypot(
            float(s.pos[0]) - base[0], float(s.pos[2]) - base[1]))
        tgt = np.array([float(dd.pos[0]), 0.0, float(dd.pos[2])])
        fired = 0
        for _ in range(12):
            m = w.launch("lo-lo", tgt)   # sea-skim profile -> hardest for SM-2
            if m is None:
                break
            fired += 1
        # Track this batch of player Oniks.
        oniks = [m for m in w.missiles if isinstance(m, Missile)
                 and not getattr(m, "is_hostile", False)]
        per_min = {id(m): 1e9 for m in oniks}
        seed_bubble = 0
        # Step the full world; count CIWS events from world.events.
        from main import PHYS_DT
        prev_ev = 0
        steps = int(420.0 / PHYS_DT)   # up to 7 min sim
        for _ in range(steps):
            w.step(PHYS_DT)
            for m in oniks:
                if not m.alive:
                    continue
                for s in destroyers:
                    d = math.hypot(float(m.pos[0]) - float(s.pos[0]),
                                   float(m.pos[1]) - float(s.pos[1]) - CIWS_MOUNT_M,
                                   float(m.pos[2]) - float(s.pos[2])) \
                        if False else math.sqrt(
                            (float(m.pos[0]) - float(s.pos[0]))**2 +
                            (float(m.pos[1]) - (float(s.pos[1]) + CIWS_MOUNT_M))**2 +
                            (float(m.pos[2]) - float(s.pos[2]))**2)
                    if d < per_min[id(m)]:
                        per_min[id(m)] = d
            # tally CIWS events
            for kind, _pos in w.events[prev_ev:]:
                if kind == "ciws_burst":
                    ciws_bursts_total += 1
                elif kind == "ciws_kill":
                    ciws_kills_total += 1
            prev_ev = len(w.events)
            if all(not m.alive for m in oniks):
                break
        reached = sum(1 for v in per_min.values() if v <= ENGAGE_RANGE)
        seed_bubble = reached
        bubble_entries += reached
        closest = min(per_min.values()) if per_min else None
        min_slants.append(closest)
        print(f"  seed {seed}: fired {fired} Oniks at nearest DD "
              f"({math.hypot(tgt[0]-base[0], tgt[2]-base[1])/1000:.0f} km), "
              f"{reached}/{fired} entered 2km bubble; "
              f"closest approach to any DD = {closest:.0f} m")
    print(f"\n  TOTALS over {n_seeds} seeds:")
    print(f"    Oniks that entered a CIWS 2 km bubble: {bubble_entries}")
    print(f"    CIWS bursts fired (world.events): {ciws_bursts_total}")
    print(f"    CIWS kills (world.events):        {ciws_kills_total}")
    print(f"    closest Oniks approach per seed: "
          f"{[f'{s:.0f}m' for s in min_slants]}")


def main():
    measure_pk_curve()
    measure_cadence_and_ammo()
    measure_integration_kill()
    measure_reachability()
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
