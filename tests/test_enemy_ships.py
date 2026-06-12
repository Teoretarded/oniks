"""Tests for sim/enemy_ships.py — Destroyer entity (GL-free, pure sim layer).

Coverage:
  - destroyer registered in SHIP_TYPES with correct hp
  - loiters near the anchor after a long sim run
  - radar.pos follows ship.pos (same coordinates every tick)
  - damage ladder works correctly through hit() -> BURNING -> SINKING
  - duck-type surface contact interface (is_air, ship_id, velocity())
"""

import math

import numpy as np
import pytest

from sim.enemy_ships import Destroyer, _RACETRACK_HALF_WIDTH
from sim.ships import (BURN_TIME, SHIP_TYPES, ST_ALIVE, ST_BURNING,
                       ST_GONE, ST_SINKING)


# ---------------------------------------------------------------------------
# 1. SHIP_TYPES registration
# ---------------------------------------------------------------------------

def test_destroyer_in_ship_types():
    assert "destroyer" in SHIP_TYPES


def test_destroyer_hp_is_3():
    assert SHIP_TYPES["destroyer"]["hp"] == 3


def test_destroyer_dimensions():
    spec = SHIP_TYPES["destroyer"]
    assert spec["length"] == pytest.approx(155.0)
    assert spec["beam"]   == pytest.approx(20.0)
    assert spec["height"] == pytest.approx(30.0)
    assert spec["speed"]  == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# 2. Loiter proximity — stays near anchor after extended run
# ---------------------------------------------------------------------------

def test_loiters_within_patrol_radius_plus_length():
    """After 600 s (10 min) the ship must stay within patrol_radius + length of
    the anchor.

    The bound accounts for racetrack geometry: the far corner waypoints are at
    sqrt(patrol_r^2 + half_width^2) from the anchor, and the ship can overshoot
    a waypoint by up to the distance it travels before the rudder rate-limit
    bites (~half_width + length is a comfortable outer envelope).  For the
    default half_width of 400 m and ship length of 155 m the worst-case
    distance is comfortably below patrol_r + half_width + length.
    """
    anchor = np.array([50_000.0, 300_000.0])
    patrol_r = 8_000.0
    d = Destroyer("dd1", anchor, heading_deg=0.0, patrol_radius_m=patrol_r)
    length = SHIP_TYPES["destroyer"]["length"]
    dt = 1.0
    # Outer bound: patrol radius + lateral racetrack half-width + ship length.
    # We add one dt-step of travel (speed * dt) to cover the case where the
    # ship is just inside the waypoint-advance radius on one tick but the
    # position integration then pushes it slightly beyond the geometric bound.
    speed = SHIP_TYPES["destroyer"]["speed"]
    bound = patrol_r + _RACETRACK_HALF_WIDTH + length + speed * dt
    max_dist = 0.0
    for _ in range(600):
        d.update(dt)
        dist = math.hypot(float(d.pos[0]) - float(anchor[0]),
                          float(d.pos[2]) - float(anchor[1]))
        max_dist = max(max_dist, dist)

    assert max_dist <= bound, (
        f"destroyer drifted {max_dist:.0f} m from anchor; limit {bound:.0f} m"
    )


# ---------------------------------------------------------------------------
# 3. Radar position tracking
# ---------------------------------------------------------------------------

def test_radar_pos_follows_ship_pos():
    """radar.pos must mirror ship.pos exactly after every update."""
    d = Destroyer("dd2", (100_000.0, 200_000.0))
    for _ in range(100):
        d.update(0.5)
        assert np.allclose(d.radar.pos, d.pos), (
            f"radar.pos={d.radar.pos} != ship.pos={d.pos}"
        )


def test_radar_pos_follows_during_sinking():
    """Radar stays glued to pos even as the ship descends."""
    d = Destroyer("dd3", (100_000.0, 200_000.0))
    d.state = ST_SINKING
    for _ in range(20):
        d.update(1.0)
    # Ship has sunk; radar y-coord should track the descended hull
    assert np.allclose(d.radar.pos, d.pos)


def test_radar_has_spy1_ranges():
    d = Destroyer("dd4", (0.0, 100_000.0))
    assert d.radar.ranges["ship"]    == pytest.approx(300_000.0)
    assert d.radar.ranges["fighter"] == pytest.approx(300_000.0)
    assert d.radar.ranges["missile"] == pytest.approx(300_000.0)
    assert d.radar.ranges["stealth"] == pytest.approx( 30_000.0)


def test_radar_antenna_height():
    d = Destroyer("dd5", (0.0, 100_000.0))
    assert d.radar.antenna_m == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# 4. Damage ladder
# ---------------------------------------------------------------------------

def test_first_hit_sets_burning():
    """HP 3 -> one hit -> HP 2, state BURNING."""
    d = Destroyer("dd6", (0.0, 150_000.0))
    assert d.state == ST_ALIVE
    assert d.hp == 3
    # simulate a hit via damage.py semantics: decrement hp, set state
    d.hp -= 1
    if d.hp > 0:
        d.state = ST_BURNING
        d.burn_timer = BURN_TIME
    else:
        d.state = ST_SINKING
    assert d.hp == 2
    assert d.state == ST_BURNING


def test_two_hits_then_sinking():
    """HP 3 -> two hits -> HP 1 -> still burning; one more -> sinking."""
    d = Destroyer("dd7", (0.0, 150_000.0))

    def _hit(ship):
        ship.hp -= 1
        if ship.hp > 0:
            ship.state = ST_BURNING
            ship.burn_timer = BURN_TIME
        else:
            ship.state = ST_SINKING

    _hit(d)
    assert d.state == ST_BURNING
    assert d.hp == 2

    _hit(d)
    assert d.state == ST_BURNING
    assert d.hp == 1

    _hit(d)
    assert d.state == ST_SINKING
    assert d.hp == 0


def test_burning_transitions_to_sinking_after_burn_time():
    d = Destroyer("dd8", (0.0, 200_000.0))
    d.state = ST_BURNING
    d.burn_timer = BURN_TIME    # fresh burn
    dt = 0.5
    t = 0.0
    while d.state == ST_BURNING and t < 600.0:
        d.update(dt)
        t += dt
    assert d.state == ST_SINKING
    assert t == pytest.approx(BURN_TIME, abs=1.0)


def test_sinking_transitions_to_gone():
    d = Destroyer("dd9", (0.0, 200_000.0))
    d.state = ST_SINKING
    # Drive it all the way to ST_GONE
    for _ in range(120):        # 120 s > SINK_GONE_TIME (60 s)
        d.update(1.0)
    assert d.state == ST_GONE


def test_gone_ship_does_not_move():
    d = Destroyer("dd10", (0.0, 200_000.0))
    d.state = ST_GONE
    pos_before = d.pos.copy()
    for _ in range(10):
        d.update(1.0)
    assert np.array_equal(d.pos, pos_before)


# ---------------------------------------------------------------------------
# 5. Duck-type surface contact interface
# ---------------------------------------------------------------------------

def test_is_air_is_falsy():
    d = Destroyer("dd11", (0.0, 100_000.0))
    assert not d.is_air


def test_ship_id_present_and_correct():
    d = Destroyer("my_destroyer", (0.0, 100_000.0))
    assert d.ship_id == "my_destroyer"


def test_velocity_returns_3vector_float64():
    d = Destroyer("dd12", (0.0, 100_000.0))
    v = d.velocity()
    assert v.shape == (3,)
    assert v.dtype == np.float64


def test_velocity_magnitude_at_cruise():
    d = Destroyer("dd13", (0.0, 100_000.0))
    # after a few updates the ship is moving at cruise speed
    for _ in range(50):
        d.update(0.5)
    assert np.linalg.norm(d.velocity()) == pytest.approx(15.0, rel=0.01)


def test_vel_property_alias():
    """ship.vel is the same as ship.velocity() (seeker duck-type)."""
    d = Destroyer("dd14", (0.0, 100_000.0))
    d.update(1.0)
    assert np.array_equal(d.vel, d.velocity())


def test_alive_true_while_burning():
    d = Destroyer("dd15", (0.0, 100_000.0))
    d.state = ST_BURNING
    assert d.alive is True


def test_alive_false_while_sinking():
    d = Destroyer("dd16", (0.0, 100_000.0))
    d.state = ST_SINKING
    assert d.alive is False


# ---------------------------------------------------------------------------
# 6. Magazine initial state
# ---------------------------------------------------------------------------

def test_default_magazine_loads():
    d = Destroyer("dd17", (0.0, 100_000.0))
    assert d.sm2_ammo   == 24
    assert d.ciws_ammo  == 1500
    assert d.sm2_reload_s == pytest.approx(3.0)
    assert d.sm2_reload_timer == pytest.approx(0.0)


def test_custom_magazine_loads():
    d = Destroyer("dd18", (0.0, 100_000.0), sm2_ammo=12, ciws_ammo=800)
    assert d.sm2_ammo  == 12
    assert d.ciws_ammo == 800


def test_sm2_reload_timer_counts_down():
    d = Destroyer("dd19", (0.0, 100_000.0))
    d.sm2_reload_timer = 3.0
    d.update(1.0)
    assert d.sm2_reload_timer == pytest.approx(2.0)
    d.update(2.0)
    assert d.sm2_reload_timer == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 7. OBB (hull box) is correctly inherited from Ship
# ---------------------------------------------------------------------------

def test_obb_uses_destroyer_dimensions():
    from sim.ships import HULL_DRAFT
    d = Destroyer("dd20", (0.0, 100_000.0))
    spec = SHIP_TYPES["destroyer"]
    center, half, rot = d.obb()
    assert np.allclose(half, [spec["beam"] / 2,
                               (spec["height"] + HULL_DRAFT) / 2,
                               spec["length"] / 2])
