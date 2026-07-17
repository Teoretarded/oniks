"""Ammunition-expansion contracts: Trident II water launch, MIRV
dispensing, Iskander-M pad round (docs/research/
ammo_expansion_2026-07-17.md).  Headless, GL-free, flat ground.
"""

from __future__ import annotations

import math

import numpy as np

from game.cinematic_icbm import ICBM_BY_ID, IcbmLaunch, TRIDENT_II
from game.cinematic_missiles import GuidedLaunch, VARIANT_BY_ID

DT = 1.0 / 120.0


def _fly(lch, max_s=900.0):
    events = []
    for _ in range(int(max_s / DT)):
        if lch.done:
            break
        ev: list = []
        lch.step(DT, ev)
        events.extend(ev)
    return events


def test_trident_specs_match_research():
    t = ICBM_BY_ID["trident"]
    assert t.water_launch and t.launch_mode == "cold"
    assert t.length_m == 13.58 and t.diameter_m == 2.11
    assert abs(sum(s.gross_kg for s in t.stages)
               + t.bus_kg + t.bus_prop_kg - 59090) < 5000
    assert t.mirv_count == 8 and t.mirv_yield_kt == 475.0


def test_trident_broaches_then_lands_on_the_mark():
    """Water launch grammar: eject AT the surface, no pallet, no smoke
    ring, ignition ABOVE the water, impact on the mark."""
    lake_y = 560.0
    lch = IcbmLaunch(TRIDENT_II, silo=(0.0, lake_y, 0.0),
                     target=(20000.0, lake_y, 5000.0),
                     ground_h=lambda x, z: lake_y)
    evs = _fly(lch)
    kinds = [k for k, _ in evs]
    assert kinds.count("eject") == 1
    assert "pallet" not in kinds and "smoke_ring" not in kinds
    ej = [p for k, p in evs if k == "eject"][0]
    assert abs(ej[1] - lake_y) < 6.0           # broach at the surface
    ign = [p for k, p in evs if k == "ignite"][0]
    assert 5.0 <= ign[1] - lake_y <= 60.0      # lights over the splash
    imp = [p for k, p in evs if k == "impact"]
    assert imp and math.hypot(imp[0][0] - 20000.0,
                              imp[0][2] - 5000.0) < 150.0


def test_mirv_dispenses_one_rv_per_mark():
    """Sarmat with 4 marks: 4 impacts, each within 300 m of ITS mark,
    per-RV yield reported for cratering."""
    marks = [(20000.0, 0.0, 0.0), (23000.0, 0.0, 2500.0),
             (26000.0, 0.0, -2000.0), (21000.0, 0.0, -4000.0)]
    lch = IcbmLaunch(ICBM_BY_ID["sarmat"], silo=(0.0, 800.0, 0.0),
                     target=marks[0], targets=marks,
                     ground_h=lambda x, z: 800.0)
    evs = _fly(lch, max_s=1200.0)
    kinds = [k for k, _ in evs]
    assert kinds.count("mirv_sep") == 3        # marks 1..3 released
    imps = [p for k, p in evs if k == "impact"]
    assert len(imps) == 4 and lch.done
    for mx, _my, mz in marks:
        best = min(math.hypot(p[0] - mx, p[2] - mz) for p in imps)
        assert best < 300.0, (mx, mz, best)
    assert lch.impact_yield_kt() == 500.0      # per-RV, not the bus


def test_single_mark_flights_unchanged_by_mirv_capacity():
    """A Sarmat fired at ONE mark keeps the legacy grammar (no
    dispensing) and the full single-warhead yield."""
    lch = IcbmLaunch(ICBM_BY_ID["sarmat"], silo=(0.0, 0.0, 0.0),
                     target=(7000.0, 0.0, 2000.0),
                     ground_h=lambda x, z: 0.0)
    evs = _fly(lch, max_s=1200.0)
    kinds = [k for k, _ in evs]
    assert "mirv_sep" not in kinds
    assert kinds.count("impact") == 1
    assert lch.impact_yield_kt() == 800.0


def test_iskander_is_the_fast_flat_pad_round():
    v = VARIANT_BY_ID["iskander"]
    assert v.mass_kg == 3800.0 and v.warhead_kg == 700.0
    m = GuidedLaunch(v, (0.0, 500.0, 0.0), 0.7, 9.1,
                     (30000.0, 0.0, 0.0), lambda x, z: 500.0)
    assert m.feasible
    evs = _fly(m, max_s=300.0)
    imp = [p for k, p in evs if k == "impact"]
    assert imp and m.impacted
    assert math.hypot(imp[0][0] - 30000.0, imp[0][2]) <= 25.0
    assert m.t <= 90.0                         # 30 km in a minute-ish
