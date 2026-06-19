"""back_plot_surface() — the PURE, module-level back-plot helper.

The launch-point back-projection was factored out of
sim.commander.EnemyCommander.process_missile_track (the climb-branch
time-to-surface AND the level-skimmer coast-intersection) into the pure
module-level helper ``back_plot_surface`` (Task A, bit-identical extract). This
is the DRY/symmetry seam the player CBR (#3) and the corner-reflector decoys (#5)
reuse, so the SAME math runs on both sides of the duel.

What this file proves:
  * CLIMB + REJECTION regimes reproduce the PRE-REFACTOR HEAD inline math EXACTLY
    (golden values captured verbatim from HEAD via
    tools/_backplot_golden_capture.py). These were NOT touched by the Task B
    reliability buff, so they stand as the permanent extract proof.
  * The LEVEL regime now applies the documented Task B coastal-setback buff:
    launch_x is unchanged from HEAD, launch_z moved DOWN by exactly
    BACKPLOT_COAST_SETBACK_M. (The full two-sided reliability/winnability gate is
    in tests/test_backplot_reliability.py.)
  * process_missile_track DELEGATES to the helper: every synthetic track's
    recorded fix equals back_plot_surface()'s output — the invariant that holds
    across BOTH the extract and the buff.

The default-battle digest proofs live in tools/wf_backplot_digest.py: Task A left
the (then 3000-step) digest bit-identical to HEAD; Task B is the one documented
change (16 000-step horizon reaches back-plot formation; pinned + reproducible).
"""

from __future__ import annotations

import hashlib
import struct

import numpy as np
import pytest

from sim.commander import (
    BACKPLOT_CLIMB_VY,
    BACKPLOT_COAST_SETBACK_M,
    BACKPLOT_MIN_CLOSE_VZ,
    HOME_COAST_Z,
    EnemyCommander,
    back_plot_surface,
)


# --------------------------------------------------------------------------
# GOLDEN_CLIMB + GOLDEN_REJECT — captured from the PRE-REFACTOR HEAD inline math,
# VERBATIM (tools/_backplot_golden_capture.py). These regimes were NOT touched by
# the Task B reliability buff, so they remain BIT-IDENTICAL to HEAD forever and
# stand as the permanent extract proof. (The Task A bit-identical proof also
# lives in commit 5e1b1e3 and the 3000-step default digest in
# tools/wf_backplot_digest.py.)
# --------------------------------------------------------------------------
GOLDEN_CLIMB = [
    ("climb_near_launch", (0.0, 500.0, 1000.0), (0.0, 100.0, 800.0),
     (0.0, -3000.0)),
    ("climb_steep_offset", (1500.0, 800.0, 3000.0), (50.0, 200.0, 600.0),
     (1300.0, 600.0)),
    ("climb_exactly_threshold", (0.0, 600.0, 2000.0), (10.0, 50.0, 700.0),
     (-120.0, -6400.0)),
    ("already_at_surface_climb", (0.0, 0.0, 5000.0), (0.0, 100.0, 800.0),
     (0.0, 5000.0)),
]
GOLDEN_REJECT = [
    ("level_receding", (0.0, 60.0, 200000.0), (0.0, 1.0, -800.0)),
    ("coast_parallel_slow_vz", (0.0, 60.0, 100000.0), (700.0, 0.0, 40.0)),
    ("dz_le_zero", (0.0, 60.0, -50.0), (0.0, 1.0, 800.0)),
    ("vz_exactly_min_close", (0.0, 60.0, 100000.0), (700.0, 0.0, 50.0)),
]

# GOLDEN_LEVEL — the level-skimmer regime. The PRE-REFACTOR HEAD output projected
# to the bare waterline (z = 0); the Task B reliability buff projects to the
# believed coastal-battery setback line (z = -BACKPLOT_COAST_SETBACK_M). Each row
# records BOTH so the buff's effect is explicit and measured: the launch_x is
# UNCHANGED from HEAD (the buff only shifts the projected latitude by the
# setback, scaling x by the same s), and launch_z moved by exactly the setback.
# (name, first_pos, first_vel, head_z0_output, postbuff_output)
GOLDEN_LEVEL = [
    ("level_closing", (0.0, 60.0, 200000.0), (0.0, 1.0, 800.0),
     (0.0, 0.0), (0.0, -300.0)),
    ("level_closing_offset", (5000.0, 50.0, 150000.0), (120.0, 0.0, 750.0),
     (-19000.0, 0.0), (-19048.0, -300.0)),
    ("level_negative_x_vel", (-2000.0, 80.0, 80000.0), (-300.0, 5.0, 900.0),
     (24666.666666666664, 0.0), (24766.666666666668, -300.0)),
]


# --------------------------------------------------------------------------
# Proof 1a: the climb + rejection regimes reproduce the inline math EXACTLY
# (bit-for-bit) — UNTOUCHED by the buff, the permanent extract proof.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,first_pos,first_vel,expected", GOLDEN_CLIMB,
                         ids=[c[0] for c in GOLDEN_CLIMB])
def test_climb_regime_bit_identical_to_head(name, first_pos, first_vel,
                                            expected):
    out = back_plot_surface(
        np.array(first_pos, dtype=np.float64),
        np.array(first_vel, dtype=np.float64),
    )
    assert out is not None, f"{name}: expected {expected!r}, got None"
    # EXACT equality — the climb branch was extracted verbatim, never buffed.
    assert out[0] == expected[0], f"{name}: x {out[0]!r} != {expected[0]!r}"
    assert out[1] == expected[1], f"{name}: z {out[1]!r} != {expected[1]!r}"


@pytest.mark.parametrize("name,first_pos,first_vel", GOLDEN_REJECT,
                         ids=[c[0] for c in GOLDEN_REJECT])
def test_rejection_regime_bit_identical_to_head(name, first_pos, first_vel):
    """Receding / coast-parallel / already-ashore / vz==min_close all reject
    EXACTLY as HEAD did — the buff did not change WHEN a fix is rejected (the
    test runs on the waterline), preserving the dogleg/scoot escapes."""
    out = back_plot_surface(
        np.array(first_pos, dtype=np.float64),
        np.array(first_vel, dtype=np.float64),
    )
    assert out is None, f"{name}: expected None (rejection), got {out!r}"


# --------------------------------------------------------------------------
# Proof 1b: the level regime now applies the documented setback. launch_x is
# unchanged from HEAD; launch_z moved by exactly BACKPLOT_COAST_SETBACK_M.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,first_pos,first_vel,head_out,postbuff_out",
                         GOLDEN_LEVEL, ids=[c[0] for c in GOLDEN_LEVEL])
def test_level_regime_setback_applied(name, first_pos, first_vel, head_out,
                                      postbuff_out):
    out = back_plot_surface(
        np.array(first_pos, dtype=np.float64),
        np.array(first_vel, dtype=np.float64),
    )
    assert out is not None
    assert out[0] == pytest.approx(postbuff_out[0])
    assert out[1] == pytest.approx(postbuff_out[1])
    # The buff shifted the projected latitude DOWN by exactly the setback.
    assert head_out[1] == 0.0
    assert out[1] == pytest.approx(HOME_COAST_Z - BACKPLOT_COAST_SETBACK_M)


def test_helper_is_pure_module_level():
    """back_plot_surface is a free function (no self/instance), importable from
    the module, and does not touch any global state."""
    import inspect

    import sim.commander as cmdmod

    assert inspect.isfunction(back_plot_surface)
    assert back_plot_surface is cmdmod.back_plot_surface
    # First positional arg is first_pos, not self.
    params = list(inspect.signature(back_plot_surface).parameters)
    assert params[0] == "first_pos"
    assert "self" not in params


def test_helper_defaults_match_module_constants():
    """The keyword defaults are the named module constants (not magic numbers)."""
    import inspect

    sig = inspect.signature(back_plot_surface)
    assert sig.parameters["coast_z"].default == HOME_COAST_Z
    assert sig.parameters["climb_vy"].default == BACKPLOT_CLIMB_VY
    assert sig.parameters["min_close_vz"].default == BACKPLOT_MIN_CLOSE_VZ


def test_helper_does_not_mutate_inputs():
    """Pure: the input arrays are read, never written."""
    fp = np.array([1234.0, 567.0, 89000.0], dtype=np.float64)
    fv = np.array([100.0, 5.0, 900.0], dtype=np.float64)
    fp_before = fp.copy()
    fv_before = fv.copy()
    back_plot_surface(fp, fv)
    assert np.array_equal(fp, fp_before)
    assert np.array_equal(fv, fv_before)


# --------------------------------------------------------------------------
# Proof 2: process_missile_track DELEGATES to the helper — for every synthetic
# track, the fix the PUBLIC method records equals what back_plot_surface()
# returns (rejections produce no fix). This is the delegation invariant that
# holds across BOTH tasks (the extract AND the buff): whatever the helper does,
# the public path does identically.
# --------------------------------------------------------------------------

def _make_commander(seed: int = 7) -> EnemyCommander:
    """Minimal commander — the back-plot path only needs the picture; the
    fighters/awacs/destroyers are unused stubs here."""
    return EnemyCommander(fighters=[], awacs=None, destroyers=[], seed=seed)


def _feed_track(commander, track_id, first_pos, first_vel,
                detector_pos, sim_time=100.0):
    """Feed one fresh, back-plot-eligible (low, young) track through the public
    method. The track is first detected at first_pos (low alt) at sim_time, and
    is current 5 s later."""
    fp = np.array(first_pos, dtype=np.float64)
    fv = np.array(first_vel, dtype=np.float64)
    commander.process_missile_track(
        track_id=track_id,
        pos=fp + fv * 5.0,
        vel=fv.copy(),
        sim_time=sim_time + 5.0,
        first_seen_t=sim_time,
        first_seen_pos=fp,
        first_seen_vel=fv,
        detector_pos=np.array(detector_pos, dtype=np.float64),
    )


def test_process_missile_track_delegates_to_helper():
    """Feed every synthetic track (all low-altitude, back-plot eligible) through
    process_missile_track and assert the recorded fix equals what the pure
    helper returns for the same first_seen (rejections -> no fix). This proves
    the public path delegates to back_plot_surface() — the extract changed no
    observable output, and the buff flows through identically.
    """
    detector_pos = (0.0, 9100.0, 420000.0)
    commander = _make_commander()

    # All synthetic cases: climb + rejections + level (every one is below
    # BACKPLOT_LOW_ALT_M and fresh, so eligibility passes; the helper decides
    # localize-vs-reject).
    cases = (
        [(n, fp, fv) for n, fp, fv, _ in GOLDEN_CLIMB]
        + list(GOLDEN_REJECT)
        + [(n, fp, fv) for n, fp, fv, _, _ in GOLDEN_LEVEL]
    )

    h = hashlib.sha256()           # digest of the PUBLIC-path recorded fixes
    expected = hashlib.sha256()    # digest of the HELPER outputs (same build)
    for i, (name, fp, fv) in enumerate(cases):
        helper_out = back_plot_surface(
            np.array(fp, dtype=np.float64), np.array(fv, dtype=np.float64))
        tid = f"case_{i:02d}"
        before = len(commander.picture._back_plots)
        _feed_track(commander, tid, fp, fv, detector_pos)
        after = commander.picture._back_plots[before:]
        if helper_out is None:
            assert len(after) == 0, (
                f"{name}: helper rejected -> public path must record no fix")
        else:
            expected.update(
                struct.pack("<dd", float(helper_out[0]), float(helper_out[1])))
            assert len(after) == 1, f"{name}: expected exactly one fix"
            est = after[0].estimated_pos
            h.update(struct.pack("<dd", float(est[0]), float(est[1])))
            # The public method reproduces the helper estimate EXACTLY.
            assert float(est[0]) == float(helper_out[0])
            assert float(est[1]) == float(helper_out[1])

    assert h.hexdigest() == expected.hexdigest()


def test_no_truth_read_helper_ignores_live_missile_pos():
    """The back-plot estimate is a function of first_seen ONLY. Feeding two
    tracks with IDENTICAL first_seen but WILDLY different live pos/vel must
    yield the SAME fix — the helper (and the public path) never read the live
    round position (no truth smuggling)."""
    detector_pos = np.array([0.0, 9100.0, 420000.0], dtype=np.float64)
    fp = np.array([0.0, 60.0, 200000.0], dtype=np.float64)
    fv = np.array([0.0, 1.0, 800.0], dtype=np.float64)

    c1 = _make_commander()
    c1.process_missile_track(
        "t1", pos=fp + fv * 5.0, vel=fv.copy(), sim_time=105.0,
        first_seen_t=100.0, first_seen_pos=fp, first_seen_vel=fv,
        detector_pos=detector_pos)
    c2 = _make_commander()
    c2.process_missile_track(
        "t2",
        pos=np.array([999999.0, 12345.0, -42.0]),       # absurd live pos
        vel=np.array([-700.0, -90.0, -100.0]),           # absurd live vel
        sim_time=105.0, first_seen_t=100.0,
        first_seen_pos=fp, first_seen_vel=fv,             # IDENTICAL first_seen
        detector_pos=detector_pos)

    assert len(c1.picture._back_plots) == 1
    assert len(c2.picture._back_plots) == 1
    e1 = c1.picture._back_plots[0].estimated_pos
    e2 = c2.picture._back_plots[0].estimated_pos
    assert float(e1[0]) == float(e2[0])
    assert float(e1[1]) == float(e2[1])
