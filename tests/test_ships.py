"""Ship lane-following / damage-state tests + ContactBoard (fuzzy contacts) tests."""
import numpy as np
import pytest

from sim.aircraft import Aircraft
from sim.contacts import AIR_UPDATE_PERIODS, ContactBoard, UPDATE_PERIODS
from sim.ships import (BURN_TIME, SHIP_TYPES, ST_ALIVE, ST_BURNING, ST_GONE,
                       ST_SINKING, Ship)


def _dist_to_polyline(p_xz, pts):
    best = np.inf
    for a, b in zip(pts[:-1], pts[1:]):
        a = np.asarray(a, dtype=np.float64)
        ab = np.asarray(b, dtype=np.float64) - a
        t = np.clip(float(np.dot(p_xz - a, ab)) / float(np.dot(ab, ab)), 0.0, 1.0)
        best = min(best, float(np.linalg.norm(a + ab * t - p_xz)))
    return best


# --- spawning -----------------------------------------------------------------

def test_spawn_interpolated_on_lane():
    ship = Ship("s1", "cargo", [(0.0, 0.0), (0.0, 10_000.0)], 0.25)
    assert np.allclose(ship.pos, [0.0, 0.0, 2_500.0])
    assert abs(ship.heading) < 1e-9                       # along lane: due north
    assert ship.state == ST_ALIVE
    assert ship.hp == SHIP_TYPES["cargo"]["hp"]


def test_spawn_reversed_direction_heads_back_down_lane():
    ship = Ship("s1", "tanker", [(0.0, 0.0), (0.0, 10_000.0)], 0.5, direction=-1)
    assert np.allclose(ship.pos, [0.0, 0.0, 5_000.0])
    assert abs(abs(ship.heading) - np.pi) < 1e-9          # due south
    v = ship.velocity()
    assert v[2] < 0.0


# --- lane following ------------------------------------------------------------

def test_velocity_matches_type_speed():
    for ship_type, spec in SHIP_TYPES.items():
        ship = Ship("s", ship_type, [(0.0, 0.0), (0.0, 50_000.0)], 0.1)
        assert np.linalg.norm(ship.velocity()) == pytest.approx(spec["speed"])
        p0 = ship.pos.copy()
        for _ in range(200):
            ship.update(0.5)
        moved = float(np.linalg.norm(ship.pos - p0))
        assert moved == pytest.approx(spec["speed"] * 100.0, rel=0.01)


def test_lane_following_stays_within_200m_of_polyline():
    lane = [(0.0, 0.0), (0.0, 6_000.0), (2_000.0, 12_000.0), (2_000.0, 20_000.0)]
    ship = Ship("s", "cargo", lane, 0.0)
    pts = [np.asarray(p) for p in lane]
    dt = 0.5
    for _ in range(int(2_400 / dt)):                      # ~18 km of a 20.3 km lane
        ship.update(dt)
        d = _dist_to_polyline(ship.pos[[0, 2]], pts)
        assert d <= 200.0, f"ship strayed {d:.1f} m from the lane"


def test_turn_rate_limited_to_1p2_deg_per_s():
    lane = [(0.0, 0.0), (0.0, 5_000.0), (5_000.0, 5_000.0)]  # sharp 90 deg bend
    ship = Ship("s", "warship", lane, 0.0)
    dt = 0.5
    max_step = 0.0
    prev_h = ship.heading
    for _ in range(int(1_200 / dt)):
        ship.update(dt)
        dh = abs((ship.heading - prev_h + np.pi) % (2.0 * np.pi) - np.pi)
        max_step = max(max_step, dh)
        prev_h = ship.heading
    assert max_step <= np.radians(1.2) * dt * 1.0001
    assert max_step > 0.0                                  # it did actually turn


def test_lane_end_reversal_loops():
    ship = Ship("s", "cargo", [(0.0, 0.0), (0.0, 3_000.0)], 0.9)
    dt = 0.5
    for _ in range(int(400 / dt)):                        # reaches the end, U-turns
        ship.update(dt)
    assert ship.state == ST_ALIVE
    assert ship.velocity()[2] < -5.0                       # now sailing back south


# --- damage-state sequence ------------------------------------------------------

def test_burning_moves_at_30_percent_speed():
    ship = Ship("s", "cargo", [(0.0, 0.0), (0.0, 50_000.0)], 0.2)
    ship.state = ST_BURNING
    p0 = ship.pos.copy()
    for _ in range(20):
        ship.update(0.5)
    moved = float(np.linalg.norm(ship.pos - p0))
    assert moved == pytest.approx(0.30 * SHIP_TYPES["cargo"]["speed"] * 10.0, rel=0.02)
    assert np.linalg.norm(ship.velocity()) == pytest.approx(
        0.30 * SHIP_TYPES["cargo"]["speed"])


def test_burning_then_sinking_sequence_timings():
    ship = Ship("s", "cargo", [(0.0, 0.0), (0.0, 50_000.0)], 0.1)
    ship.state = ST_BURNING
    dt = 0.5
    t = 0.0
    while ship.state == ST_BURNING and t < 600.0:
        ship.update(dt)
        t += dt
    assert ship.state == ST_SINKING
    assert t == pytest.approx(BURN_TIME, abs=1.0)

    xz0 = ship.pos[[0, 2]].copy()
    y0 = ship.pos[1]
    for _ in range(int(25.0 / dt)):                        # 25 s into the sinking
        ship.update(dt)
    assert np.allclose(ship.pos[[0, 2]], xz0)              # dead in the water
    assert ship.pos[1] - y0 == pytest.approx(-1.2 * 25.0, abs=0.1)
    assert ship.list_angle == pytest.approx(np.radians(35.0), abs=np.radians(1.0))
    assert ship.state == ST_SINKING

    for _ in range(int(36.0 / dt)):                        # past 60 s total sinking
        ship.update(dt)
    assert ship.state == ST_GONE
    p_gone = ship.pos.copy()
    ship.update(dt)                                        # GONE ships never move
    assert np.array_equal(ship.pos, p_gone)


# --- hull OBB -------------------------------------------------------------------

def test_obb_dimensions_and_orientation():
    ship = Ship("s", "warship", [(0.0, 0.0), (10_000.0, 0.0)], 0.5)  # heading east
    spec = SHIP_TYPES["warship"]
    center, half, rot = ship.obb()
    assert np.allclose(half, [ship.collision_beam / 2,
                              (ship.collision_height + ship.draft) / 2,
                              spec["length"] / 2])
    assert np.allclose(rot @ np.array([0.0, 0.0, 1.0]), [1.0, 0.0, 0.0], atol=1e-9)
    # box spans -draft .. +height around the waterline center
    assert center[1] == pytest.approx(
        (ship.collision_height - ship.draft) / 2)
    assert np.allclose(center[[0, 2]], ship.pos[[0, 2]])


# --- ContactBoard (fuzzy delayed contact picture) --------------------------------

def test_contact_refresh_period_honored_near_base():
    ship = Ship("s1", "cargo", [(0.0, 50_000.0), (0.0, 120_000.0)], 0.0)
    board = ContactBoard((0.0, 0.0))
    board.update([ship], 1.0, 0.0)                         # first sight -> track
    assert "s1" in board.tracks
    p0 = board.tracks["s1"]["pos"].copy()
    t = 0.0
    for _ in range(19):                                    # t = 1 .. 19: stale
        t += 1.0
        ship.update(1.0)
        board.update([ship], 1.0, t)
    assert np.array_equal(board.tracks["s1"]["pos"], p0)
    assert board.tracks["s1"]["age"] == pytest.approx(19.0)
    t += 1.0                                               # t = 20: 50 km < 100 km -> 20 s period
    ship.update(1.0)
    board.update([ship], 1.0, t)
    assert board.tracks["s1"]["age"] == 0.0
    assert np.allclose(board.tracks["s1"]["pos"], ship.pos)


def test_contact_period_longer_far_from_base():
    near = Ship("near", "cargo", [(0.0, 50_000.0), (0.0, 120_000.0)], 0.0)
    mid = Ship("mid", "cargo", [(0.0, 250_000.0), (0.0, 300_000.0)], 0.0)
    far = Ship("far", "cargo", [(0.0, 340_000.0), (0.0, 400_000.0)], 0.0)
    board = ContactBoard((0.0, 0.0))
    board.update([near, mid, far], 1.0, 0.0)
    assert board.tracks["near"]["t_next"] == pytest.approx(UPDATE_PERIODS[0][1])
    assert board.tracks["mid"]["t_next"] == pytest.approx(UPDATE_PERIODS[1][1])
    assert board.tracks["far"]["t_next"] == pytest.approx(UPDATE_PERIODS[2][1])


def test_estimated_pos_dead_reckons_with_velocity():
    ship = Ship("s1", "cargo", [(0.0, 50_000.0), (0.0, 120_000.0)], 0.0)
    board = ContactBoard((0.0, 0.0))
    board.update([ship], 1.0, 0.0)
    t = 0.0
    for _ in range(10):                                    # 10 s of staleness
        t += 1.0
        ship.update(1.0)
        board.update([ship], 1.0, t)
    est = board.estimated_pos("s1", t)
    assert not np.allclose(board.tracks["s1"]["pos"], ship.pos, atol=0.5)  # raw is stale
    assert np.allclose(est, ship.pos, atol=1e-3)           # dead-reckoned is current


def test_sinking_ship_drops_after_one_refresh_cycle():
    ship = Ship("s1", "cargo", [(0.0, 50_000.0), (0.0, 120_000.0)], 0.0)
    board = ContactBoard((0.0, 0.0))
    board.update([ship], 1.0, 0.0)
    ship.state = ST_SINKING
    t = 0.0
    for _ in range(19):                                    # still tracked until refresh
        t += 1.0
        board.update([ship], 1.0, t)
    assert "s1" in board.tracks
    t += 1.0
    board.update([ship], 1.0, t)                           # refresh at t=20 -> dropped
    assert "s1" not in board.tracks


# --- air contacts (Task S1: aircraft on the same board) ---------------------------

def _aircraft(z0, aircraft_id):
    """Patrol racetrack starting at (0, z0): range from a (0,0) base ~= z0."""
    return Aircraft(aircraft_id, "patrol", (0.0, z0), (16_000.0, z0 + 60_000.0))


def test_air_refresh_periods_faster_than_surface():
    assert AIR_UPDATE_PERIODS == ((100_000, 15.0), (300_000, 30.0), (1e12, 60.0))


def test_air_contact_period_by_range_and_is_air_flag():
    near = _aircraft(50_000.0, "air_near")
    mid = _aircraft(250_000.0, "air_mid")
    far = _aircraft(340_000.0, "air_far")
    ship = Ship("surf", "cargo", [(0.0, 50_000.0), (0.0, 120_000.0)], 0.0)
    board = ContactBoard((0.0, 0.0))
    board.update([ship, near, mid, far], 1.0, 0.0)
    assert board.tracks["air_near"]["t_next"] == pytest.approx(15.0)
    assert board.tracks["air_mid"]["t_next"] == pytest.approx(30.0)
    assert board.tracks["air_far"]["t_next"] == pytest.approx(60.0)
    assert board.tracks["air_near"]["is_air"] is True
    assert board.tracks["surf"]["is_air"] is False
    assert board.tracks["surf"]["t_next"] == pytest.approx(UPDATE_PERIODS[0][1])


def test_air_track_stale_then_refreshes_at_15s():
    ac = _aircraft(50_000.0, "air_1")
    board = ContactBoard((0.0, 0.0))
    board.update([ac], 1.0, 0.0)
    p0 = board.tracks["air_1"]["pos"].copy()
    t = 0.0
    for _ in range(14):                                    # t = 1 .. 14: stale
        t += 1.0
        ac.update(1.0)
        board.update([ac], 1.0, t)
    assert np.array_equal(board.tracks["air_1"]["pos"], p0)
    assert board.tracks["air_1"]["age"] == pytest.approx(14.0)
    t += 1.0                                               # t = 15: 50 km -> 15 s period
    ac.update(1.0)
    board.update([ac], 1.0, t)
    assert board.tracks["air_1"]["age"] == 0.0
    assert np.allclose(board.tracks["air_1"]["pos"], ac.pos)


def test_air_estimated_pos_dead_reckons_in_3d():
    ac = _aircraft(50_000.0, "air_1")
    board = ContactBoard((0.0, 0.0))
    board.update([ac], 1.0, 0.0)
    t = 0.0
    for _ in range(10):                                    # 10 s of staleness
        t += 1.0
        ac.update(1.0)
        board.update([ac], 1.0, t)
    est = board.estimated_pos("air_1", t)
    assert est[1] == pytest.approx(6_500.0)                # altitude carried in 3D
    assert not np.allclose(board.tracks["air_1"]["pos"], ac.pos, atol=0.5)
    assert np.allclose(est, ac.pos, atol=1e-3)             # dead-reckoned is current


def test_falling_aircraft_drops_after_one_refresh_cycle():
    ac = _aircraft(50_000.0, "air_1")
    board = ContactBoard((0.0, 0.0))
    board.update([ac], 1.0, 0.0)
    ac.kill()                                              # AC_FALLING: not trackable
    t = 0.0
    for _ in range(14):                                    # tracked until next refresh
        t += 1.0
        board.update([ac], 1.0, t)
    assert "air_1" in board.tracks
    t += 1.0
    board.update([ac], 1.0, t)                             # refresh at t=15 -> dropped
    assert "air_1" not in board.tracks
