"""Task RTG: mid-flight retargeting + Oniks terminal-profile accuracy
(GL-free, normative: docs/research/oniks_reference.md flight-profile section).

Covers: Missile.retarget gates (allowed in CLIMB/CRUISE/DESCENT before the
terminal seeker hunts, refused after), route rebuild + close-range cruise
rescale from the CURRENT position, DESCENT re-climb on a long new leg,
in-flight waypoint append/clear, the SAM target swap (BOOST/MIDCOURSE only)
with contact closure via WorldState.retarget_sam, the skim-capture window
(at skim altitude 50-75 km out — the seeker fix window) and the terminal
evasive weave (S-curve cross-track 150-250 m inside 12 km, gone by 1.5 km,
deterministic phase per salvo ordinal) that must not cost a hit.
"""

import math

import numpy as np
import pytest

from sim.aircraft import AC_ALIVE, AC_FALLING, Aircraft
from sim.arsenal import ONIKS, S300
from sim.damage import apply_missile_hits
from sim.missile import (Missile, PH_BOOST, PH_CLIMB, PH_CRUISE, PH_DESCENT,
                         PH_TERMINAL, SKIM_CAPTURE_RANGE, WEAVE_END_RANGE,
                         WEAVE_RANGE)
from sim.sam import SPH_MIDCOURSE, SPH_TERMINAL, SamMissile
from sim.ships import ST_ALIVE, ST_BURNING, ST_SINKING, Ship
from world.world import WorldState

DT = 1.0 / 120.0


class _World:   # minimal stub: open ocean
    ships = []

    def terrain_height_at(self, x, z):
        return -50.0


class _WorldWithShips(_World):
    def __init__(self, ships):
        self.ships = ships


def _launch(profile="hi-lo", target=(0.0, 0.0, 200_000.0), waypoints=(),
            salvo=0):
    return Missile(ONIKS, np.array([0.0, 60.0, 0.0]), heading=0.0,
                   profile=profile, target_point=np.array(target),
                   waypoints=waypoints, salvo=salvo)


def _fly_until(m, w, pred, t_max):
    while m.alive and m.t < t_max:
        m.update(DT, w)
        if pred(m):
            return True
    return False


# --- retarget gates ------------------------------------------------------------

def test_retarget_refused_through_launch_phases():
    """The launch cinematic is not steerable: EJECT through BOOST refuse."""
    m = _launch()
    w = _World()
    new = np.array([50_000.0, 0.0, 50_000.0])
    tp0 = m.target_point.copy()
    route0 = list(m.route)
    while m.phase != PH_CLIMB:                 # EJECT/RIDEOUT/PITCHOVER/BOOST
        assert m.retarget(new) is False
        assert np.array_equal(m.target_point, tp0)
        assert m.route == route0
        m.update(DT, w)
    assert m.retarget(new) is True             # CLIMB: now allowed


def test_retarget_rebuilds_route_and_rescales_cruise_mid_cruise():
    m = _launch(target=(0.0, 0.0, 250_000.0))
    w = _World()
    assert _fly_until(m, w, lambda m: m.phase == PH_CRUISE, 120.0)
    assert m.cruise_alt == ONIKS.cruise_alt_hi          # long leg: full alt
    # Retarget to a close point west: route rebuilt from CURRENT position,
    # the close-range rule rescales the commanded cruise altitude down.
    new = np.array([-60_000.0, 0.0, float(m.pos[2])])
    assert m.retarget(new, new_waypoints=((-20_000.0, float(m.pos[2])),)) is True
    assert m.route == [(-20_000.0, float(m.pos[2])),
                       (-60_000.0, float(m.pos[2]))]
    assert np.array_equal(m.target_point, new)
    assert m.cruise_alt < ONIKS.cruise_alt_hi           # ~60 km leg rescales
    assert m.cruise_alt >= ONIKS.lo_alt


@pytest.mark.slow
def test_retarget_in_descent_reclimbs_on_long_new_leg():
    m = _launch(target=(0.0, 0.0, 250_000.0))
    w = _World()
    assert _fly_until(m, w, lambda m: m.phase == PH_DESCENT, 400.0)
    # Fly a real chunk of the letdown first (2026-07-05 energy re-pin):
    # retargeting at the exact TOP of the descent left alt0 == cruise_alt,
    # so "climbs above alt0" hinged on float noise around 14000.0 — from
    # 12 km the re-climb is a real, measurable contract.
    assert _fly_until(m, w, lambda m: float(m.pos[1]) < 12_000.0, 400.0)
    alt0 = float(m.pos[1])
    assert m.retarget(np.array([0.0, 0.0, 480_000.0])) is True
    assert m.phase == PH_CLIMB                          # re-climb, not dive
    assert m.cruise_alt == ONIKS.cruise_alt_hi          # full profile again
    for _ in range(int(20.0 / DT)):
        m.update(DT, w)
    assert m.alive and float(m.pos[1]) > alt0           # actually climbing


@pytest.mark.slow
def test_e2e_retarget_mid_cruise_hits_new_ship():
    """Plan TDD: redirect a cruising round onto a second ship; the original
    target sails on untouched."""
    lane_a = [(-40_000.0, 180_000.0), (40_000.0, 180_000.0)]
    lane_b = [(25_000.0, 140_000.0), (-35_000.0, 140_000.0)]
    ship_a = Ship("a", "cargo", lane_a, 0.45)
    ship_b = Ship("b", "cargo", lane_b, 0.30)
    w = _WorldWithShips([ship_a, ship_b])
    stale = ship_a.pos + ship_a.velocity() * 40.0
    m = Missile(ONIKS, np.array([0.0, 60.0, 0.0]), 0.0, "hi-lo",
                target_point=np.array([stale[0], 0.0, stale[2]]))
    retargeted = False
    for _ in range(int(700 / DT)):
        m.update(DT, w)
        ship_a.update(DT)
        ship_b.update(DT)
        apply_missile_hits([m], [ship_a, ship_b], [])
        if not retargeted and m.phase == PH_CRUISE:
            est = ship_b.pos + ship_b.velocity() * 30.0     # stale-ish contact
            assert m.retarget(np.array([est[0], 0.0, est[2]])) is True
            retargeted = True
        if not m.alive:
            break
    assert retargeted
    assert ship_b.state in (ST_BURNING, ST_SINKING)     # the NEW ship is hit
    assert ship_a.state == ST_ALIVE                     # original untouched


@pytest.mark.slow
def test_retarget_refused_after_lock_still_kills_original():
    """Plan TDD: once the terminal seeker is locked the round is COMMITTED —
    retarget refuses, state stays, the original ship still dies."""
    lane = [(-40_000.0, 180_000.0), (40_000.0, 180_000.0)]
    ship = Ship("c1", "cargo", lane, 0.45)
    w = _WorldWithShips([ship])
    stale = ship.pos + ship.velocity() * 40.0
    m = Missile(ONIKS, np.array([0.0, 60.0, 0.0]), 0.0, "hi-lo",
                target_point=np.array([stale[0], 0.0, stale[2]]))
    refused = False
    for _ in range(int(700 / DT)):
        m.update(DT, w)
        ship.update(DT)
        apply_missile_hits([m], [ship], [])
        if not refused and m.locked_ship is not None:
            tp0 = m.target_point.copy()
            route0 = [tuple(p) for p in m.route]
            phase0 = m.phase
            assert m.retarget(np.array([-80_000.0, 0.0, 80_000.0])) is False
            assert np.array_equal(m.target_point, tp0)   # state unchanged
            assert [tuple(p) for p in m.route] == route0
            assert m.phase == phase0
            refused = True
        if not m.alive:
            break
    assert refused
    assert ship.state in (ST_BURNING, ST_SINKING)       # still kills original


# --- in-flight waypoint edits ----------------------------------------------------

def test_inflight_waypoint_append_and_clear():
    m = _launch("lo-lo", target=(0.0, 0.0, 200_000.0))
    w = _World()
    assert m.append_waypoint((5_000.0, 30_000.0)) is False   # launch: refused
    assert _fly_until(m, w, lambda m: m.phase == PH_CRUISE, 60.0)
    tgt = m.route[-1]
    assert m.append_waypoint((5_000.0, 30_000.0)) is True
    assert m.route[-2] == (5_000.0, 30_000.0)
    assert m.route[-1] == tgt                       # final target kept last
    while len(m.route) - 1 < 8:                     # fill to the cap of 8
        assert m.append_waypoint((6_000.0, 40_000.0)) is True
    assert m.append_waypoint((7_000.0, 50_000.0)) is False   # cap: refused
    assert len(m.route) - 1 == 8
    assert m.clear_route_waypoints() is True
    assert m.route == [tgt]                         # only the target remains


# --- SAM retarget -----------------------------------------------------------------

def _patrol(rng_m, z0=0.0, ident="air_t"):
    return Aircraft(ident, "patrol", (-rng_m, z0), (-rng_m + 16_000.0,
                                                    z0 + 70_000.0))


def test_sam_retarget_midcourse_kills_second_aircraft():
    ac_a = _patrol(60_000.0, ident="a")
    ac_b = _patrol(70_000.0, z0=15_000.0, ident="b")
    m = SamMissile(S300, np.array([0.0, 5.0, 0.0]), ac_a)
    w = _World()
    swapped = False
    t = 0.0
    while m.alive and t < 120.0:
        ac_a.update(DT)
        ac_b.update(DT)
        m.update(DT, w)
        t += DT
        if not swapped and m.phase == SPH_MIDCOURSE:
            assert m.retarget(ac_b) is True
            assert m.target is ac_b
            swapped = True
    assert swapped
    assert ac_b.state == AC_FALLING                 # the new target dies
    assert ac_a.state == AC_ALIVE                   # the old one flies on


def test_sam_retarget_refused_in_terminal():
    ac_a = _patrol(60_000.0, ident="a")
    ac_b = _patrol(60_000.0, z0=20_000.0, ident="b")
    m = SamMissile(S300, np.array([0.0, 5.0, 0.0]), ac_a)
    w = _World()
    t = 0.0
    while m.alive and m.phase != SPH_TERMINAL and t < 120.0:
        ac_a.update(DT)
        ac_b.update(DT)
        m.update(DT, w)
        t += DT
    assert m.phase == SPH_TERMINAL
    assert m.retarget(ac_b) is False                # COMMITTED
    assert m.target is ac_a                         # swap did not happen


def test_world_retarget_sam_swaps_contact_closure():
    """WorldState.retarget_sam: validates a live air track, swaps the target
    aircraft AND rebuilds the contact-estimate closure onto the new id."""
    ws = WorldState()
    ws.step(DT)
    m = ws.launch_sam("air_patrol_00")
    assert m is not None
    m.phase = SPH_MIDCOURSE                         # eligible window
    assert ws.retarget_sam(m, "cargo_00") is False  # surface track: refused
    assert ws.retarget_sam(m, "bogus") is False
    assert ws.retarget_sam(m, "air_patrol_01") is True
    new_target = next(a for a in ws.aircraft if a.aircraft_id == "air_patrol_01")
    assert m.target is new_target
    est_pos, _ = m.contact_estimate_fn()
    board_est = ws.contacts.estimated_pos("air_patrol_01", ws.sim_time)
    assert np.allclose(est_pos, board_est)          # closure follows the NEW id
    m.phase = SPH_TERMINAL
    assert ws.retarget_sam(m, "air_patrol_02") is False   # committed


# --- Oniks profile accuracy: skim capture window ----------------------------------

@pytest.mark.slow
def test_skim_capture_50_to_75km_out():
    """Plan: descent is timed so the missile is AT skim altitude 50-75 km
    from the target (SKIM_CAPTURE_RANGE = 60 km) — the seeker fix window."""
    assert 50_000.0 <= SKIM_CAPTURE_RANGE <= 75_000.0
    target = np.array([0.0, 0.0, 250_000.0])
    m = _launch(target=tuple(target))
    w = _World()
    capture_d = None
    for _ in range(int(900 / DT)):
        m.update(DT, w)
        if (capture_d is None and m.phase in (PH_DESCENT, PH_TERMINAL)
                and float(m.pos[1]) <= ONIKS.skim_alt + 8.0):
            capture_d = math.hypot(float(m.pos[0]) - target[0],
                                   float(m.pos[2]) - target[2])
        if not m.alive:
            break
    assert capture_d is not None
    assert 50_000.0 <= capture_d <= 75_000.0


# --- Oniks profile accuracy: terminal evasive weave --------------------------------

def test_terminal_weave_excursion_then_clean_finish():
    """Plan TDD: cross-track S-curve excursion 150-250 m inside the 12 km
    window, tapered out by 1.5 km, and the missile still hits within the
    existing tolerance."""
    assert WEAVE_RANGE == 12_000.0 and WEAVE_END_RANGE == 1_500.0
    target = np.array([0.0, 0.0, 90_000.0])
    m = _launch("lo-lo", target=tuple(target))
    w = _World()
    max_cross = 0.0
    finish_cross = 0.0
    for _ in range(int(220 / DT)):
        m.update(DT, w)
        d = math.hypot(float(m.pos[0]) - target[0],
                       float(m.pos[2]) - target[2])
        x = abs(float(m.pos[0]))                    # straight shot: |x| = cross
        if WEAVE_END_RANGE < d < WEAVE_RANGE:
            max_cross = max(max_cross, x)
        elif d <= 1_200.0:
            finish_cross = max(finish_cross, x)
        if not m.alive:
            break
    assert not m.alive and m.impact_pos is not None
    assert np.linalg.norm(m.impact_pos[[0, 2]] - target[[0, 2]]) < 600.0
    assert 150.0 <= max_cross <= 250.0              # the jinks happened
    assert finish_cross < 40.0                      # ... and were gone by 1.5 km


def test_weave_phase_deterministic_per_salvo():
    a = _launch(salvo=2)
    b = _launch(salvo=2)
    c = _launch(salvo=3)
    assert a.weave_phi == b.weave_phi               # same ordinal: same phase
    assert a.weave_phi != c.weave_phi               # next round desyncs


def test_world_launch_assigns_salvo_ordinals():
    """WorldState.launch feeds the weave phase a fresh ordinal per round so
    a salvo does not jink in formation."""
    ws = WorldState()
    m1 = ws.launch("hi-lo", np.array([0.0, 0.0, 100_000.0]))
    ws.reload_left = 0.0
    m2 = ws.launch("hi-lo", np.array([0.0, 0.0, 100_000.0]))
    assert m1 is not None and m2 is not None
    assert m1.weave_phi != m2.weave_phi


@pytest.mark.slow
def test_weaving_flight_bit_deterministic():
    runs = []
    for _ in range(2):
        m = _launch("lo-lo", target=(0.0, 0.0, 60_000.0), salvo=1)
        w = _World()
        while m.alive and m.t < 200.0:
            m.update(DT, w)
        runs.append(m.impact_pos.copy())
    assert runs[0] is not None and np.array_equal(runs[0], runs[1])
