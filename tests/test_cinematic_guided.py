"""Universal T-targeting contracts: guided pad rounds fly to the mark.

Headless, GL-free, synthetic terrain.  The flight computer is
piecewise drag-aware Lambert with terrain gates and a bit-exact
verification pass (game/cinematic_missiles.GuidedLaunch, 2026-07-17
user order: every non-MANPADS round flies to the T-mark on the best
possible FASTEST route).
"""

from __future__ import annotations

import math

import numpy as np

from game.cinematic_missiles import GuidedLaunch, VARIANT_BY_ID, VARIANTS

DT = 1.0 / 120.0
PAD = (0.0, 500.0, 0.0)


def _flat(x, z):
    return 500.0


def _wall(x, z):
    """A 1500 m ridge crossing the route at x ~ 6000."""
    return 500.0 + 1500.0 * math.exp(-((x - 6000.0) / 900.0) ** 2)


def _fly(m, max_s=600.0):
    events = []
    for _ in range(int(max_s / DT)):
        if m.done:
            break
        ev: list = []
        m.step(DT, ev)
        events.extend(ev)
    return events


def test_guided_hits_flat_mark_fast():
    """8 km flat shot: dead on the mark, well under a minute."""
    v = VARIANT_BY_ID["48n6"]
    m = GuidedLaunch(v, PAD, 0.7, 9.1, (8000.0, 0.0, 2000.0), _flat)
    assert m.feasible
    evs = _fly(m)
    imp = [p for k, p in evs if k == "impact"]
    assert imp and m.impacted
    assert math.hypot(imp[0][0] - 8000.0, imp[0][2] - 2000.0) <= 25.0
    assert m.t <= 60.0                     # FAST, not a loiter
    assert m.t >= 5.0


def test_guided_gates_over_a_ridge():
    """Mark behind a 1500 m wall: the round must clear the crest and
    still land on the mark (two-sided: no wall clip, no silly loft)."""
    v = VARIANT_BY_ID["48n6"]
    m = GuidedLaunch(v, PAD, 0.7, 9.1, (14000.0, 0.0, 0.0), _wall)
    assert m.feasible
    max_y_at_wall = -1e9
    apex = -1e9
    events = []
    for _ in range(int(600.0 / DT)):
        if m.done:
            break
        ev: list = []
        m.step(DT, ev)
        events.extend(ev)
        apex = max(apex, float(m.pos[1]))
        if 5200.0 <= m.pos[0] <= 6800.0:
            max_y_at_wall = max(max_y_at_wall, float(m.pos[1]))
    imp = [p for k, p in events if k == "impact"]
    assert imp and m.impacted
    assert math.hypot(imp[0][0] - 14000.0, imp[0][2]) <= 25.0
    assert max_y_at_wall >= 2000.0 + 40.0  # over the crest, not through
    assert apex <= 30_000.0                # ...and not via the stratosphere


def test_guided_refuses_beyond_range():
    """A 5V55 (75 km book range) at 100 km: honest refusal, no round."""
    v = VARIANT_BY_ID["5v55"]
    m = GuidedLaunch(v, PAD, 0.7, 9.1, (100_000.0, 0.0, 0.0), _flat)
    assert not m.feasible


def test_guided_is_deterministic():
    def run():
        m = GuidedLaunch(VARIANT_BY_ID["9m96"], PAD, 0.7, 9.1,
                         (12000.0, 0.0, -3000.0), _flat)
        _fly(m)
        return m.pos.copy(), m.t
    (p1, t1), (p2, t2) = run(), run()
    assert np.array_equal(p1, p2) and t1 == t2


def test_every_variant_reaches_a_valley_mark():
    """All four pad rounds accept T-targeting (universal, not 48N6-only)."""
    for v in VARIANTS:
        m = GuidedLaunch(v, PAD, 0.7, 9.1, (9000.0, 0.0, 4000.0), _flat)
        assert m.feasible, v.id
        evs = _fly(m)
        imp = [p for k, p in evs if k == "impact"]
        assert imp and m.impacted, v.id
        assert math.hypot(imp[0][0] - 9000.0,
                          imp[0][2] - 4000.0) <= 25.0, v.id
