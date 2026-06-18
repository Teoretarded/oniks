"""M5 AirDefenseShip behavior (spec 05 b).

  * an AAW ship sustains MORE concurrent SM-2 than a general destroyer in the
    SAME raid (count rounds in flight) — the higher sm2_max_inflight cap the
    controller reads via getattr;
  * a lo-lo Oniks still LEAKS at the spec band against the AAW ship (the
    sea-skim multipath physics in sim/sam.py is unchanged — a deeper magazine
    does not change the per-shot kill physics; balance guard).
"""

import math

import numpy as np

from sim.arsenal import ONIKS, SM2
from sim.enemy_defense import (SM2_MAX_INFLIGHT, EnemyDefenseController)
from sim.enemy_ship_classes import AirDefenseShip, GeneralDestroyer
from sim.missile import PH_CRUISE, Missile
from sim.sam import SamMissile

DT = 1.0 / 120.0
ANCHOR = (-40_000.0, 320_000.0)     # verified open water (world/combat.py)


class _StubWorld:
    def __init__(self):
        self.missiles = []
        self.events = []
        self.sim_time = 0.0


def _oniks(pos, vel, profile="hi-lo"):
    m = Missile(ONIKS, np.array(pos, dtype=np.float64), 0.0, profile,
                np.array([0.0, 0.0, 0.0]))
    m.vel[:] = vel
    m.prev_pos[:] = m.pos
    m.phase = PH_CRUISE
    return m


def _sams(world):
    return [m for m in world.missiles
            if isinstance(m, SamMissile) and m.weapon is SM2]


def _raid(ship, n_inbound=12):
    """Fan n hi-flying Oniks at the ship from a spread of bearings, then run
    with the fire-control reload zeroed (the in-flight cap is the ONLY gate)
    long enough to saturate it.  Returns the controller's stub world."""
    ctrl = EnemyDefenseController([ship])
    w = _StubWorld()
    for i in range(n_inbound):
        # spread the raid across a shallow arc so tracks are distinct
        ox = ship.pos[0] + (i - n_inbound / 2) * 3_000.0
        w.missiles.append(_oniks((ox, 14_000.0, ANCHOR[1] - 100_000.0),
                                 (0.0, 0.0, 680.0)))
    for _ in range(int(12.0 / DT)):
        w.sim_time += DT
        ship.update(DT)
        ship.sm2_reload_timer = 0.0     # the in-flight cap is the only gate
        ctrl.step(w, DT)
    return w


def test_aaw_sustains_more_concurrent_sm2_than_general():
    """SAME 12-missile raid: the AAW ship has > the general destroyer's
    concurrent SM-2s in flight, and at least matches its own higher cap."""
    gen = GeneralDestroyer("gen", ANCHOR)
    aaw = AirDefenseShip("aaw", ANCHOR)

    w_gen = _raid(gen)
    w_aaw = _raid(aaw)

    n_gen = len(_sams(w_gen))
    n_aaw = len(_sams(w_aaw))

    # The general destroyer is pinned at the LOCKED const.
    assert n_gen == SM2_MAX_INFLIGHT, (
        f"general destroyer should hold {SM2_MAX_INFLIGHT}, got {n_gen}")
    # The AAW ship holds strictly MORE concurrent rounds.
    assert n_aaw > n_gen, (
        f"AAW {n_aaw} not greater than general {n_gen}")
    # And it reaches its own (higher) cap.
    assert n_aaw == aaw.sm2_max_inflight, (
        f"AAW should saturate its {aaw.sm2_max_inflight}-round cap, "
        f"got {n_aaw}")


def test_aaw_inflight_cap_matches_its_def():
    """The cap the controller enforces is the ship's own sm2_max_inflight."""
    aaw = AirDefenseShip("aaw", ANCHOR)
    assert aaw.sm2_max_inflight == 8
    w = _raid(aaw)
    assert len(_sams(w)) == 8


def test_lo_lo_oniks_still_leaks_against_aaw_at_spec_band():
    """Balance guard: the AAW ship's deeper magazine must NOT change the per-
    shot kill physics.  A lo-lo sea-skimmer 100 km out is STILL under the
    radar horizon (no track, no shot) — exactly as against a general
    destroyer.  The multipath physics that makes lo-lo king (sim/sam.py) is
    untouched by the class change."""
    aaw = AirDefenseShip("aaw_lo", ANCHOR)
    gen = GeneralDestroyer("gen_lo", ANCHOR)
    skim = _oniks((ANCHOR[0], 15.0, ANCHOR[1] - 100_000.0),
                  (0.0, 0.0, 680.0), profile="lo-lo")
    # Same horizon truth for both hulls (identical radar / antenna height).
    assert not aaw.radar.detects(skim.pos, "missile")
    assert not gen.radar.detects(skim.pos, "missile")

    ctrl = EnemyDefenseController([aaw])
    w = _StubWorld()
    w.missiles.append(skim)
    for _ in range(int(5.0 / DT)):
        w.sim_time += DT
        aaw.update(DT)
        ctrl.step(w, DT)
    assert _sams(w) == [], "lo-lo skimmer must leak (no SM-2 track at 100 km)"
    assert aaw.sm2_ammo == aaw.CLASS_DEF.sm2_ammo
