"""MEASURE the enemy launch-site back-plot reliability on the REAL world.

The enemy commander's back-plot is its ONLY base-kill path: it back-plots a
player Oniks/SAM launch, clusters >= BACKPLOT_FIXES_NEEDED fixes within
BACKPLOT_CLUSTER_R_M, then fires TLAM/JASSM at the cluster centroid. GAME_ANALYSIS
flags it as "too timid" — it mis-projects a sea-skimmer so clusters rarely form.

This probe QUANTIFIES the current behavior (print measured numbers, NO asserts —
the probe idiom). It fires representative salvos in a real CombatWorld, steps
them, and prints, for each scenario:
  - does a LaunchCluster form? after how many launches?
  - the cluster centroid error vs the TRUE pad XZ (m)?
  - the per-fix back-projection error (m)?
  - the first-seen alt/range/vy of the back-plotted track (the geometry).

Scenarios:
  A. STRAIGHT lo-lo (sea-skim) salvo from the real Bastion pad -> SHOULD localize.
  B. DOGLEG: a lo-lo salvo aimed coast-parallel (the player evades) -> should NOT.
  C. SCOOT: a salvo fired from a 2nd, offset pad -> localizes to the OTHER spot.

Run BEFORE the buff (baseline), apply the buff, run AFTER (same scenarios) — the
buff flips A from "no cluster / large error" to "reliable cluster, small error"
while B/C still escape. Set APPLY_LABEL via the BACKPLOT_BUFFED env hint only for
the printed banner; the model change itself lives in sim/commander.py.

Run: python tools/probe_backplot_reliability.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from world.combat import CombatWorld
from world.combat_config import CombatConfig
from world.generation import BASE_POS
from sim.commander import (
    BACKPLOT_CLUSTER_R_M,
    BACKPLOT_ERR_FRAC,
    BACKPLOT_FIXES_NEEDED,
    BACKPLOT_LOW_ALT_M,
    BACKPLOT_MAX_AGE_S,
    HOME_COAST_Z,
)

DT = 1.0 / 120.0
TRUE_PAD_XZ = (float(BASE_POS[0]), float(BASE_POS[2]))   # (0.0, -600.0)


def _fmt(x):
    return "None" if x is None else f"{x:,.1f}"


def _cluster_summary(pic, true_xz):
    """Return (n_raw_fixes, n_clusters, best_targetable_cluster_or_None,
    centroid_err_m_or_None, per_fix_errs)."""
    raw = list(pic._back_plots)
    per_fix_errs = []
    for bp in raw:
        e = math.hypot(float(bp.estimated_pos[0]) - true_xz[0],
                       float(bp.estimated_pos[1]) - true_xz[1])
        per_fix_errs.append(e)
    # The raw _back_plots list is PRUNED to BACKPLOT_MAX_AGE_S, so it only holds
    # recent fixes; the clusters retain their own fixes independently. Report
    # both: total fixes ACROSS clusters is the meaningful accumulation count.
    cluster_fix_total = sum(len(c.fixes) for c in pic.clusters)
    # Per-fix errors across ALL retained cluster fixes (the real accumulation).
    for c in pic.clusters:
        for f in c.fixes:
            e = math.hypot(float(f.estimated_pos[0]) - true_xz[0],
                           float(f.estimated_pos[1]) - true_xz[1])
            per_fix_errs.append(e)
    targ = pic.targetable_clusters()
    best = None
    cerr = None
    if targ:
        best = min(
            targ,
            key=lambda c: math.hypot(float(c.centre[0]) - true_xz[0],
                                     float(c.centre[1]) - true_xz[1]))
        cerr = math.hypot(float(best.centre[0]) - true_xz[0],
                          float(best.centre[1]) - true_xz[1])
    return (len(raw), len(pic.clusters), best, cerr, per_fix_errs,
            cluster_fix_total)


def _run_scenario(name, target_xz, true_pad_xz, n_salvos=4,
                  salvo_gap_steps=15_000, steps=60_000):
    """Fire n_salvos lo-lo Oniks at target_xz from the real Bastion pad, step the
    world, and report the back-plot pipeline state. Returns a dict of measured
    numbers.

    Timing is set from the MEASURED flight (tools/_backplot_diag2.py): a lo-lo
    Oniks is first detected ~114 s after launch (~350 km slant to the AWACS), and
    the default tube reload is 120 s. We fire two rounds, wait a full reload, fire
    two more, and run long enough (60 000 steps = 500 s) for every round to be
    seen and back-plotted."""
    cfg = CombatConfig(seed=1337)
    cw = CombatWorld(cfg)
    pic = cw.commander.picture

    tx = np.array([float(target_xz[0]), 0.0, float(target_xz[1])])

    launches_seen = 0
    first_cluster_at = None
    # Fire in PAIRS (2 tubes) every reload window so distinct rounds accumulate.
    fire_steps = set()
    for k in range(n_salvos):
        fire_steps.add(60 + k * salvo_gap_steps)
    fire_track_first_seen = []   # (alt, range) per back-plotted fix

    prev_raw = 0
    for i in range(steps):
        if i in fire_steps:
            m = cw.launch("lo-lo", tx)
            if m is not None:
                launches_seen += 1
        cw.step(DT)
        raw_now = len(pic._back_plots)
        if raw_now > prev_raw:
            for bp in pic._back_plots[prev_raw:]:
                mt = pic.missile_tracks.get(bp.track_id, {})
                fire_track_first_seen.append((
                    mt.get("alt_at_first"), mt.get("range_at_first")))
            prev_raw = raw_now
        if first_cluster_at is None and pic.targetable_clusters():
            first_cluster_at = launches_seen

    (n_raw, n_clusters, best, cerr, per_fix,
     cluster_fix_total) = _cluster_summary(pic, true_pad_xz)

    print(f"\n=== Scenario {name} ===")
    print(f"  salvos fired (rounds that left a tube): {launches_seen}")
    print(f"  raw (un-pruned) back-plot fixes:        {n_raw}")
    print(f"  total fixes retained across clusters:   {cluster_fix_total}")
    print(f"  clusters formed (any):                  {n_clusters}")
    print(f"  targetable cluster formed?              "
          f"{'YES' if best is not None else 'NO'}"
          + (f" after {first_cluster_at} launches" if first_cluster_at else ""))
    print(f"  centroid error vs true pad {true_pad_xz}: {_fmt(cerr)} m")
    if per_fix:
        print(f"  per-fix back-projection error: "
              f"min {_fmt(min(per_fix))} / mean {_fmt(sum(per_fix)/len(per_fix))}"
              f" / max {_fmt(max(per_fix))} m  (n={len(per_fix)})")
    else:
        print("  per-fix back-projection error: (no fixes formed)")
    if fire_track_first_seen:
        alts = [a for a, _ in fire_track_first_seen if a is not None]
        rngs = [r for _, r in fire_track_first_seen if r is not None]
        if alts:
            print(f"  first-seen alt of fixes: "
                  f"min {_fmt(min(alts))} / max {_fmt(max(alts))} m "
                  f"(eligibility ceiling {BACKPLOT_LOW_ALT_M:,.0f} m)")
        if rngs:
            print(f"  first-seen detection range of fixes: "
                  f"min {_fmt(min(rngs))} / max {_fmt(max(rngs))} m")
    return dict(name=name, launches=launches_seen, n_raw=n_raw,
                n_clusters=n_clusters, targetable=best is not None,
                first_cluster_at=first_cluster_at, centroid_err=cerr,
                per_fix=per_fix)


def main():
    # The probe reflects the CURRENT model in sim/commander.py. To compare
    # BEFORE vs AFTER, run it on the two git states (or temporarily set
    # BACKPLOT_COAST_SETBACK_M = 0.0). The setback is reported live below so the
    # banner is never out of sync with the model actually being measured.
    from sim.commander import BACKPLOT_COAST_SETBACK_M
    print("#" * 70)
    print(f"# BACK-PLOT RELIABILITY PROBE  "
          f"(live model: BACKPLOT_COAST_SETBACK_M = {BACKPLOT_COAST_SETBACK_M} m)")
    print(f"# true Bastion pad XZ = {TRUE_PAD_XZ}  (z={TRUE_PAD_XZ[1]}, south of "
          f"HOME_COAST_Z={HOME_COAST_Z})")
    print(f"# BACKPLOT_FIXES_NEEDED={BACKPLOT_FIXES_NEEDED}  "
          f"CLUSTER_R_M={BACKPLOT_CLUSTER_R_M}  ERR_FRAC={BACKPLOT_ERR_FRAC}  "
          f"MAX_AGE_S={BACKPLOT_MAX_AGE_S}")
    print("#" * 70)

    # A. STRAIGHT lo-lo toward the fleet band (the realistic sea-skim leak).
    _run_scenario("A_STRAIGHT_seaskim", target_xz=(0.0, 220_000.0),
                  true_pad_xz=TRUE_PAD_XZ)

    # B. DOGLEG: aim far to the EAST so the ground track is closer to
    # coast-parallel (low closing vz toward the home coast) — the player evades
    # localization. A round aimed mostly along +x with little +z closing should
    # NOT localize.
    _run_scenario("B_DOGLEG_coastparallel",
                  target_xz=(400_000.0, 8_000.0),
                  true_pad_xz=TRUE_PAD_XZ)

    # C. SCOOT context: fire the straight salvo but score the centroid against an
    # OFFSET "true" pad 8 km away — i.e. if the player had relocated, would a
    # salvo at the formed centroid hit the NEW spot? (Large error => miss => the
    # relocated player is safe.)
    res = _run_scenario("C_SCOOT_offset_score",
                        target_xz=(0.0, 220_000.0),
                        true_pad_xz=(8_000.0, -600.0))
    print("\n  (C scores the SAME straight salvo against a pad 8 km away: a large "
          "error here means a scooted player is not hit by the stale centroid.)")


if __name__ == "__main__":
    main()
