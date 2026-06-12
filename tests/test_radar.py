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
