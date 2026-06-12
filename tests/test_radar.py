"""sim/radar.py: horizon math, terrain LOS, Radar.detects, RadarNetwork."""

import pytest

from sim.radar import (HORIZON_K, Radar, RadarNetwork, radar_horizon_m,
                       terrain_blocks)


def FLAT(x, z):
    return 0.0


def test_horizon_formula_matches_constant():
    assert radar_horizon_m(100.0, 0.0) == pytest.approx(HORIZON_K * 10.0)
    assert radar_horizon_m(100.0, 10_000.0) == pytest.approx(HORIZON_K * 110.0)
    assert radar_horizon_m(0.0, 0.0) == 0.0
    assert radar_horizon_m(-5.0, 0.0) == 0.0          # clamps, never NaN


def test_terrain_blocks_flat_hill_and_low_hill():
    a, b = (0.0, 120.0, 0.0), (100_000.0, 8_000.0, 0.0)
    assert not terrain_blocks(a, b, height_fn=FLAT)
    # 5 km wall mid-path rises above the climbing sight line: blocked
    hill = lambda x, z: 5_000.0 if 40_000.0 < x < 60_000.0 else 0.0
    assert terrain_blocks(a, b, height_fn=hill)
    # 500 m bump stays below the sight line: clear
    low = lambda x, z: 500.0 if 40_000.0 < x < 60_000.0 else 0.0
    assert not terrain_blocks(a, b, height_fn=low)


def test_terrain_blocks_short_path_never_self_blocks():
    # under 2 sample steps -> no interior samples -> never blocked
    assert not terrain_blocks((0.0, 10.0, 0.0), (1_000.0, 10.0, 0.0),
                              height_fn=lambda x, z: 9_999.0)


RANGES = {"ship": 350_000.0, "fighter": 350_000.0, "stealth": 35_000.0}


def make_radar(**kw):
    kw.setdefault("radar_id", "r0")
    kw.setdefault("pos", (0.0, 100.0, 0.0))      # 100 m coastal hill
    kw.setdefault("antenna_m", 20.0)
    kw.setdefault("ranges", RANGES)
    return Radar(**kw)


def test_detects_high_target_in_range_over_open_water():
    # 150 km out over the ocean at 8 km altitude: in range, above horizon
    r = make_radar()
    assert r.detects((0.0, 8_000.0, 150_000.0), "fighter")


def test_rejects_beyond_class_range_and_unknown_class():
    r = make_radar()
    assert not r.detects((0.0, 8_000.0, 360_000.0), "fighter")  # > 350 km
    assert not r.detects((0.0, 8_000.0, 150_000.0), "no_such")  # range 0
    # stealth class: same target, tiny range -> rejected
    assert not r.detects((0.0, 8_000.0, 150_000.0), "stealth")


def test_sea_skimmer_hides_below_the_horizon():
    # 15 m target at 150 km: horizon ~ 4120*(sqrt(120)+sqrt(15)) ~ 61 km
    r = make_radar()
    assert not r.detects((0.0, 15.0, 150_000.0), "ship")
    assert r.detects((0.0, 15.0, 40_000.0), "ship")     # inside the horizon


def test_dead_or_silent_radar_sees_nothing():
    tgt = (0.0, 8_000.0, 150_000.0)
    r = make_radar(); r.alive = False
    assert not r.detects(tgt, "fighter")
    r = make_radar(); r.emitting = False
    assert not r.detects(tgt, "fighter")


def test_network_is_any_of_and_empty_network_is_blind():
    far = make_radar(radar_id="far", pos=(0.0, 100.0, 100_000.0))
    near_dead = make_radar(radar_id="dead"); near_dead.alive = False
    net = RadarNetwork([near_dead, far])
    assert net.visible((0.0, 8_000.0, 200_000.0), "fighter")
    assert not RadarNetwork([]).visible((0.0, 8_000.0, 0.0), "fighter")
