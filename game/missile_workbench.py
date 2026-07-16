"""GL-free batch harness used by the F3 missile-flight workbench and AI CLI."""

from __future__ import annotations

import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
import os
from statistics import median
from typing import Callable

from tools.probe_sam_flight_computer import MOTION_VELOCITIES, run_case


WEAPONS = ("40n6", "s300", "sm6", "sm2", "buk_9m317", "buk_9m338",
           "pantsir_57e6")
WEAPON_LABELS = {
    "40n6": "S-300 / 40N6",
    "s300": "S-300 / 48N6",
    "sm6": "AEGIS / SM-6",
    "sm2": "AEGIS / SM-2",
    "buk_9m317": "BUK / 9M317",
    "buk_9m338": "BUK / 9M338",
    "pantsir_57e6": "PANTSIR / 57E6",
}
RANGES_KM = (20.0, 40.0, 60.0, 90.0, 120.0, 160.0, 200.0, 250.0,
             300.0, 340.0, 360.0)
ALTITUDES_KM = (0.05, 1.0, 4.0, 6.5, 9.0, 12.0, 18.0, 24.0, 30.0)
TRACK_UPDATES_S = (0.1, 0.5, 1.0, 2.0, 5.0, 10.0)
RUN_COUNTS = (1, 10, 25, 100)
VARIATIONS = (0.0, 0.02, 0.05, 0.10)
TELEMETRY_LEVELS = ("fast", "full")


@dataclass(frozen=True, slots=True)
class WorkbenchConfig:
    weapon: str = "40n6"
    range_km: float = 90.0
    altitude_km: float = 6.5
    motion: str = "cross"
    track_update_s: float = 1.0
    runs: int = 10
    variation: float = 0.05
    telemetry: str = "fast"


@dataclass(frozen=True, slots=True)
class WorkbenchBatch:
    config: WorkbenchConfig
    results: tuple[dict, ...]
    trajectories: tuple[tuple[dict, ...], ...]
    hit_rate: float
    median_closest_m: float
    median_apogee_km: float
    ranked_indices: tuple[int, ...]
    output_dir: str


def _balanced(index: int, multiplier: int) -> float:
    """Deterministic low-discrepancy-ish value in [-1, 1]."""
    return 2.0 * (((index * multiplier) % 101) / 100.0) - 1.0


def varied_case(config: WorkbenchConfig, index: int) -> tuple[float, float, float]:
    """Vary geometry/sensor cadence; identical repeats teach nothing."""
    amount = max(0.0, float(config.variation))
    r = max(1.0, config.range_km * (1.0 + amount * _balanced(index, 37)))
    a = max(0.01, config.altitude_km
            * (1.0 + amount * _balanced(index, 61)))
    track = max(1.0 / 120.0, config.track_update_s
                * (1.0 + amount * _balanced(index, 83)))
    return r, a, track


def _relative_scores(values, *, lower_is_better: bool) -> list[float]:
    numbers = [float(value) for value in values]
    lo, hi = min(numbers), max(numbers)
    if hi - lo <= 1e-12:
        return [1.0] * len(numbers)
    scores = [(value - lo) / (hi - lo) for value in numbers]
    return [1.0 - value for value in scores] if lower_is_better else scores


def score_results(results: list[dict]) -> tuple[int, ...]:
    """Rank comparable runs from one batch on a transparent 100-point scale.

    A hit is worth 55 points, so no clean miss can outrank a hit.  The rest
    rewards closest approach (20), retained terminal speed (10), shorter time
    (10), and less excess loft above that run's target altitude (5).
    """
    if not results:
        return ()
    proximity = _relative_scores(
        (row["closest_m"] for row in results), lower_is_better=True)
    speed = _relative_scores(
        (row["impact_speed_mps"] for row in results), lower_is_better=False)
    flight_time = _relative_scores(
        (row["flight_time_s"] for row in results), lower_is_better=True)
    altitude = _relative_scores(
        (max(0.0, float(row["apogee_km"]) - float(row["altitude_km"]))
         for row in results), lower_is_better=True)
    for index, row in enumerate(results):
        score = (55.0 if row["hit"] else 0.0)
        score += 20.0 * proximity[index]
        score += 10.0 * speed[index]
        score += 10.0 * flight_time[index]
        score += 5.0 * altitude[index]
        row["performance_score"] = round(score, 3)
    ranked = tuple(sorted(
        range(len(results)),
        key=lambda index: (-results[index]["performance_score"],
                           float(results[index]["closest_m"]), index)))
    for rank, index in enumerate(ranked, 1):
        results[index]["performance_rank"] = rank
    return ranked


def _run_workbench_case(payload):
    """Pickle-safe process worker; returns its input index for stable order."""
    config, index = payload
    range_km, altitude_km, track_update_s = varied_case(config, index)
    result, trajectory = run_case(
        config.weapon, range_km, altitude_km, config.motion,
        track_update_s=track_update_s, trace=True,
        planner_detail=config.telemetry == "full")
    row = asdict(result)
    row["run"] = index + 1
    return index, row, tuple(trajectory)


def run_batch(config: WorkbenchConfig, output_root: str,
              progress: Callable[[int, int], None] | None = None,
              cancelled: Callable[[], bool] | None = None) -> WorkbenchBatch:
    if config.weapon not in WEAPONS:
        raise ValueError(f"unsupported weapon {config.weapon!r}")
    if config.motion not in MOTION_VELOCITIES:
        raise ValueError(f"unsupported motion {config.motion!r}")
    if config.runs <= 0 or config.runs > 500:
        raise ValueError("runs must be in [1, 500]")
    if config.telemetry not in TELEMETRY_LEVELS:
        raise ValueError(f"telemetry must be one of {TELEMETRY_LEVELS}")

    completed: list[tuple[int, dict, tuple[dict, ...]]] = []
    payloads = [(config, index) for index in range(config.runs)]
    cpu_count = max(1, os.cpu_count() or 1)
    worker_cap = 4 if config.telemetry == "full" else 8
    workers = min(config.runs, max(1, cpu_count - 1), worker_cap)
    if workers == 1:
        for payload in payloads:
            if cancelled is not None and cancelled():
                break
            completed.append(_run_workbench_case(payload))
            if progress is not None:
                progress(len(completed), config.runs)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_run_workbench_case, payload)
                       for payload in payloads]
            for future in as_completed(futures):
                if cancelled is not None and cancelled():
                    for pending in futures:
                        pending.cancel()
                    break
                completed.append(future.result())
                if progress is not None:
                    progress(len(completed), config.runs)
    completed.sort(key=lambda item: item[0])
    results = [item[1] for item in completed]
    trajectories = [item[2] for item in completed]
    if not results:
        raise RuntimeError("batch cancelled before its first run")
    ranked_indices = score_results(results)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.abspath(os.path.join(output_root, stamp))
    os.makedirs(output_dir, exist_ok=True)
    summary = {
        "config": asdict(config),
        "hit_rate": sum(bool(row["hit"]) for row in results) / len(results),
        "median_closest_m": median(row["closest_m"] for row in results),
        "median_apogee_km": median(row["apogee_km"] for row in results),
        "completed_runs": len(results),
        "best_run": results[ranked_indices[0]],
        "score_weights": {
            "hit": 55, "closest_approach": 20, "terminal_speed": 10,
            "flight_time": 10, "altitude_efficiency": 5,
        },
    }
    with open(os.path.join(output_dir, "summary.json"), "w",
              encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)
    with open(os.path.join(output_dir, "runs.csv"), "w", newline="",
              encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(results[0]))
        writer.writeheader()
        writer.writerows(results)
    with open(os.path.join(output_dir, "blackbox.jsonl"), "w",
              encoding="utf-8") as handle:
        for row, trajectory in zip(results, trajectories):
            json.dump({"result": row, "trajectory": trajectory}, handle,
                      separators=(",", ":"))
            handle.write("\n")
    return WorkbenchBatch(
        config=config,
        results=tuple(results),
        trajectories=tuple(trajectories),
        hit_rate=summary["hit_rate"],
        median_closest_m=summary["median_closest_m"],
        median_apogee_km=summary["median_apogee_km"],
        ranked_indices=ranked_indices,
        output_dir=output_dir,
    )


def cycle_value(values: tuple, current, delta: int):
    try:
        index = values.index(current)
    except ValueError:
        index = 0
    return values[(index + int(delta)) % len(values)]


def finite_plot_points(trajectory: tuple[dict, ...], x_key: str, y_key: str):
    return tuple((float(row[x_key]), float(row[y_key])) for row in trajectory
                 if math.isfinite(float(row[x_key]))
                 and math.isfinite(float(row[y_key])))


__all__ = (
    "ALTITUDES_KM", "RANGES_KM", "RUN_COUNTS", "TELEMETRY_LEVELS",
    "TRACK_UPDATES_S",
    "VARIATIONS", "WEAPONS", "WEAPON_LABELS", "WorkbenchBatch", "WorkbenchConfig",
    "cycle_value", "finite_plot_points", "run_batch", "score_results",
    "varied_case",
)
