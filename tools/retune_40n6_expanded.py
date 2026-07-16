"""Expanded 49+49 target retune for the production 40N6 autopilot."""

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

from tools.tune_40n6_flight_computer import (  # noqa: E402
    DEFAULTS,
    MOTIONS,
    TRACKS,
    TargetCase,
    run_matrix,
    summarize,
)


def _matrix(ranges, altitudes, offset: int) -> tuple[TargetCase, ...]:
    return tuple(
        TargetCase(
            float(distance), float(altitude),
            MOTIONS[(2 * ri + 3 * ai + offset) % len(MOTIONS)],
            TRACKS[(3 * ri + 2 * ai + offset) % len(TRACKS)],
        )
        for ri, distance in enumerate(ranges)
        for ai, altitude in enumerate(altitudes)
    )


TUNING_49 = _matrix(
    (50, 90, 130, 180, 230, 290, 340),
    (4, 6.5, 10, 15, 22, 30, 38), 1)
HELD_OUT_49 = _matrix(
    (70, 110, 150, 200, 260, 310, 350),
    (4, 8, 12, 18, 26, 34, 40), 4)

# These do not enter the 49-case aggregate score.  They are hard constraints:
# preserve the visible high-loft identity and known near/long intercepts.
GUARDS = (
    TargetCase(120.0, 18.0, "static", 1.0),
    TargetCase(90.0, 6.5, "cross", 5.0),
    TargetCase(340.0, 6.5, "cross", 5.0),
)


def _analyze(rows: list[dict]) -> dict:
    primary = summarize(rows[:49])
    guards = rows[49:]
    identity = guards[0]["result"]
    guard_results = {
        "identity_hit": bool(identity["hit"]),
        "identity_apogee_km": float(identity["apogee_km"]),
        "near_hit": bool(guards[1]["result"]["hit"]),
        "long_hit": bool(guards[2]["result"]["hit"]),
    }
    guard_results["pass"] = (
        guard_results["identity_hit"]
        and guard_results["identity_apogee_km"] >= 36.0
        and guard_results["near_hit"] and guard_results["long_hit"])
    return {"primary": primary, "guards": guard_results}


def _rank(analysis: dict):
    summary = analysis["primary"]
    guards = analysis["guards"]
    return (
        int(guards["pass"]),
        summary["hits"],
        summary["median_impact_speed_mps"],
        -summary["p95_closest_m"],
        -summary["median_time_s"],
        -summary["median_path_ratio"],
    )


def _stage(name: str, base: dict, candidates: list[dict], workers: int,
           report_stages: list[dict]) -> dict:
    evaluated = []
    cases = TUNING_49 + GUARDS
    for number, overrides in enumerate(candidates, 1):
        rows = run_matrix(cases, overrides, workers)
        analysis = _analyze(rows)
        evaluated.append({"overrides": overrides, "analysis": analysis})
        summary, guards = analysis["primary"], analysis["guards"]
        print(
            f"[{name} {number}/{len(candidates)}] "
            f"guard={'OK' if guards['pass'] else 'FAIL'} "
            f"hit={summary['hits']:02d}/49 "
            f"v={summary['median_impact_speed_mps']:.0f}m/s "
            f"p95={summary['p95_closest_m']:.0f}m "
            f"t={summary['median_time_s']:.0f}s "
            f"path={summary['median_path_ratio']:.3f}", flush=True)
    winner = max(evaluated, key=lambda item: _rank(item["analysis"]))
    report_stages.append({"name": name, "candidates": evaluated})
    return dict(winner["overrides"])


def _vary(base: dict, **choices) -> list[dict]:
    candidates = []
    for values in zip(*choices.values()):
        candidates.append({**base, **dict(zip(choices, values))})
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int,
                        default=min(8, max(1, (os.cpu_count() or 2) - 1)))
    parser.add_argument("--output", default="testing_flights")
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()
    workers = max(1, min(16, int(args.workers)))
    report = {
        "tuning_49": [asdict(case) for case in TUNING_49],
        "held_out_49": [asdict(case) for case in HELD_OUT_49],
        "guards": [asdict(case) for case in GUARDS],
    }

    baseline_rows = run_matrix(HELD_OUT_49 + GUARDS, DEFAULTS, workers)
    report["baseline"] = {
        "overrides": dict(DEFAULTS), "analysis": _analyze(baseline_rows),
        "rows": baseline_rows}
    print("[baseline]", json.dumps(report["baseline"]["analysis"]), flush=True)

    best = dict(DEFAULTS)
    stages = []
    if not args.baseline_only:
        best = _stage("floor", best, _vary(
            best, energy_fallback_floor_fraction=(0.35, 0.28, 0.32, 0.38, 0.42)),
            workers, stages)
        best = _stage("minimum", best, _vary(
            best, energy_fallback_min_range_m=(140_000.0, 120_000.0,
                                               130_000.0, 150_000.0,
                                               160_000.0)), workers, stages)
        best = _stage("geometry", best, _vary(
            best,
            energy_fallback_near_scale=(2.0, 1.75, 2.0, 2.25, 2.5),
            energy_fallback_far_scale=(4.0, 3.5, 3.5, 4.0, 4.5)),
            workers, stages)
        best = _stage("long-horizon", best, _vary(
            best, long_range_control_lookahead_m=(12_000.0, 11_000.0,
                                                  13_000.0, 14_000.0)),
            workers, stages)
        best = _stage("horizon-blend", best, _vary(
            best,
            long_range_control_start_m=(120_000.0, 100_000.0,
                                        140_000.0, 160_000.0),
            long_range_control_full_m=(200_000.0, 180_000.0,
                                       220_000.0, 240_000.0)),
            workers, stages)

    final_rows = run_matrix(HELD_OUT_49 + GUARDS, best, workers)
    report["stages"] = stages
    report["best_overrides"] = best
    report["final"] = {
        "overrides": best, "analysis": _analyze(final_rows),
        "rows": final_rows}
    stamp = datetime.now().strftime("40n6_expanded_%Y%m%d_%H%M%S")
    folder = os.path.abspath(os.path.join(args.output, stamp))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "report.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print("[best]", json.dumps(best, sort_keys=True), flush=True)
    print("[final]", json.dumps(report["final"]["analysis"]), flush=True)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
