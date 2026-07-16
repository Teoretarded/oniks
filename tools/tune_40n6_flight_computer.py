"""Production-physics coordinate search for the 40N6 flight computer.

The search uses 25 tuning targets and a different fixed 25-target evaluation
matrix.  A candidate must retain kills first; retained impact energy, closest
approach, time, and path efficiency break ties.  No reduced-order simulator is
used here: every case steps :class:`sim.sam.SamMissile` at 120 Hz.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
import os
from statistics import median
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.probe_sam_flight_computer import run_case  # noqa: E402


@dataclass(frozen=True, slots=True)
class TargetCase:
    range_km: float
    altitude_km: float
    motion: str
    track_update_s: float


MOTIONS = ("static", "cross", "away", "toward", "climb")
TRACKS = (0.5, 1.0, 2.0, 5.0, 10.0)


def _matrix(ranges, altitudes, offset: int) -> tuple[TargetCase, ...]:
    return tuple(
        TargetCase(
            range_km=float(distance), altitude_km=float(altitude),
            motion=MOTIONS[(ri + 2 * ai + offset) % len(MOTIONS)],
            track_update_s=TRACKS[(2 * ri + ai + offset) % len(TRACKS)],
        )
        for ri, distance in enumerate(ranges)
        for ai, altitude in enumerate(altitudes)
    )


TUNING_CASES = _matrix(
    (80, 140, 200, 260, 330), (4, 6.5, 12, 20, 28), 1)
EVALUATION_CASES = _matrix(
    (60, 120, 180, 240, 300), (4, 6.5, 12, 18, 24), 3)
STRESS_CASES = _matrix(
    (100, 175, 250, 325, 360), (4, 8, 15, 24, 32), 4)

PRE_TUNING_DEFAULTS = {
    "energy_fallback_floor_fraction": 0.5,
    "energy_fallback_min_range_m": 100_000.0,
    "energy_fallback_near_scale": 2.5,
    "energy_fallback_far_scale": 5.0,
    "control_lookahead_m": 9_500.0,
    "long_range_control_lookahead_m": None,
    "terminal_capture_fraction": 0.65,
}
DEFAULTS = {
    "energy_fallback_floor_fraction": 0.35,
    "energy_fallback_min_range_m": 120_000.0,
    "energy_fallback_near_scale": 2.0,
    "energy_fallback_far_scale": 4.0,
    "control_lookahead_m": 9_500.0,
    "long_range_control_lookahead_m": 12_000.0,
    "long_range_control_start_m": 120_000.0,
    "long_range_control_full_m": 200_000.0,
    "terminal_capture_fraction": 0.65,
}


def _case_worker(payload):
    index, case, overrides = payload
    result, _ = run_case(
        "40n6", case.range_km, case.altitude_km, case.motion,
        track_update_s=case.track_update_s, trace=False,
        planner_overrides=overrides)
    return index, asdict(case), asdict(result)


def run_matrix(cases: tuple[TargetCase, ...], overrides: dict,
               workers: int) -> list[dict]:
    payloads = [(index, case, dict(overrides))
                for index, case in enumerate(cases)]
    completed = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_case_worker, payload) for payload in payloads]
        for future in as_completed(futures):
            completed.append(future.result())
    completed.sort(key=lambda item: item[0])
    return [{"case": case, "result": result}
            for _index, case, result in completed]


def summarize(rows: list[dict]) -> dict:
    results = [row["result"] for row in rows]
    hits = [row for row in results if row["hit"]]
    closest = sorted(float(row["closest_m"]) for row in results)
    p95_index = min(len(closest) - 1, math.ceil(0.95 * len(closest)) - 1)
    return {
        "hits": len(hits),
        "cases": len(results),
        "hit_rate": len(hits) / len(results),
        "p95_closest_m": closest[p95_index],
        "median_closest_m": median(closest),
        "median_impact_speed_mps": (
            median(float(row["impact_speed_mps"]) for row in hits)
            if hits else 0.0),
        "median_time_s": median(float(row["flight_time_s"]) for row in results),
        "median_path_ratio": median(
            float(row["path_length_km"])
            / max(math.hypot(float(row["range_km"]),
                             float(row["altitude_km"])), 1e-9)
            for row in results),
        "median_apogee_km": median(float(row["apogee_km"]) for row in results),
    }


def _rank(summary: dict):
    # Lexicographic on purpose: never trade a kill for prettier energy numbers.
    return (
        summary["hits"],
        summary["median_impact_speed_mps"],
        -summary["p95_closest_m"],
        -summary["median_time_s"],
        -summary["median_path_ratio"],
    )


def evaluate_candidates(label: str, cases: tuple[TargetCase, ...],
                        candidates: list[dict], workers: int):
    stage = []
    for number, overrides in enumerate(candidates, 1):
        rows = run_matrix(cases, overrides, workers)
        summary = summarize(rows)
        stage.append({"overrides": dict(overrides), "summary": summary})
        print(
            f"[{label} {number}/{len(candidates)}] "
            f"hit={summary['hits']:02d}/{summary['cases']} "
            f"p95={summary['p95_closest_m']:.1f}m "
            f"v={summary['median_impact_speed_mps']:.0f}m/s "
            f"t={summary['median_time_s']:.0f}s "
            f"path={summary['median_path_ratio']:.3f}",
            flush=True)
    best = max(stage, key=lambda item: _rank(item["summary"]))
    return best, stage


def _vary(base: dict, key: str, values) -> list[dict]:
    return [{**base, key: value} for value in values]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int,
                        default=min(8, max(1, (os.cpu_count() or 2) - 1)))
    parser.add_argument("--output", default="testing_flights")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--stress-compare", action="store_true")
    args = parser.parse_args()
    workers = max(1, min(int(args.workers), 16))
    report = {"tuning_cases": [asdict(case) for case in TUNING_CASES],
              "evaluation_cases": [asdict(case) for case in EVALUATION_CASES],
              "stress_cases": [asdict(case) for case in STRESS_CASES]}

    if args.stress_compare:
        old_rows = run_matrix(STRESS_CASES, PRE_TUNING_DEFAULTS, workers)
        new_rows = run_matrix(STRESS_CASES, DEFAULTS, workers)
        report["stress_before"] = {
            "overrides": PRE_TUNING_DEFAULTS, "summary": summarize(old_rows),
            "rows": old_rows}
        report["stress_after"] = {
            "overrides": DEFAULTS, "summary": summarize(new_rows),
            "rows": new_rows}
        stamp = datetime.now().strftime("40n6_stress_%Y%m%d_%H%M%S")
        folder = os.path.abspath(os.path.join(args.output, stamp))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "report.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        print("[stress-before]", json.dumps(report["stress_before"]["summary"]))
        print("[stress-after]", json.dumps(report["stress_after"]["summary"]))
        print(path)
        return 0

    baseline_rows = run_matrix(EVALUATION_CASES, DEFAULTS, workers)
    report["baseline"] = {
        "overrides": dict(DEFAULTS), "summary": summarize(baseline_rows),
        "rows": baseline_rows,
    }
    print("[baseline]", json.dumps(report["baseline"]["summary"]), flush=True)
    if args.baseline_only:
        best = dict(DEFAULTS)
        stages = []
    else:
        best = dict(DEFAULTS)
        stages = []
        winner, stage = evaluate_candidates(
            "floor", TUNING_CASES,
            _vary(best, "energy_fallback_floor_fraction",
                  (0.35, 0.45, 0.5, 0.6, 0.7)), workers)
        best = winner["overrides"]
        stages.append({"name": "floor", "candidates": stage})

        geometry = []
        for near, far in ((2.0, 4.0), (2.0, 5.0), (2.5, 4.5),
                          (2.5, 5.0), (2.5, 6.0), (3.0, 5.0), (3.0, 6.0)):
            geometry.append({**best,
                             "energy_fallback_near_scale": near,
                             "energy_fallback_far_scale": far})
        winner, stage = evaluate_candidates(
            "geometry", TUNING_CASES, geometry, workers)
        best = winner["overrides"]
        stages.append({"name": "geometry", "candidates": stage})

        winner, stage = evaluate_candidates(
            "lookahead", TUNING_CASES,
            _vary(best, "control_lookahead_m",
                  (7_500.0, 9_500.0, 12_000.0, 15_000.0)), workers)
        best = winner["overrides"]
        stages.append({"name": "lookahead", "candidates": stage})

        winner, stage = evaluate_candidates(
            "capture", TUNING_CASES,
            _vary(best, "terminal_capture_fraction",
                  (0.5, 0.6, 0.65, 0.7, 0.8)), workers)
        best = winner["overrides"]
        stages.append({"name": "capture", "candidates": stage})

    final_rows = run_matrix(EVALUATION_CASES, best, workers)
    report["stages"] = stages
    report["best_overrides"] = best
    report["final"] = {
        "overrides": best, "summary": summarize(final_rows),
        "rows": final_rows,
    }
    stamp = datetime.now().strftime("40n6_tuning_%Y%m%d_%H%M%S")
    folder = os.path.abspath(os.path.join(args.output, stamp))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "report.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print("[best]", json.dumps(best, sort_keys=True), flush=True)
    print("[final]", json.dumps(report["final"]["summary"]), flush=True)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
