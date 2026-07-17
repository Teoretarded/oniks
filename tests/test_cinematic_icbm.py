"""ICBM flight core contracts (docs/plans/icbm_cinematic_plan_2026-07-17.md).

Headless, GL-free, flat-ground — the trajectory physics only.  Numbers
trace to docs/research/icbm_reference_2026-07-17.md; contracts are the
plan's verbatim test blocks (BLOCKED > weakened, never edit tolerances).
"""

from __future__ import annotations

import math

import numpy as np

from game.cinematic_icbm import (
    ICBM_BY_ID,
    ICBMS,
    IcbmLaunch,
    MINUTEMAN_III,
    SARMAT,
)

DT = 1.0 / 120.0


def _fly(lch, max_s: float = 900.0, until_event: str | None = None):
    """Step the launch collecting (kind, pos) events."""
    events = []
    steps = int(max_s / DT)
    for _ in range(steps):
        if lch.done:
            break
        evs: list = []
        lch.step(DT, evs)
        events.extend(evs)
        if until_event is not None and any(k == until_event
                                           for k, _ in evs):
            break
    return events


# ----------------------------------------------------------- plan contracts

def test_icbm_specs_match_research():
    mm = ICBM_BY_ID["mm3"]; sar = ICBM_BY_ID["sarmat"]
    assert [s.burn_s for s in mm.stages] == [61.0, 65.0, 61.0]
    assert abs(sum(s.gross_kg for s in mm.stages) + mm.bus_kg - 36030) < 1500
    assert mm.diameter_m == 1.68 and mm.length_m == 18.3
    assert sar.launch_mode == "cold" and mm.launch_mode == "hot"
    assert abs(sar.stages[0].prop_kg - 150000) < 5000
    assert sar.length_m == 35.3 and sar.diameter_m == 3.0


def test_map_scale_shot_is_fast_and_direct():
    """User order 2026-07-17 ('best possible fastest route'): a map-
    scale shot thrust-terminates in stage 1, flies a direct arc — no
    energy-wasting weave (the old GEMS corkscrew swept 5-30 km cross-
    track and read as 'flying off into the distance') — and still
    lands inside the accuracy contract.  Two-sided bounds: fast but
    never terrain-scraping."""
    lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0., 800., 0.),
                     target=(8000., 800., 3000.), ground_h=lambda x, z: 800.)
    tgt = np.array([8000.0, 0.0, 3000.0])
    along = tgt / np.linalg.norm(tgt)
    cross = np.array([along[2], 0.0, -along[0]])
    max_cross = 0.0
    events = []
    steps = int(400.0 / DT)
    for _ in range(steps):
        if lch.done:
            break
        evs: list = []
        lch.step(DT, evs)
        events.extend(evs)
        max_cross = max(max_cross, abs(float(np.dot(lch.pos, cross))))
    assert lch.burnout_t is not None and lch.burnout_t <= 61.0  # S1 term
    assert any(k == "term" for k, _ in events)   # vent ports fired
    imp = [p for k, p in events if k == "impact"]
    assert imp and math.hypot(imp[0][0] - 8000., imp[0][2] - 3000.) < 150.0
    assert lch.t <= 200.0                        # FAST: minutes, not tens
    assert lch.t >= 60.0                         # ...but not a rail gun
    assert max_cross < 1000.0                    # direct: no weave sweep
    assert 3000.0 <= lch.apex_m - 800.0 <= 25_000.0  # a real arc, no scrape


def test_long_shot_stages_naturally_and_lands():
    """When the range demands more delta-v than one stage holds, the
    stack burns through separations exactly as before — full staging
    returns with real ranges (the future globe shots)."""
    lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0., 0., 0.),
                     target=(700_000., 0., 0.), ground_h=lambda x, z: 0.)
    evs = _fly(lch, max_s=1200.)
    kinds = [k for k, _ in evs]
    assert lch.burnout_t is not None and lch.burnout_t > 61.0  # staged
    assert kinds.count("stage") >= 2             # S1 sep + later jettison
    imp = [p for k, p in evs if k == "impact"]
    assert imp and math.hypot(imp[0][0] - 700_000., imp[0][2]) < 300.0


def test_sarmat_cuts_off_at_vg_zero():
    lch = IcbmLaunch(ICBM_BY_ID["sarmat"], silo=(0., 800., 0.),
                     target=(-6000., 800., 5000.), ground_h=lambda x, z: 800.)
    evs = _fly(lch, max_s=1200.)
    assert any(k == "cutoff" for k, _ in evs)  # liquid shutdown happened
    imp = [p for k, p in evs if k == "impact"]
    assert imp and math.hypot(imp[0][0] + 6000., imp[0][2] - 5000.) < 150.0


def test_trajectory_is_deterministic():
    def run():
        lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0., 0., 0.),
                         target=(5000., 0., -4000.),
                         ground_h=lambda x, z: 0.)
        return _fly(lch, max_s=900.), lch.pos.copy()
    (e1, p1), (e2, p2) = run(), run()
    assert np.array_equal(p1, p2) and len(e1) == len(e2)


def test_cold_vs_hot_ignition_altitude():
    sar = IcbmLaunch(ICBM_BY_ID["sarmat"], silo=(0., 100., 0.),
                     target=(7000., 100., 0.), ground_h=lambda x, z: 100.)
    evs = _fly(sar, until_event="ignite")
    ign = [p for k, p in evs if k == "ignite"][0]
    assert 15.0 <= ign[1] - 100.0 <= 40.0      # research: mortar to ~25 m
    mm = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0., 100., 0.),
                    target=(7000., 100., 0.), ground_h=lambda x, z: 100.)
    evs = _fly(mm, until_event="ignite")
    ign = [p for k, p in evs if k == "ignite"][0]
    assert ign[1] - 100.0 < 2.0                # hot: lights in the tube


def test_mm3_emits_smoke_ring_once_at_tube_exit():
    lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0., 0., 0.),
                     target=(6000., 0., 0.), ground_h=lambda x, z: 0.)
    evs = _fly(lch, max_s=20.)
    rings = [p for k, p in evs if k == "smoke_ring"]
    assert len(rings) == 1 and 0.0 <= rings[0][1] <= 25.0


# ------------------------------------------------------- structural checks

def test_event_grammar_and_staging_counts():
    """Hot map shot: door/ignite/smoke_ring + term + ONE stage (the
    jettison at thrust termination).  Cold: door/eject/pallet/ignite +
    cutoff + one stage.  Exactly one boost-end event per flight; impact
    ends both."""
    mm = IcbmLaunch(MINUTEMAN_III, silo=(0., 0., 0.),
                    target=(7000., 0., 2000.), ground_h=lambda x, z: 0.)
    evs = _fly(mm, max_s=900.)
    kinds = [k for k, _ in evs]
    assert kinds.count("door") == 1 and kinds.count("ignite") == 1
    assert kinds.count("term") == 1 and kinds.count("cutoff") == 0
    assert kinds.count("stage") == 1             # stack jettison at term
    assert kinds.count("impact") == 1 and mm.done
    assert "eject" not in kinds and "pallet" not in kinds

    sar = IcbmLaunch(SARMAT, silo=(0., 0., 0.),
                     target=(7000., 0., 2000.), ground_h=lambda x, z: 0.)
    evs = _fly(sar, max_s=1200.)
    kinds = [k for k, _ in evs]
    assert kinds.count("eject") == 1 and kinds.count("pallet") == 1
    assert kinds.count("cutoff") == 1 and kinds.count("term") == 0
    assert kinds.count("stage") == 1
    assert kinds.count("impact") == 1 and sar.done
    assert "smoke_ring" not in kinds


def test_gate_keeps_boost_near_vertical_low_down():
    """Below the gate the missile must climb, not corkscrew (safety +
    the visual truth: GEMS shaping happens at altitude)."""
    lch = IcbmLaunch(MINUTEMAN_III, silo=(0., 0., 0.),
                     target=(8000., 0., 0.), ground_h=lambda x, z: 0.)
    max_tilt = 0.0
    while lch.pos[1] < MINUTEMAN_III.gate_agl_m and not lch.done:
        lch.step(DT, [])
        if lch.pos[1] > 0.0:
            max_tilt = max(max_tilt, math.degrees(
                math.acos(float(np.clip(lch.axis[1], -1.0, 1.0)))))
    assert max_tilt <= 8.0


def test_mass_depletes_monotonically_to_bus():
    lch = IcbmLaunch(MINUTEMAN_III, silo=(0., 0., 0.),
                     target=(6000., 0., 0.), ground_h=lambda x, z: 0.)
    last = lch.mass
    assert abs(last - 36530.0) < 1500.0        # stages + bus + bus prop
    while not lch.done and not lch.rv_only:
        lch.step(DT, [])
        assert lch.mass <= last + 1e-9
        last = lch.mass
    assert lch.mass <= MINUTEMAN_III.bus_kg + MINUTEMAN_III.bus_prop_kg + 1.0


def test_module_is_gl_free():
    import game.cinematic_icbm as mod
    import sys
    assert "OpenGL" not in getattr(mod, "__dict__", {})
    assert not any(m.startswith("OpenGL") for m in sys.modules
                   if "cinematic_icbm" in str(
                       getattr(sys.modules.get(m), "__file__", "")))
