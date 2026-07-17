"""Flight-physics contracts: every cinematic missile flies on forces.

Headless, GL-free, flat ground.  Numbers trace to
docs/research/missile_flight_physics_reference.md (SIM CONSTANTS).
Contracts are two-sided; BLOCKED > weakened, never edit tolerances.

Planning notes on the tolerances (set BEFORE implementation from the
rocket equation on the real stage specs, not tuned to the code):
- The engine is flat-earth uniform-gravity: no Earth-rotation bonus
  (~+400 m/s) and no curvature relief on gravity loss, so the honest
  Minuteman burnout window is [5500, 7300] m/s against the real-world
  6.7-7.0 km/s, and the 45-degree loft puts burnout higher than the
  real ~190 km — the altitude window is a loose sanity band.
- "Monotonic on coast" holds while ASCENDING (drag + gravity both
  oppose the climb); a falling airframe legitimately regains speed.
"""

from __future__ import annotations

import math

import numpy as np

from game.cinematic_icbm import ICBM_BY_ID, IcbmLaunch
from game.cinematic_missiles import (GuidedLaunch, ScriptedLaunch,
                                     VARIANT_BY_ID)

DT = 1.0 / 120.0
PAD = (0.0, 500.0, 0.0)


def _flat0(x, z):
    return 0.0


def _flat500(x, z):
    return 500.0


def _fly_icbm(lch, max_s=2400.0):
    events = []
    for _ in range(int(max_s / DT)):
        if lch.done:
            break
        evs: list = []
        lch.step(DT, evs)
        events.extend(evs)
    return events


# ------------------------------------------------- contract 1 + 2: boost

def test_mm3_full_boost_matches_research():
    """A range-limit shot burns the full stack: burnout speed in the
    flat-earth window, the real ~187 s of stage clock, and a sane
    boost altitude."""
    lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0.0, 0.0, 0.0),
                     target=(3_500_000.0, 0.0, 0.0), ground_h=_flat0)
    speeds, alts = [], []
    t = 0.0
    while lch.burnout_t is None and t < 400.0:
        evs: list = []
        lch.step(DT, evs)
        t += DT
        speeds.append(float(np.linalg.norm(lch.vel)))
        alts.append(float(lch.pos[1]))
    assert lch.burnout_t is not None
    powered = lch.burnout_t - lch.ignite_t
    burnout_speed = speeds[-1]
    burnout_alt = alts[-1]
    assert 5500.0 <= burnout_speed <= 7300.0
    assert 170.0 <= powered <= 195.0
    assert 100_000.0 <= burnout_alt <= 450_000.0


def test_boost_drag_is_real():
    """Drag is a force, not a cosmetic.  The observable is the OPEN-
    LOOP display launch: closed-loop ICBM guidance terminates at the
    demanded velocity either way (drag shows up as extra burn time and
    propellant, not burnout speed), so the speed assertion lives where
    thrust is unguided.  Threshold unchanged from the plan (40 m/s —
    the real gap measures far larger at SAM altitudes)."""
    import game.cinematic_missiles as cm

    def burnout_speed():
        s = ScriptedLaunch(VARIANT_BY_ID["48n6"], PAD, 0.7, 9.1)
        t = 0.0
        while t < 14.0:                # burnout at ignite 0.9 s + 12 s
            s.step(DT, [])
            t += DT
        return float(np.linalg.norm(s.vel))

    v_air = burnout_speed()
    orig = cm.drag_force_scalar
    cm.drag_force_scalar = lambda *a, **k: 0.0
    try:
        v_vac = burnout_speed()
    finally:
        cm.drag_force_scalar = orig
    assert v_vac >= v_air + 40.0


# --------------------------------------------------- contract 3: reentry

def test_rv_reentry_decelerates_like_an_rv():
    """Peak deceleration in the tens of g, deep in the atmosphere, and
    an impact speed in the low km/s — the Allen-Eggers picture for a
    Mk21-class beta, emerging from the integrated drag (not scripted)."""
    lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0.0, 0.0, 0.0),
                     target=(3_500_000.0, 0.0, 0.0), ground_h=_flat0)
    prev_v = None
    peak_dec, peak_alt, impact_speed = 0.0, None, None
    t = 0.0
    while not lch.done and t < 2400.0:
        evs: list = []
        lch.step(DT, evs)
        t += DT
        sp = float(np.linalg.norm(lch.vel))
        if lch.rv_only and prev_v is not None and lch.vel[1] < 0.0:
            dec = (prev_v - sp) / DT
            if dec > peak_dec:
                peak_dec = dec
                peak_alt = float(lch.pos[1])
        if any(k == "impact" for k, _ in evs):
            impact_speed = prev_v
            break
        prev_v = sp
    assert impact_speed is not None, "the round never landed"
    assert 30.0 * 9.81 <= peak_dec <= 70.0 * 9.81
    assert peak_alt is not None and peak_alt < 40_000.0
    assert 1000.0 <= impact_speed <= 4500.0


# --------------------------------------------------- contract 4: no snap

def _max_tick_rotation(get_axis, stepper, ticks, dt=0.05):
    worst = 0.0
    prev = get_axis().copy()
    for _ in range(ticks):
        stepper(dt)
        cur = get_axis().copy()
        cosang = float(np.clip(np.dot(prev, cur), -1.0, 1.0))
        worst = max(worst, math.degrees(math.acos(cosang)))
        prev = cur
    return worst


def test_no_attitude_snaps_anywhere():
    """Body attitude never rotates faster than the declared slew limit
    (plus rounding slack) for all three families."""
    s = ScriptedLaunch(VARIANT_BY_ID["48n6"], PAD, 0.7, 9.1)
    worst = _max_tick_rotation(
        lambda: s.axis, lambda dt: s.step(dt, []), ticks=600)
    assert worst <= s.slew_deg_s * 0.05 + 0.5

    g = GuidedLaunch(VARIANT_BY_ID["48n6"], PAD, 0.7, 9.1,
                     (8000.0, 0.0, 2000.0), _flat500)
    worst = _max_tick_rotation(
        lambda: g.axis, lambda dt: g.step(dt, []), ticks=600)
    assert worst <= g.slew_deg_s * 0.05 + 0.5

    i = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0.0, 0.0, 0.0),
                   target=(200_000.0, 0.0, 0.0), ground_h=_flat0)
    worst = _max_tick_rotation(
        lambda: i.axis, lambda dt: i.step(dt, []), ticks=1200)
    assert worst <= i.slew_deg_s * 0.05 + 0.5


# ------------------------------------- contract 5: display launch physics

def test_48n6_display_launch_flies_on_forces():
    """The unmarked pad launch: real Mach numbers, a speed ceiling, and
    drag-only deceleration while it climbs after burnout."""
    from sim.physics import mach_scalar

    s = ScriptedLaunch(VARIANT_BY_ID["48n6"], PAD, 0.7, 9.1)
    max_speed, mach_by_20s = 0.0, 0.0
    speeds_after_burnout = []
    t = 0.0
    while t < 39.0:
        s.step(DT, [])
        t += DT
        sp = float(np.linalg.norm(s.vel))
        max_speed = max(max_speed, sp)
        if t <= 20.0 and s.ignited:
            mach_by_20s = max(mach_by_20s,
                              mach_scalar(sp, max(float(s.pos[1]), 0.0)))
        if (s.ignited and not s.burning() and s.vel[1] > 0.0
                and float(s.pos[1]) < 25_000.0):
            speeds_after_burnout.append(sp)
    assert mach_by_20s >= 2.5
    assert max_speed <= 2600.0
    diffs = np.diff(np.array(speeds_after_burnout))
    assert len(diffs) > 100 and (diffs <= 1e-6).all()


# ------------------------------------------- contract 6 + 7: still on the mark

def test_guided_accuracy_preserved():
    """Slew-limited attitude must not cost accuracy: same 25 m contract
    as test_cinematic_guided."""
    m = GuidedLaunch(VARIANT_BY_ID["48n6"], PAD, 0.7, 9.1,
                     (8000.0, 0.0, 2000.0), _flat500)
    assert m.feasible
    events = []
    for _ in range(int(600.0 / DT)):
        if m.done:
            break
        ev: list = []
        m.step(DT, ev)
        events.extend(ev)
    imp = [p for k, p in events if k == "impact"]
    assert imp and math.hypot(imp[0][0] - 8000.0,
                              imp[0][2] - 2000.0) <= 25.0


def test_icbm_lands_on_the_mark_with_drag():
    """Twin/live coherence + drag-biased aim: the full-physics flight
    still puts the RV within 400 m of the designated point."""
    lch = IcbmLaunch(ICBM_BY_ID["mm3"], silo=(0.0, 800.0, 0.0),
                     target=(60_000.0, 800.0, 20_000.0),
                     ground_h=lambda x, z: 800.0)
    events = _fly_icbm(lch)
    imp = [p for k, p in events if k == "impact"]
    assert imp, "no impact recorded"
    miss = math.hypot(imp[0][0] - 60_000.0, imp[0][2] - 20_000.0)
    assert miss <= 400.0
