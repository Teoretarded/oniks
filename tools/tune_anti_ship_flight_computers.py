"""Family-specific production-physics tuner for Oniks, Zircon, and Swarm."""

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

from tools.probe_anti_ship_flight_computer import run_case  # noqa: E402


@dataclass(frozen=True, slots=True)
class FamilySpec:
    weapon: str
    profile: str
    ranges_km: tuple[float, ...]


MOTIONS = ("static", "cross", "away", "toward", "diagonal")
FAMILIES = (
    FamilySpec("oniks", "hi-lo", (60, 120, 180, 260, 340)),
    FamilySpec("oniks", "lo-lo", (40, 80, 120, 160, 200)),
    FamilySpec("zircon", "hi-lo", (80, 150, 220, 300, 380)),
    # Low-altitude hypersonic drag makes 140 km the measured Zircon lo-lo
    # energy edge; Swarm's declared honest envelope is 40 km.
    FamilySpec("zircon", "lo-lo", (30, 60, 90, 120, 140)),
    FamilySpec("swarm", "lo-lo", (8, 16, 24, 32, 40)),
)


def _cases(spec: FamilySpec):
    return tuple((float(distance), MOTIONS[(ri + mi) % len(MOTIONS)])
                 for ri, distance in enumerate(spec.ranges_km)
                 for mi in range(len(MOTIONS)))


def _worker(payload):
    index, spec, distance, motion, planner_overrides, weapon_overrides = payload
    result, _ = run_case(
        spec.weapon, spec.profile, distance, motion,
        planner_overrides=planner_overrides,
        weapon_overrides=weapon_overrides, trace=False)
    return index, asdict(result)


def run_family(spec: FamilySpec, workers: int, *,
               planner_overrides: dict | None = None,
               weapon_overrides: dict | None = None):
    payloads = [
        (index, spec, distance, motion, planner_overrides, weapon_overrides)
        for index, (distance, motion) in enumerate(_cases(spec))]
    completed = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_worker, payload) for payload in payloads]
        for future in as_completed(futures):
            completed.append(future.result())
    completed.sort(key=lambda item: item[0])
    return [result for _index, result in completed]


def summarize(results: list[dict]) -> dict:
    hits = [row for row in results if row["hit"]]
    closest = sorted(float(row["closest_m"]) for row in results)
    p95 = closest[min(len(closest) - 1, math.ceil(0.95 * len(closest)) - 1)]
    terminal_speeds = [float(row["terminal_speed_mps"])
                       for row in hits if row["terminal_speed_mps"] is not None]
    terminal_fuel = [float(row["terminal_fuel_kg"])
                     for row in hits if row["terminal_fuel_kg"] is not None]
    return {
        "hits": len(hits), "cases": len(results),
        "hit_rate": len(hits) / len(results),
        "p95_closest_m": p95,
        "median_closest_m": median(closest),
        "median_impact_speed_mps": median(
            float(row["impact_speed_mps"]) for row in hits) if hits else 0.0,
        "median_terminal_speed_mps": median(terminal_speeds)
        if terminal_speeds else 0.0,
        "median_terminal_fuel_kg": median(terminal_fuel)
        if terminal_fuel else 0.0,
        "median_fuel_left_kg": median(float(row["fuel_left_kg"])
                                      for row in results),
        "median_time_s": median(float(row["flight_time_s"])
                                for row in results),
        "median_path_ratio": median(float(row["path_ratio"])
                                    for row in results),
        "median_apogee_km": median(float(row["apogee_km"])
                                   for row in results),
        "median_corridor_switches": median(
            int(row["corridor_switches"]) for row in results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int,
                        default=min(8, max(1, (os.cpu_count() or 2) - 1)))
    parser.add_argument("--output", default="testing_flights")
    parser.add_argument("--weapon", choices=("oniks", "zircon", "swarm"))
    parser.add_argument("--profile", choices=("hi-lo", "lo-lo"))
    args = parser.parse_args()
    workers = max(1, min(16, int(args.workers)))
    report = {"families": []}
    selected = [
        spec for spec in FAMILIES
        if (args.weapon is None or spec.weapon == args.weapon)
        and (args.profile is None or spec.profile == args.profile)]
    for spec in selected:
        results = run_family(spec, workers)
        summary = summarize(results)
        report["families"].append({
            "spec": asdict(spec), "summary": summary, "results": results})
        print(f"[{spec.weapon} {spec.profile}] {json.dumps(summary)}", flush=True)
    stamp = datetime.now().strftime("anti_ship_matrix_%Y%m%d_%H%M%S")
    folder = os.path.abspath(os.path.join(args.output, stamp))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "report.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
