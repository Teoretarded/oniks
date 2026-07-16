"""Standalone contracts for the online energy-aware flight computer."""

import math

from sim.arsenal import KH31P, ONIKS, TOMAHAWK
from sim.aero import q_scalar
from sim.flight_computer import (
    MAX_ROLLOUT_STEPS,
    AirframeEnvelope,
    FlightMode,
    FlightState,
    MissionSnapshot,
    OnlineFlightComputer,
    route_arc_length_m,
)


def _flat(_x, _z):
    return 0.0


def _env(**overrides):
    values = dict(
        ref_area_m2=0.35,
        cl_max=4.0,
        max_g=10.0,
        k_induced=0.08,
        dry_mass_kg=2_000.0,
        fuel_capacity_kg=500.0,
        max_thrust_n=100_000.0,
        isp_s=1_000.0,
        thrust_tau_s=1.0,
        preferred_mach=2.0,
        low_mach=1.6,
        preferred_alt_m=10_000.0,
        preferred_alt_is_agl=False,
        deck_agl_m=20.0,
        max_climb_gamma_rad=math.radians(20.0),
        max_descent_gamma_rad=math.radians(25.0),
        terminal_speed_min_mps=350.0,
        fuel_reserve_kg=10.0,
    )
    values.update(overrides)
    return AirframeEnvelope(**values)


def _state(*, pos=(0.0, 2_000.0, 0.0), vel=(0.0, 0.0, 600.0),
           fuel=400.0, thrust=60_000.0):
    env = _env()
    return FlightState(
        pos=pos,
        vel=vel,
        mass_kg=env.dry_mass_kg + fuel,
        fuel_kg=fuel,
        thrust_actual_n=thrust,
    )


def _mission(path=((0.0, 150_000.0),), **kwargs):
    return MissionSnapshot(path_xz=path, **kwargs)


def test_route_arc_length_uses_every_waypoint_not_direct_range():
    pos = (0.0, 100.0, 0.0)
    path = ((3_000.0, 4_000.0), (6_000.0, 4_000.0))
    assert route_arc_length_m(pos, path) == 8_000.0
    assert route_arc_length_m(pos, path) > math.hypot(6_000.0, 4_000.0)


def test_command_is_cached_for_quarter_second_then_replanned():
    fc = OnlineFlightComputer(_env())
    state = _state()
    mission = _mission()

    first = fc.update(0.0, state, mission, _flat)
    assert first.plan_id == 1
    assert fc.update(0.10, state, mission, _flat) is first
    assert fc.update(0.14, state, mission, _flat) is first
    second = fc.update(0.01, state, mission, _flat)
    assert second is not first
    assert second.plan_id == 2


def test_corridor_dwell_stops_equal_feasibility_mode_chatter():
    fc = OnlineFlightComputer(_env(corridor_min_hold_s=0.5))
    fc._last_corridor = "deck"
    fc._corridor_age_s = 0.0
    state = _state()
    mission = _mission(path=((0.0, 50_000.0),))

    held = fc.update(0.0, state, mission, _flat)
    assert held.prediction.corridor == "deck"

    # Once the short dwell expires, the live optimizer is free to take the
    # cheaper feasible corridor; the path itself was never preprogrammed.
    released = fc.update(0.5, state, mission, _flat)
    assert released.prediction.corridor == "mid"


def test_debug_snapshot_contains_the_real_candidate_rollouts_only_when_on():
    fc = OnlineFlightComputer(_env())
    state = _state()
    mission = _mission()

    fc.set_debug_enabled(True)
    command = fc.update(0.0, state, mission, _flat)
    snapshot = fc.debug_snapshot
    assert snapshot is not None
    assert snapshot.plan_id == command.plan_id
    assert snapshot.selected == command.prediction.corridor
    assert len(snapshot.candidates) == 5
    assert sum(candidate.selected for candidate in snapshot.candidates) == 1
    assert all(len(candidate.path_world) >= 2
               for candidate in snapshot.candidates)

    fc.set_debug_enabled(False)
    assert fc.debug_snapshot is None


def test_route_change_invalidates_cache_immediately():
    fc = OnlineFlightComputer(_env())
    state = _state()
    first = fc.update(0.0, state, _mission(), _flat)
    dogleg = _mission(path=((40_000.0, 30_000.0), (0.0, 150_000.0)))
    second = fc.update(0.01, state, dogleg, _flat)
    assert second.plan_id == first.plan_id + 1
    assert second.prediction.route_range_m == route_arc_length_m(
        state.pos, dogleg.path_xz)


def test_identical_computers_are_deterministic():
    a = OnlineFlightComputer(_env())
    b = OnlineFlightComputer(_env())
    state = _state()
    mission = _mission(path=((25_000.0, 40_000.0), (0.0, 150_000.0)))
    for dt in (0.0, 0.1, 0.15, 0.25, 0.07):
        ca = a.update(dt, state, mission, _flat)
        cb = b.update(dt, state, mission, _flat)
        assert ca == cb


def test_rollout_is_bounded_even_for_intercontinental_route():
    env = AirframeEnvelope.from_weapon(TOMAHAWK, "strike")
    fc = OnlineFlightComputer(env)
    state = FlightState((0.0, 50.0, 0.0), (0.0, 0.0, 250.0),
                        TOMAHAWK.launch_mass, TOMAHAWK.fuel_mass, 2_000.0)
    cmd = fc.update(0.0, state, _mission(path=((0.0, 2_000_000.0),)), _flat)
    assert 0 < cmd.prediction.rollout_samples <= MAX_ROLLOUT_STEPS
    assert cmd.prediction.route_range_m == 2_000_000.0
    assert abs(cmd.prediction.terminal_altitude_error_m) < 100.0


def test_terminal_latch_outputs_downward_bounded_path_command():
    env = _env()
    fc = OnlineFlightComputer(env)
    state = _state(pos=(0.0, 1_000.0, 0.0), vel=(0.0, 0.0, 600.0))
    mission = _mission(path=((0.0, 1_500.0),), terminal_latched=True,
                       terminal_commit_max_m=2_000.0)
    cmd = fc.update(0.0, state, mission, _flat)
    assert cmd.mode == FlightMode.TERMINAL
    assert cmd.terminal_commit
    assert cmd.target_path_gamma_rad < 0.0
    assert cmd.path_normal_accel_mps2 < 0.0
    # Structural and q limits both bound the emitted normal command.
    speed = math.sqrt(sum(float(v) ** 2 for v in state.vel))
    q_cap = (q_scalar(speed, float(state.pos[1])) * env.ref_area_m2
             * env.cl_max / state.mass_kg)
    assert abs(cmd.path_normal_accel_mps2) <= min(
        env.max_g * 9.81, q_cap) + 1e-9
    assert fc.update(0.10, state, mission, _flat) is cmd


def test_terminal_reference_uses_full_line_of_sight_range():
    fc = OnlineFlightComputer(_env(max_descent_gamma_rad=math.radians(40.0)))
    state = _state(pos=(0.0, 4_500.0, 0.0), vel=(0.0, 0.0, 1_400.0))
    mission = _mission(path=((0.0, 30_000.0),), terminal_latched=True,
                       terminal_commit_max_m=30_000.0)
    cmd = fc.update(0.0, state, mission, _flat)
    assert math.isclose(
        cmd.target_path_gamma_rad,
        math.atan2(-4_500.0, 30_000.0),
        rel_tol=0.0, abs_tol=1e-12)


def test_terminal_commit_waits_when_a_ridge_blocks_direct_line():
    def ridge(_x, z):
        return 600.0 if 700.0 < z < 900.0 else 0.0

    fc = OnlineFlightComputer(_env(terminal_speed_min_mps=200.0))
    state = _state(pos=(0.0, 500.0, 0.0), vel=(0.0, 0.0, 500.0))
    mission = _mission(path=((0.0, 1_600.0),), terminal_commit_max_m=2_000.0)
    cmd = fc.update(0.0, state, mission, ridge)
    assert not cmd.terminal_commit
    assert cmd.mode != FlightMode.TERMINAL


def test_short_high_shot_predicts_less_margin_than_long_descent_room():
    env = _env(terminal_speed_min_mps=300.0)
    state = _state(pos=(0.0, 10_000.0, 0.0), vel=(0.0, 0.0, 550.0))
    near = OnlineFlightComputer(env).update(
        0.0, state, _mission(path=((0.0, 5_000.0),)), _flat)
    far = OnlineFlightComputer(env).update(
        0.0, state, _mission(path=((0.0, 100_000.0),)), _flat)
    assert near.target_path_gamma_rad <= far.target_path_gamma_rad
    assert (not near.prediction.feasible
            or near.prediction.terminal_altitude_error_m
            > far.prediction.terminal_altitude_error_m)


def test_weapon_factory_supports_both_existing_families():
    oniks = AirframeEnvelope.from_weapon(ONIKS, "missile", "hi-lo")
    tlam = AirframeEnvelope.from_weapon(TOMAHAWK, "strike")
    kh31 = AirframeEnvelope.from_weapon(KH31P, "arm")
    assert oniks.preferred_mach == ONIKS.cruise_mach_hi
    assert oniks.preferred_alt_m == ONIKS.cruise_alt_hi
    assert not oniks.preferred_alt_is_agl
    assert oniks.deck_agl_m == ONIKS.lo_alt
    assert tlam.preferred_mach == TOMAHAWK.cruise_mach
    assert tlam.preferred_alt_is_agl
    assert tlam.deck_agl_m == TOMAHAWK.cruise_alt
    assert kh31.preferred_alt_m == 16_000.0
    assert kh31.control_lookahead_m == 2_000.0


def test_nominal_tomahawk_prediction_is_feasible_and_energy_consistent():
    env = AirframeEnvelope.from_weapon(TOMAHAWK, "strike")
    state = FlightState(
        pos=(0.0, TOMAHAWK.cruise_alt, 0.0),
        vel=(0.0, 0.0, 250.0),
        mass_kg=TOMAHAWK.launch_mass,
        fuel_kg=TOMAHAWK.fuel_mass,
        thrust_actual_n=2_000.0,
    )
    mission = _mission(path=((0.0, 300_000.0),))
    pred = OnlineFlightComputer(env).update(0.0, state, mission, _flat).prediction
    assert pred.feasible
    assert pred.terminal_fuel_kg > env.fuel_reserve_kg
    assert abs(pred.terminal_altitude_error_m) < 10.0
    expected = (0.5 * pred.terminal_speed_mps ** 2
                + 9.81 * pred.terminal_altitude_error_m)
    assert math.isclose(pred.terminal_specific_energy_jkg, expected,
                        rel_tol=1e-12)


def test_low_fuel_is_reported_as_terminally_infeasible():
    env = AirframeEnvelope.from_weapon(TOMAHAWK, "strike")
    fuel = 5.0
    state = FlightState(
        pos=(0.0, TOMAHAWK.cruise_alt, 0.0),
        vel=(0.0, 0.0, 250.0),
        mass_kg=env.dry_mass_kg + fuel,
        fuel_kg=fuel,
        thrust_actual_n=2_000.0,
    )
    mission = _mission(path=((0.0, 300_000.0),))
    pred = OnlineFlightComputer(env).update(0.0, state, mission, _flat).prediction
    assert not pred.feasible
    assert pred.terminal_fuel_kg < env.fuel_reserve_kg


def test_long_infeasible_high_mission_latches_balanced_energy_corridor():
    """An impossible early rollout must preserve boost energy, not dive.

    The latch remains stable as range decreases so a 0.5 s feasibility
    flicker cannot alternate MID/DIRECT commands throughout the coast.
    """
    env = _env(preferred_alt_m=40_000.0,
               terminal_speed_min_mps=5_000.0,
               latch_infeasible_midcourse=True)
    fc = OnlineFlightComputer(env)
    mission = _mission(path=((0.0, 340_000.0),), target_y_m=12_000.0,
                       preferred_altitude_m=36_000.0,
                       terminal_handover_alt_m=22_000.0,
                       terminal_commit_max_m=25_000.0)
    launch = _state(pos=(0.0, 50.0, 0.0), vel=(0.0, 30.0, 1.0))
    first = fc.update(0.0, launch, mission, _flat)
    assert not first.prediction.feasible
    assert first.prediction.corridor == "energy"
    assert first.target_path_gamma_rad > 0.0

    # Same mission later in flight: remaining range is now below the initial
    # long-shot threshold, but the degraded energy objective stays latched.
    coast = _state(pos=(0.0, 25_000.0, 170_000.0),
                   vel=(0.0, -20.0, 1_100.0), fuel=0.0, thrust=0.0)
    second = fc.update(fc.replan_interval_s, coast, mission, _flat)
    assert second.prediction.corridor == "energy"


def test_long_range_control_horizon_latches_without_affecting_medium_shots():
    env = _env(
        control_lookahead_m=9_500.0,
        long_range_control_lookahead_m=12_000.0,
        long_range_control_start_m=120_000.0,
        long_range_control_full_m=200_000.0,
    )
    fc = OnlineFlightComputer(env)
    assert fc._control_lookahead(120_000.0) == 9_500.0
    assert fc._control_lookahead(200_000.0) == 12_000.0

    fc._energy_fallback_latched = True
    assert fc._control_lookahead(300_000.0) == 12_000.0
    # Range countdown cannot collapse the original long-shot horizon.
    assert fc._control_lookahead(100_000.0) == 12_000.0


def test_dogleg_prediction_reports_more_range_and_time_cost():
    env = _env(terminal_speed_min_mps=250.0)
    state = _state(pos=(0.0, 2_000.0, 0.0), vel=(0.0, 0.0, 600.0))
    straight_mission = _mission(path=((0.0, 120_000.0),))
    dogleg_mission = _mission(
        path=((50_000.0, 50_000.0), (0.0, 120_000.0)))
    straight = OnlineFlightComputer(env).update(
        0.0, state, straight_mission, _flat).prediction
    dogleg = OnlineFlightComputer(env).update(
        0.0, state, dogleg_mission, _flat).prediction
    assert dogleg.route_range_m > straight.route_range_m
    assert dogleg.time_to_go_s > straight.time_to_go_s
