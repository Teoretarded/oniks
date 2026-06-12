"""Spawn zone placement contracts (world/spawn_zones.py)."""

import math

import numpy as np
import pytest

from world.generation import BASE_POS
from world.spawn_zones import (CARRIER_RANGE_MAX_M, CARRIER_RANGE_MIN_M,
                               MIN_SEPARATION_M, ZONE_HALF_ANGLE_DEG,
                               ZONE_RANGE_MAX_M, ZONE_RANGE_MIN_M,
                               is_open_water, sample_fleet)

BASE = (float(BASE_POS[0]), float(BASE_POS[2]))


def fleet(seed=1337, n=10):
    return sample_fleet(np.random.default_rng(seed), n)


def hulls(f):
    return [f["carrier"], *f["destroyers"]]


def rng_bearing(p):
    dx, dz = p[0] - BASE[0], p[1] - BASE[1]
    return math.hypot(dx, dz), abs(math.degrees(math.atan2(dx, dz)))


def test_deterministic_per_seed():
    assert fleet(7) == fleet(7)
    assert fleet(7) != fleet(8)


def test_ten_ship_fleet_fits_with_separation():
    f = fleet(n=10)
    pts = hulls(f)
    assert len(f["destroyers"]) == 10
    for i, p in enumerate(pts):
        for q in pts[i + 1:]:
            assert math.hypot(p[0] - q[0], p[1] - q[1]) >= MIN_SEPARATION_M


def test_every_hull_in_open_water_and_inside_the_sector():
    for seed in (1, 2, 3, 1337):
        for p in hulls(fleet(seed, n=6)):
            assert is_open_water(*p)
            rng_m, brg = rng_bearing(p)
            assert brg <= ZONE_HALF_ANGLE_DEG + 12.0   # escorts ring out a bit
            assert rng_m <= CARRIER_RANGE_MAX_M + 36_000.0


def test_carrier_sits_in_the_deep_band():
    for seed in (1, 2, 3, 1337):
        rng_m, _ = rng_bearing(fleet(seed)["carrier"])
        assert CARRIER_RANGE_MIN_M <= rng_m <= CARRIER_RANGE_MAX_M


def test_escorts_hug_the_carrier_and_screen_stays_in_zone():
    f = fleet(n=8)
    cx, cz = f["carrier"]
    escorts = f["destroyers"][:2]
    for p in escorts:
        assert 20_000.0 <= math.hypot(p[0] - cx, p[1] - cz) <= 35_000.0
    for p in f["destroyers"][2:]:
        rng_m, _ = rng_bearing(p)
        assert ZONE_RANGE_MIN_M <= rng_m <= ZONE_RANGE_MAX_M


def test_range_density_peaks_in_the_middle_band():
    """The triangular draw: over many seeds, the 150-230 km middle band
    holds more screen hulls than the near and far tails combined edges.
    Two-sided so the shape cannot silently flatten or spike."""
    rng = np.random.default_rng(42)
    ranges = []
    for _ in range(40):
        f = sample_fleet(rng, 6)
        for p in f["destroyers"][2:]:
            ranges.append(rng_bearing(p)[0])
    mid = sum(1 for r in ranges if 150_000.0 <= r <= 230_000.0)
    frac = mid / len(ranges)
    assert 0.45 <= frac <= 0.85, f"middle-band fraction {frac:.2f}"
