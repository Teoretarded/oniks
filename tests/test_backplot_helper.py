"""Task A — back_plot_surface() is a PURE, module-level, BIT-IDENTICAL extract.

The launch-point back-projection was factored out of
sim.commander.EnemyCommander.process_missile_track (the climb-branch
time-to-surface AND the level-skimmer coast-intersection) into the pure
module-level helper ``back_plot_surface``. This is the DRY/symmetry seam the
player CBR (#3) and the corner-reflector decoys (#5) reuse, so the SAME math
runs on both sides of the duel.

THE GATE (proved two ways here):
  1. A parametrized table of synthetic (first_pos, first_vel) tracks — climb,
     level-closing, level-receding, coast-parallel, dz<=0, already-at-surface,
     the degenerate vz<=min_close_vz rejection — returns EXACTLY the values the
     PRE-REFACTOR inline math produced. The golden outputs were captured from
     git HEAD (the verbatim inline math) via tools/_backplot_golden_capture.py
     BEFORE the extract and are pinned below.
  2. process_missile_track DELEGATES to the helper: a multi-track digest of its
     add_back_plot outputs is bit-identical to the pre-refactor digest (the same
     synthetic tracks fed through the public method produce the same fixes).

The 3000-step DEFAULT-battle bit-identical proof lives in
tools/wf_backplot_digest.py (run separately; the extract leaves it unchanged).
"""

from __future__ import annotations

import hashlib
import struct

import numpy as np
import pytest

from sim.commander import (
    BACKPLOT_CLIMB_VY,
    BACKPLOT_MIN_CLOSE_VZ,
    HOME_COAST_Z,
    EnemyCommander,
    back_plot_surface,
)


# --------------------------------------------------------------------------
# GOLDEN TABLE — captured from the PRE-REFACTOR HEAD inline math, VERBATIM
# (tools/_backplot_golden_capture.py). Each entry: (name, first_pos,
# first_vel, expected (launch_x, launch_z) OR None).
# --------------------------------------------------------------------------
GOLDEN = [
    ("climb_near_launch", (0.0, 500.0, 1000.0), (0.0, 100.0, 800.0),
     (0.0, -3000.0)),
    ("climb_steep_offset", (1500.0, 800.0, 3000.0), (50.0, 200.0, 600.0),
     (1300.0, 600.0)),
    ("climb_exactly_threshold", (0.0, 600.0, 2000.0), (10.0, 50.0, 700.0),
     (-120.0, -6400.0)),
    ("level_closing", (0.0, 60.0, 200000.0), (0.0, 1.0, 800.0),
     (0.0, 0.0)),
    ("level_closing_offset", (5000.0, 50.0, 150000.0), (120.0, 0.0, 750.0),
     (-19000.0, 0.0)),
    ("level_receding", (0.0, 60.0, 200000.0), (0.0, 1.0, -800.0),
     None),
    ("coast_parallel_slow_vz", (0.0, 60.0, 100000.0), (700.0, 0.0, 40.0),
     None),
    ("dz_le_zero", (0.0, 60.0, -50.0), (0.0, 1.0, 800.0),
     None),
    ("already_at_surface_climb", (0.0, 0.0, 5000.0), (0.0, 100.0, 800.0),
     (0.0, 5000.0)),
    ("vz_exactly_min_close", (0.0, 60.0, 100000.0), (700.0, 0.0, 50.0),
     None),
    ("level_negative_x_vel", (-2000.0, 80.0, 80000.0), (-300.0, 5.0, 900.0),
     (24666.666666666664, 0.0)),
]


# --------------------------------------------------------------------------
# Proof 1: the helper reproduces the inline math EXACTLY (bit-for-bit float).
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,first_pos,first_vel,expected", GOLDEN,
                         ids=[c[0] for c in GOLDEN])
def test_helper_matches_pre_refactor_inline_math(name, first_pos, first_vel,
                                                 expected):
    out = back_plot_surface(
        np.array(first_pos, dtype=np.float64),
        np.array(first_vel, dtype=np.float64),
    )
    if expected is None:
        assert out is None, f"{name}: expected None, got {out!r}"
    else:
        assert out is not None, f"{name}: expected {expected!r}, got None"
        # EXACT equality — the extract must not perturb a single float bit.
        assert out[0] == expected[0], f"{name}: x {out[0]!r} != {expected[0]!r}"
        assert out[1] == expected[1], f"{name}: z {out[1]!r} != {expected[1]!r}"


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
# Proof 2: process_missile_track DELEGATES to the helper — a digest of the
# add_back_plot outputs over the synthetic tracks is bit-identical to the
# pre-refactor expectation (re-derived from the GOLDEN table, since the public
# path is exactly the inline math the golden captured).
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


def test_process_missile_track_delegates_bit_identical_digest():
    """Feed every GOLDEN track that has a LOW first-detection altitude through
    process_missile_track and digest the resulting back-plot fixes. The fix
    estimate for each must equal the GOLDEN (helper) output exactly (rejections
    produce no fix). This proves the public path runs the same math as the
    helper — the extract changed no observable output of process_missile_track.
    """
    detector_pos = (0.0, 9100.0, 420000.0)
    commander = _make_commander()

    h = hashlib.sha256()
    expected = hashlib.sha256()
    for i, (name, fp, fv, gold) in enumerate(GOLDEN):
        # Only low-altitude first detections are back-plot eligible; the helper
        # table includes some higher-y climb cases (y up to 800 m) — all are
        # below BACKPLOT_LOW_ALT_M (2 km), so every one is eligible. Use a fresh
        # track id per case so each contributes its own fix.
        tid = f"gold_{i:02d}"
        before = len(commander.picture._back_plots)
        _feed_track(commander, tid, fp, fv, detector_pos)
        after = commander.picture._back_plots[before:]
        # Build the expected digest contribution from the GOLDEN table.
        if gold is None:
            expected.update(b"NONE")
            assert len(after) == 0, (
                f"{name}: a rejected geometry must produce no fix")
        else:
            expected.update(struct.pack("<dd", float(gold[0]), float(gold[1])))
            assert len(after) == 1, f"{name}: expected exactly one fix"
            est = after[0].estimated_pos
            h.update(struct.pack("<dd", float(est[0]), float(est[1])))
            # The public method must reproduce the helper/inline estimate EXACTLY.
            assert float(est[0]) == float(gold[0])
            assert float(est[1]) == float(gold[1])

    # And the running digest of the produced fixes equals the digest built from
    # the GOLDEN (helper) outputs for the non-rejected cases.
    gold_fix_digest = hashlib.sha256()
    for name, fp, fv, gold in GOLDEN:
        if gold is not None:
            gold_fix_digest.update(
                struct.pack("<dd", float(gold[0]), float(gold[1])))
    assert h.hexdigest() == gold_fix_digest.hexdigest()


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
