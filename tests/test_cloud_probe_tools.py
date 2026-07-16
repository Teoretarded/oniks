"""GL-free contracts for the deterministic cloud acceptance tooling."""

import numpy as np

from tools.cloud_probe_metrics import (ALTITUDE_SWEEP_M, PRESET_NAMES,
                                       PRESET_VIEW_PLAN, gate_failures,
                                       lightning_metrics, repeat_metrics,
                                       sequence_metrics)
from tools.probe_cloud_suite import command_matrix, quantitative_commands
from tools.probe_cloud_flight import _resolve_point
from tools.probe_cloud_shots import (ORBIT_AZIMUTHS_DEG,
                                     ORBIT_ELEVATIONS_DEG,
                                     orbit_matrix_views)


def test_preset_view_plan_covers_every_weather_and_special_view():
    assert set(PRESET_VIEW_PLAN) == set(range(7)) == set(range(len(PRESET_NAMES)))
    assert "high_cirrus_below" in PRESET_VIEW_PLAN[4]
    assert "high_cirrus_above" in PRESET_VIEW_PLAN[4]
    assert "storm_underbelly" in PRESET_VIEW_PLAN[6]
    assert "storm_tower_wide" in PRESET_VIEW_PLAN[6]
    assert "lightning_watch" in PRESET_VIEW_PLAN[6]
    assert ALTITUDE_SWEEP_M == (60.0, 1_000.0, 4_000.0, 10_000.0,
                               17_500.0, 30_000.0, 50_000.0)


def test_sequence_metrics_count_disappearing_components_and_coverage():
    first = np.zeros((24, 24), dtype=np.float32)
    first[2:8, 2:8] = 0.8
    first[14:20, 14:20] = 0.8
    second = first.copy()
    second[14:20, 14:20] = 0.0
    metrics = sequence_metrics([first, second])
    assert metrics["max_component_disappear"] == 1
    assert metrics["max_component_change"] == 1
    assert metrics["max_coverage_drop"] > 0.05
    assert gate_failures(metrics, "stationary")
    empty = sequence_metrics([np.zeros((8, 8), dtype=np.float32)] * 2)
    assert any("coverage_max" in failure
               for failure in gate_failures(empty, "motion"))


def test_repeat_metrics_are_zero_for_identical_buffers_and_detect_change():
    alpha = [np.full((8, 8), 0.4, dtype=np.float32) for _ in range(3)]
    depth = [np.full((8, 8), 2_000.0, dtype=np.float32) for _ in range(3)]
    exact = repeat_metrics(alpha, alpha, depth, depth)
    assert exact["alpha_mae_mean"] == 0.0
    assert exact["alpha_mismatch_ratio_max"] == 0.0
    changed = [frame.copy() for frame in alpha]
    changed[1][0, 0] = 0.8
    mismatch = repeat_metrics(alpha, changed)
    assert mismatch["alpha_mae_max"] > 0.0
    assert mismatch["alpha_mismatch_ratio_max"] > 0.0

    long_depth = [np.full((8, 8), 450_000.0, dtype=np.float32) for _ in range(3)]
    assert repeat_metrics(alpha, alpha, long_depth, long_depth)[
        "depth_rel_p95_max"] == 0.0


def test_lightning_metric_requires_localized_positive_pulse():
    dark = np.zeros((40, 40), dtype=np.float32)
    flash = dark.copy()
    flash[:8, :] = 0.5                    # 20% of pixels: survives p99.5
    metrics = lightning_metrics([dark, flash, dark])
    assert metrics["flash_count"] == 1
    assert metrics["brightest_pulse"] >= 0.49
    assert lightning_metrics([dark, dark])["flash_count"] == 0


def test_suite_matrix_is_fresh_process_complete_and_seed_override_safe():
    commands = command_matrix(seed=42, quality="med", mode="all")
    assert len(commands) == 13             # 7 presets + 3 sweeps + 3 metrics
    visual = commands[:7]
    assert {command[command.index("--preset") + 1] for command in visual} \
        == {str(i) for i in range(7)}
    quant = quantitative_commands(42, "med")
    assert all(command[command.index("tools.probe_cloud_flight") + 1] == "42"
               for command in quant)
    assert all("--override-spec-seed" in command for command in quant)
    assert "--expect-lightning" in quant[-1]
    assert "--expect-lightning" not in quantitative_commands(
        42, "med", require_lightning=False)[-1]


def test_flight_specs_can_lock_to_resolved_cluster_points():
    cluster = {
        "center": np.array([1.0, 2.0, 3.0]),
        "edge": np.array([4.0, 5.0, 6.0]),
        "outside": np.array([7.0, 8.0, 9.0]),
    }
    point = _resolve_point({"cluster_point": "outside"}, "from", {}, None,
                           cluster)
    assert np.array_equal(point, cluster["outside"])
    assert point is not cluster["outside"]


def test_orbit_matrix_is_four_azimuths_at_five_elevations():
    views, cluster = orbit_matrix_views(7, 0)
    assert cluster is None
    assert ORBIT_AZIMUTHS_DEG == (0, 90, 180, 270)
    assert ORBIT_ELEVATIONS_DEG == (0, 45, 90, -45, -90)
    assert len(views) == 20
    assert len({name for name, *_ in views}) == 20
    assert all(len(view) == 4 for view in views)
