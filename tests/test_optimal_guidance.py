import math

import numpy as np
import pytest

from sim.optimal_guidance import (
    bounded_pursuit_accel,
    estimate_time_to_go,
    genex_accel,
    minimum_effort_zem_accel,
    project_normal,
)


Z3 = np.zeros(3)


def test_time_to_go_uses_positive_closing_speed():
    est = estimate_time_to_go(
        Z3, np.array([0.0, 0.0, 100.0]),
        np.array([0.0, 0.0, 1_000.0]), Z3,
    )
    assert est.closing
    assert est.range_m == 1_000.0
    assert est.closing_speed == 100.0
    assert est.raw_tgo == 10.0
    assert est.tgo == 10.0
    assert not est.clamped_low and not est.clamped_high


def test_time_to_go_nonclosing_uses_intercept_root_for_bounded_horizon():
    est = estimate_time_to_go(
        Z3, np.array([100.0, 0.0, 0.0]),
        np.array([0.0, 0.0, 1_000.0]), Z3,
    )
    assert not est.closing
    assert est.closing_speed == 0.0
    assert est.raw_tgo == 10.0
    assert est.tgo == 10.0


def test_time_to_go_unreachable_receding_target_uses_maximum():
    est = estimate_time_to_go(
        Z3, np.array([0.0, 0.0, 100.0]),
        np.array([0.0, 0.0, 1_000.0]),
        np.array([0.0, 0.0, 200.0]),
        max_tgo=30.0,
    )
    assert not est.closing
    assert est.closing_speed == -100.0
    assert math.isinf(est.raw_tgo)
    assert est.tgo == 30.0 and est.clamped_high


def test_time_to_go_short_range_is_clamped_without_division_blowup():
    est = estimate_time_to_go(
        Z3, np.array([0.0, 0.0, 1_000.0]),
        np.array([0.0, 0.0, 0.01]), Z3,
        min_tgo=0.1,
    )
    assert est.closing
    assert est.raw_tgo == pytest.approx(1e-5)
    assert est.tgo == 0.1 and est.clamped_low


def test_projection_is_exact_for_general_and_tiny_velocities():
    vec = np.array([7.0, -3.0, 5.0])
    for vel in (np.array([2.0, 4.0, -1.0]),
                np.array([5e-10, 0.0, 0.0])):
        out = project_normal(vec, vel)
        assert out.dtype == np.float64
        scale = max(float(np.linalg.norm(out) * np.linalg.norm(vel)), 1e-30)
        assert abs(float(out @ vel)) < 1e-14 * scale
    np.testing.assert_array_equal(project_normal(vec, Z3), vec)


def test_position_only_zem_matches_closed_form_command():
    accel = minimum_effort_zem_accel(
        Z3, np.array([0.0, 0.0, 100.0]),
        np.array([100.0, 0.0, 1_000.0]), Z3,
        tgo=10.0, max_accel=100.0,
    )
    np.testing.assert_allclose(accel, [3.0, 0.0, 0.0], atol=1e-12)


def test_position_only_zem_is_zero_on_collision_course():
    accel = minimum_effort_zem_accel(
        Z3, np.array([0.0, 0.0, 100.0]),
        np.array([0.0, 0.0, 1_000.0]), Z3,
        max_accel=100.0,
    )
    np.testing.assert_allclose(accel, Z3, atol=1e-12)


def test_zem_command_is_norm_limited_and_normal_to_velocity():
    vel = np.array([0.0, 10.0, 100.0])
    accel = minimum_effort_zem_accel(
        Z3, vel, np.array([1e6, 0.0, 1_000.0]), Z3,
        tgo=1.0, max_accel=7.0,
    )
    assert np.linalg.norm(accel) == pytest.approx(7.0)
    assert abs(float(accel @ vel)) < 1e-9


def test_nonclosing_target_behind_uses_deterministic_bounded_turn():
    args = (Z3, np.array([0.0, 0.0, 100.0]),
            np.array([0.0, 0.0, -1_000.0]), Z3)
    first = minimum_effort_zem_accel(*args, max_accel=10.0)
    second = minimum_effort_zem_accel(*args, max_accel=10.0)
    np.testing.assert_array_equal(first, second)
    np.testing.assert_allclose(first, [10.0, 0.0, 0.0], atol=1e-12)
    assert float(first @ args[1]) == 0.0


def test_short_tgo_uses_bounded_pursuit_instead_of_singular_zem():
    vel = np.array([0.0, 0.0, 1_000.0])
    accel = minimum_effort_zem_accel(
        Z3, vel, np.array([1.0, 0.0, 1.0]), Z3,
        max_accel=5.0, min_tgo=0.1,
    )
    np.testing.assert_allclose(accel, [5.0, 0.0, 0.0], atol=1e-12)


def test_public_pursuit_fallback_is_bounded_and_perpendicular():
    vel = np.array([30.0, -5.0, 80.0])
    accel = bounded_pursuit_accel(
        Z3, vel, np.array([1_000.0, 200.0, 500.0]), max_accel=12.0)
    assert np.linalg.norm(accel) == pytest.approx(12.0)
    assert abs(float(accel @ vel)) < 1e-9


def test_genex_matches_position_and_terminal_velocity_formula():
    accel = genex_accel(
        Z3, np.array([0.0, 0.0, 100.0]),
        np.array([100.0, 0.0, 1_000.0]), Z3,
        np.array([10.0, 0.0, 100.0]),
        tgo=10.0, max_accel=100.0,
    )
    # 6*ZEM/T^2 - 2*(v_des-v)/T = 6*x - 2*x.
    np.testing.assert_allclose(accel, [4.0, 0.0, 0.0], atol=1e-12)


def test_genex_removes_unavailable_longitudinal_velocity_demand():
    accel = genex_accel(
        Z3, np.array([0.0, 0.0, 100.0]),
        np.array([0.0, 0.0, 1_000.0]), Z3,
        np.array([0.0, 0.0, 200.0]),
        tgo=10.0, max_accel=100.0,
    )
    np.testing.assert_allclose(accel, Z3, atol=1e-12)


def test_float32_inputs_still_return_float64_deterministically():
    args = (
        np.zeros(3, dtype=np.float32),
        np.array([0.0, 0.0, 100.0], dtype=np.float32),
        np.array([100.0, 0.0, 1_000.0], dtype=np.float32),
        np.zeros(3, dtype=np.float32),
    )
    first = minimum_effort_zem_accel(
        *args, tgo=10.0, max_accel=100.0)
    second = minimum_effort_zem_accel(
        *args, tgo=10.0, max_accel=100.0)
    assert first.dtype == np.float64
    np.testing.assert_array_equal(first, second)


@pytest.mark.parametrize("kwargs", [
    {"min_tgo": 0.0},
    {"min_tgo": 2.0, "max_tgo": 1.0},
    {"closing_epsilon": -1.0},
])
def test_estimator_rejects_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        estimate_time_to_go(Z3, Z3, np.ones(3), Z3, **kwargs)


def test_guidance_rejects_bad_vectors_and_unbounded_accel_limits():
    with pytest.raises(ValueError):
        minimum_effort_zem_accel(
            [0.0, 0.0], Z3, np.ones(3), Z3, max_accel=10.0)
    with pytest.raises(ValueError):
        minimum_effort_zem_accel(
            Z3, Z3, np.ones(3), Z3, max_accel=math.inf)
    with pytest.raises(ValueError):
        genex_accel(
            Z3, Z3, np.ones(3), Z3, [math.nan, 0.0, 0.0],
            max_accel=10.0)
