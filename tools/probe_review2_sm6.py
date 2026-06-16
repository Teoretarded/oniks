"""REVIEW 2 / check (c): SM-6 engages HIGH inbound cruise missiles, ignores low.
Plus check (e) over-saturation: SM-6 rounds fired per target across the fleet.

Drives ShipDefense directly (same harness shape as tests/test_sm6_area_defense)
with controlled tracks, and ALSO runs a fleet-level saturation sweep: many ships,
one high target, count total SM-6 rounds committed to it.

  C1 high inbound (14 km, 100 km out)  -> SM-6 engages.
  C2 low sea-skimmer (50 m, 60 km out) -> SM-6 does NOT engage.
  C3 sensor-only (silent radar)        -> no track -> no SM-6.
  C4 (saturation) one high target vs the whole fleet: total SM-6 rounds and
     rounds-per-ship; flag gross over-commit.

Run: python tools/probe_review2_sm6.py
"""
import math
import os
import sys
import types

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sim.arsenal import SM6
from sim.enemy_defense import (ShipDefense, TRACK_FORM_S, VIS_CHECK_PERIOD,
                               SM6_MAX_INFLIGHT, SM6_AREA_MIN_ALT_M,
                               SM6_MIN_RANGE_M)
from sim.enemy_ships import Destroyer
from sim.sam import SamMissile
from world.combat import CombatWorld
from world.combat_config import CombatConfig

DT = 1.0 / 120.0


class _Missile:
    def __init__(self, pos, vel):
        self.pos = np.array(pos, dtype=np.float64)
        self.vel = np.array(vel, dtype=np.float64)
        self.alive = True


def _ship():
    w = CombatWorld(CombatConfig(seed=7))
    ship = next(s for s in w.ships if isinstance(s, Destroyer))
    ship.sm6_ammo = 8
    ship.sm6_reload_timer = 0.0
    ship.sm2_ammo = 24
    ship.sm2_reload_timer = 0.0
    return ship


def _form_and_fire(defense, missile, ship):
    world = types.SimpleNamespace(missiles=[missile], sim_time=0.0, drone=None)
    t = 0.0
    while t <= TRACK_FORM_S + VIS_CHECK_PERIOD + 0.1:
        defense._update_tracks([missile], t, DT)
        t += DT
    world.sim_time = t
    defense._try_sm6_launch(world, t)
    return [r for r in world.missiles
            if isinstance(r, SamMissile) and r.weapon is SM6]


def run():
    results = {}

    # ---- C1: high inbound -> engages -----------------------------------------
    ship = _ship()
    d = ShipDefense(ship, np.random.default_rng(1))
    sx, sz = float(ship.pos[0]), float(ship.pos[2])
    m = _Missile((sx, 14_000.0, sz - 100_000.0), (0.0, 0.0, 250.0))
    r = _form_and_fire(d, m, ship)
    results["C1"] = len(r) == 1
    print(f"C1 high inbound (14km,100km): SM-6 fired={len(r)} "
          f"-> {'PASS' if results['C1'] else 'FAIL'}")

    # ---- C2: low sea-skimmer -> ignores --------------------------------------
    ship = _ship()
    d = ShipDefense(ship, np.random.default_rng(2))
    sx, sz = float(ship.pos[0]), float(ship.pos[2])
    m = _Missile((sx, 50.0, sz - 60_000.0), (0.0, 0.0, 250.0))
    r = _form_and_fire(d, m, ship)
    results["C2"] = len(r) == 0
    print(f"C2 low sea-skimmer (50m,60km): SM-6 fired={len(r)} "
          f"-> {'PASS (ignored)' if results['C2'] else 'FAIL (poached low)'}")

    # ---- C3: sensor-only (silent radar) --------------------------------------
    ship = _ship()
    ship.radar.emitting = False
    d = ShipDefense(ship, np.random.default_rng(3))
    sx, sz = float(ship.pos[0]), float(ship.pos[2])
    m = _Missile((sx, 14_000.0, sz - 100_000.0), (0.0, 0.0, 250.0))
    r = _form_and_fire(d, m, ship)
    results["C3"] = len(r) == 0
    print(f"C3 silent radar (no track): SM-6 fired={len(r)} "
          f"-> {'PASS (no-cheat)' if results['C3'] else 'FAIL'}")

    # ---- C4: fleet saturation on ONE high target -----------------------------
    # Each ship runs its own ShipDefense; how many SM-6 does the WHOLE fleet
    # commit to a single high inbound over a sustained window? SM6_MAX_INFLIGHT
    # caps per-ship in-flight, but there is no cross-ship coordination, so N
    # ships can each throw SM6_MAX_INFLIGHT at the same track.
    w = CombatWorld(CombatConfig(seed=7))
    ships = [s for s in w.ships if isinstance(s, Destroyer)]
    for s in ships:
        s.sm6_ammo = 8
        s.sm6_reload_timer = 0.0
    defenses = [ShipDefense(s, np.random.default_rng(10 + i))
                for i, s in enumerate(ships)]
    # One high inbound aimed at the fleet centroid.
    cx = float(np.mean([s.pos[0] for s in ships]))
    cz = float(np.mean([s.pos[2] for s in ships]))
    tgt = _Missile((cx, 16_000.0, cz - 120_000.0), (0.0, 0.0, 250.0))
    world = types.SimpleNamespace(missiles=[tgt], sim_time=0.0, drone=None)
    t = 0.0
    total_window = TRACK_FORM_S + 60.0   # form + 60 s of engagement
    while t <= total_window:
        # Move the target slowly inbound so it stays in the high band & in range.
        tgt.pos = tgt.pos + tgt.vel * DT
        for dfn in defenses:
            dfn._update_tracks([tgt], t, DT)
        if t >= TRACK_FORM_S:
            world.sim_time = t
            for dfn in defenses:
                # mirror ShipDefense.step pruning of dead inflight
                dfn._sm6_inflight = [(s, k) for s, k in dfn._sm6_inflight
                                     if s.alive]
                dfn._try_sm6_launch(world, t)
        t += DT
    sm6_rounds = [r for r in world.missiles
                  if isinstance(r, SamMissile) and r.weapon is SM6]
    per_ship = {}
    for dfn, s in zip(defenses, ships):
        fired = 8 - s.sm6_ammo
        per_ship[s.ship_id] = fired
    total = len(sm6_rounds)
    n_ships = len(ships)
    # Reasonable: each ship may volley up to its inflight cap then reload-gate.
    # Over 60 s with the reload timer, a handful per ship is expected; gross
    # over-saturation would be the whole fleet emptying 8 each at one target.
    avg = total / max(n_ships, 1)
    c4_reasonable = avg <= 6.0      # not emptying the magazine at one track
    results["C4"] = c4_reasonable
    print(f"C4 fleet saturation: ships={n_ships} total_SM6_at_one_target={total} "
          f"avg/ship={avg:.1f} per_ship={per_ship} inflight_cap={SM6_MAX_INFLIGHT} "
          f"-> {'PASS (bounded)' if c4_reasonable else 'FAIL (over-saturation)'}")

    ok = all(results.values())
    print(f"\n(c)+(e) SM-6 OVERALL: {'PASS' if ok else 'FAIL'}  {results}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run())
