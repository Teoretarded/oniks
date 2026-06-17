"""M3-F1 EW burn-through field model (sim/ew.py).

The keystone EW physics: a jammer raises a victim radar's noise floor so a
target only "burns through" (is detected) inside the burn-through (crossover)
range. Open-source J/S geometry: echo power ~1/R_target^4, barrage-jam power
at the receiver ~1/R_jammer^2, so the jammer wins at long range and the target
burns through up close. Pure, GL-free, DETERMINISTIC — NO RNG anywhere.

The regression contract: ``effective_range(radar, sc, tgt, ())`` is IDENTICAL
to ``radar.ranges.get(sc, 0.0)``, and ``Radar.detects`` / ``RadarNetwork.visible``
with the default ``jammers=()`` are byte-identical to today.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import sim.ew as ew
from sim.radar import Radar, RadarNetwork


# --- representative geometry: the player station's ship ring (~350 km) -------
RADAR_POS = (40_000.0, 0.0, -6_000.0)      # x, y_ground, z (matches world/combat)
RADAR_ANTENNA_M = 18.0
SHIP_RING_M = 350_000.0
PLAYER_RANGES = {
    "ship": SHIP_RING_M, "fighter": SHIP_RING_M,
    "missile": 120_000.0, "stealth": 35_000.0,
}


class _Jammer:
    """Minimal duck-typed jammer: ``.pos`` (3,) and ``.jam_power_w`` (watts)."""

    def __init__(self, pos, jam_power_w):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.jam_power_w = float(jam_power_w)


def _radar():
    return Radar("rt", RADAR_POS, RADAR_ANTENNA_M, dict(PLAYER_RANGES))


def _at_ground_range(rng_m, bearing_rad=0.0, alt_m=0.0):
    """A target position ``rng_m`` ground range from the radar at ``alt_m``."""
    return (
        RADAR_POS[0] + rng_m * math.cos(bearing_rad),
        alt_m,
        RADAR_POS[2] + rng_m * math.sin(bearing_rad),
    )


# ---------------------------------------------------------------------------
# Regression gate: the empty path must not change one bit.
# ---------------------------------------------------------------------------

def test_no_jammer_effective_range_is_max():
    r = _radar()
    tgt = _at_ground_range(100_000.0)
    # effective_range with no jammers == the raw lookup, EXACTLY.
    assert ew.effective_range(r, "ship", tgt, ()) == r.ranges["ship"]
    assert ew.effective_range(r, "fighter", tgt, ()) == r.ranges["fighter"]
    # an absent size class still degrades to the 0.0 lookup default.
    assert ew.effective_range(r, "nonesuch", tgt, ()) == 0.0

    # detects() must be byte-identical across a grid of targets between
    # the legacy call, the explicit empty kwarg, and a fresh-radar baseline.
    for rng in (10_000.0, 200_000.0, 349_000.0, 351_000.0, 500_000.0):
        for bearing in (0.0, 1.0, 2.5, 4.0):
            for alt in (0.0, 8_000.0, 30_000.0):
                t = _at_ground_range(rng, bearing, alt)
                legacy = r.detects(t, "ship")
                explicit = r.detects(t, "ship", jammers=())
                assert legacy == explicit
                # ground-truth: re-derive the legacy gate independently.
                dx = t[0] - RADAR_POS[0]
                dz = t[2] - RADAR_POS[2]
                grng = math.hypot(dx, dz)
                expect = grng <= SHIP_RING_M
                # horizon / terrain may further deny; only assert the
                # range-deny half-plane is honoured identically.
                if grng > SHIP_RING_M:
                    assert legacy is False
                assert (legacy is True) == (explicit is True)


def test_network_empty_jammers_passthrough_identical():
    r = _radar()
    net = RadarNetwork([r])
    for rng in (50_000.0, 200_000.0, 360_000.0):
        t = _at_ground_range(rng, 0.5, 5_000.0)
        assert net.visible(t, "ship") == net.visible(t, "ship", jammers=())
        assert net.visible(t, "ship") == r.detects(t, "ship")


# ---------------------------------------------------------------------------
# The physics: crossover, monotonicity, floor, multi-jammer, LOS gate.
# ---------------------------------------------------------------------------

def test_target_inside_burnthrough_detected_outside_not():
    r = _radar()
    # A standoff jammer well behind the threat axis (opposite bearing so the
    # jammer LOS is clear and far from the target line).
    jx, jz = RADAR_POS[0], RADAR_POS[2] + 150_000.0
    jam = _Jammer((jx, 12_000.0, jz), 200.0)
    bt = ew.burn_through_range(r, _at_ground_range(100_000.0), [jam])
    assert ew.EW_CLOSE_FLOOR_M < bt < SHIP_RING_M  # ring genuinely collapsed

    inside = _at_ground_range(bt - 5_000.0)
    outside = _at_ground_range(bt + 5_000.0, alt_m=20_000.0)  # high to clear horizon
    # effective_range straddles the target: inside <= eff, outside > eff.
    eff = ew.effective_range(r, "ship", inside, [jam])
    assert (bt - 5_000.0) <= eff
    assert ew.effective_range(r, "ship", outside, [jam]) < (bt + 5_000.0)


def test_monotonic_in_jammer_standoff():
    r = _radar()
    tgt = _at_ground_range(80_000.0)
    base = 120_000.0
    near = _Jammer((RADAR_POS[0], 12_000.0, RADAR_POS[2] + base / 2.0), 200.0)
    mid = _Jammer((RADAR_POS[0], 12_000.0, RADAR_POS[2] + base), 200.0)
    far = _Jammer((RADAR_POS[0], 12_000.0, RADAR_POS[2] + base * 2.0), 200.0)
    bt_near = ew.burn_through_range(r, tgt, [near])
    bt_mid = ew.burn_through_range(r, tgt, [mid])
    bt_far = ew.burn_through_range(r, tgt, [far])
    # bigger standoff (jammer farther from radar) -> weaker jam -> target
    # burns through at LONGER range.
    assert bt_near < bt_mid < bt_far
    # halving the standoff lowers it; doubling raises it.
    assert bt_far > 2.0 * 0.0  # sanity; the strict chain above is the real test


def test_close_in_floor_always_detected():
    r = _radar()
    # An absurdly loud jammer sitting right on top of the radar.
    monster = _Jammer((RADAR_POS[0], 50.0, RADAR_POS[2] + 1_000.0), 1.0e9)
    # The RANGE GATE for a close leaker never collapses below the floor, no
    # matter how loud the jammer — even one that would otherwise crush the
    # ring to ~0 (horizon / terrain LOS are separate and unchanged).
    leaker = _at_ground_range(ew.EW_CLOSE_FLOOR_M * 0.5, alt_m=200.0)
    assert ew.effective_range(r, "ship", leaker, [monster]) >= ew.EW_CLOSE_FLOOR_M

    # Behavioural contract: jamming must NEVER deny a close-in detection the
    # radar would make unjammed. Find a close target the radar sees with no
    # jammer (clear LOS, above horizon, inside the floor) and confirm the
    # monster jammer does not remove it.
    seen_unjammed = None
    for bearing in (0.0, 0.7, 1.4, 2.1, 2.8, 3.5, 4.2, 4.9, 5.6):
        cand = _at_ground_range(ew.EW_CLOSE_FLOOR_M * 0.5, bearing, alt_m=400.0)
        if r.detects(cand, "ship"):           # unjammed baseline
            seen_unjammed = cand
            break
    assert seen_unjammed is not None, "no clear close-in target found"
    assert r.detects(seen_unjammed, "ship", jammers=[monster]) is True


def test_multi_jammer_min_burnthrough():
    r = _radar()
    tgt = _at_ground_range(80_000.0)
    quiet = _Jammer((RADAR_POS[0], 12_000.0, RADAR_POS[2] + 200_000.0), 50.0)
    loud = _Jammer((RADAR_POS[0], 12_000.0, RADAR_POS[2] + 120_000.0), 400.0)
    bt_quiet = ew.burn_through_range(r, tgt, [quiet])
    bt_loud = ew.burn_through_range(r, tgt, [loud])
    bt_both = ew.burn_through_range(r, tgt, [quiet, loud])
    # the loudest (smallest burn-through) wins; order must not matter.
    assert bt_both == min(bt_quiet, bt_loud)
    assert ew.burn_through_range(r, tgt, [loud, quiet]) == bt_both


def test_terrain_masked_jammer_does_not_jam():
    r = _radar()
    tgt = _at_ground_range(80_000.0)
    jam = _Jammer((RADAR_POS[0], 12_000.0, RADAR_POS[2] + 120_000.0), 400.0)

    # With clear LOS the ring collapses.
    flat = lambda x, z: -100.0
    bt_clear = ew.burn_through_range(r, tgt, [jam], height_fn=flat)
    assert bt_clear < SHIP_RING_M

    # A wall taller than the jammer/radar sight line between them masks it:
    # the jammer contributes NOTHING, so the ring stays at max. With no
    # effective jammer the crossover is +inf (never collapses) and the
    # user-facing effective_range clamps back to the radar's full ring.
    wall = lambda x, z: 1.0e6
    bt_masked = ew.burn_through_range(r, tgt, [jam], height_fn=wall)
    assert bt_masked == float("inf")
    assert ew.effective_range(r, "ship", tgt, [jam], height_fn=wall) == SHIP_RING_M


def test_field_model_is_pure_deterministic():
    r = _radar()
    tgt = _at_ground_range(90_000.0)
    jam = _Jammer((RADAR_POS[0], 12_000.0, RADAR_POS[2] + 130_000.0), 200.0)
    a = [ew.burn_through_range(r, tgt, [jam]) for _ in range(5)]
    b = [ew.effective_range(r, "ship", tgt, [jam]) for _ in range(5)]
    c = [ew.js_db(r.pos, tgt, jam) for _ in range(5)]
    assert len(set(a)) == 1 and len(set(b)) == 1 and len(set(c)) == 1
    # the module must not import the RNG.
    import inspect
    src = inspect.getsource(ew)
    assert "import random" not in src
    assert "np.random" not in src and "numpy.random" not in src


def test_js_db_sign_and_crossover():
    """J/S > 0 dB long of burn-through (jammer wins), < 0 dB short of it."""
    r = _radar()
    jam = _Jammer((RADAR_POS[0], 12_000.0, RADAR_POS[2] + 120_000.0), 200.0)
    bt = ew.burn_through_range(r, _at_ground_range(100_000.0), [jam])
    long_t = _at_ground_range(bt + 20_000.0)
    short_t = _at_ground_range(bt - 20_000.0)
    assert ew.js_db(r.pos, long_t, jam) > 0.0
    assert ew.js_db(r.pos, short_t, jam) < 0.0
    # at the crossover J/S ~ 0 dB.
    cross = _at_ground_range(bt)
    assert abs(ew.js_db(r.pos, cross, jam)) < 1e-6


# ---------------------------------------------------------------------------
# Calibration band — LOCKED to the probe run (tools/probe_ew_burnthrough.py).
# Default Growler-class jammer (jam_power_w=200.0) at default standoff
# (~150 km behind the screen) collapses the 350 km ship ring to roughly HALF.
# Band filled from the probe; see comment with the run.
# ---------------------------------------------------------------------------

def test_calibration_band():
    r = _radar()
    jam = _Jammer(
        (RADAR_POS[0], ew.EW_DEFAULT_JAMMER_ALT_M,
         RADAR_POS[2] + ew.EW_DEFAULT_STANDOFF_M),
        ew.EW_DEFAULT_JAM_POWER_W,
    )
    tgt = _at_ground_range(100_000.0)
    eff = ew.effective_range(r, "ship", tgt, [jam])
    # MEASURED band (probe run 2026-06-17, EW_CAL locked): default jammer at
    # 150 km standoff collapses the 350 km ring to ~175 km (half).
    LO_M = 165_000.0
    HI_M = 185_000.0
    assert LO_M < eff < HI_M, f"effective_range={eff:.0f} outside [{LO_M},{HI_M}]"
