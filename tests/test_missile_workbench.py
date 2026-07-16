"""GL-free contracts for the F3 missile-flight batch harness."""

import json
import os

from game.missile_workbench import (
    WorkbenchConfig,
    run_batch,
    score_results,
    varied_case,
)


def test_case_spread_is_deterministic_and_changes_useful_inputs():
    config = WorkbenchConfig(variation=0.05)
    a = varied_case(config, 7)
    b = varied_case(config, 7)
    assert a == b
    assert a != (config.range_km, config.altitude_km, config.track_update_s)


def test_performance_score_keeps_hits_above_misses_and_uses_altitude():
    base = {
        "closest_m": 20.0, "impact_speed_mps": 1_000.0,
        "flight_time_s": 100.0, "altitude_km": 6.5,
    }
    rows = [
        {**base, "hit": True, "apogee_km": 12.0},
        {**base, "hit": True, "apogee_km": 18.0},
        {**base, "hit": False, "apogee_km": 6.5,
         "closest_m": 1.0, "impact_speed_mps": 2_000.0,
         "flight_time_s": 50.0},
    ]
    ranked = score_results(rows)
    assert ranked[:2] == (0, 1)
    assert rows[0]["performance_score"] > rows[1]["performance_score"]
    assert rows[1]["performance_score"] > rows[2]["performance_score"]
    assert [rows[index]["performance_rank"] for index in ranked] == [1, 2, 3]


def test_one_run_exports_summary_csv_and_full_blackbox(tmp_path):
    config = WorkbenchConfig(
        weapon="40n6", range_km=20.0, altitude_km=4.0,
        motion="static", track_update_s=1.0, runs=1, variation=0.0)
    batch = run_batch(config, str(tmp_path))

    assert len(batch.results) == 1
    assert len(batch.trajectories) == 1
    assert batch.trajectories[0]
    assert batch.ranked_indices == (0,)
    assert batch.results[0]["performance_rank"] == 1
    assert "performance_score" in batch.results[0]
    sample = next(row for row in batch.trajectories[0]
                  if row["plan_id"] is not None)
    for key in ("speed_mps", "altitude_m", "corridor", "plan_id",
                "gamma_command_deg", "path_accel_g",
                "predicted_terminal_speed_mps", "energy_margin_jkg"):
        assert key in sample

    for name in ("summary.json", "runs.csv", "blackbox.jsonl"):
        assert os.path.isfile(os.path.join(batch.output_dir, name))
    with open(os.path.join(batch.output_dir, "summary.json"),
              encoding="utf-8") as handle:
        summary = json.load(handle)
    assert summary["completed_runs"] == 1
    assert summary["best_run"]["performance_rank"] == 1
