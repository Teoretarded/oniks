"""Calibration probe for M3-F3: ELINT bearing-sigma elevation under jamming.

MEASURE-FIRST.  The enemy barrage jammer (default Growler) raises the noise
floor at the drone's passive ELINT receiver, widening the per-bearing sigma
(sim/recon.EW_ELINT_SIGMA_K) so a REAL emitter's least-squares fix gets
HONESTLY softer.  This probe measures, for the SAME seeded cross-track pass:

  1. the dimensionless jam floor (sim/ew.noise_floor_at) the drone reads, and
     the resulting sigma inflation, along the pass;
  2. how many distinct cross-track bearing pairs the drone needs to reach an
     ACTIONABLE fix (quality < ELINT_FIX_ACTIONABLE_M) WITHOUT jam vs WITH the
     default Growler up — i.e. the extra baseline the jam costs;
  3. the fix-quality inflation at a fixed pair count.

The spec risk: EW_ELINT_SIGMA_K too high and the player can NEVER localize
under jam.  This probe confirms a determined player STILL localizes; the chosen
K is what the test band (tests/test_ew_elint_sigma.py) is pinned to.

Run:  python tools/probe_ew_elint_sigma.py
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

import sim.ew as ew  # noqa: E402
from sim.radar import Radar  # noqa: E402
from sim.recon import (  # noqa: E402
    ELINT_BEARING_SIGMA_RAD,
    ELINT_FIX_ACTIONABLE_M,
    EW_ELINT_SIGMA_K,
    ElintReceiver,
)

FLAT = lambda x, z: -100.0   # flat sea so LOS is always clear

EMITTER_POS = (0.0, 0.0, 80_000.0)   # emitter 80 km north of the track
EMITTER_ID = "enemy_r0"
DRONE_ALT = 18_000.0
N_SAMPLES = 120
TRAVERSE_M = 60_000.0


class Jammer:
    def __init__(self, pos, jam_power_w):
        self.pos = np.asarray(pos, dtype=np.float64)
        self.jam_power_w = float(jam_power_w)


def _radar():
    r = Radar("enemy_r0", np.asarray(EMITTER_POS, dtype=np.float64), 20.0,
              {"ship": 300_000, "stealth": 30_000, "fighter": 300_000,
               "missile": 300_000})
    r.alive = True
    r.emitting = True
    return r


def _drone_positions(n=N_SAMPLES):
    return [
        np.array([-30_000.0 + i * (TRAVERSE_M / n), DRONE_ALT, 0.0],
                 dtype=np.float64)
        for i in range(n)
    ]


def _default_growler():
    # North of the track, behind the emitter (clear LOS to the drone).
    return Jammer(
        (0.0, ew.EW_DEFAULT_JAMMER_ALT_M,
         EMITTER_POS[2] + ew.EW_DEFAULT_STANDOFF_M),
        ew.EW_DEFAULT_JAM_POWER_W,
    )


def pairs_to_actionable(jammers, seed):
    elint = ElintReceiver(rng=np.random.default_rng(seed), height_fn=FLAT)
    radar = _radar()
    for k, dp in enumerate(_drone_positions(), start=1):
        elint.update(dp, [(EMITTER_ID, radar)], jammers=jammers)
        if elint.fix_quality(EMITTER_ID) < ELINT_FIX_ACTIONABLE_M:
            return k, elint.fix_quality(EMITTER_ID)
    return None, elint.fix_quality(EMITTER_ID)


def full_pass_quality(jammers, seed):
    elint = ElintReceiver(rng=np.random.default_rng(seed), height_fn=FLAT)
    radar = _radar()
    for dp in _drone_positions():
        elint.update(dp, [(EMITTER_ID, radar)], jammers=jammers)
    return elint.fix_quality(EMITTER_ID)


def main() -> int:
    growler = _default_growler()

    print(f"EW_ELINT_SIGMA_K        = {EW_ELINT_SIGMA_K}")
    print(f"ELINT_BEARING_SIGMA_RAD = {ELINT_BEARING_SIGMA_RAD} "
          f"({math.degrees(ELINT_BEARING_SIGMA_RAD):.2f} deg)")
    print(f"default Growler         = {ew.EW_DEFAULT_JAM_POWER_W:.0f} W @ "
          f"{ew.EW_DEFAULT_STANDOFF_M/1000:.0f} km standoff")
    print(f"actionable threshold    = {ELINT_FIX_ACTIONABLE_M/1000:.1f} km")
    print()

    # 1) Floor + sigma inflation along the pass.
    print("Jam floor + sigma inflation along the cross-track pass:")
    print(f"  {'drone_x_km':>10} {'R_jammer_km':>12} {'floor':>8} "
          f"{'sigma_mult':>11} {'sigma_deg':>10}")
    for dp in _drone_positions()[::20]:
        floor = ew.noise_floor_at(dp, [growler], height_fn=FLAT)
        mult = 1.0 + EW_ELINT_SIGMA_K * floor
        r_j = math.hypot(dp[0] - growler.pos[0], dp[2] - growler.pos[2])
        print(f"  {dp[0]/1000:>10.1f} {r_j/1000:>12.1f} {floor:>8.3f} "
              f"{mult:>11.3f} "
              f"{math.degrees(ELINT_BEARING_SIGMA_RAD * mult):>10.3f}")
    print()

    # 2) Pairs-to-actionable across several seeds (determined-player test).
    # A wide seed set: the per-seed crossing is noisy (not monotone in sigma),
    # so the EXPECTED extra baseline only stabilises over many realisations.
    seeds = list(range(24))
    print(f"Pairs to ACTIONABLE fix over {len(seeds)} seeds "
          f"(clear vs default Growler):")
    nc_list = [pairs_to_actionable((), s)[0] for s in seeds]
    nj_list = [pairs_to_actionable([growler], s)[0] for s in seeds]
    clear_fails = sum(1 for x in nc_list if x is None)
    jam_fails = sum(1 for x in nj_list if x is None)
    ratios = [nj_list[i] / nc_list[i] for i in range(len(seeds))
              if nc_list[i] and nj_list[i]]
    # show a few representative seeds, then the aggregate
    print(f"  {'seed':>6} {'clear':>7} {'jam':>7}")
    for i in (0, 7, 15, 23):
        if i < len(seeds):
            cs = str(nc_list[i]) if nc_list[i] is not None else "NONE"
            js = str(nj_list[i]) if nj_list[i] is not None else "NONE"
            print(f"  {seeds[i]:>6} {cs:>7} {js:>7}")
    print(f"  ... ({len(seeds)} seeds total)")
    print()

    # 3) Fix-quality inflation at the FULL pass (fixed 120 pairs).
    print("Full-pass (120-pair) fix quality, clear vs jam, per seed:")
    print(f"  {'seed':>6} {'q_clear_m':>11} {'q_jam_m':>11} {'inflation':>10}")
    q_infl = []
    for s in seeds:
        qc = full_pass_quality((), s)
        qj = full_pass_quality([growler], s)
        infl = qj / qc if math.isfinite(qc) and qc > 0 else float("inf")
        if math.isfinite(infl):
            q_infl.append(infl)
        print(f"  {s:>6} {qc:>11.1f} {qj:>11.1f} {infl:>10.2f}")
    print()

    # Averaged pairs-to-actionable (single-seed crossing is NOT monotone in
    # sigma; the EXPECTED extra baseline is the honest cost measure).
    avg_pairs_clear = avg_pairs_jam = None
    ncv = [x for x in nc_list if x is not None]
    njv = [x for x in nj_list if x is not None]
    if ncv and njv:
        avg_pairs_clear = sum(ncv) / len(ncv)
        avg_pairs_jam = sum(njv) / len(njv)

    # Verdict.  The MONOTONE, physically meaningful gates: (a) full-pass quality
    # is WORSE under jam (the CRLB softens the fix); (b) on AVERAGE more baseline
    # is needed; (c) a determined player STILL localizes every seed.
    print("-" * 56)
    if avg_pairs_clear is not None:
        print(f"avg pairs-to-actionable: clear={avg_pairs_clear:.1f} "
              f"jam={avg_pairs_jam:.1f} (ratio {avg_pairs_jam/avg_pairs_clear:.2f})")
    if ratios:
        print(f"(per-seed pairs ratio is noisy/non-monotone: "
              f"min={min(ratios):.2f} max={max(ratios):.2f} — use the average)")
    if q_infl:
        print(f"full-pass quality inflation (jam/clear): "
              f"min={min(q_infl):.2f} mean={sum(q_infl)/len(q_infl):.2f} "
              f"max={max(q_infl):.2f}")
    print(f"clear passes that NEVER reached actionable: {clear_fails}/{len(seeds)}")
    print(f"jammed passes that NEVER reached actionable: {jam_fails}/{len(seeds)}")
    ok = (
        clear_fails == 0 and jam_fails == 0
        and q_infl and (sum(q_infl) / len(q_infl)) > 1.0
        and avg_pairs_jam is not None and avg_pairs_jam > avg_pairs_clear
    )
    print()
    if jam_fails > 0:
        print("WARNING: a determined cross-track pass FAILED to localize under "
              "jam — EW_ELINT_SIGMA_K is likely TOO HIGH (spec risk).")
    if ok:
        print("OK: jam meaningfully softens the fix (worse quality, more "
              "baseline on average) yet a determined player STILL localizes "
              "under the default Growler.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
