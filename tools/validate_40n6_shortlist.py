"""Shortlist validation plus a third fresh 49-case 40N6 final matrix."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.retune_40n6_expanded import (  # noqa: E402
    GUARDS,
    HELD_OUT_49,
    _analyze,
    _matrix,
    _rank,
)
from tools.tune_40n6_flight_computer import DEFAULTS, run_matrix  # noqa: E402


FINAL_49 = _matrix(
    (60, 100, 145, 210, 270, 320, 360),
    (5, 9, 14, 20, 28, 36, 40), 2)


def _candidate(name: str, **changes):
    return name, {**DEFAULTS, **changes}


SHORTLIST = (
    _candidate("current"),
    _candidate("min-120", energy_fallback_min_range_m=120_000.0),
    _candidate("min-130", energy_fallback_min_range_m=130_000.0),
    _candidate("geometry-1.75-3.5",
               energy_fallback_near_scale=1.75,
               energy_fallback_far_scale=3.5),
    _candidate("floor-0.28", energy_fallback_floor_fraction=0.28),
    _candidate("horizon-11k", long_range_control_lookahead_m=11_000.0),
    _candidate("expanded-winner",
               energy_fallback_min_range_m=130_000.0,
               energy_fallback_near_scale=1.75,
               energy_fallback_far_scale=3.5,
               long_range_control_lookahead_m=11_000.0,
               long_range_control_start_m=140_000.0,
               long_range_control_full_m=220_000.0),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int,
                        default=min(8, max(1, (os.cpu_count() or 2) - 1)))
    parser.add_argument("--output", default="testing_flights")
    args = parser.parse_args()
    workers = max(1, min(16, int(args.workers)))
    evaluated = []
    for number, (name, overrides) in enumerate(SHORTLIST, 1):
        rows = run_matrix(HELD_OUT_49 + GUARDS, overrides, workers)
        analysis = _analyze(rows)
        evaluated.append({"name": name, "overrides": overrides,
                          "analysis": analysis, "rows": rows})
        summary = analysis["primary"]
        print(
            f"[shortlist {number}/{len(SHORTLIST)}] {name} "
            f"guard={'OK' if analysis['guards']['pass'] else 'FAIL'} "
            f"hit={summary['hits']}/49 "
            f"v={summary['median_impact_speed_mps']:.0f} "
            f"t={summary['median_time_s']:.0f} "
            f"path={summary['median_path_ratio']:.3f}", flush=True)
    validation_winner = max(
        evaluated, key=lambda item: _rank(item["analysis"]))

    finalists = [evaluated[0]]
    if validation_winner["name"] != "current":
        finalists.append(validation_winner)
    final_results = []
    for finalist in finalists:
        rows = run_matrix(FINAL_49 + GUARDS, finalist["overrides"], workers)
        analysis = _analyze(rows)
        final_results.append({"name": finalist["name"],
                              "overrides": finalist["overrides"],
                              "analysis": analysis, "rows": rows})
        print(f"[final] {finalist['name']} {json.dumps(analysis)}", flush=True)
    robust_winner = max(
        final_results, key=lambda item: _rank(item["analysis"]))
    report = {
        "held_out_49": [asdict(case) for case in HELD_OUT_49],
        "final_49": [asdict(case) for case in FINAL_49],
        "guards": [asdict(case) for case in GUARDS],
        "shortlist": evaluated,
        "validation_winner": validation_winner["name"],
        "finalists": final_results,
        "robust_winner": robust_winner,
    }
    stamp = datetime.now().strftime("40n6_shortlist_%Y%m%d_%H%M%S")
    folder = os.path.abspath(os.path.join(args.output, stamp))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "report.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print(f"[robust-winner] {robust_winner['name']}")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
