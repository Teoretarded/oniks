"""segment-vs-OBB hit tests + warhead application tests."""
import numpy as np
import pytest

from sim.damage import apply_missile_hits, segment_hits_obb
from sim.missile import PH_DEAD
from sim.ships import ST_ALIVE, ST_BURNING, ST_SINKING, Ship

# A cargo-like axis-aligned hull box: beam 28, height 22 + 5 draft, length 180.
_CENTER = np.zeros(3)
_HALF = np.array([14.0, 13.5, 90.0])
_EYE = np.eye(3)


def test_segment_through_obb_center_hits():
    assert segment_hits_obb(np.array([-100.0, 0.0, 0.0]),
                            np.array([100.0, 0.0, 0.0]),
                            _CENTER, _HALF, _EYE)


def test_parallel_segment_50m_abeam_misses():
    assert not segment_hits_obb(np.array([50.0, 0.0, -200.0]),
                                np.array([50.0, 0.0, 200.0]),
                                _CENTER, _HALF, _EYE)


def test_fast_step_tunneling_caught():
    # 12 m apart, BOTH endpoints outside the box, segment clips through the
    # deck-edge corner — a point-sample test would tunnel straight through.
    p0 = np.array([8.0, 15.5, 0.0])      # above the deck (y > 13.5)
    p1 = np.array([16.0, 6.56, 0.0])     # off the side (x > 14)
    assert float(np.linalg.norm(p1 - p0)) == pytest.approx(12.0, abs=0.05)
    assert np.any(np.abs(p0) > _HALF) and np.any(np.abs(p1) > _HALF)
    assert segment_hits_obb(p0, p1, _CENTER, _HALF, _EYE)
    # same 12 m segment shifted fully outside the corner: clean miss
    q0 = np.array([15.0, 16.5, 0.0])
    q1 = np.array([23.0, 7.56, 0.0])
    assert not segment_hits_obb(q0, q1, _CENTER, _HALF, _EYE)


def test_degenerate_point_segment():
    assert segment_hits_obb(np.zeros(3), np.zeros(3), _CENTER, _HALF, _EYE)
    assert not segment_hits_obb(np.array([0.0, 50.0, 0.0]),
                                np.array([0.0, 50.0, 0.0]),
                                _CENTER, _HALF, _EYE)


def test_rotated_obb_respects_heading():
    ship = Ship("w", "warship", [(0.0, 0.0), (10_000.0, 0.0)], 0.5)  # heading east
    c, h, r = ship.obb()
    # crossing the (now north-south) beam through the center: hit
    assert segment_hits_obb(c + np.array([0.0, 0.0, -100.0]),
                            c + np.array([0.0, 0.0, 100.0]), c, h, r)
    # parallel run 50 m north of the hull: miss (half beam is 9.5 m)
    assert not segment_hits_obb(c + np.array([-200.0, 0.0, 50.0]),
                                c + np.array([200.0, 0.0, 50.0]), c, h, r)


class _FakeMissile:
    def __init__(self, p0, p1):
        self.prev_pos = np.asarray(p0, dtype=np.float64)
        self.pos = np.asarray(p1, dtype=np.float64)
        self.alive = True
        self.phase = 5
        self.impact_pos = None


def test_apply_missile_hits_walks_damage_ladder():
    ship = Ship("c", "cargo", [(0.0, 0.0), (0.0, 50_000.0)], 0.5)
    c, _, _ = ship.obb()
    effects = []

    m1 = _FakeMissile(c + np.array([-200.0, 0.0, 0.0]), c + np.array([40.0, 0.0, 0.0]))
    apply_missile_hits([m1], [ship], effects)
    assert not m1.alive and m1.phase == PH_DEAD
    assert np.allclose(m1.impact_pos, (m1.prev_pos + m1.pos) * 0.5)
    assert ship.hp == 1 and ship.state == ST_BURNING
    assert len(effects) == 1 and effects[0][0] == "ship_hit"

    m2 = _FakeMissile(c + np.array([-200.0, 0.0, 0.0]), c + np.array([40.0, 0.0, 0.0]))
    apply_missile_hits([m2], [ship], effects)
    assert not m2.alive
    assert ship.hp == 0 and ship.state == ST_SINKING
    assert len(effects) == 2

    # sinking ships are no longer hittable
    m3 = _FakeMissile(c + np.array([-200.0, 0.0, 0.0]), c + np.array([40.0, 0.0, 0.0]))
    apply_missile_hits([m3], [ship], effects)
    assert m3.alive and len(effects) == 2


def test_apply_missile_hits_clean_miss_changes_nothing():
    ship = Ship("c", "cargo", [(0.0, 0.0), (0.0, 50_000.0)], 0.5)
    effects = []
    m = _FakeMissile(ship.pos + np.array([500.0, 10.0, -200.0]),
                     ship.pos + np.array([500.0, 10.0, 200.0]))
    apply_missile_hits([m], [ship], effects)
    assert m.alive and ship.state == ST_ALIVE and ship.hp == 2 and not effects


def test_apply_missile_hits_skips_dead_missiles():
    ship = Ship("c", "cargo", [(0.0, 0.0), (0.0, 50_000.0)], 0.5)
    c, _, _ = ship.obb()
    m = _FakeMissile(c + np.array([-200.0, 0.0, 0.0]), c + np.array([40.0, 0.0, 0.0]))
    m.alive = False
    effects = []
    apply_missile_hits([m], [ship], effects)
    assert ship.state == ST_ALIVE and ship.hp == 2 and not effects
