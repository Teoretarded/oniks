"""Spawn zone placement contracts (world/spawn_zones.py)."""

import math

import numpy as np
import pytest

from world.generation import BASE_POS
from world.spawn_zones import (AAW_RANGE_MAX_M, CARRIER_RANGE_MAX_M,
                               CARRIER_RANGE_MIN_M, ESCORT_OFFSET_M,
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


# ===========================================================================
# M5: typed roster (flagship / aaw / ground_attack / transports)
# ===========================================================================

def _all_hulls(f):
    hs = [f["carrier"], *f["aaw"], *f["ground_attack"], *f["general"],
          *f["transports"]]
    if f["flagship"] is not None:
        hs.append(f["flagship"])
    return hs


def test_default_roster_is_byte_identical_to_legacy_destroyers():
    """THE GATE: with NO new classes the typed mixer's draw is bit-for-bit the
    legacy layout — the 'general'/'destroyers' lists equal the legacy
    'destroyers' output for the SAME seed/draw, and every new role is empty.
    (The legacy reference is the SAME function with the new counts at their 0
    defaults, which by construction reproduces the pre-M5 draw sequence.)"""
    f = sample_fleet(np.random.default_rng(1337), 3)
    assert f["flagship"] is None
    assert f["aaw"] == []
    assert f["ground_attack"] == []
    assert f["transports"] == []
    # The back-compat alias mirrors the general list exactly.
    assert f["destroyers"] == f["general"]
    # Re-draw with the new counts explicitly 0 -> identical (no perturbation).
    f0 = sample_fleet(np.random.default_rng(1337), 3,
                      n_flagship=0, n_aaw=0, n_ground_attack=0, n_transports=0)
    assert f0["destroyers"] == f["destroyers"]
    assert f0["carrier"] == f["carrier"]


def test_typed_roster_has_all_keys():
    f = sample_fleet(np.random.default_rng(7), 2, n_flagship=1, n_aaw=2,
                     n_ground_attack=2, n_transports=1)
    for key in ("carrier", "flagship", "aaw", "ground_attack", "general",
                "transports", "destroyers"):
        assert key in f


def test_zero_of_a_role_yields_empty_list():
    f = sample_fleet(np.random.default_rng(3), 4, n_flagship=0, n_aaw=0,
                     n_ground_attack=0)
    assert f["flagship"] is None
    assert f["aaw"] == []
    assert f["ground_attack"] == []
    assert len(f["general"]) == 4


def test_typed_roster_deterministic_per_seed():
    kw = dict(n_flagship=1, n_aaw=2, n_ground_attack=2, n_transports=1)
    a = sample_fleet(np.random.default_rng(9), 3, **kw)
    b = sample_fleet(np.random.default_rng(9), 3, **kw)
    assert a == b
    c = sample_fleet(np.random.default_rng(10), 3, **kw)
    assert a != c


def test_carrier_and_flagship_sit_deep_central():
    """Carrier in its deep band; the flagship rides the carrier escort ring
    (deep-central, near the asset it protects)."""
    for seed in (1, 2, 3, 1337):
        f = sample_fleet(np.random.default_rng(seed), 3, n_flagship=1)
        rng_c, _ = rng_bearing(f["carrier"])
        assert CARRIER_RANGE_MIN_M <= rng_c <= CARRIER_RANGE_MAX_M
        cx, cz = f["carrier"]
        d = math.hypot(f["flagship"][0] - cx, f["flagship"][1] - cz)
        assert ESCORT_OFFSET_M[0] <= d <= ESCORT_OFFSET_M[1], (
            "flagship must ride the carrier's 20-35 km escort ring")


def test_aaw_screens_forward_of_the_carrier():
    """The AAW picket leans toward the player coast (smaller range) — it sits
    forward of the deep carrier band."""
    for seed in (1, 2, 3, 1337):
        f = sample_fleet(np.random.default_rng(seed), 2, n_aaw=3)
        for p in f["aaw"]:
            rng_m, _ = rng_bearing(p)
            assert ZONE_RANGE_MIN_M <= rng_m <= AAW_RANGE_MAX_M
            assert rng_m < CARRIER_RANGE_MIN_M, (
                "AAW picket must sit forward of the carrier band")


def test_transports_sit_rear_in_the_deep_band():
    for seed in (1, 2, 1337):
        f = sample_fleet(np.random.default_rng(seed), 2, n_transports=2)
        for p in f["transports"]:
            rng_m, _ = rng_bearing(p)
            assert CARRIER_RANGE_MIN_M <= rng_m <= CARRIER_RANGE_MAX_M


def test_any_mix_is_open_water_and_separated():
    """Every hull in ANY role mix is open-water + >= 25 km separated."""
    mixes = [
        dict(n_flagship=1, n_aaw=2, n_ground_attack=2, n_transports=1),
        dict(n_flagship=1, n_aaw=4),
        dict(n_ground_attack=4),
        dict(n_aaw=1, n_ground_attack=1, n_transports=2),
    ]
    for seed in (1, 2, 1337):
        for kw in mixes:
            f = sample_fleet(np.random.default_rng(seed), 3, **kw)
            hs = _all_hulls(f)
            for p in hs:
                assert is_open_water(*p)
            for i, p in enumerate(hs):
                for q in hs[i + 1:]:
                    assert math.hypot(p[0] - q[0], p[1] - q[1]) \
                        >= MIN_SEPARATION_M
