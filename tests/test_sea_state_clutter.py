"""F3-P1/P2 sea state + clutter contracts — VERBATIM from
docs/plans/feature_expansion_review_2026-07-06.md §3 (LOCKED; the fixture
helpers are the only additions).  Research: docs/research/sea_clutter.md.
"""

import numpy as np

from sim.radar import Radar


def _spy1(sea_state: int) -> Radar:
    """SPY-1-class fixture for the duel-band contract: 20 m antenna, and a
    30 km missile ring chosen BELOW the ~34 km horizon vs a 15 m skimmer —
    the clutter factor, not the horizon, must set the range ratio."""
    return Radar("spy1_fixture", (0.0, 0.0, 0.0), 20.0,
                 {"missile": 30_000.0, "ship": 200_000.0,
                  "fighter": 150_000.0, "stealth": 25_000.0},
                 height_fn=lambda x, z: 0.0, sea_state=sea_state)


def _detect_range(radar: Radar, target_alt: float) -> float:
    """Bisect the detects() boundary range at the given altitude."""
    lo, hi = 100.0, 400_000.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if radar.detects(np.array([0.0, target_alt, mid]), "missile"):
            lo = mid
        else:
            hi = mid
    return lo


def test_sea_state_default_is_identity():
    from world.ocean import sea_amp_scale
    from sim.clutter import sea_clutter_range_factor
    assert sea_amp_scale(3) == 1.0                      # exact — not approx
    for alt in (2.0, 15.0, 50.0, 200.0, 9_000.0):
        assert sea_clutter_range_factor(3, alt) == 1.0  # exact — not approx


def test_clutter_monotonic_and_bounded():
    from sim.clutter import sea_clutter_range_factor as f
    for alt in (5.0, 15.0, 30.0):
        factors = [f(s, alt) for s in range(10)]
        assert all(a >= b for a, b in zip(factors, factors[1:]))  # non-increasing
        assert all(0.25 <= x <= 1.0 for x in factors)   # never blinds, never boosts


def test_high_altitude_immune_to_clutter():
    from sim.clutter import sea_clutter_range_factor as f
    for s in range(10):
        assert f(s, 9_000.0) == 1.0     # a 9 km fighter is not in sea clutter


def test_sea_skimmer_detection_two_sided():
    # SPY-1-class radar vs a 15 m sea-skimmer: state 6 must cut the
    # detection range meaningfully but not blind the ship.
    r3 = _spy1(sea_state=3)
    r6 = _spy1(sea_state=6)
    d3 = _detect_range(r3, target_alt=15.0)   # bisect the detects() boundary
    d6 = _detect_range(r6, target_alt=15.0)
    assert 0.45 * d3 <= d6 <= 0.85 * d3


def test_sea_state_config_default_unchanged():
    from world.combat_config import CombatConfig
    assert CombatConfig().sea_state == 3


def test_clutter_deeper_is_worse():
    # Curve-shape sanity: at a fixed rough state, a lower target sits
    # deeper in the clutter ridge and is hurt MORE.
    from sim.clutter import sea_clutter_range_factor as f
    for s in (5, 7, 9):
        assert f(s, 5.0) < f(s, 50.0) < f(s, 99.0) < 1.0


def test_sea_amp_scale_monotonic_douglas():
    from world.ocean import sea_amp_scale
    vals = [sea_amp_scale(s) for s in range(10)]
    assert vals[0] == 0.0                               # state 0: glass
    assert all(a < b for a, b in zip(vals, vals[1:]))   # strictly rising
    assert vals[3] == 1.0                               # today, exact
