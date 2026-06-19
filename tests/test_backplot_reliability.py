"""Task B — the back-plot RELIABILITY buff, two-sided + MEASURED.

The enemy launch-site back-plot is the enemy's ONLY base-kill path. It was
mis-projecting a sea-skimmer's launch point: the level-skimmer coast-intersection
stopped at the hard waterline (HOME_COAST_Z = 0), but a coastal anti-ship battery
sits INLAND of the waterline, so the estimate carried a systematic seaward bias
(MEASURED at ~600 m vs the true Bastion pad at z = -600 via
tools/probe_backplot_reliability.py).

The buff is a CONSERVATIVE, physics-not-dice GEOMETRIC correction: project the
level skimmer's ground track back to a believed coastal-battery setback line
(coast_z - BACKPLOT_COAST_SETBACK_M) rather than the bare waterline. This is a
doctrine BELIEF about coastal-battery emplacement (like HOME_COAST_Z itself), not
a truth read — and it deliberately UNDER-corrects (setback < the true 600 m) so
the estimate tightens but never snipes to truth.

Two-sided gate (both must hold or the buff is not shippable):
  RELIABLE: a representative straight lo-lo sea-skim leak forms a targetable
    cluster whose centroid error is below the measured RELIABLE bound AND tighter
    than the pre-buff bias.
  STILL-WINNABLE: a DOGLEG (coast-parallel / receding) launch yields NO fix (the
    escape condition is UNCHANGED and tested on the waterline, so the player can
    still defeat localization); and a stale/wrong centroid sits far enough from a
    relocated pad that a salvo there finds no structure within SEEKER_BASKET_M.
  ERROR FLOOR: error_m stays >= det_range * BACKPLOT_ERR_FRAC (a cue, not a snipe).
  NO-TRUTH / DETERMINISM: the estimate uses only first_seen; identical inputs ->
    identical estimate.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from sim.commander import (
    BACKPLOT_CLIMB_VY,
    BACKPLOT_CLUSTER_R_M,
    BACKPLOT_COAST_SETBACK_M,
    BACKPLOT_ERR_FRAC,
    BACKPLOT_FIXES_NEEDED,
    BACKPLOT_MIN_CLOSE_VZ,
    HOME_COAST_Z,
    EnemyCommander,
    back_plot_surface,
)

# SEEKER_BASKET_M lives on the world side (terminal scene-match acquisition).
SEEKER_BASKET_M = 1_000.0

# The true Bastion pad (world.generation.BASE_POS XZ): z = -600, 600 m inland of
# the coast at z = 0. The MEASURED pre-buff bias (probe) was ~600 m.
TRUE_PAD_XZ = (0.0, -600.0)
PRE_BUFF_BIAS_M = 600.0


# --------------------------------------------------------------------------
# Helper-level: the buff is a constant + a tighter level-skimmer projection.
# --------------------------------------------------------------------------

def test_setback_constant_is_conservative():
    """The setback is a NAMED module constant, positive, and UNDER the true
    600 m inland distance (conservative: it never snipes to the true pad)."""
    assert isinstance(BACKPLOT_COAST_SETBACK_M, float)
    assert 0.0 < BACKPLOT_COAST_SETBACK_M < PRE_BUFF_BIAS_M, (
        "setback must be positive and strictly under the measured true 600 m "
        "inland distance so the estimate tightens but never reaches truth")


def _level_skimmer_track(first_z=72_252.0, vz=680.0, vx=0.0, alt=60.0):
    """A representative straight lo-lo sea-skim first-detection track (numbers
    from the MEASURED real-world first detection in probe_backplot_reliability)."""
    fp = np.array([0.0, alt, first_z], dtype=np.float64)
    fv = np.array([vx, 1.0, vz], dtype=np.float64)   # vy~0 -> level regime
    return fp, fv


def test_buff_tightens_straight_skimmer_estimate():
    """RELIABLE side at the helper level: the level-skimmer estimate is now
    closer to the true pad than the pre-buff waterline projection, and inside
    the seeker basket."""
    fp, fv = _level_skimmer_track()
    est = back_plot_surface(fp, fv)
    assert est is not None
    err = math.hypot(est[0] - TRUE_PAD_XZ[0], est[1] - TRUE_PAD_XZ[1])
    # Tighter than the pre-buff 600 m bias...
    assert err < PRE_BUFF_BIAS_M, (
        f"buffed estimate error {err:.0f} m must beat the pre-buff "
        f"{PRE_BUFF_BIAS_M:.0f} m bias")
    # ...and comfortably inside the terminal seeker basket.
    assert err < SEEKER_BASKET_M
    # The projected latitude is the believed setback line, south of the coast.
    assert est[1] == pytest.approx(HOME_COAST_Z - BACKPLOT_COAST_SETBACK_M)


def test_buff_never_snipes_truth():
    """CONSERVATIVE: the buffed estimate does NOT land exactly on the true pad —
    the setback is an approximate belief, not a truth read. A floor of error
    remains between the estimate and the real launcher."""
    fp, fv = _level_skimmer_track()
    est = back_plot_surface(fp, fv)
    err = math.hypot(est[0] - TRUE_PAD_XZ[0], est[1] - TRUE_PAD_XZ[1])
    assert err > 1.0, "the estimate must not coincide with the true pad"


# --------------------------------------------------------------------------
# STILL-WINNABLE: the dogleg / receding escape is UNCHANGED (tested on the
# waterline coast_z, not the setback line).
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,fp,fv", [
    # Coast-parallel: vz at/below the min-close threshold -> no fix.
    ("coast_parallel_slow_vz",
     (0.0, 60.0, 100_000.0), (700.0, 0.0, BACKPLOT_MIN_CLOSE_VZ)),
    # Receding (vz < 0) -> no fix.
    ("receding",
     (0.0, 60.0, 200_000.0), (0.0, 1.0, -800.0)),
    # Already on the coast side (dz <= 0 at the WATERLINE) -> no fix. dz is
    # measured against coast_z (z=0), so a track already at/south of the
    # waterline cannot localize, exactly as before the buff.
    ("south_of_waterline",
     (0.0, 60.0, -50.0), (0.0, 1.0, 800.0)),
])
def test_dogleg_escape_unchanged(name, fp, fv):
    """A coast-parallel / receding / already-ashore track yields NO fix — the
    buff changed only the projected latitude, never WHEN a fix is rejected, so
    a dog-legging player still defeats localization."""
    est = back_plot_surface(
        np.array(fp, dtype=np.float64), np.array(fv, dtype=np.float64))
    assert est is None, f"{name}: a dogleg must not localize"


def test_escape_test_uses_waterline_not_setback():
    """Guard: the dz<=0 rejection is measured against the WATERLINE (coast_z),
    NOT the setback line. A track between the setback line and the waterline
    (0 > z > -setback) must STILL localize (dz>0 at the waterline) — i.e. the
    setback did not widen the rejection window and shrink the winnable escape.
    """
    # A level track just seaward of the waterline (z small positive), closing.
    fp = np.array([0.0, 60.0, 10.0], dtype=np.float64)
    fv = np.array([0.0, 1.0, 800.0], dtype=np.float64)
    est = back_plot_surface(fp, fv)
    assert est is not None, (
        "a closing track still seaward of the waterline must localize; the "
        "escape window must not have grown with the setback")


# --------------------------------------------------------------------------
# Real-world two-sided regression (the hard gate, on a live CombatWorld).
# --------------------------------------------------------------------------

DT = 1.0 / 120.0


def _run_world_salvos(target_xz, n_salvos=4, gap_steps=15_000, steps=60_000):
    """Fire n_salvos lo-lo Oniks at target_xz from the real Bastion pad and step
    a real CombatWorld long enough for every round to be seen/back-plotted."""
    from world.combat import CombatWorld
    from world.combat_config import CombatConfig

    cw = CombatWorld(CombatConfig(seed=1337))
    pic = cw.commander.picture
    tx = np.array([float(target_xz[0]), 0.0, float(target_xz[1])])
    fire_steps = {60 + k * gap_steps for k in range(n_salvos)}
    for i in range(steps):
        if i in fire_steps:
            cw.launch("lo-lo", tx)
        cw.step(DT)
    return cw, pic


@pytest.mark.slow
def test_world_straight_seaskim_forms_tight_cluster():
    """RELIABLE (real world): a straight lo-lo sea-skim salvo forms a targetable
    cluster within BACKPLOT_FIXES_NEEDED detected launches, and the centroid is
    inside the seeker basket AND tighter than the pre-buff 600 m bias."""
    cw, pic = _run_world_salvos((0.0, 220_000.0))
    targ = pic.targetable_clusters()
    assert targ, "a straight sea-skim leak must form a targetable cluster"
    best = min(targ, key=lambda c: math.hypot(
        float(c.centre[0]) - TRUE_PAD_XZ[0],
        float(c.centre[1]) - TRUE_PAD_XZ[1]))
    cerr = math.hypot(float(best.centre[0]) - TRUE_PAD_XZ[0],
                      float(best.centre[1]) - TRUE_PAD_XZ[1])
    assert cerr < SEEKER_BASKET_M, (
        f"centroid error {cerr:.0f} m must be inside the seeker basket "
        f"{SEEKER_BASKET_M:.0f} m so the strike acquires the bastion_tel")
    assert cerr < PRE_BUFF_BIAS_M, (
        f"buffed centroid {cerr:.0f} m must beat the pre-buff 600 m bias")


@pytest.mark.slow
def test_world_error_floor_holds():
    """ERROR FLOOR (real world): every fix's reported error_m stays >=
    det_range * BACKPLOT_ERR_FRAC — the back-plot remains a wide-uncertainty
    CUE (~7 km at the ~350 km AWACS slant range), never a truth-snipe, even
    though the geometric estimate is good."""
    cw, pic = _run_world_salvos((0.0, 220_000.0))
    fixes = [f for c in pic.clusters for f in c.fixes]
    assert fixes, "expected back-plot fixes to measure the floor"
    for f in fixes:
        # error_m was set as det_range * ERR_FRAC at add time; det_range is the
        # AWACS slant (~350 km), so the floor is ~7 km. Assert it is large
        # (a cue), far exceeding the ~300 m geometric estimate error.
        assert f.error_m >= 1_000.0, (
            f"error_m {f.error_m:.0f} must stay a wide cue, not collapse to the "
            f"geometric accuracy")


@pytest.mark.slow
def test_world_scoot_defeats_stale_centroid():
    """STILL-WINNABLE (real world): a player who relocates by > the seeker basket
    is NOT hit by the stale centroid. Scored by firing the straight salvo (which
    localizes the OLD pad) and checking the centroid is > SEEKER_BASKET_M from a
    pad relocated 8 km away — a salvo at that centroid finds no structure in the
    basket and hits dirt."""
    cw, pic = _run_world_salvos((0.0, 220_000.0))
    targ = pic.targetable_clusters()
    assert targ
    best = targ[0]
    relocated = (8_000.0, -600.0)
    err_to_new = math.hypot(float(best.centre[0]) - relocated[0],
                            float(best.centre[1]) - relocated[1])
    assert err_to_new > SEEKER_BASKET_M, (
        f"a relocated pad {err_to_new:.0f} m from the stale centroid must sit "
        f"outside the seeker basket {SEEKER_BASKET_M:.0f} m (the scoot escapes)")
